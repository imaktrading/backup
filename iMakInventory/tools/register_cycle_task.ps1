# register_cycle_task.ps1
#
# iMakInventory_Cycle タスクを Windows タスクスケジューラに登録 (4 時間ごと)
# 本番運用用、TEST タスクで動作確認 OK 後に登録すること。
#
# 起動時刻: 10:00, 14:00, 18:00, 22:00, 02:00, 06:00 (毎日 6 回)
#   ─ trabajo (08/12/16/20/00/04 起動) と 2h ずらして並走 (Phase 9a)
# 失敗時 retry: 1 回 (15 分後)
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1
#
# Unregister:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Unregister
#
# Status:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Status

param (
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Register"
)

$TaskName = "iMakInventory_Cycle"
$WorkingDir = "C:\dev\iMak\iMakInventory"
$PythonExe = "python"
$Args = "-u run_cycle.py"

if ($Action -eq "Unregister") {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "[OK] $TaskName 削除完了"
    } else {
        Write-Output "[INFO] $TaskName は登録されていません"
    }
    exit 0
}

if ($Action -eq "Status") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Output "[OK] $TaskName 登録済み"
        $task | Format-List TaskName, State, Triggers, Actions
        Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime, NextRunTime, LastTaskResult
    } else {
        Write-Output "[INFO] $TaskName 未登録"
    }
    exit 0
}

# Register
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Output "[WARN] $TaskName 既存、上書き登録します"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 4h サイクル: 10:00, 14:00, 18:00, 22:00, 02:00, 06:00 の 6 トリガー
# (trabajo の 08/12/16/20/00/04 と 2h ずらしで並走 ─ Phase 9a)
$triggers = @()
foreach ($h in 2, 6, 10, 14, 18, 22) {
    $triggers += New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.AddHours($h))
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $Args -WorkingDirectory $WorkingDir
$settings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
            -RestartCount 1 `
            -RestartInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "iMakInventory 本番 cycle (4h おき: 10/14/18/22/02/06 時、trabajo と 2h ずらし並走)" `
    | Out-Null

Write-Output "[OK] $TaskName 登録完了"
Write-Output "  schedule: 4h サイクル (10:00, 14:00, 18:00, 22:00, 02:00, 06:00)"
Write-Output "  並走対象: trabajo (08/12/16/20/00/04) と 2h ずらし"
Write-Output "  command: $PythonExe $Args"
Write-Output "  cwd: $WorkingDir"
Write-Output "  retry: 1 回 / 15 分後"
Write-Output "  execution time limit: 3h"
Write-Output ""
Write-Output "確認:  PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Status"
Write-Output "削除:  PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Unregister"
