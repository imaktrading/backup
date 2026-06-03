# run_cycle.ps1 - リバイスくん 1 cycle 実行 (タスクスケジューラから呼ばれる).
#
# 設計:
#   - 監視くん cycle (4h) の +30 分後に走る前提
#   - 監視くんが N 列を更新した直後に動くことで、変動を検知できる
#   - ログは decision_log/cron_<timestamp>.log
#   - エラーは LASTEXITCODE に乗せて Task Scheduler で見える形にする
#
# Usage (タスクスケジューラ Action):
#   Program: powershell.exe
#   Args:    -ExecutionPolicy Bypass -File C:\dev\iMak_revise\iMakRevise\tools\run_cycle.ps1
#   Start in: C:\dev\iMak_revise\iMakRevise

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "decision_log"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "cron_$Timestamp.log"

# UTF-8 強制 (Windows console は cp932 default)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Write-Host "=== リバイスくん cycle 開始: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Tee-Object -FilePath $LogFile

try {
    $pyArgs = @(
        "-X", "utf8",
        (Join-Path $ProjectRoot "run_revise.py")
    )
    & python @pyArgs 2>&1 | Tee-Object -FilePath $LogFile -Append
    $exitCode = $LASTEXITCODE
} catch {
    "ERROR: $_" | Tee-Object -FilePath $LogFile -Append
    $exitCode = 1
}

Write-Host "=== cycle 終了 (exit=$exitCode): $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Tee-Object -FilePath $LogFile -Append

# 古いログ自動削除 (30 日超)
Get-ChildItem -Path $LogDir -Filter "cron_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $exitCode
