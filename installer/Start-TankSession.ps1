#requires -Version 5.1
[CmdletBinding()]
param([switch]$SmokeTest)

# This small original launcher stays in place. Updated managers are immutable
# bundles selected by one atomic pointer, verified before any new script runs.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'Manage-TankSession.ps1')
$managerRoot = $PSScriptRoot
$game = ''; $client = ''; $includePreview = $null; $notice = ''
do {
    $directory = $managerRoot
    try {
        $active = Read-TankSessionManagerPointer $managerRoot
        if ($null -ne $active) { $directory = $active.Directory }
    } catch {
        $notice = 'Не удалось проверить обновлённый менеджер. Открыт исходный пакет: ' + $_.Exception.Message
    }
    $arguments = @{ ManagerRoot = $managerRoot; SelectedGame = $game; SelectedClient = $client; StartupNotice = $notice; SmokeTest = $SmokeTest }
    if ($null -ne $includePreview) { $arguments['IncludePreview'] = $includePreview }
    # Splatting parameters avoids command-string interpolation for paths with
    # spaces, apostrophes, $, &, and other legal filesystem characters.
    $result = & (Join-Path $directory 'TankSession-Manager.ps1') @arguments
    $restart = -not $SmokeTest -and $null -ne $result -and $result.PSObject.Properties['Restart'] -and $result.Restart
    if ($restart) {
        $game = $result.Game; $client = $result.Client; $includePreview = [bool]$result.IncludePreview
        $notice = 'Установлена версия ' + $result.Version + '. Менеджер обновлён. История и настройки сохранены.'
    } elseif ($SmokeTest) { $result }
} while ($restart)
