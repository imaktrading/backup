# register_cycle_both_task.ps1
#
# Register iMakInventory_Cycle_BothDaily0930 Windows scheduled task.
# Runs once daily at 09:30, with --sheet both (HIGH + LOW sequential).
#
# Background: in addition to iMakInventory_Cycle (4h interval, HIGH only),
#             also process LOW once a day (Takaaki request 2026-05-10).
# Duration: HIGH ~40min + LOW ~30min = ~70min total (09:30 -> 10:40 done).
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_both_task.ps1
#   ... -Action Unregister
#   ... -Action Status

param (
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Register",
    [string]$Time = "09:30"
)

$ErrorActionPreference = 'Stop'

try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$TaskName = "iMakInventory_Cycle_BothDaily0930"
$WorkingDir = "C:\dev\iMak_inventory\iMakInventory"

$pythonExe = $null
try {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
} catch {
    throw "Python not found in PATH: $($_.Exception.Message)"
}
$pythonwExe = Join-Path (Split-Path $pythonExe -Parent) "pythonw.exe"
if (Test-Path $pythonwExe) {
    $pythonExe = $pythonwExe
}

$cmdArgs = "-u run_cycle.py --sheet both"

if ($Action -eq "Unregister") {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "[OK] $TaskName unregistered"
    } else {
        Write-Output "[INFO] $TaskName not registered"
    }
    exit 0
}

if ($Action -eq "Status") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Output "[OK] $TaskName registered"
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Output "  State          : $($task.State)"
        Write-Output "  LastRunTime    : $($info.LastRunTime)"
        Write-Output "  NextRunTime    : $($info.NextRunTime)"
        Write-Output ("  LastTaskResult : 0x{0:X8} ({1})" -f $info.LastTaskResult, $info.LastTaskResult)
        foreach ($a in $task.Actions) {
            Write-Output "  Execute   : $($a.Execute)"
            Write-Output "  Arguments : $($a.Arguments)"
        }
        foreach ($trg in $task.Triggers) {
            if ($trg.StartBoundary) {
                try {
                    $hhmm = ([datetime]$trg.StartBoundary).ToString("HH:mm")
                    Write-Output "  Trigger   : $hhmm daily"
                } catch {}
            }
        }
    } else {
        Write-Output "[INFO] $TaskName not registered"
    }
    exit 0
}

# Register
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Output "[WARN] $TaskName exists, overwriting"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if ($Time -notmatch '^\d{1,2}:\d{2}$') {
    throw "Time must be HH:MM format (NG: '$Time')"
}
$dt = [DateTime]::Parse($Time)
$trigger = New-ScheduledTaskTrigger -Daily -At $dt

Write-Output "[INFO] Python: $pythonExe"

$taskAction = New-ScheduledTaskAction -Execute $pythonExe -Argument $cmdArgs -WorkingDirectory $WorkingDir
$taskSettings = New-ScheduledTaskSettingsSet `
            -Hidden `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
            -RestartCount 1 `
            -RestartInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $taskAction `
    -Trigger $trigger `
    -Settings $taskSettings `
    -Description "iMakInventory 09:30 daily: HIGH + LOW both (Takaaki request 2026-05-10)" `
    | Out-Null

Write-Output "[OK] $TaskName registered"
Write-Output "  schedule : $($dt.ToString('HH:mm')) daily"
Write-Output "  command  : $pythonExe $cmdArgs"
Write-Output "  cwd      : $WorkingDir"
Write-Output "  retry    : 1x / 15min"
Write-Output "  exec lim : 3h"
