#requires -Version 5.1
[CmdletBinding()]
param([switch]$SmokeTest)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'Manage-TankSession.ps1')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

$script:TsaBundle = Read-TankSessionBundle $PSScriptRoot
$script:TsaReleaseUrl = 'https://github.com/xeemoff/tanksession-analytics/releases'
$script:TsaButtons = @()
$script:TsaForm = New-Object Windows.Forms.Form
$script:TsaForm.Text = 'TankSession Analytics — управление'
$script:TsaForm.Size = New-Object Drawing.Size 860, 780
$script:TsaForm.MinimumSize = New-Object Drawing.Size 760, 680
$script:TsaForm.StartPosition = 'CenterScreen'
$script:TsaForm.Font = New-Object Drawing.Font 'Segoe UI', 10
$script:TsaForm.BackColor = [Drawing.Color]::FromArgb(246, 248, 251)
$script:TsaForm.AutoScaleMode = [Windows.Forms.AutoScaleMode]::Dpi

$layout = New-Object Windows.Forms.TableLayoutPanel
$layout.Dock = 'Fill'; $layout.Padding = New-Object Windows.Forms.Padding 22
$layout.ColumnCount = 1; $layout.RowCount = 9
$layout.AutoScroll = $true
$script:TsaForm.Controls.Add($layout)

function Add-TsaLabel([string]$Text, [bool]$Title = $false) {
    $label = New-Object Windows.Forms.Label
    $label.Text = $Text; $label.AutoSize = $true
    $label.Margin = New-Object Windows.Forms.Padding 0, 6, 0, 12
    $label.MaximumSize = New-Object Drawing.Size 760, 0
    if ($Title) { $label.Font = New-Object Drawing.Font 'Segoe UI', 18, ([Drawing.FontStyle]::Bold) }
    $layout.Controls.Add($label)
}

function New-TsaRow {
    $row = New-Object Windows.Forms.FlowLayoutPanel
    $row.AutoSize = $true; $row.WrapContents = $true; $row.Dock = 'Top'
    $row.Margin = New-Object Windows.Forms.Padding 0, 0, 0, 12
    $layout.Controls.Add($row)
    return $row
}

function Add-TsaButton($Row, [string]$Text, [scriptblock]$Action) {
    $button = New-Object Windows.Forms.Button
    $button.Text = $Text; $button.AutoSize = $true
    $button.Padding = New-Object Windows.Forms.Padding 10, 5, 10, 5
    $button.Margin = New-Object Windows.Forms.Padding 0, 0, 10, 8
    $button.Add_Click($Action)
    $Row.Controls.Add($button)
    $script:TsaButtons += $button
}

function Write-TsaStatus([string]$Text) {
    $script:TsaStatus.AppendText($Text + [Environment]::NewLine + [Environment]::NewLine)
    $script:TsaStatus.SelectionStart = $script:TsaStatus.TextLength
    $script:TsaStatus.ScrollToCaret()
}

function Invoke-TsaAction([scriptblock]$Action) {
    foreach ($button in $script:TsaButtons) { $button.Enabled = $false }
    $script:TsaForm.UseWaitCursor = $true
    try { & $Action }
    catch { Write-TsaStatus ('Операция остановлена: ' + $_.Exception.Message) }
    finally {
        $script:TsaForm.UseWaitCursor = $false
        foreach ($button in $script:TsaButtons) { $button.Enabled = $true }
    }
}

function Refresh-TsaBackups {
    $script:TsaBackups.Items.Clear()
    if (Test-Path -LiteralPath $script:TsaPath.Text -PathType Container) {
        foreach ($path in @(Get-TankSessionPackageBackups $script:TsaPath.Text $script:TsaVersion.Text)) {
            $null = $script:TsaBackups.Items.Add($path)
        }
    }
    if ($script:TsaBackups.Items.Count -gt 0) { $script:TsaBackups.SelectedIndex = 0 }
}

Add-TsaLabel ('TankSession Analytics ' + $script:TsaBundle.version) $true
Add-TsaLabel ('Клиент: ' + (@($script:TsaBundle.client_versions) -join ', ') +
    '. ' + $(if ($script:TsaBundle.native_validation -eq 'verified') { 'Игровая проверка записана.' } else { 'Предварительный выпуск: проверка этого пакета в игре ещё не завершена.' }) +
    ' Закройте игру и просмотр истории перед изменениями.')

$row = New-TsaRow
$script:TsaPath = New-Object Windows.Forms.ComboBox
$script:TsaPath.Width = 400; $script:TsaPath.AccessibleName = 'Папка игры'
$row.Controls.Add($script:TsaPath)
Add-TsaButton $row 'Выбрать папку…' {
    $dialog = New-Object Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Папка игры, содержащая mods и WorldOfTanks.exe / Tanki.exe'
    if ($dialog.ShowDialog($script:TsaForm) -eq 'OK') { $script:TsaPath.Text = $dialog.SelectedPath; Refresh-TsaBackups }
    $dialog.Dispose()
}
Add-TsaButton $row 'Найти игру' {
    Invoke-TsaAction {
        $found = @(Find-TankSessionGames)
        $script:TsaPath.Items.Clear()
        foreach ($path in $found) { $null = $script:TsaPath.Items.Add($path) }
        if ($found.Count -eq 1) { $script:TsaPath.SelectedIndex = 0 }
        Write-TsaStatus ('Найдено папок: ' + $found.Count + '. Проверьте выбранную папку игры.')
        Refresh-TsaBackups
    }
}

$row = New-TsaRow
$versionLabel = New-Object Windows.Forms.Label
$versionLabel.Text = 'Версия клиента'; $versionLabel.AutoSize = $true
$versionLabel.Padding = New-Object Windows.Forms.Padding 0, 7, 8, 0
$row.Controls.Add($versionLabel)
$script:TsaVersion = New-Object Windows.Forms.ComboBox
$script:TsaVersion.Width = 140; $script:TsaVersion.DropDownStyle = 'DropDownList'
$script:TsaVersion.AccessibleName = 'Поддерживаемая версия клиента'
foreach ($version in @($script:TsaBundle.client_versions)) { $null = $script:TsaVersion.Items.Add($version) }
$script:TsaVersion.SelectedIndex = 0
$row.Controls.Add($script:TsaVersion)
Add-TsaButton $row 'Проверить' {
    Invoke-TsaAction {
        $null = Install-TankSessionBundle $PSScriptRoot $script:TsaPath.Text $script:TsaVersion.Text $true
        Write-TsaStatus 'Пакет, контрольные суммы и папка клиента проверены. Можно устанавливать.'
    }
}
Add-TsaButton $row 'Установить / обновить' {
    Invoke-TsaAction {
        $result = Install-TankSessionBundle $PSScriptRoot $script:TsaPath.Text $script:TsaVersion.Text
        Write-TsaStatus ('Установлена версия ' + $result.Version + '. История и настройки сохранены.' +
            $(if ($result.HistoryBackup) { "`r`nКопия данных: " + $result.HistoryBackup }) +
            $(if ($result.Backup) { "`r`nПрежний пакет: " + $result.Backup }))
        Refresh-TsaBackups
    }
}
Add-TsaButton $row 'Удалить мод' {
    if ([Windows.Forms.MessageBox]::Show($script:TsaForm, 'Удалить пакеты TankSession из выбранной версии игры? История, настройки и резервные копии сохранятся.', 'Удаление мода', 'YesNo', 'Question') -ne 'Yes') { return }
    Invoke-TsaAction {
        $result = Set-TankSessionPackages $PSScriptRoot $script:TsaPath.Text $script:TsaVersion.Text
        Write-TsaStatus ('Удалены пакеты: ' + $result.Count + '. Копия: ' + $result.Backup)
        Refresh-TsaBackups
    }
}

$row = New-TsaRow
$script:TsaBackups = New-Object Windows.Forms.ComboBox
$script:TsaBackups.Width = 550; $script:TsaBackups.DropDownStyle = 'DropDownList'
$script:TsaBackups.AccessibleName = 'Резервные копии пакетов'
$row.Controls.Add($script:TsaBackups)
Add-TsaButton $row 'Вернуть пакет' {
    Invoke-TsaAction {
        if ($script:TsaBackups.SelectedIndex -lt 0) { throw 'Выберите резервную копию пакета.' }
        $result = Set-TankSessionPackages $PSScriptRoot $script:TsaPath.Text $script:TsaVersion.Text $script:TsaBackups.Text
        Write-TsaStatus ('Предыдущий пакет восстановлен. Заменённый пакет сохранён: ' + $result.Backup)
        Refresh-TsaBackups
    }
}
$script:TsaPath.Add_SelectedIndexChanged({ Refresh-TsaBackups })
$script:TsaVersion.Add_SelectedIndexChanged({ Refresh-TsaBackups })

Add-TsaLabel 'История всех локальных аккаунтов и настройки: экспорт создаёт ZIP-снимок. Импорт заменяет файлы из снимка, предварительно сохраняя текущие данные. Архив содержит локальные ID; храните его как личный файл.'
$row = New-TsaRow
Add-TsaButton $row 'Экспорт / резервная копия…' {
    $dialog = New-Object Windows.Forms.SaveFileDialog
    $dialog.Filter = 'История TankSession (*.zip)|*.zip'
    $dialog.FileName = 'TankSession-history-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '.zip'
    if ($dialog.ShowDialog($script:TsaForm) -eq 'OK') {
        $script:TsaArchive = $dialog.FileName
        Invoke-TsaAction {
            $result = Export-TankSessionHistory $script:TsaPath.Text $script:TsaArchive
            Write-TsaStatus ('Архив сохранён: ' + $result.Path + "`r`nSHA-256: " + $result.Sha256)
        }
    }
    $dialog.Dispose()
}
Add-TsaButton $row 'Импортировать снимок…' {
    $dialog = New-Object Windows.Forms.OpenFileDialog
    $dialog.Filter = 'История TankSession (*.zip)|*.zip'
    if ($dialog.ShowDialog($script:TsaForm) -eq 'OK') {
        $script:TsaArchive = $dialog.FileName
        if ([Windows.Forms.MessageBox]::Show($script:TsaForm, 'Заменить историю и настройки файлами из выбранного снимка? Перед заменой будет создана резервная копия. Бои из двух журналов не объединяются.', 'Импорт истории', 'YesNo', 'Question') -eq 'Yes') {
            Invoke-TsaAction {
                $result = Import-TankSessionHistory $script:TsaPath.Text $script:TsaArchive
                Write-TsaStatus ('Восстановлено файлов: ' + $result.Files + '. Предыдущие данные: ' + $result.Backup)
            }
        }
    }
    $dialog.Dispose()
}
Add-TsaButton $row 'Обновить список копий' { Invoke-TsaAction { Refresh-TsaBackups } }

$row = New-TsaRow
$script:TsaPreview = New-Object Windows.Forms.CheckBox
$script:TsaPreview.Text = 'Учитывать предварительные версии'; $script:TsaPreview.AutoSize = $true
$script:TsaPreview.Checked = $script:TsaBundle.channel -eq 'prerelease'
$row.Controls.Add($script:TsaPreview)
Add-TsaButton $row 'Проверить обновления' {
    Invoke-TsaAction {
        Write-TsaStatus 'Проверяю опубликованные выпуски на GitHub…'
        $result = Get-TankSessionUpdate $script:TsaBundle.version $script:TsaPreview.Checked
        $script:TsaReleaseUrl = $result.Url
        Write-TsaStatus $(if ($result.Available) { 'Доступна версия ' + $result.Available + '. Откройте страницу и проверьте её требования к клиенту.' } else { 'Более новая версия в выбранном канале не найдена.' })
    }
}
Add-TsaButton $row 'Страница выпуска' { Start-Process $script:TsaReleaseUrl }

$script:TsaStatus = New-Object Windows.Forms.TextBox
$script:TsaStatus.Multiline = $true; $script:TsaStatus.ReadOnly = $true
$script:TsaStatus.ScrollBars = 'Vertical'; $script:TsaStatus.Dock = 'Fill'
$script:TsaStatus.MinimumSize = New-Object Drawing.Size 680, 120
$script:TsaStatus.AccessibleName = 'Результаты операций'
$layout.Controls.Add($script:TsaStatus)
Write-TsaStatus 'Укажите папку игры или нажмите «Найти игру». Установка и копии работают без интернета; запрос к GitHub выполняется только кнопкой проверки обновлений.'

if ($SmokeTest) {
    [PSCustomObject]@{ Title = $script:TsaForm.Text; Buttons = $script:TsaButtons.Count; Client = $script:TsaVersion.Text; Status = 'constructed' } | ConvertTo-Json -Compress
} else { $null = $script:TsaForm.ShowDialog() }
$script:TsaForm.Dispose()
