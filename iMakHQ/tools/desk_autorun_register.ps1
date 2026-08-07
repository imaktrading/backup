# 窓口 ALPHA の自走をスケジューラに登録する (2026-08-02)。
#
# .bat から呼ばれる。.bat は cmd.exe が CP932 で読むため、長い PowerShell を直書きすると
# 日本語コメントが行を壊す (test_bat_encoding_20260730 の教訓)。処理はこちらに寄せる。
#
# 管理者権限は不要 (自分のユーザーのタスクなので)。
param([int]$Minutes = 5)   # 起動間隔。変えたいときはここだけ

$ErrorActionPreference = 'Stop'
try {
    $py  = 'C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\pythonw.exe'
    $act = New-ScheduledTaskAction -Execute $py `
        -Argument '-X utf8 "C:\dev\iMak\iMakHQ\tools\desk_autorun.py" --who ALPHA' `
        -WorkingDirectory 'C:\dev\iMak'
    # 既定5分。1件ずつしか取らないので、詰まっていれば5分ごとに1件ずつ減っていく。
    # ★短くしてもコストはほぼゼロ: 残務が無い起動は agent を立てずに1秒未満で終わる
    #   (`skip-empty`)。課金が発生するのは「実際に仕事があった時」だけ。
    #   走行中は IgnoreNew で新規起動しないので、間隔を詰めても多重にはならない。
    $trg = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(6) `
        -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
    # IgnoreNew: 前の1件が走っている間は新しく起動しない (1窓口1件を守る)
    # ExecutionTimeLimit 40分: desk_autorun 側の 30分 timeout より少し長く取る
    $set = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -Hidden
    Register-ScheduledTask -TaskName 'iMakHQ_DeskAutorun_ALPHA' `
        -Action $act -Trigger $trg -Settings $set `
        -Description '窓口ALPHAが手すきの間、残務を1件ずつ自走で片付ける (2026-08-02 ユーザー承認・1窓口のみ)' `
        -Force | Out-Null
    $v = Get-ScheduledTask -TaskName 'iMakHQ_DeskAutorun_ALPHA'
    Write-Host ('  registered: state=' + $v.State + ' interval=' + $v.Triggers[0].Repetition.Interval)
    exit 0
} catch {
    Write-Host ('  FAILED: ' + $_.Exception.Message)
    exit 1
}
