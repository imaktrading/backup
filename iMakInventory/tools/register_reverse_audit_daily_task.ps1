# register_reverse_audit_daily_task.ps1
#
# Register iMakInventory_ReverseAudit_Daily Windows scheduled task.
# Runs once daily at 09:30: `python reverse_audit.py --mode all`
#   = reverse_audit (D=○ × eBay qty>0 = 取下げ漏れ reconciliation)
#   + ebay_down_audit (D空欄 × eBay qty=0/ended = review シート書出)
#   を共有 eBay active map で両方走らせ、 乖離 / audit 不能を非-silent に通知。
#
# Background (2026-06-25):
#   06-16 のスケジュール再編で旧 iMakInventory_Cycle_BothDaily0930 (--sheet both) が消滅し、
#   run_cycle の Phase 5 reverse_audit (発火条件 sheet=="both") が自動実行されなくなった。
#   安全原則「定期 reconciliation で乖離ゼロを継続証跡」が本体側で途切れたため、
#   source 再スキャン不要な reverse_audit を専用 daily cron に切り出して復旧する。
#   (reverse_audit は HIGH/LOW シートを eBay と直接突合するので monitor scan 移行と独立)
# Duration: eBay GetSellerList 全件 DL (~7800 listing) で ~5-7min (DNS retry 込み)。
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_reverse_audit_daily_task.ps1
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

$TaskName = "iMakInventory_ReverseAudit_Daily"
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

$cmdArgs = "-u reverse_audit.py --mode all"

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
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -RestartCount 1 `
            -RestartInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $taskAction `
    -Trigger $trigger `
    -Settings $taskSettings `
    -Description "iMakInventory 09:30 daily: reverse_audit + ebay_down_audit (取下げ漏れ reconciliation 継続証跡, 2026-06-25 復旧)" `
    | Out-Null

Write-Output "[OK] $TaskName registered"
Write-Output "  schedule : $($dt.ToString('HH:mm')) daily"
Write-Output "  command  : $pythonExe $cmdArgs"
Write-Output "  cwd      : $WorkingDir"
Write-Output "  retry    : 1x / 15min"
Write-Output "  exec lim : 1h"
