# 出品くん Console のサーバを安全に入れ替える (2026-09-16)。
#
# ★実害: 2026-09-16 18:11 に、走っていた 🤖自動 (PSA) の最中にサーバを再起動して落とした。
#   これからは **走行中は入れ替えない**。どうしても入れ替える時は -Force を付ける
#   (その場合も、走っている作業は別プロセスグループなので巻き込まれない)。
#
#   使い方: powershell -NoProfile -ExecutionPolicy Bypass -File restart.ps1 [-Force]
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

try {
    $job = (Invoke-WebRequest -Uri 'http://127.0.0.1:8770/api/log?after=0' -UseBasicParsing -TimeoutSec 10).Content | ConvertFrom-Json
} catch { $job = $null }

if ($job -and $job.job -and $job.job.running -and -not $Force) {
    Write-Output ("走行中です: {0} ({1}〜)。終わってから入れ替えてください (どうしてもなら -Force)" -f $job.job.label, $job.job.started)
    exit 1
}

$c = Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue
if ($c) { Stop-Process -Id $c.OwningProcess -Force; Start-Sleep -Seconds 2; Write-Output "古いサーバを止めました" }
wscript.exe (Join-Path $here 'start_console.vbs')
Start-Sleep -Seconds 5
try {
    $v = (Invoke-WebRequest -Uri 'http://127.0.0.1:8770/api/version' -UseBasicParsing -TimeoutSec 20).Content | ConvertFrom-Json
    Write-Output ("入れ替えました: v{0}" -f $v.version)
} catch { Write-Output "起動を確認できません" }
