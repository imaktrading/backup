# 出品くん Console のデスクトップショートカットを作る (2026-09-16)。
# 作り直したい時・別PCに入れる時はこれを1回走らせる:
#   powershell -NoProfile -ExecutionPolicy Bypass -File make_shortcut.ps1
# 旧 出品くん (出品くん.lnk) はそのまま。並べて置いて、少しずつ新しい方に移る。
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop '出品くん Console.lnk'

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($link)
$s.TargetPath = Join-Path $here 'start_console.vbs'   # 二重起動しない (動いていれば窓だけ開く)
$s.WorkingDirectory = $here
$s.IconLocation = (Join-Path $here 'static\icon.ico') + ',0'  # 店舗ロゴのうさぎ (窓アイコンと同じ・2026-09-17)
$s.Description = '出品くん Console (新しい画面・Edge のアプリ窓で開く)'
$s.Save()
Write-Output ("作成: " + $link)
