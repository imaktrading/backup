# register_test_task.ps1
#
# iMakInventory_TEST タスクを Windows タスクスケジューラに登録 (5 分ごと)
# - 動作確認用、本番タスク登録前に短サイクルで挙動 verify
# - test-mode + --limit 3 で軽量実行
#
# Usage (管理者権限不要):
#   PowerShell -ExecutionPolicy Bypass -File tools\register_test_task.ps1
#
# Unregister:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_test_task.ps1 -Action Unregister

param (
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Register"
)

$TaskName = "iMakInventory_TEST"
$WorkingDir = "C:\dev\iMak\iMakInventory"
$PythonExe = "python"
$Args = "-u run_cycle.py --test-mode --limit 3"

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

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $Args -WorkingDirectory $WorkingDir
$trigger = New-ScheduledTaskTrigger -Once -At ([DateTime]::Now.AddMinutes(2)) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Hours 24)
$settings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
            -RestartCount 1 `
            -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "iMakInventory TEST cycle (5 分ごと、動作確認用、確認後 削除前提)" `
    | Out-Null

Write-Output "[OK] $TaskName 登録完了"
Write-Output "  schedule: 5 分ごと (24h)"
Write-Output "  command: $PythonExe $Args"
Write-Output "  cwd: $WorkingDir"
Write-Output ""
Write-Output "確認:  PowerShell -ExecutionPolicy Bypass -File tools\register_test_task.ps1 -Action Status"
Write-Output "削除:  PowerShell -ExecutionPolicy Bypass -File tools\register_test_task.ps1 -Action Unregister"
