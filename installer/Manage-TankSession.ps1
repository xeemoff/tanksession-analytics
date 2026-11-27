#requires -Version 5.1
# Commands used by both the graphical manager and Windows CI. No automatic network calls.
. (Join-Path $PSScriptRoot 'Install-TankSession.ps1')

function Find-TankSessionGames([string[]]$Candidates = @()) {
    $paths = @($Candidates)
    if ($paths.Count -eq 0) {
        foreach ($drive in @(Get-PSDrive -PSProvider FileSystem)) {
            if ($drive.Root -notmatch '^[A-Za-z]:\\$') { continue }
            foreach ($relative in @('Games\Tanki', 'Games\Mir_tankov', 'Games\World_of_Tanks', 'Tanki', 'Lesta\Mir_Tankov')) {
                $paths += Join-Path $drive.Root $relative
            }
        }
        # Read only bounded uninstall metadata; no recursive disk or registry scan.
        foreach ($key in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
                           'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
                           'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
            foreach ($entry in @(Get-ItemProperty $key -ErrorAction SilentlyContinue)) {
                $properties = $entry.PSObject.Properties
                if ($properties['DisplayName'] -and $properties['InstallLocation'] -and
                    $entry.DisplayName -match 'Мир танков|Mir Tankov|World of Tanks|Tanki') { $paths += $entry.InstallLocation }
            }
        }
    }
    $found = @{}
    foreach ($path in $paths) {
        if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path -LiteralPath $path -PathType Container)) { continue }
        try {
            Assert-TankSessionRegularPath $path
            $root = (Get-Item -LiteralPath $path).FullName
            if (-not (Test-Path -LiteralPath (Join-Path $root 'mods') -PathType Container)) { continue }
            foreach ($binary in @('WorldOfTanks.exe', 'Tanki.exe', 'win64\WorldOfTanks.exe', 'win32\WorldOfTanks.exe')) {
                if (Test-Path -LiteralPath (Join-Path $root $binary) -PathType Leaf) { $found[$root] = $root; break }
            }
        } catch { continue }
    }
    return @($found.Values | Sort-Object)
}

function Get-TankSessionPackageBackups([string]$GameRoot, [string]$Version) {
    $folder = Join-Path (Join-Path $GameRoot 'mods') 'tanksession_backups'
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) { return @() }
    Assert-TankSessionRegularPath $folder
    return @(Get-ChildItem -LiteralPath $folder -Directory | Where-Object {
        $_.Name.StartsWith($Version + '-', [StringComparison]::Ordinal) -and
        (Test-Path -LiteralPath (Join-Path $_.FullName 'backup-manifest.json') -PathType Leaf)
    } | Sort-Object Name -Descending | Select-Object -ExpandProperty FullName)
}

function Read-TankSessionPackageBackup([string]$GameRoot, [string]$Version, [string]$Backup) {
    Assert-TankSessionRegularPath $Backup
    $backupRoot = Join-Path (Join-Path $GameRoot 'mods') 'tanksession_backups'
    Assert-TankSessionRegularPath $backupRoot
    $root = (Get-Item -LiteralPath $backupRoot).FullName.TrimEnd('\') + '\'
    $path = (Get-Item -LiteralPath $Backup).FullName
    if (-not $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetDirectoryName($path).TrimEnd('\') -ine $root.TrimEnd('\')) { throw 'Выберите копию из папки tanksession_backups этой игры.' }
    $manifestPath = Join-Path $path 'backup-manifest.json'
    Assert-TankSessionRegularPath $manifestPath
    if ((Get-Item -LiteralPath $manifestPath).Length -gt 65536) { throw 'Слишком большой манифест копии.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.kind -cne 'tanksession-packages' -or $manifest.client_version -cne $Version) { throw 'Копия относится к другой версии клиента.' }
    $seen = @{}
    foreach ($file in @($manifest.files)) {
        if ($file.name -cnotmatch '^ru\.tanksession\.analytics_[0-9A-Za-z._-]+\.mtmod$' -or
            $file.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $seen.ContainsKey($file.name)) { throw 'Некорректный состав резервной копии.' }
        $seen[$file.name] = $true
        $member = Join-Path $path $file.name
        Assert-TankSessionRegularPath $member
        if ((Get-Item -LiteralPath $member).Length -gt 16777216 -or
            (Get-TankSessionHash $member) -cne $file.sha256) { throw 'Повреждён пакет резервной копии.' }
    }
    if ($seen.Count -lt 1 -or $seen.Count -gt 16) { throw 'Некорректное число пакетов копии.' }
    return $manifest
}

function Set-TankSessionPackages([string]$Directory, [string]$GameRoot, [string]$Version, [string]$Restore = '') {
    $bundle = Read-TankSessionBundle $Directory
    $destination = Get-TankSessionDestination $GameRoot $Version $bundle
    Assert-TankSessionGameStopped
    $source = $null
    if ($Restore) { $source = Read-TankSessionPackageBackup $GameRoot $Version $Restore }
    $mods = (Get-Item -LiteralPath $destination).Parent.FullName
    $lockPath = Join-Path $mods '.tanksession-install.lock'
    if (Test-Path -LiteralPath $lockPath) { Assert-TankSessionRegularPath $lockPath }
    $lock = $null; $saved = @(); $installed = @(); $backupPath = $null
    try {
        try { $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw 'Другая операция TankSession уже работает.' }
        $current = @(Get-ChildItem -LiteralPath $destination -File | Where-Object { $_.Name -cmatch '^ru\.tanksession\.analytics_[0-9A-Za-z._-]+\.mtmod$' })
        if ($current.Count -gt 16) { throw 'Обнаружено слишком много пакетов TankSession.' }
        if ($current.Count -gt 0) {
            $backupRoot = Join-Path $mods 'tanksession_backups'
            if (Test-Path -LiteralPath $backupRoot) { Assert-TankSessionRegularPath $backupRoot }
            $backupPath = Join-Path $backupRoot ($Version + '-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
            $null = New-Item -ItemType Directory -Path $backupPath -Force
            foreach ($file in $current) {
                Assert-TankSessionRegularPath $file.FullName
                $hash = Get-TankSessionHash $file.FullName
                $copy = Join-Path $backupPath $file.Name
                Copy-Item -LiteralPath $file.FullName -Destination $copy
                if ((Get-TankSessionHash $copy) -cne $hash) { throw 'Не удалось проверить резервную копию.' }
                $saved += [PSCustomObject]@{ name = $file.Name; sha256 = $hash }
            }
            $manifest = @{ schema = 1; kind = 'tanksession-packages'; client_version = $Version; files = @($saved) }
            [IO.File]::WriteAllText((Join-Path $backupPath 'backup-manifest.json'), ($manifest | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
        }
        Assert-TankSessionGameStopped
        foreach ($file in $saved) {
            $target = Join-Path $destination $file.name
            if ((Get-TankSessionHash $target) -cne $file.sha256) { throw 'Пакет изменился во время операции.' }
            Remove-Item -LiteralPath $target
        }
        if ($null -ne $source) {
            foreach ($file in @($source.files)) {
                $target = Join-Path $destination $file.name
                if (Test-Path -LiteralPath $target) { throw 'Место восстановления уже занято.' }
                $installed += $target
                Copy-Item -LiteralPath (Join-Path $Restore $file.name) -Destination $target
                if ((Get-TankSessionHash $target) -cne $file.sha256) { throw 'Не совпала проверка восстановленного пакета.' }
            }
        }
        return [PSCustomObject]@{ Status = $(if ($Restore) { 'restored' } else { 'uninstalled' }); Backup = $backupPath; Count = $saved.Count }
    } catch {
        $original = $_; $failed = $false
        foreach ($path in $installed) { try { [IO.File]::Delete($path) } catch { $failed = $true } }
        foreach ($file in $saved) {
            try {
                $target = Join-Path $destination $file.name
                if (-not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath (Join-Path $backupPath $file.name) -Destination $target }
                if ((Get-TankSessionHash $target) -cne $file.sha256) { throw 'Откат не завершён.' }
            } catch { $failed = $true }
        }
        if ($failed) { throw ('Откат требует внимания. Резервные пакеты: ' + $backupPath) }
        throw $original
    } finally { if ($null -ne $lock) { $lock.Dispose() } }
}

function ConvertTo-TankSessionSemVer([string]$Value) {
    if ($Value.Length -gt 96 -or $Value -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$') { throw 'Некорректная версия выпуска.' }
    $match = $Matches
    $pre = @()
    if ($match.ContainsKey(4)) { $pre = @($match[4].Split('.')) }
    foreach ($part in $pre) { if ($part -match '^0[0-9]+$') { throw 'Некорректный числовой идентификатор версии.' } }
    return [PSCustomObject]@{ Major = [long]$match[1]; Minor = [long]$match[2]; Patch = [long]$match[3]; Pre = $pre; Text = $Value }
}

function Compare-TankSessionSemVer($A, $B) {
    foreach ($field in @('Major', 'Minor', 'Patch')) {
        if ($A.$field -gt $B.$field) { return 1 }
        if ($A.$field -lt $B.$field) { return -1 }
    }
    if ($A.Pre.Count -eq 0 -and $B.Pre.Count -gt 0) { return 1 }
    if ($B.Pre.Count -eq 0 -and $A.Pre.Count -gt 0) { return -1 }
    for ($i = 0; $i -lt [Math]::Min($A.Pre.Count, $B.Pre.Count); $i++) {
        $left = $A.Pre[$i]; $right = $B.Pre[$i]
        if ($left -ceq $right) { continue }
        $ln = $left -cmatch '^[0-9]+$'; $rn = $right -cmatch '^[0-9]+$'
        if ($ln -and $rn) {
            if ($left.Length -ne $right.Length) { return [Math]::Sign($left.Length - $right.Length) }
        } elseif ($ln -ne $rn) { if ($ln) { return -1 }; return 1 }
        return [Math]::Sign([string]::CompareOrdinal($left, $right))
    }
    return [Math]::Sign($A.Pre.Count - $B.Pre.Count)
}

function Select-TankSessionUpdate([object[]]$Releases, [string]$Current, [bool]$IncludePrerelease = $false) {
    $installed = ConvertTo-TankSessionSemVer $Current
    $newest = $installed; $candidate = $null
    foreach ($release in $Releases) {
        try {
            if ($release.draft -ne $false -or ($release.prerelease -ne $false -and -not $IncludePrerelease) -or
                $release.tag_name -cnotmatch '^v[0-9]') { continue }
            $version = ConvertTo-TankSessionSemVer $release.tag_name.Substring(1)
            if (($version.Pre.Count -gt 0) -ne [bool]$release.prerelease) { continue }
            if ((Compare-TankSessionSemVer $version $newest) -le 0) { continue }
            $asset = @($release.assets | Where-Object { $_.name -ceq ('TankSession_Analytics_' + $version.Text + '_Windows.zip') -and $_.state -ceq 'uploaded' })
            if ($asset.Count -ne 1) { continue }
            $newest = $version; $candidate = $version.Text
        } catch { continue }
    }
    return [PSCustomObject]@{ Current = $Current; Available = $candidate; Url = $(if ($candidate) { 'https://github.com/xeemoff/tanksession-analytics/releases/tag/v' + $candidate } else { 'https://github.com/xeemoff/tanksession-analytics/releases' }) }
}

function Get-TankSessionUpdate([string]$Current, [bool]$IncludePrerelease = $false, [scriptblock]$Progress = $null) {
    $response = @(Get-TankSessionReleaseJson '?per_page=100' $Progress)
    return Select-TankSessionUpdate $response $Current $IncludePrerelease
}

. (Join-Path $PSScriptRoot 'Update-TankSession.ps1')
