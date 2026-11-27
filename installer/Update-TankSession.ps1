#requires -Version 5.1
# Loaded only by the trusted local manager. No network or execution on import.

function Send-TankSessionProgress([scriptblock]$Progress, [string]$Stage, [long]$Done = 0, [long]$Total = 0) {
    if ($null -ne $Progress) { $null = & $Progress $Stage $Done $Total }
}

function Assert-TankSessionDownloadUri([Uri]$Uri, [bool]$Redirect = $false, [bool]$Api = $false) {
    if (-not $Uri.IsAbsoluteUri -or $Uri.Scheme -cne 'https' -or $Uri.Port -ne 443 -or
        $Uri.UserInfo -or $Uri.Fragment) { throw 'Недопустимый адрес загрузки.' }
    if ($Api) {
        if ($Redirect -or $Uri.Host -cne 'api.github.com' -or
            $Uri.AbsolutePath -cnotmatch '^/repos/xeemoff/tanksession-analytics/releases(?:/tags/v[0-9A-Za-z.-]+)?$' -or
            ($Uri.Query -and $Uri.Query -cne '?per_page=100')) { throw 'Недопустимый адрес сервиса выпусков.' }
    } elseif (-not $Redirect) {
        if ($Uri.Host -cne 'github.com' -or $Uri.Query -or
            $Uri.AbsolutePath -cnotmatch '^/xeemoff/tanksession-analytics/releases/download/v[0-9A-Za-z.-]+/TankSession_Analytics_[0-9A-Za-z.-]+_Windows\.zip(?:\.sha256)?$') {
            throw 'Допускаются только файлы официального выпуска TankSession.'
        }
    } elseif ($Uri.Host -cnotin @('release-assets.githubusercontent.com', 'objects.githubusercontent.com', 'github-releases.githubusercontent.com')) {
        throw 'GitHub перенаправил загрузку на неподдерживаемый сервер.'
    }
}

function Wait-TankSessionNetwork($Async, $Request, $Clock, [scriptblock]$Progress, [string]$Stage, [long]$Done, [long]$Total) {
    # HttpWebRequest.Timeout does not cover BeginGetResponse/BeginRead. This
    # monotonic whole-request deadline also covers redirects and stalled reads.
    while (-not $Async.AsyncWaitHandle.WaitOne(50)) {
        Send-TankSessionProgress $Progress $Stage $Done $Total
        if ($Clock.Elapsed.TotalSeconds -gt 120) { $Request.Abort(); throw 'Истекло время загрузки. Попробуйте ещё раз.' }
    }
    if ($Clock.Elapsed.TotalSeconds -gt 120) { $Request.Abort(); throw 'Истекло время загрузки.' }
}

function Receive-TankSessionFile([string]$Url, [string]$Destination, [long]$Limit,
                                 [scriptblock]$Progress = $null, [string]$Stage = 'Загрузка', [bool]$Api = $false) {
    if ($Limit -lt 1 -or $Limit -gt 33554432) { throw 'Недопустимый предел загрузки.' }
    Assert-TankSessionRegularPath ([IO.Path]::GetDirectoryName($Destination))
    if (Test-Path -LiteralPath $Destination) { throw 'Место загрузки уже занято.' }
    $uri = [Uri]$Url
    Assert-TankSessionDownloadUri $uri $false $Api
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $output = $null; $request = $null; $response = $null; $inputStream = $null
    try {
        for ($redirect = 0; $redirect -le 4; $redirect++) {
            $request = [Net.HttpWebRequest]::Create($uri)
            $request.AllowAutoRedirect = $false; $request.Method = 'GET'
            $request.UserAgent = 'TankSession-Manager'; $request.Timeout = 15000; $request.ReadWriteTimeout = 15000
            $request.AutomaticDecompression = [Net.DecompressionMethods]::None
            $request.Accept = $(if ($Api) { 'application/vnd.github+json' } else { 'application/octet-stream' })
            $async = $request.BeginGetResponse($null, $null)
            try {
                Wait-TankSessionNetwork $async $request $clock $Progress $Stage 0 0
                $response = $request.EndGetResponse($async)
            } finally { $async.AsyncWaitHandle.Close() }
            $status = [int]$response.StatusCode
            if ($status -in @(301, 302, 303, 307, 308)) {
                if ($Api -or $redirect -eq 4) { throw 'Неожиданное перенаправление сервиса выпусков.' }
                $next = New-Object Uri $uri, $response.Headers['Location']
                Assert-TankSessionDownloadUri $next $true $false
                $response.Close(); $response = $null; $uri = $next
                continue
            }
            if ($status -ne 200 -or $response.ContentLength -gt $Limit) { throw 'Недопустимый ответ или размер загрузки.' }
            $output = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $inputStream = $response.GetResponseStream()
            $buffer = New-Object byte[] 65536
            [long]$total = 0
            while ($true) {
                $async = $inputStream.BeginRead($buffer, 0, $buffer.Length, $null, $null)
                try {
                    Wait-TankSessionNetwork $async $request $clock $Progress $Stage $total $response.ContentLength
                    $count = $inputStream.EndRead($async)
                } finally { $async.AsyncWaitHandle.Close() }
                if ($count -eq 0) { break }
                $total += $count
                if ($total -gt $Limit) { throw 'Загрузка превысила допустимый размер.' }
                $output.Write($buffer, 0, $count)
                Send-TankSessionProgress $Progress $Stage $total $response.ContentLength
            }
            if ($response.ContentLength -ge 0 -and $total -ne $response.ContentLength) { throw 'Загрузка оборвалась до получения всего файла.' }
            $output.Flush($true)
            return
        }
        throw 'Не удалось завершить загрузку.'
    } catch {
        if ($null -ne $request) { $request.Abort() }
        throw ('Загрузка остановлена: ' + $(if ($_.Exception -is [Net.WebException]) { 'GitHub недоступен или соединение прервано.' } else { $_.Exception.Message }))
    } finally {
        if ($null -ne $inputStream) { $inputStream.Dispose() }
        if ($null -ne $output) { $output.Dispose() }
        if ($null -ne $response) { $response.Close() }
        $clock.Stop()
    }
}

function Remove-TankSessionStage([string]$Directory, [string]$Parent) {
    # Our temporary/staged bundles are flat. Never recurse through a substituted
    # junction, unexpected directory or caller-controlled path during cleanup.
    Assert-TankSessionRegularPath $Parent
    Assert-TankSessionRegularPath $Directory
    $item = Get-Item -Force -LiteralPath $Directory
    $trim = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $parentPath = (Get-Item -Force -LiteralPath $Parent).FullName.TrimEnd($trim)
    if (-not $item.PSIsContainer -or $item.Parent.FullName.TrimEnd($trim) -ine $parentPath) { throw 'Некорректная временная папка.' }
    $children = @(Get-ChildItem -LiteralPath $Directory -Force)
    foreach ($child in $children) {
        Assert-TankSessionRegularPath $child.FullName
        if ($child.PSIsContainer) { throw 'Неожиданный каталог во временной папке.' }
    }
    foreach ($child in $children) { [IO.File]::Delete($child.FullName) }
    [IO.Directory]::Delete($Directory, $false)
}

function Get-TankSessionReleaseJson([string]$Suffix, [scriptblock]$Progress = $null) {
    $folder = Join-Path ([IO.Path]::GetTempPath()) ('tanksession-check-' + [Guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $folder
    try {
        Assert-TankSessionRegularPath $folder
        $path = Join-Path $folder 'releases.json'
        Receive-TankSessionFile ('https://api.github.com/repos/xeemoff/tanksession-analytics/releases' + $Suffix) $path 4194304 $Progress 'Проверка выпусков' $true
        return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } finally { if (Test-Path -LiteralPath $folder) { try { Remove-TankSessionStage $folder ([IO.Path]::GetTempPath()) } catch { } } }
}

function Get-TankSessionUpdatePlan($Release, [string]$Version, [string]$Current, [bool]$IncludePrerelease) {
    $selection = Select-TankSessionUpdate @($Release) $Current $IncludePrerelease
    if ($selection.Available -cne $Version) { throw 'Выпуск больше не доступен в выбранном канале или не новее текущего менеджера.' }
    $name = 'TankSession_Analytics_' + $Version + '_Windows.zip'
    $base = 'https://github.com/xeemoff/tanksession-analytics/releases/download/v' + $Version + '/'
    $result = @{}
    foreach ($suffix in @('', '.sha256')) {
        $asset = @($Release.assets | Where-Object { $_.name -ceq ($name + $suffix) -and $_.state -ceq 'uploaded' })
        if ($asset.Count -ne 1) { throw 'В выпуске отсутствует единственный Windows-архив с контрольной суммой.' }
        $a = $asset[0]
        if ($a.browser_download_url -cne ($base + $name + $suffix) -or $a.size -lt 1 -or
            $a.size -gt $(if ($suffix) { 512 } else { 33554432 })) { throw 'Некорректные сведения о файле выпуска.' }
        $digest = $null
        if ($a.PSObject.Properties['digest'] -and $null -ne $a.digest) {
            if ($a.digest -cnotmatch '^sha256:[0-9a-f]{64}$') { throw 'Неподдерживаемая контрольная сумма GitHub.' }
            $digest = $a.digest.Substring(7)
        }
        $result[$suffix] = [PSCustomObject]@{ Url = $base + $name + $suffix; Size = [long]$a.size; Digest = $digest }
    }
    return [PSCustomObject]@{ Version = $Version; Name = $name; Archive = $result['']; Checksum = $result['.sha256'] }
}

function Get-TankSessionBundleNames([string]$Version) {
    $null = ConvertTo-TankSessionSemVer $Version
    $package = 'ru.tanksession.analytics_' + $Version + '.mtmod'
    return @($package, ($package + '.sha256'), 'manifest.json', 'install.cmd', 'manager.cmd',
             'Install-TankSession.ps1', 'Data-TankSession.ps1', 'Manage-TankSession.ps1',
             'TankSession-Manager.ps1', 'Start-TankSession.ps1', 'Update-TankSession.ps1',
             'INSTALL_RU.md', 'RELEASE_NOTES_RU.md', 'LICENSE')
}

function Expand-TankSessionUpdate([string]$Archive, [string]$Directory, [string]$Version, [string]$Digest) {
    # Verify every entry before creating or extracting a single member. Flat
    # allowlisting rejects traversal, ADS, case collisions, symlinks and extras.
    Assert-TankSessionRegularPath $Archive
    if ((Get-TankSessionHash $Archive) -cne $Digest) { throw 'SHA-256 Windows-архива не совпадает.' }
    if (Test-Path -LiteralPath $Directory) { throw 'Папка нового менеджера уже существует.' }
    Assert-TankSessionRegularPath ([IO.Path]::GetDirectoryName($Directory))
    $expected = @(Get-TankSessionBundleNames $Version)
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -ne $expected.Count) { throw 'Неподдерживаемый состав Windows-архива.' }
        $seen = @{}; [long]$expanded = 0
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            if ($expected -cnotcontains $name -or $seen.ContainsKey($name) -or $entry.Length -lt 1 -or
                $entry.Length -gt $(if ($name.EndsWith('.mtmod')) { 16777216 } elseif ($name -ceq 'manifest.json') { 65536 } else { 2097152 }) -or
                (($entry.ExternalAttributes -shr 16) -band 61440) -eq 40960 -or ($entry.ExternalAttributes -band 1024) -ne 0) {
                throw 'Небезопасный путь, тип или размер файла в Windows-архиве.'
            }
            $seen[$name] = $true; $expanded += $entry.Length
            if ($expanded -gt 33554432) { throw 'Windows-архив слишком велик после распаковки.' }
        }
        $null = New-Item -ItemType Directory -Path $Directory
        $members = @()
        foreach ($entry in $zip.Entries) {
            $target = Join-Path $Directory $entry.FullName
            $inputStream = $entry.Open(); $output = [IO.File]::Open($target, [IO.FileMode]::CreateNew)
            try {
                $buffer = New-Object byte[] 65536; [long]$copied = 0
                while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $copied += $count
                    if ($copied -gt $entry.Length) { throw 'Файл превысил заявленный размер при распаковке.' }
                    $output.Write($buffer, 0, $count)
                }
                $output.Flush($true)
            }
            finally { $inputStream.Dispose(); $output.Dispose() }
            if ((Get-Item -Force -LiteralPath $target).Length -ne $entry.Length) { throw 'Неполная распаковка обновления.' }
            $members += @{ path = $entry.FullName; size = $entry.Length; sha256 = Get-TankSessionHash $target }
        }
        $bundle = Read-TankSessionBundle $Directory
        if (-not $bundle.PSObject.Properties['manager_update_protocol'] -or $bundle.manager_update_protocol -ne 1 -or
            $bundle.version -cne $Version -or (($Version.Contains('-')) -ne ($bundle.channel -ceq 'prerelease'))) {
            throw 'Версия распакованного пакета отличается от выбранного выпуска.'
        }
        $receipt = @{ schema = 1; version = $Version; archive_sha256 = $Digest; members = $members }
        $receiptPath = Join-Path $Directory 'update-receipt.json'
        [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
        return [PSCustomObject]@{ Directory = $Directory; Version = $Version; ReceiptHash = Get-TankSessionHash $receiptPath }
    } finally { $zip.Dispose() }
}

function Read-TankSessionManagerPointer([string]$ManagerRoot) {
    Assert-TankSessionRegularPath $ManagerRoot
    $pointerPath = Join-Path $ManagerRoot '.tanksession-current.json'
    if (-not (Test-Path -LiteralPath $pointerPath)) { return $null }
    Assert-TankSessionRegularPath $pointerPath
    if ((Get-Item -Force -LiteralPath $pointerPath).Length -gt 2048) { throw 'Повреждён указатель менеджера.' }
    $pointer = Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($pointer.schema -ne 1 -or $pointer.receipt_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $pointer.folder -cnotmatch '^[0-9A-Za-z.-]+-[0-9a-f]{64}-[0-9a-f]{32}$') { throw 'Неподдерживаемый указатель менеджера.' }
    $version = $pointer.folder.Substring(0, $pointer.folder.Length - 98)
    $null = ConvertTo-TankSessionSemVer $version
    $folder = Join-Path (Join-Path $ManagerRoot '.tanksession-updates') $pointer.folder
    Assert-TankSessionRegularPath $folder
    $receiptPath = Join-Path $folder 'update-receipt.json'
    Assert-TankSessionRegularPath $receiptPath
    if ((Get-Item -Force -LiteralPath $receiptPath).Length -gt 65536 -or
        (Get-TankSessionHash $receiptPath) -cne $pointer.receipt_sha256) { throw 'Изменилась контрольная запись менеджера.' }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.schema -ne 1 -or $receipt.version -cne $version -or
        $pointer.folder.Substring(0, $pointer.folder.Length - 33) -cne ($version + '-' + $receipt.archive_sha256)) { throw 'Не совпала версия менеджера.' }
    $expected = @(Get-TankSessionBundleNames $version); $seen = @{}
    foreach ($m in @($receipt.members)) {
        if ($expected -cnotcontains $m.path -or $seen.ContainsKey($m.path) -or
            $m.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $m.size -lt 1 -or $m.size -gt 16777216) { throw 'Некорректный список файлов менеджера.' }
        $seen[$m.path] = $true
        $path = Join-Path $folder $m.path; Assert-TankSessionRegularPath $path
        if ((Get-Item -Force -LiteralPath $path).Length -ne $m.size -or (Get-TankSessionHash $path) -cne $m.sha256) { throw 'Один из файлов нового менеджера изменён. Используйте исходный архив.' }
    }
    if ($seen.Count -ne $expected.Count -or @(Get-ChildItem -LiteralPath $folder -Force).Count -ne ($seen.Count + 1)) { throw 'Изменился состав папки менеджера.' }
    $null = Read-TankSessionBundle $folder
    return [PSCustomObject]@{ Directory = $folder; Version = $version; ReceiptHash = $pointer.receipt_sha256 }
}

function Set-TankSessionManagerPointer([string]$ManagerRoot, $Prepared) {
    Assert-TankSessionRegularPath $ManagerRoot
    $folder = [IO.Path]::GetFileName($Prepared.Directory)
    $parent = (Get-Item -Force -LiteralPath (Join-Path $ManagerRoot '.tanksession-updates')).FullName
    if ([IO.Path]::GetDirectoryName($Prepared.Directory) -cne $parent) { throw 'Папка обновления находится вне менеджера.' }
    $value = @{ schema = 1; folder = $folder; receipt_sha256 = $Prepared.ReceiptHash }
    $target = Join-Path $ManagerRoot '.tanksession-current.json'
    if (Test-Path -LiteralPath $target) { Assert-TankSessionRegularPath $target }
    $temporary = Join-Path $ManagerRoot ('.tanksession-pointer-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $bytes = (New-Object Text.UTF8Encoding $false).GetBytes(($value | ConvertTo-Json -Compress))
        $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        # The only commit point. No fallible operations follow replacement.
        if (Test-Path -LiteralPath $target) { [IO.File]::Replace($temporary, $target, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $target) }
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -ErrorAction SilentlyContinue } }
}

function Assert-TankSessionNoDowngrade($Manifest, [string]$Destination) {
    $targetVersion = ConvertTo-TankSessionSemVer $Manifest.version
    foreach ($file in @(Get-ChildItem -LiteralPath $Destination -File)) {
        if ($file.Name -cmatch '^ru\.tanksession\.analytics_(.+)\.mtmod$') {
            Assert-TankSessionRegularPath $file.FullName
            $installed = ConvertTo-TankSessionSemVer $Matches[1]
            $comparison = Compare-TankSessionSemVer $targetVersion $installed
            if ($comparison -lt 0) { throw 'В игре уже установлен более новый мод. Обновление не понижает версию.' }
            if ($comparison -eq 0 -and (Get-TankSessionHash $file.FullName) -cne $Manifest.sha256) {
                throw 'В игре уже есть эта версия с другими байтами. Выполните проверку установленного пакета.'
            }
        }
    }
}

function Install-TankSessionUpdate([string]$Directory, [string]$ManagerRoot, [string]$GameRoot, [string]$ClientVersion,
                                  [string]$Version, [bool]$IncludePrerelease, [scriptblock]$Progress = $null) {
    $null = ConvertTo-TankSessionSemVer $Version
    $current = Read-TankSessionBundle $Directory
    $null = Get-TankSessionDestination $GameRoot $ClientVersion $current
    Assert-TankSessionGameStopped
    Assert-TankSessionRegularPath $ManagerRoot
    $root = (Get-Item -Force -LiteralPath $ManagerRoot).FullName
    $active = Read-TankSessionManagerPointer $root
    if ($null -ne $active -and $active.Directory -cne (Get-Item -Force -LiteralPath $Directory).FullName) { throw 'Другой менеджер уже обновлён. Закройте это окно и откройте manager.cmd заново.' }
    $release = Get-TankSessionReleaseJson ('/tags/v' + $Version) $Progress
    $plan = Get-TankSessionUpdatePlan $release $Version $current.version $IncludePrerelease
    $updates = Join-Path $root '.tanksession-updates'
    if (-not (Test-Path -LiteralPath $updates)) { $null = New-Item -ItemType Directory -Path $updates }
    Assert-TankSessionRegularPath $updates
    $lockPath = Join-Path $updates '.update.lock'
    if (Test-Path -LiteralPath $lockPath) { Assert-TankSessionRegularPath $lockPath }
    $lock = $null; $incoming = $null; $staged = $null; $committed = $false
    try {
        try { $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw 'Другой менеджер уже загружает обновление.' }
        $incoming = Join-Path $updates ('incoming-' + [Guid]::NewGuid().ToString('N'))
        $null = New-Item -ItemType Directory -Path $incoming
        $archivePath = Join-Path $incoming $plan.Name; $checksumPath = $archivePath + '.sha256'
        Receive-TankSessionFile $plan.Checksum.Url $checksumPath 512 $Progress 'Загрузка контрольной суммы'
        Receive-TankSessionFile $plan.Archive.Url $archivePath 33554432 $Progress 'Загрузка обновления'
        foreach ($pair in @(@($checksumPath, $plan.Checksum), @($archivePath, $plan.Archive))) {
            if ((Get-Item -Force -LiteralPath $pair[0]).Length -ne $pair[1].Size -or
                ($pair[1].Digest -and (Get-TankSessionHash $pair[0]) -cne $pair[1].Digest)) { throw 'Скачанный файл отличается от сведений GitHub.' }
        }
        $fields = @((Get-Content -LiteralPath $checksumPath -Raw -Encoding ASCII).Trim() -split '\s+')
        if ($fields.Count -ne 2 -or $fields[0] -cnotmatch '^[0-9a-f]{64}$' -or $fields[1] -cne $plan.Name) { throw 'Некорректный файл контрольной суммы.' }
        $digest = $fields[0]
        if ((Get-TankSessionHash $archivePath) -cne $digest) { throw 'SHA-256 обновления не совпадает. Установка не началась.' }
        Send-TankSessionProgress $Progress 'Проверка и распаковка обновления'
        # A fresh immutable folder lets retry ignore an interrupted preparation.
        # Previous prepared folders are never overwritten or trusted implicitly.
        $candidatePath = Join-Path $updates ($Version + '-' + $digest + '-' + [Guid]::NewGuid().ToString('N'))
        if (Test-Path -LiteralPath $candidatePath) { throw 'Место подготовки обновления уже занято.' }
        $staged = $candidatePath
        $prepared = Expand-TankSessionUpdate $archivePath $staged $Version $digest
        $manifest = Read-TankSessionBundle $staged
        $destination = Get-TankSessionDestination $GameRoot $ClientVersion $manifest
        Assert-TankSessionNoDowngrade $manifest $destination
        Send-TankSessionProgress $Progress 'Резервная копия и установка'
        $context = [PSCustomObject]@{ Root = $root; Directory = $Directory; Prepared = $prepared }
        # Explicit callback state preserves the invoking script's function scope.
        # GetNewClosure would move helpers into an unrelated dynamic module.
        $before = {
            param($m, $d, $state)
            $live = Read-TankSessionManagerPointer $state.Root
            if ($null -ne $live -and $live.Directory -cne (Get-Item -Force -LiteralPath $state.Directory).FullName) { throw 'Менеджер уже обновлён другим процессом.' }
            Assert-TankSessionNoDowngrade $m $d
        }
        $after = { param($m, $d, $state) Set-TankSessionManagerPointer $state.Root $state.Prepared }
        $installed = Install-TankSessionBundle $staged $GameRoot $ClientVersion $false $before $after $context
        $committed = $true
        return [PSCustomObject]@{ Status = 'updated'; Version = $Version; Directory = $staged; Backup = $installed.Backup; HistoryBackup = $installed.HistoryBackup }
    } finally {
        # Only exact newly-created directories are removed. No recursive walk
        # through an unvalidated caller-selected path is used for cleanup.
        if ($null -ne $incoming -and (Test-Path -LiteralPath $incoming)) { try { Remove-TankSessionStage $incoming $updates } catch { } }
        if (-not $committed -and $null -ne $staged -and (Test-Path -LiteralPath $staged)) {
            try { Remove-TankSessionStage $staged $updates } catch { }
        }
        if ($null -ne $lock) { $lock.Dispose() }
    }
}
