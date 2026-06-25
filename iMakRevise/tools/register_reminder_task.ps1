# register_reminder_task.ps1 - リバイス作業 週次リマインダーメールをタスクスケジューラに登録/削除/状態確認.
#
# 毎週 月曜 06:00 に send_reminder.py を実行 (= 起床後に目に入る)。
# revise 自体は実行せず、リマインダーメールを 1 通送るだけ。
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File register_reminder_task.ps1 -Action Register
#   PowerShell -ExecutionPolicy Bypass -File register_reminder_task.ps1 -Action Unregister
#   PowerShell -ExecutionPolicy Bypass -File register_reminder_task.ps1 -Action Status
#   -At "06:00"  -DayOfWeek Monday   で時刻/曜日を上書き可

param(
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Status",
    [string]$At = "06:00",
    [string]$DayOfWeek = "Monday"
)

$TaskName = "iMakRevise_WeeklyReminder"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $ProjectRoot "revise\send_reminder.py"

# pythonw.exe (コンソール窓を出さない) を優先、無ければ python.exe
$PyW = "$env:LOCALAPPDATA\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
if (-not (Test-Path $PyW)) { $PyW = "pythonw.exe" }

switch ($Action) {
    "Status" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) { Write-Host "[STATUS] 未登録: $TaskName"; exit 0 }
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "[STATUS] 登録済: $TaskName"
        Write-Host "  State:          $($task.State)"
        Write-Host "  LastRunTime:    $($info.LastRunTime)"
        Write-Host "  LastTaskResult: $($info.LastTaskResult) (0=success)"
        Write-Host "  NextRunTime:    $($info.NextRunTime)"
        exit 0
    }

    "Unregister" {
        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "[UNREGISTER] 削除完了: $TaskName"
        } else {
            Write-Host "[UNREGISTER] 未登録のためスキップ: $TaskName"
        }
        exit 0
    }

    "Register" {
        if (-not (Test-Path $Script)) { Write-Error "send_reminder.py が見つかりません: $Script"; exit 1 }

        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "[REGISTER] 既存タスク削除"
        }

        $TaskAction = New-ScheduledTaskAction `
            -Execute $PyW `
            -Argument "-X utf8 `"$Script`"" `
            -WorkingDirectory $ProjectRoot

        $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $At

        $Settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

        $Principal = New-ScheduledTaskPrincipal `
            -UserId $env:USERNAME `
            -LogonType Interactive `
            -RunLevel Limited

        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $TaskAction `
            -Trigger $Trigger `
            -Settings $Settings `
            -Principal $Principal `
            -Description "iMakRevise 週次リバイス推進リマインダーメール" | Out-Null

        Write-Host "[REGISTER] 登録完了: $TaskName"
        Write-Host "  実行: $PyW -X utf8 $Script"
        Write-Host "  スケジュール: 毎週 $DayOfWeek $At"
        exit 0
    }
}
