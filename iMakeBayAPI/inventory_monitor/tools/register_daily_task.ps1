# register_daily_task.ps1
#
# inventory_monitor の 1 日 1 cycle (08:00) をタスクスケジューラに登録。
# run_daily.py が main.py + auto_qty_zero (zero/restore --execute) を順次実行。
# max件数キャップ撤廃済 (= 1 cycle で全件処理)。
#
# 起動時刻 (default): 08:00 (= 既存監視くん 10/14/18/22/02/06 と被らず、当日 report 後)
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_daily_task.ps1
#   PowerShell -ExecutionPolicy Bypass -File tools\register_daily_task.ps1 -Action Status
#   PowerShell -ExecutionPolicy Bypass -File tools\register_daily_task.ps1 -Action Unregister
#   PowerShell -ExecutionPolicy Bypass -File tools\register_daily_task.ps1 -Times "07:30"

param (
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Register",

    [string]$Times = "08:00"
)

$ErrorActionPreference = 'Stop'

try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$TaskName    = "iMakInventory_Monitor_Daily"
$WorkingDir  = "C:\dev\iMak_inventory\iMakeBayAPI\inventory_monitor"
$ScriptPath  = "$WorkingDir\run_daily.py"

# Python 解決 (絶対パス必須、cron 環境 PATH に依存しない)
$pythonExe = $null
try {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
} catch {
    throw "Python が PATH 上に見つからない: $($_.Exception.Message)"
}
$pythonwExe = Join-Path (Split-Path $pythonExe -Parent) "pythonw.exe"
if (Test-Path $pythonwExe) {
    $pythonExe = $pythonwExe  # 黒窓抑制
}

# Unregister
if ($Action -eq "Unregister") {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "[OK] $TaskName 削除完了"
    } else {
        Write-Output "[INFO] $TaskName は登録されていません"
    }
    exit 0
}

# Status
if ($Action -eq "Status") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Output "[OK] $TaskName 登録済み"
        Write-Output "  State          : $($task.State)"
        Write-Output "  LastRunTime    : $($info.LastRunTime)"
        Write-Output "  NextRunTime    : $($info.NextRunTime)"
        Write-Output ("  LastTaskResult : 0x{0:X8}" -f $info.LastTaskResult)
        foreach ($a in $task.Actions) {
            Write-Output "  Execute        : $($a.Execute)"
            Write-Output "  Arguments      : $($a.Arguments)"
        }
        $timesArr = @()
        foreach ($trg in $task.Triggers) {
            if ($trg.StartBoundary) {
                try { $timesArr += ([datetime]$trg.StartBoundary).ToString("HH:mm") } catch {}
            }
        }
        $timesSorted = @($timesArr | Sort-Object)
        foreach ($tm in $timesSorted) { Write-Output "  StartTime      : $tm" }
        Write-Output "  (計 $($timesSorted.Count) 回/日)"
    } else {
        Write-Output "[INFO] $TaskName 未登録"
    }
    exit 0
}

# Register
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Output "[WARN] $TaskName 既存、上書き登録"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if (-not (Test-Path $ScriptPath)) {
    throw "run_daily.py 不在: $ScriptPath"
}

# 時刻 parse (複数)
$timeList = @()
foreach ($t in ($Times -split ",")) {
    $t = $t.Trim()
    if ($t -eq "") { continue }
    if ($t -notmatch '^\d{1,2}:\d{2}$') {
        throw "起動時刻は HH:MM 形式で指定 (NG: '$t')"
    }
    try { $timeList += [DateTime]::Parse($t) }
    catch { throw "起動時刻 parse 失敗: '$t'" }
}
if ($timeList.Count -eq 0) {
    throw "起動時刻が 1 件もない (-Times 空)"
}
$timesDisplay = ($timeList | ForEach-Object { $_.ToString("HH:mm") }) -join ", "

$cmdArgs = "-u `"$ScriptPath`""

Write-Output "[INFO] Python  : $pythonExe"
Write-Output "[INFO] Script  : $ScriptPath"
Write-Output "[INFO] Times   : $timesDisplay ($($timeList.Count) 回/日)"

$taskAction   = New-ScheduledTaskAction -Execute $pythonExe -Argument $cmdArgs -WorkingDirectory $WorkingDir
$triggers = @()
foreach ($dt in $timeList) {
    $triggers += New-ScheduledTaskTrigger -Daily -At $dt
}
$taskTrigger = $triggers
$taskSettings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $taskAction `
    -Trigger $taskTrigger `
    -Settings $taskSettings `
    -Description "inventory_monitor 1 日 1 cycle (DL + K列同期 + zero/restore 実行)" `
    | Out-Null

Write-Output "[OK] $TaskName 登録完了"
Write-Output "  schedule : 毎日 $timesDisplay"
Write-Output "  cmd      : $pythonExe $cmdArgs"
Write-Output "  cwd      : $WorkingDir"
Write-Output ""
Write-Output "確認:  PowerShell -ExecutionPolicy Bypass -File tools\register_daily_task.ps1 -Action Status"
Write-Output "削除:  PowerShell -ExecutionPolicy Bypass -File tools\register_daily_task.ps1 -Action Unregister"
