# register_oneshot_task.ps1
#
# iMakInventory_OneShot タスクを「指定時刻に 1 回だけ実行」で登録 (Phase 9 拡張)
#
# - 4h cycle と独立、テスト用途や臨時巡回用
# - 既定は TEST_PARALLEL スプシ + skip-upload (=並走 Stage 1 と同等)
# - 既存 OneShot タスクがあれば上書き登録
# - 過去の時刻を渡すと翌日同時刻に自動シフト
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_oneshot_task.ps1 -At "17:05"
#   PowerShell -ExecutionPolicy Bypass -File tools\register_oneshot_task.ps1 -At "2026-05-01 06:00"
#   PowerShell -ExecutionPolicy Bypass -File tools\register_oneshot_task.ps1 -Action Unregister
#   PowerShell -ExecutionPolicy Bypass -File tools\register_oneshot_task.ps1 -Action Status
#
# 引数 (Register 時):
#   -At <HH:MM or "YYYY-MM-DD HH:MM">  必須、ターゲット時刻
#   -SheetId <ID>                       (default: TEST_PARALLEL ID)
#   -SheetLabel <Label>                 (default: "TEST_PARALLEL")
#   -SkipUpload <$true|$false>          (default: $true、Stage 1 同等)

param (
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Register",

    [string]$At = "",

    [string]$SheetId = "1oDjQC8WN_3WC2InPHAV-hPKmsa96rdNd4jxbGBzDimc",
    [string]$SheetLabel = "TEST_PARALLEL",
    [bool]$SkipUpload = $true
)

# fail-fast
$ErrorActionPreference = 'Stop'

# console を UTF-8 化 (日本語メッセージ文字化け防止)
try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$TaskName = "iMakInventory_OneShot"
$WorkingDir = "C:\dev\iMak\iMakInventory"

if ($Action -eq "Unregister") {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "[OK] $TaskName 削除完了"
    } else {
        Write-Output "[INFO] $TaskName 未登録"
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

# === Register ===
if (-not $At) {
    throw "-At <時刻> は必須 (例: '17:05' または '2026-05-01 06:00')"
}

# 時刻 parse: "HH:MM" → today HH:MM、past なら翌日にシフト
[DateTime]$target = $null
try {
    $target = [DateTime]::Parse($At)
} catch {
    throw "-At の解析失敗: '$At' (HH:MM or 'YYYY-MM-DD HH:MM' 形式)"
}
if ($target -lt (Get-Date)) {
    $target = $target.AddDays(1)
    Write-Output "[INFO] 過去時刻 → 翌日 $($target.ToString('yyyy-MM-dd HH:mm')) に shift"
}

# Python 絶対パス + pythonw 優先
$pythonExe = $null
try {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
} catch {
    throw "Python 実行ファイルを PATH 上で見つけられない"
}
if (-not (Test-Path $pythonExe)) {
    throw "Python 実行ファイル不在: $pythonExe"
}
$pythonwExe = Join-Path (Split-Path $pythonExe -Parent) "pythonw.exe"
if (Test-Path $pythonwExe) {
    Write-Output "[INFO] pythonw.exe (no console): $pythonwExe"
    $pythonExe = $pythonwExe
} else {
    Write-Warning "pythonw.exe 不在 → python.exe で fallback (黒窓出ます)"
}

# 引数組立 (--sheet-id / --sheet-label / --skip-upload)
$argParts = @("-u", "run_cycle.py", "--sheet-id", $SheetId, "--sheet-label", $SheetLabel)
if ($SkipUpload) {
    $argParts += "--skip-upload"
}
$cmdArgs = $argParts -join " "

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Output "[WARN] $TaskName 既存、上書き登録します"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Trigger: 単発 (一度だけ実行)
$taskTrigger = New-ScheduledTaskTrigger -Once -At $target

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
    -Trigger $taskTrigger `
    -Settings $taskSettings `
    -Description "iMakInventory ワンショット予約 ($($target.ToString('yyyy-MM-dd HH:mm')) に 1 回実行)" `
    | Out-Null

$stageMode = if ($SkipUpload) { "Stage 1 (eBay upload skip)" } else { "Stage 2 (eBay upload 有効)" }
Write-Output "[OK] $TaskName 登録完了"
Write-Output "  fire_at:     $($target.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Output "  sheet_id:    $SheetId"
Write-Output "  sheet_label: $SheetLabel"
Write-Output "  mode:        $stageMode"
Write-Output "  command:     $pythonExe $cmdArgs"
Write-Output ""
Write-Output "確認:  PowerShell -ExecutionPolicy Bypass -File tools\register_oneshot_task.ps1 -Action Status"
Write-Output "解除:  PowerShell -ExecutionPolicy Bypass -File tools\register_oneshot_task.ps1 -Action Unregister"
