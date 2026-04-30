# register_cycle_task.ps1
#
# iMakInventory_Cycle タスクを Windows タスクスケジューラに登録 (4 時間ごと)
# 本番運用用、TEST タスクで動作確認 OK 後に登録すること。
#
# 起動時刻: 10:00, 14:00, 18:00, 22:00, 02:00, 06:00 (毎日 6 回)
#   ─ trabajo (08/12/16/20/00/04 起動) と 2h ずらして並走 (Phase 9a)
# 失敗時 retry: 1 回 (15 分後)
#
# === Phase 9 並走モード (Stage 1) ===
# trabajo 本番をコピーした TEST スプシで Inventory を走らせる。
# eBay upload は trabajo に任せる (-SkipUpload デフォルト ON)。
#   monitor + スプシ更新 + audit + backup + Revise CSV 生成 まで実行
#   (Phase 7e verify は upload なしのため自動 skip)
#
# Stage 2 切替 (eBay upload を Inventory に移行する時):
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -SkipUpload:$false
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -SheetId <ID> -SheetLabel <LABEL>
#
# Unregister:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Unregister
#
# Status:
#   PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Status

param (
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Register",

    # Phase 9 並走モード: TEST スプシ (trabajo 本番をコピー済) で Inventory 走行
    [string]$SheetId = "1oDjQC8WN_3WC2InPHAV-hPKmsa96rdNd4jxbGBzDimc",
    [string]$SheetLabel = "TEST_PARALLEL",

    # eBay upload skip (Stage 1 = $true、Stage 2 移行時は -SkipUpload:$false で無効化)
    [bool]$SkipUpload = $true
)

# fail-fast: 途中エラーで success メッセージを誤出力しない
$ErrorActionPreference = 'Stop'

# コンソール出力を UTF-8 化 (日本語メッセージ文字化け防止、Windows PS 5.1 既定 cp932 回避)
try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$TaskName = "iMakInventory_Cycle"
$WorkingDir = "C:\dev\iMak\iMakInventory"

# Execute は絶対パス必須 (タスクスケジューラ環境では PATH 解決されない:
# bug 実例 2026-04-30 14:00 起動失敗 LastResult 0x80070002 = ERROR_FILE_NOT_FOUND)
# Get-Command で動的解決し、hardcode は避ける
$pythonExe = $null
try {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
} catch {
    throw "Python 実行ファイルを PATH 上で見つけられない: $($_.Exception.Message)"
}
if (-not (Test-Path $pythonExe)) {
    throw "Python 実行ファイル不在: $pythonExe"
}
# 黒窓 (console window) 抑制のため pythonw.exe を優先 (Phase 9 拡張 A1)
# python.exe と同 dir にある想定。なければ警告して python.exe で fallback。
$pythonwExe = Join-Path (Split-Path $pythonExe -Parent) "pythonw.exe"
if (Test-Path $pythonwExe) {
    Write-Output "[INFO] pythonw.exe (no console): $pythonwExe"
    $pythonExe = $pythonwExe
} else {
    Write-Warning "pythonw.exe が同 dir に不在 ($pythonwExe) → python.exe で fallback (黒窓出ます)"
}

# run_cycle.py 引数を組立 (--sheet-id / --sheet-label / --skip-upload)
# ※ $Args / $args は PowerShell 自動変数のため使用不可、$cmdArgs を使う
$argParts = @("-u", "run_cycle.py", "--sheet-id", $SheetId, "--sheet-label", $SheetLabel)
if ($SkipUpload) {
    $argParts += "--skip-upload"
}
$cmdArgs = $argParts -join " "

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
        # Execute が絶対パスかチェック (bug 再発防止)
        $executePath = $task.Actions[0].Execute
        if ($executePath -and -not [System.IO.Path]::IsPathRooted($executePath)) {
            Write-Warning "Execute が絶対パスでない: '$executePath' → タスク起動時に ERROR_FILE_NOT_FOUND の可能性"
            Write-Warning "再登録推奨: -Action Unregister → Register でこのスクリプトが絶対パスを再設定する"
        }
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

Write-Output "[INFO] Python: $pythonExe"

# ※ $action は $Action パラメータと衝突 (PS 変数名は大小区別なし) → $taskAction
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
    -Trigger $triggers `
    -Settings $taskSettings `
    -Description "iMakInventory 本番 cycle (4h おき: 10/14/18/22/02/06 時、trabajo と 2h ずらし並走)" `
    | Out-Null

Write-Output "[OK] $TaskName 登録完了"
Write-Output "  schedule: 4h サイクル (10:00, 14:00, 18:00, 22:00, 02:00, 06:00)"
Write-Output "  並走対象: trabajo (08/12/16/20/00/04) と 2h ずらし"
Write-Output "  sheet_id:    $SheetId"
Write-Output "  sheet_label: $SheetLabel"
$stageMode = if ($SkipUpload) { "Stage 1 (eBay upload skip)" } else { "Stage 2 (eBay upload 有効)" }
Write-Output "  mode:        $stageMode"
Write-Output "  command: $pythonExe $cmdArgs"
Write-Output "  cwd: $WorkingDir"
Write-Output "  retry: 1 回 / 15 分後"
Write-Output "  execution time limit: 3h"
Write-Output ""
Write-Output "確認:  PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Status"
Write-Output "削除:  PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -Action Unregister"
Write-Output "Stage 2 移行時:  PowerShell -ExecutionPolicy Bypass -File tools\register_cycle_task.ps1 -SkipUpload:`$false"
