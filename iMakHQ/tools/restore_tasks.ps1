# 予約タスクを新しい PC に戻す (2026-09-30)。
#   powershell -ExecutionPolicy Bypass -File C:\dev\iMak\iMakHQ\tools\restore_tasks.ps1 -Kit <restore_kit のフォルダ>
#
# 控えの xml には元の PC のユーザー番号 (SID) が入っていて、そのままでは登録できない。今のユーザーに差し替えて登録する。
# 止めてあったタスク (監視くん = LAPTOP に移した分 等) は止めたまま戻る。
# 動かす物 (python.exe 等) が無いタスクは一覧に出す (Python は Microsoft Store 版 3.11 が前提)。
param([Parameter(Mandatory = $true)][string]$Kit, [switch]$DryRun)   # -DryRun = 登録せずに確かめるだけ

$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$ok = 0; $bad = @(); $noexe = @()
foreach ($f in Get-ChildItem (Join-Path $Kit 'scheduled_tasks') -Filter *.xml) {
    $x = [IO.File]::ReadAllText($f.FullName)
    $x = [regex]::Replace($x, '<UserId>S-1-5-21-[0-9-]+</UserId>', "<UserId>$sid</UserId>")
    foreach ($m in [regex]::Matches($x, '[A-Za-z]:\\[^"<]*?\.(exe|cmd|bat|vbs)')) {
        if (-not (Test-Path $m.Value)) { $noexe += "$($f.BaseName): $($m.Value)" }
    }
    $tmp = Join-Path $env:TEMP ($f.BaseName + '.xml')
    [IO.File]::WriteAllText($tmp, $x, [Text.Encoding]::Unicode)
    if ($DryRun) { if ($x -match "<UserId>$sid</UserId>") { $ok++ } else { $bad += $f.BaseName }; Remove-Item $tmp; continue }
    schtasks /create /tn $f.BaseName /xml $tmp /f | Out-Null
    if ($LASTEXITCODE -eq 0) { $ok++ } else { $bad += $f.BaseName }
    Remove-Item $tmp
}
"登録できた: $ok 本"
if ($bad) { "⚠️要対応 登録できなかった: $($bad -join ', ')" }
if ($noexe) { "⚠️要対応 動かす物が無い (入れてから走らせ直す):"; $noexe | Sort-Object -Unique }
if (-not $bad -and -not $noexe) { "✅ 正常: 全部戻った" }
