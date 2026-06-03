# register_task.ps1 - リバイスくん cron をタスクスケジューラに登録/削除/状態確認.
#
# 監視くん cycle (4h: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00) の
# +30 分後 (00:30, 04:30, 08:30, 12:30, 16:30, 20:30) に走らせる。
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File register_task.ps1 -Action Register     # 登録
#   PowerShell -ExecutionPolicy Bypass -File register_task.ps1 -Action Unregister   # 削除
#   PowerShell -ExecutionPolicy Bypass -File register_task.ps1 -Action Status       # 状態確認
#
# control_panel.py から呼ばれる。stdout で結果を返す (GUI で表示)。

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("Register", "Unregister", "Status")]
    [string]$Action = "Status"
)

$TaskName = "iMakRevise_PriceCycle"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunCycleScript = Join-Path $ProjectRoot "tools\run_cycle.ps1"

function Get-TaskInfo {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { return $null }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    return @{ Task = $task; Info = $info }
}

switch ($Action) {
    "Status" {
        $r = Get-TaskInfo
        if (-not $r) {
            Write-Host "[STATUS] 未登録: $TaskName"
            exit 0
        }
        $task = $r.Task
        $info = $r.Info
        Write-Host "[STATUS] 登録済: $TaskName"
        Write-Host "  State:           $($task.State)"
        Write-Host "  LastRunTime:     $($info.LastRunTime)"
        Write-Host "  LastTaskResult:  $($info.LastTaskResult) (0=success)"
        Write-Host "  NextRunTime:     $($info.NextRunTime)"
        Write-Host "  NumberOfMissedRuns: $($info.NumberOfMissedRuns)"
        $triggers = $task.Triggers | ForEach-Object {
            if ($_.StartBoundary) {
                ([DateTime]$_.StartBoundary).ToString("HH:mm")
            }
        }
        Write-Host "  Triggers (毎日): $($triggers -join ', ')"
        exit 0
    }

    "Unregister" {
        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "[UNREGISTER] 削除完了: $TaskName"
        } else {
            Write-Host "[UNREGISTER] 未登録のため削除スキップ: $TaskName"
        }
        exit 0
    }

    "Register" {
        if (-not (Test-Path $RunCycleScript)) {
            Write-Error "run_cycle.ps1 が見つかりません: $RunCycleScript"
            exit 1
        }

        # 既存タスク削除 (re-register 用)
        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "[REGISTER] 既存タスク削除"
        }

        $TaskAction = New-ScheduledTaskAction `
            -Execute "powershell.exe" `
            -Argument "-ExecutionPolicy Bypass -NonInteractive -File `"$RunCycleScript`"" `
            -WorkingDirectory $ProjectRoot

        # 監視くん +30 分オフセット (4h cycle: HH=00,04,08,12,16,20 + 30min)
        $Triggers = @()
        foreach ($hour in @(0, 4, 8, 12, 16, 20)) {
            $time = "{0:D2}:30" -f $hour
            $Triggers += New-ScheduledTaskTrigger -Daily -At $time
        }

        $Settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

        $Principal = New-ScheduledTaskPrincipal `
            -UserId $env:USERNAME `
            -LogonType Interactive `
            -RunLevel Limited

        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $TaskAction `
            -Trigger $Triggers `
            -Settings $Settings `
            -Principal $Principal `
            -Description "iMakRevise Phase 1 - 価格 revise (監視くん cycle +30min)" | Out-Null

        Write-Host "[REGISTER] 登録完了: $TaskName"
        Write-Host "  実行 script: $RunCycleScript"
        Write-Host "  実行時刻 (毎日): 00:30, 04:30, 08:30, 12:30, 16:30, 20:30"
        Write-Host "  ログ: $ProjectRoot\decision_log\cron_<timestamp>.log"
        exit 0
    }
}
