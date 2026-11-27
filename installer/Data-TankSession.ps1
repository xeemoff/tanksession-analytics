#requires -Version 5.1
# Offline, snapshot-based history transfer. Dot-source Install-TankSession.ps1 first.

function Test-TankSessionDataName([string]$Name) {
    return ($Name -cin @('battles.jsonl', 'settings.json', 'goals.json')) -or
        ($Name -cmatch '^profiles/[0-9a-f]{64}\.json$')
}

function Get-TankSessionDataRoot([string]$GameRoot) {
    if (-not (Test-Path -LiteralPath $GameRoot -PathType Container)) { throw 'Папка игры не найдена.' }
    Assert-TankSessionRegularPath $GameRoot
    $mods = Join-Path (Get-Item -LiteralPath $GameRoot).FullName 'mods'
    if (-not (Test-Path -LiteralPath $mods -PathType Container)) { throw 'Папка mods не найдена.' }
    Assert-TankSessionRegularPath $mods
    $configs = Join-Path $mods 'configs'
    if (Test-Path -LiteralPath $configs) { Assert-TankSessionRegularPath $configs }
    $root = Join-Path $configs 'tanksession_analytics'
    if (Test-Path -LiteralPath $root) { Assert-TankSessionRegularPath $root }
    return $root
}

function Get-TankSessionDataFiles([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return @() }
    Assert-TankSessionRegularPath $Root
    $files = @()
    foreach ($name in @('battles.jsonl', 'settings.json', 'goals.json')) {
        $path = Join-Path $Root $name
        if (Test-Path -LiteralPath $path) {
            Assert-TankSessionRegularPath $path
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Вместо файла истории обнаружен каталог.' }
            $files += [PSCustomObject]@{ Name = $name; Path = $path }
        }
    }
    $profiles = Join-Path $Root 'profiles'
    if (Test-Path -LiteralPath $profiles) {
        Assert-TankSessionRegularPath $profiles
        foreach ($file in @(Get-ChildItem -LiteralPath $profiles -File | Sort-Object Name)) {
            if ($file.Name -cmatch '^[0-9a-f]{64}\.json$') {
                Assert-TankSessionRegularPath $file.FullName
                $files += [PSCustomObject]@{ Name = ('profiles/' + $file.Name); Path = $file.FullName }
            }
        }
    }
    if ($files.Count -gt 512) { throw 'Слишком много профилей для архива.' }
    return $files
}

function New-TankSessionBackupPath([string]$GameRoot, [string]$Kind) {
    if ($Kind -notin @('data', 'packages')) { throw 'Неизвестный вид резервной копии.' }
    $folder = Join-Path (Join-Path $GameRoot 'mods') ('tanksession_' + $Kind + '_backups')
    if (Test-Path -LiteralPath $folder) { Assert-TankSessionRegularPath $folder }
    else { $null = New-Item -ItemType Directory -Path $folder }
    return Join-Path $folder ([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
}

function Export-TankSessionHistory([string]$GameRoot, [string]$ArchivePath) {
    Assert-TankSessionGameStopped
    $root = Get-TankSessionDataRoot $GameRoot
    $files = @(Get-TankSessionDataFiles $root)
    if ($files.Count -eq 0) { throw 'Нет истории или настроек для сохранения.' }
    $archiveFull = [IO.Path]::GetFullPath($ArchivePath)
    $parent = [IO.Path]::GetDirectoryName($archiveFull)
    Assert-TankSessionRegularPath $parent
    if (Test-Path -LiteralPath $archiveFull) { throw 'Архив уже существует. Выберите новое имя.' }
    # Sharing.Read prevents modification of an input while its bytes are copied.
    $temporary = Join-Path $parent ('.tanksession-export-' + [Guid]::NewGuid().ToString('N'))
    $archive = $null
    try {
        $archive = [IO.Compression.ZipFile]::Open($temporary, [IO.Compression.ZipArchiveMode]::Create)
        $members = @()
        [long]$total = 0
        foreach ($file in $files) {
            $input = [IO.File]::Open($file.Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            try {
                $total += $input.Length
                if ($input.Length -gt 134217728 -or $total -gt 268435456) { throw 'История превышает предел архива: 128 МиБ на файл, 256 МиБ всего.' }
                $hasher = [Security.Cryptography.SHA256]::Create()
                try { $digest = [BitConverter]::ToString($hasher.ComputeHash($input)).Replace('-', '').ToLowerInvariant() }
                finally { $hasher.Dispose() }
                $input.Position = 0
                $entry = $archive.CreateEntry($file.Name, [IO.Compression.CompressionLevel]::Optimal)
                $out = $entry.Open()
                try { $input.CopyTo($out) } finally { $out.Dispose() }
                $members += [PSCustomObject]@{ path = $file.Name; size = $input.Length; sha256 = $digest }
            } finally { $input.Dispose() }
        }
        $manifest = @{ schema = 1; kind = 'tanksession-history'; created_at = [DateTime]::UtcNow.ToString('o'); files = @($members) }
        $entry = $archive.CreateEntry('history-manifest.json', [IO.Compression.CompressionLevel]::Optimal)
        $out = $entry.Open()
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes(($manifest | ConvertTo-Json -Depth 6 -Compress))
            $out.Write($bytes, 0, $bytes.Length)
        } finally { $out.Dispose() }
        $archive.Dispose(); $archive = $null
        # Reopen and verify every copied byte before publishing the archive.
        $null = Read-TankSessionHistoryArchive $temporary
        [IO.File]::Move($temporary, $archiveFull)
        return [PSCustomObject]@{ Status = 'exported'; Path = $archiveFull; Files = $members.Count; Sha256 = (Get-TankSessionHash $archiveFull) }
    } finally {
        if ($null -ne $archive) { $archive.Dispose() }
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Read-TankSessionHistoryArchive([string]$ArchivePath, [string]$Staging = '') {
    Assert-TankSessionRegularPath $ArchivePath
    if ((Get-Item -LiteralPath $ArchivePath).Length -gt 285212672) { throw 'Архив истории слишком велик.' }
    $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        if ($archive.Entries.Count -lt 2 -or $archive.Entries.Count -gt 513) { throw 'Неверный состав архива истории.' }
        $manifestEntry = $archive.GetEntry('history-manifest.json')
        if ($null -eq $manifestEntry -or $manifestEntry.Length -gt 131072) { throw 'Нет допустимого манифеста истории.' }
        $reader = New-Object IO.StreamReader ($manifestEntry.Open()), ([Text.Encoding]::UTF8), $true
        try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($manifest.schema -ne 1 -or $manifest.kind -cne 'tanksession-history') { throw 'Неизвестный формат истории.' }
        $expected = @{}
        [long]$expanded = 0
        foreach ($member in @($manifest.files)) {
            if (-not (Test-TankSessionDataName $member.path) -or $expected.ContainsKey($member.path) -or
                $member.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
                $member.size -isnot [ValueType] -or $member.size -is [bool] -or
                $member.size -lt 0 -or $member.size -gt 134217728 -or
                [long]$member.size -ne $member.size) { throw 'Некорректный файл в манифесте истории.' }
            $expanded += $member.size
            if ($expanded -gt 268435456) { throw 'Слишком большой распакованный архив.' }
            $expected[$member.path] = $member
        }
        if ($expected.Count -lt 1 -or $expected.Count -gt 512 -or $expected.Count + 1 -ne $archive.Entries.Count) {
            throw 'Состав архива отличается от манифеста истории.'
        }
        $seen = @{}
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName
            if ($seen.ContainsKey($name)) { throw 'Повторяющееся имя в архиве истории.' }
            $seen[$name] = $true
            if ($name -ceq 'history-manifest.json') { continue }
            if (-not (Test-TankSessionDataName $name) -or -not $expected.ContainsKey($name) -or
                $entry.Length -ne $expected[$name].size) { throw 'Небезопасный путь или размер в архиве истории.' }
            $input = $entry.Open()
            try {
                $hasher = [Security.Cryptography.SHA256]::Create()
                try { $digest = [BitConverter]::ToString($hasher.ComputeHash($input)).Replace('-', '').ToLowerInvariant() }
                finally { $hasher.Dispose() }
            } finally { $input.Dispose() }
            if ($digest -cne $expected[$name].sha256) { throw 'SHA-256 файла истории не совпадает.' }
            if (-not [string]::IsNullOrEmpty($Staging)) {
                $destination = Join-Path $Staging ($name.Replace('/', [IO.Path]::DirectorySeparatorChar))
                $folder = [IO.Path]::GetDirectoryName($destination)
                if (-not (Test-Path -LiteralPath $folder)) { $null = New-Item -ItemType Directory -Path $folder }
                $input = $entry.Open()
                $output = [IO.File]::Open($destination, [IO.FileMode]::CreateNew)
                try { $input.CopyTo($output); $output.Flush($true) } finally { $output.Dispose(); $input.Dispose() }
                if ((Get-TankSessionHash $destination) -cne $expected[$name].sha256) { throw 'Изменились данные при распаковке истории.' }
            }
        }
        return $manifest
    } finally { $archive.Dispose() }
}

function Import-TankSessionHistory([string]$GameRoot, [string]$ArchivePath) {
    Assert-TankSessionGameStopped
    $root = Get-TankSessionDataRoot $GameRoot
    $mods = Join-Path $GameRoot 'mods'
    $lockPath = Join-Path $mods '.tanksession-install.lock'
    if (Test-Path -LiteralPath $lockPath) { Assert-TankSessionRegularPath $lockPath }
    $lock = $null; $stage = $null; $backup = $null; $applied = @()
    try {
        try { $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw 'Другая операция TankSession уже работает.' }
        $stage = Join-Path $mods ('.tanksession-import-' + [Guid]::NewGuid().ToString('N'))
        $null = New-Item -ItemType Directory -Path $stage
        $manifest = Read-TankSessionHistoryArchive $ArchivePath $stage
        $existing = @(Get-TankSessionDataFiles $root)
        if ($existing.Count -gt 0) {
            $backup = (New-TankSessionBackupPath $GameRoot 'data') + '.zip'
            $null = Export-TankSessionHistory $GameRoot $backup
        }
        # A verified old snapshot exists before any destination can be replaced.
        $rollback = Join-Path $stage '_rollback'
        $null = New-Item -ItemType Directory -Path $rollback
        if (-not (Test-Path -LiteralPath $root)) { $null = New-Item -ItemType Directory -Path $root -Force }
        Assert-TankSessionRegularPath $root
        foreach ($member in @($manifest.files)) {
            Assert-TankSessionGameStopped
            $relative = $member.path.Replace('/', [IO.Path]::DirectorySeparatorChar)
            $destination = Join-Path $root $relative
            $parent = [IO.Path]::GetDirectoryName($destination)
            if (Test-Path -LiteralPath $parent) { Assert-TankSessionRegularPath $parent }
            else { $null = New-Item -ItemType Directory -Path $parent }
            $previous = $null
            if (Test-Path -LiteralPath $destination) {
                Assert-TankSessionRegularPath $destination
                if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw 'Файл истории перекрыт каталогом.' }
                $previous = Join-Path $rollback ([Guid]::NewGuid().ToString('N'))
                [IO.File]::Replace((Join-Path $stage $relative), $destination, $previous)
            } else { [IO.File]::Move((Join-Path $stage $relative), $destination) }
            $applied += [PSCustomObject]@{ Destination = $destination; Previous = $previous }
            if ((Get-TankSessionHash $destination) -cne $member.sha256) { throw 'Не совпала проверка установленной истории.' }
        }
        return [PSCustomObject]@{ Status = 'imported'; Files = @($manifest.files).Count; Backup = $backup }
    } catch {
        $original = $_; $failed = $false
        for ($i = $applied.Count - 1; $i -ge 0; $i--) {
            try {
                $item = $applied[$i]
                if ($null -ne $item.Previous) { [IO.File]::Replace($item.Previous, $item.Destination, $null) }
                else { [IO.File]::Delete($item.Destination) }
            } catch { $failed = $true }
        }
        if ($failed) {
            $savedStage = $stage; $stage = $null
            throw ('Импорт не завершён; сохранена копия ' + $backup + '. Файлы для ручного восстановления: ' + $savedStage)
        }
        throw $original
    } finally {
        if ($null -ne $stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Recurse -Force }
        if ($null -ne $lock) { $lock.Dispose() }
    }
}
