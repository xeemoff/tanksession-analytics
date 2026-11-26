#requires -Version 5.1
<#
TankSession Analytics offline installer. Run from the extracted Windows ZIP.
Only this project's .mtmod files inside one explicitly selected version are
replaced. Account journals, settings and unrelated mods are never modified.
#>
[CmdletBinding()]
param(
    [string]$GamePath,
    [string]$ClientVersion,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-TankSessionHash([string]$Path) {
    # Windows PowerShell launched through another runtime can inherit a
    # PowerShell Core PSModulePath where the Get-FileHash function is unavailable.
    # Hash the file directly with the .NET runtime already required by this script.
    $stream = [IO.File]::OpenRead($Path)
    try {
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $hasher.Dispose() }
    } finally { $stream.Dispose() }
}

function Assert-TankSessionRegularPath([string]$Path) {
    # Reject directory junctions as well as symlinks before deriving paths.
    $current = Get-Item -LiteralPath $Path -Force
    while ($null -ne $current) {
        if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Путь содержит ссылку или junction: $($current.FullName)"
        }
        if ($current -is [IO.DirectoryInfo]) { $current = $current.Parent }
        else { $current = $current.Directory }
    }
}

function Assert-TankSessionGameStopped {
    # Conservative: a running second installation is also a reason to stop.
    $running = @(Get-Process -Name 'WorldOfTanks', 'Tanki' -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        throw 'Закройте клиент «Мира танков» перед установкой. Установщик не завершает процессы.'
    }
}

function Read-TankSessionBundle([string]$Directory) {
    Assert-TankSessionRegularPath $Directory
    $manifestPath = Join-Path $Directory 'manifest.json'
    Assert-TankSessionRegularPath $manifestPath
    if ((Get-Item -LiteralPath $manifestPath).Length -gt 65536) { throw 'Слишком большой manifest.json.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.id -cne 'ru.tanksession.analytics') {
        throw 'Неподдерживаемый manifest.json.'
    }
    if ($manifest.version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$' -or
        $manifest.package -cne ('ru.tanksession.analytics_' + $manifest.version + '.mtmod') -or
        $manifest.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw 'Некорректные имя, версия или контрольная сумма пакета.'
    }
    if ($manifest.channel -notin @('stable', 'prerelease') -or
        $manifest.native_validation -notin @('pending', 'verified') -or
        ($manifest.channel -eq 'stable' -and $manifest.native_validation -ne 'verified')) {
        throw 'Некорректный статус выпуска.'
    }
    $versions = @($manifest.client_versions)
    if ($versions.Count -eq 0 -or $versions.Count -gt 8) { throw 'Не указана версия клиента.' }
    foreach ($version in $versions) {
        if ($version -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw 'Некорректная версия клиента.' }
    }
    $packagePath = Join-Path $Directory $manifest.package
    Assert-TankSessionRegularPath $packagePath
    $package = Get-Item -LiteralPath $packagePath
    if ($package.PSIsContainer -or $package.Length -gt 16777216 -or
        $package.Length -ne $manifest.package_size) { throw 'Некорректный размер .mtmod.' }
    if ((Get-TankSessionHash $packagePath) -cne $manifest.sha256.ToLowerInvariant()) {
        throw 'SHA-256 пакета не совпадает. Скачайте архив заново.'
    }
    $sidecarPath = $packagePath + '.sha256'
    Assert-TankSessionRegularPath $sidecarPath
    if ((Get-Item -LiteralPath $sidecarPath).Length -gt 512) { throw 'Некорректный файл SHA-256.' }
    $sidecar = (Get-Content -LiteralPath $sidecarPath -Raw -Encoding ASCII).Trim()
    if ($sidecar -cne ($manifest.sha256.ToLowerInvariant() + '  ' + $manifest.package)) {
        throw 'Файл контрольной суммы отличается от manifest.json.'
    }
    $expected = @{}
    foreach ($member in @($manifest.members)) {
        if ($expected.ContainsKey($member.path) -or $member.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
            $member.size -lt 1 -or $member.size -gt 2097152) { throw 'Некорректный список файлов .mtmod.' }
        $expected[$member.path] = $member
    }
    if ($expected.Count -lt 8 -or $expected.Count -gt 128) { throw 'Некорректное число файлов .mtmod.' }
    $mandatory = @(
        'meta.xml',
        'res/scripts/client/gui/mods/mod_tanksession_analytics.pyc',
        'res/scripts/client/gui/mods/tanksession_analytics/__init__.pyc',
        'res/scripts/client/gui/mods/tanksession_analytics/game.pyc',
        'res/scripts/client/gui/mods/tanksession_analytics/core.pyc',
        'res/scripts/client/gui/mods/tanksession_analytics/economy.pyc',
        'res/scripts/client/gui/mods/tanksession_analytics/storage.pyc',
        'res/scripts/client/gui/mods/tanksession_analytics/vehicles.pyc',
        'res/gui/gameface/mods/tanksession/Analytics.html',
        'res/gui/gameface/mods/tanksession/app.js',
        'res/gui/gameface/mods/tanksession/app.css',
        'res/gui/gameface/mods/tanksession/THIRD_PARTY_LICENSES.txt',
        'res/mods/configs/res_map/ru.tanksession.analytics.json'
    )
    foreach ($name in $mandatory) {
        if (-not $expected.ContainsKey($name)) { throw "Нет обязательного файла $name" }
    }
    $archive = [IO.Compression.ZipFile]::OpenRead($packagePath)
    try {
        if ($archive.Entries.Count -ne $expected.Count) { throw 'Состав .mtmod отличается от manifest.json.' }
        $seen = @{}
        [long]$expandedSize = 0
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName
            if ($seen.ContainsKey($name) -or -not $expected.ContainsKey($name) -or
                $name.Contains('\') -or $name.Contains(':') -or
                $name -match '(^|/)(\.|\.\.|)(/|$)' -or $name.StartsWith('/')) {
                throw 'Повторяющийся или небезопасный путь в .mtmod.'
            }
            $allowed = ($mandatory -ccontains $name) -or
                ($name -cmatch '^res/scripts/client/gui/mods/tanksession_analytics/[a-z_]+\.pyc$')
            if (-not $allowed) { throw "Посторонний файл в .mtmod: $name" }
            $seen[$name] = $true
            $expandedSize += $entry.Length
            if ($entry.Length -gt 2097152 -or $entry.Length -ne $expected[$name].size -or
                $entry.CompressedLength -ne $entry.Length -or $expandedSize -gt 16777216) {
                throw 'Неподдерживаемое сжатие или размер внутри .mtmod.'
            }
            $inputStream = $entry.Open()
            $memory = New-Object IO.MemoryStream
            try {
                $inputStream.CopyTo($memory)
                $bytes = $memory.ToArray()
                $hasher = [Security.Cryptography.SHA256]::Create()
                try { $hash = [BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant() }
                finally { $hasher.Dispose() }
                if ($hash -cne $expected[$name].sha256.ToLowerInvariant()) { throw 'Повреждён файл внутри .mtmod.' }
                if ($name.EndsWith('.pyc') -and ($bytes.Length -le 8 -or
                    $bytes[0] -ne 3 -or $bytes[1] -ne 243 -or $bytes[2] -ne 13 -or $bytes[3] -ne 10 -or $bytes[8] -ne 99)) {
                    throw 'Пакет содержит неподдерживаемый Python-байткод.'
                }
                if ($name -ceq 'meta.xml') {
                    $xmlSettings = New-Object Xml.XmlReaderSettings
                    $xmlSettings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
                    $xmlSettings.XmlResolver = $null
                    $textReader = New-Object IO.StringReader ([Text.Encoding]::UTF8.GetString($bytes))
                    $xmlReader = [Xml.XmlReader]::Create($textReader, $xmlSettings)
                    try {
                        $metadata = New-Object Xml.XmlDocument
                        $metadata.XmlResolver = $null
                        $metadata.Load($xmlReader)
                        # The PowerShell XML adapter exposes child elements as
                        # properties: <name> shadows XmlElement.Name. Call the
                        # CLR getters and XPath methods explicitly instead.
                        $documentRoot = $metadata.get_DocumentElement()
                        if ($null -eq $documentRoot -or $documentRoot.get_Name() -cne 'root') {
                            throw 'Метаданные .mtmod не совпадают с manifest.json: ожидается корневой элемент root.'
                        }
                        $idNode = $documentRoot.SelectSingleNode('id')
                        $versionNode = $documentRoot.SelectSingleNode('version')
                        if ($null -eq $idNode -or $null -eq $versionNode -or
                            $idNode.get_InnerText() -cne $manifest.id -or
                            $versionNode.get_InnerText() -cne $manifest.version) {
                            throw 'Метаданные .mtmod не совпадают с manifest.json.'
                        }
                    } finally { $xmlReader.Dispose(); $textReader.Dispose() }
                }
            } finally { $inputStream.Dispose(); $memory.Dispose() }
        }
    } finally { $archive.Dispose() }
    return $manifest
}

function Get-TankSessionDestination([string]$Path, [string]$Version, $Manifest) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw 'Укажите существующую папку установленной игры.'
    }
    Assert-TankSessionRegularPath $Path
    $root = (Get-Item -LiteralPath $Path).FullName
    $gameFound = $false
    foreach ($name in @('WorldOfTanks.exe', 'Tanki.exe', 'win64\WorldOfTanks.exe', 'win32\WorldOfTanks.exe')) {
        if (Test-Path -LiteralPath (Join-Path $root $name) -PathType Leaf) { $gameFound = $true }
    }
    if (-not $gameFound) { throw 'В указанной папке не найден исполняемый файл игры.' }
    if ([string]::IsNullOrWhiteSpace($Version) -or $Version -notmatch '^\d+\.\d+\.\d+\.\d+$') {
        throw 'Укажите точную версию клиента, например 1.46.0.0. Автоматический выбор не выполняется.'
    }
    if (@($Manifest.client_versions) -cnotcontains $Version) {
        throw "Этот пакет не предназначен для клиента $Version. Проверьте описание выпуска."
    }
    $destination = Join-Path (Join-Path $root 'mods') $Version
    if (-not (Test-Path -LiteralPath $destination -PathType Container)) {
        throw "Нет папки mods\$Version. Уточните путь к игре и версию клиента."
    }
    Assert-TankSessionRegularPath $destination
    return $destination
}

function Install-TankSessionBundle([string]$Directory, [string]$Path, [string]$Version, [bool]$ValidateOnly = $false) {
    $manifest = Read-TankSessionBundle $Directory
    $destination = Get-TankSessionDestination $Path $Version $manifest
    if (Test-Path -LiteralPath (Join-Path $destination $manifest.package) -PathType Container) {
        throw 'На месте пакета находится каталог. Уберите конфликт имён перед установкой.'
    }
    Assert-TankSessionGameStopped
    $oldPackages = @(Get-ChildItem -LiteralPath $destination -File | Where-Object {
        $_.Name -cmatch '^ru\.tanksession\.analytics_[0-9A-Za-z._-]+\.mtmod$'
    })
    foreach ($old in $oldPackages) { Assert-TankSessionRegularPath $old.FullName }
    if ($ValidateOnly) {
        return [PSCustomObject]@{ Status = 'checked'; Version = $manifest.version; ExistingPackages = $oldPackages.Count; Backup = $null }
    }
    $mods = (Get-Item -LiteralPath $destination).Parent.FullName
    $lockPath = Join-Path $mods '.tanksession-install.lock'
    if (Test-Path -LiteralPath $lockPath) { Assert-TankSessionRegularPath $lockPath }
    $lock = $null
    $temporary = Join-Path $destination ('.tanksession-' + [Guid]::NewGuid().ToString('N') + '.pending')
    $target = Join-Path $destination $manifest.package
    $backupPath = $null
    $backups = @()
    $installed = $false
    try {
        try { $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw 'Другой установщик уже работает или нет доступа к папке mods.' }
        # Rescan after taking the lock, before creating the backup transaction.
        $oldPackages = @(Get-ChildItem -LiteralPath $destination -File | Where-Object {
            $_.Name -cmatch '^ru\.tanksession\.analytics_[0-9A-Za-z._-]+\.mtmod$'
        })
        foreach ($old in $oldPackages) { Assert-TankSessionRegularPath $old.FullName }
        Copy-Item -LiteralPath (Join-Path $Directory $manifest.package) -Destination $temporary
        if ((Get-TankSessionHash $temporary) -cne $manifest.sha256.ToLowerInvariant()) { throw 'Ошибка проверки временной копии.' }
        if ($oldPackages.Count -gt 0) {
            $backupRoot = Join-Path $mods 'tanksession_backups'
            if (Test-Path -LiteralPath $backupRoot) { Assert-TankSessionRegularPath $backupRoot }
            $backupPath = Join-Path $backupRoot ($Version + '-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
            $null = New-Item -ItemType Directory -Path $backupPath
            foreach ($old in $oldPackages) {
                $oldHash = Get-TankSessionHash $old.FullName
                $copy = Join-Path $backupPath $old.Name
                Copy-Item -LiteralPath $old.FullName -Destination $copy
                if ((Get-TankSessionHash $copy) -cne $oldHash) { throw 'Ошибка проверки резервной копии.' }
                $backups += [PSCustomObject]@{ Original = $old.FullName; Copy = $copy; Hash = $oldHash }
            }
        }
        Assert-TankSessionGameStopped
        foreach ($backup in $backups) {
            if ((Get-TankSessionHash $backup.Original) -cne $backup.Hash) { throw 'Старый пакет изменился во время установки.' }
            Remove-Item -LiteralPath $backup.Original
        }
        Move-Item -LiteralPath $temporary -Destination $target
        $installed = $true
        if ((Get-TankSessionHash $target) -cne $manifest.sha256.ToLowerInvariant()) { throw 'Ошибка итоговой проверки.' }
        return [PSCustomObject]@{ Status = 'installed'; Version = $manifest.version; ExistingPackages = $oldPackages.Count; Backup = $backupPath }
    } catch {
        $originalError = $_
        $rollbackErrors = @()
        if ($installed -and (Test-Path -LiteralPath $target)) {
            try { Remove-Item -LiteralPath $target } catch { $rollbackErrors += 'Не удалось удалить новый пакет.' }
        }
        foreach ($backup in $backups) {
            try {
                if (-not (Test-Path -LiteralPath $backup.Original)) {
                    Copy-Item -LiteralPath $backup.Copy -Destination $backup.Original
                }
                if ((Get-TankSessionHash $backup.Original) -cne $backup.Hash) { throw 'Неполный откат.' }
            } catch { $rollbackErrors += 'Не удалось восстановить ' + [IO.Path]::GetFileName($backup.Original) }
        }
        if ($rollbackErrors.Count -gt 0) {
            throw ($originalError.Exception.Message + ' Откат требует внимания: ' + ($rollbackErrors -join ' ') + ' Резервная копия: ' + $backupPath)
        }
        throw $originalError
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -ErrorAction SilentlyContinue }
        if ($null -ne $lock) { $lock.Dispose() }
    }
}

function Invoke-TankSessionInstaller {
    try {
        if ([string]::IsNullOrWhiteSpace($GamePath)) { $script:GamePath = (Read-Host 'Полный путь к игре, например C:\Games\Tanki').Trim().Trim('"') }
        if ([string]::IsNullOrWhiteSpace($ClientVersion)) { $script:ClientVersion = (Read-Host 'Версия клиента — имя папки внутри mods, например 1.46.0.0').Trim() }
        $result = Install-TankSessionBundle $PSScriptRoot $GamePath $ClientVersion ([bool]$CheckOnly)
        if ($result.Status -eq 'checked') { Write-Host 'Проверка выполнена. Файлы игры не изменены.' }
        else {
            Write-Host ('Установлен TankSession Analytics ' + $result.Version)
            Write-Host 'История, настройки и остальные моды сохранены.'
            if ($result.Backup) { Write-Host ('Предыдущие пакеты: ' + $result.Backup) }
        }
        Write-Host 'Статус совместимости, Gameface и известные ограничения — в INSTALL_RU.md и RELEASE_NOTES_RU.md.'
        exit 0
    } catch {
        Write-Host ('Установка остановлена: ' + $_.Exception.Message) -ForegroundColor Red
        exit 1
    }
}

# Dot-sourcing exposes pure checks/transaction functions for Windows CI.
if ($MyInvocation.InvocationName -ne '.') { Invoke-TankSessionInstaller }
