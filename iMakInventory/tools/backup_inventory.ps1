# backup_inventory.ps1
#
# iMakInventory の完全バックアップを 1 つの zip に固めて C:\local_backup\iMakInventory\
# に保存する。5 世代保持 (古いものは自動削除)。
#
# 事故 2026-05-05 (eBay session 切れ silent 失敗 24h) を受けた防衛施策:
# 監視くん本体が物理的に壊れた / 誤操作で消えた場合に直近 5 日のどの時点にも
# 戻せる体制にする。GitHub にコードはあるが chrome profile / decision_log /
# タスクスケジューラ定義は local のみのため、これらを zip に同梱する。
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\backup_inventory.ps1
#
# Schedule:
#   毎日 1 回 (例: 04:00) cron 化推奨。cycle (5:30/9:30/.. 4h おき) と重ならない
#   時刻を選ぶこと。
#
# バックアップ内容:
#   - iMakInventory worktree フォルダ全体 (= C:\dev\iMak_inventory\)
#       - コード (uncommit 含む) / decision_log / csv_output / .gui_state.json 等
#   - chrome profile (C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay\)
#       - eBay login cookie (再ログイン回避用)
#   - タスクスケジューラ XML (iMakInventory_Cycle export)

$ErrorActionPreference = 'Stop'

# UTF-8 console (日本語ログの文字化け防止)
try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

# 設定
$WorkTreeRoot = "C:\dev\iMak_inventory"
$ChromeProfileDir = "C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay"
$BackupRoot = "C:\local_backup\iMakInventory"
$TaskName = "iMakInventory_Cycle"
$Generations = 5

# ステージング dir (zip に固める前の作業領域)
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StagingDir = Join-Path $env:TEMP "iMakInventory_backup_staging_$Stamp"
$ZipPath = Join-Path $BackupRoot ("backup_iMakInventory_$Stamp.zip")

Write-Output "[INFO] iMakInventory backup 開始: $Stamp"
Write-Output "[INFO] 出力先: $ZipPath"

# 出力 dir 確保
if (-not (Test-Path $BackupRoot)) {
    New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
    Write-Output "[INFO] backup root 作成: $BackupRoot"
}
if (Test-Path $StagingDir) { Remove-Item -Recurse -Force $StagingDir }
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null

# 1. worktree (コード + decision_log + csv_output + .gui_state.json 等)
#    .git は除外しない (uncommit な変更を保全するため、丸ごと copy)
Write-Output "[1/3] worktree copy: $WorkTreeRoot"
if (Test-Path $WorkTreeRoot) {
    $dest = Join-Path $StagingDir "worktree"
    # robocopy /MIR は staging 用、/XJ で junction 除外、/NFL /NDL で進捗 quiet
    robocopy $WorkTreeRoot $dest /E /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed (exit=$LASTEXITCODE) for $WorkTreeRoot"
    }
    Write-Output "  ✅ done"
} else {
    Write-Warning "  ⚠️ worktree path 不在: $WorkTreeRoot"
}

# 2. chrome profile (eBay login cookie)
Write-Output "[2/3] chrome profile copy: $ChromeProfileDir"
if (Test-Path $ChromeProfileDir) {
    $dest = Join-Path $StagingDir "chrome_profile_ebay"
    robocopy $ChromeProfileDir $dest /E /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed (exit=$LASTEXITCODE) for $ChromeProfileDir"
    }
    Write-Output "  ✅ done"
} else {
    Write-Warning "  ⚠️ chrome profile 不在: $ChromeProfileDir"
}

# 3. タスクスケジューラ XML
Write-Output "[3/3] タスクスケジューラ XML export: $TaskName"
$taskXmlPath = Join-Path $StagingDir "${TaskName}.xml"
try {
    $xml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Set-Content -Path $taskXmlPath -Value $xml -Encoding UTF8
    Write-Output "  ✅ done: $taskXmlPath"
} catch {
    Write-Warning "  ⚠️ task XML export 失敗: $($_.Exception.Message)"
}

# 4. zip 圧縮
Write-Output "[zip] 圧縮: $StagingDir → $ZipPath"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
$zipSize = (Get-Item $ZipPath).Length / 1MB
Write-Output "  ✅ zip done: $($zipSize.ToString('F1')) MB"

# staging 削除
Remove-Item -Recurse -Force $StagingDir

# 5. 世代管理: 5 個を超えたら最古を削除
Write-Output "[gen] 世代管理: $Generations 世代保持"
$existing = Get-ChildItem -Path $BackupRoot -Filter "backup_iMakInventory_*.zip" |
    Sort-Object Name -Descending
if ($existing.Count -gt $Generations) {
    $toDelete = $existing | Select-Object -Skip $Generations
    foreach ($f in $toDelete) {
        Remove-Item -Force $f.FullName
        Write-Output "  🗑️ 削除 (古い世代): $($f.Name)"
    }
}
$remaining = Get-ChildItem -Path $BackupRoot -Filter "backup_iMakInventory_*.zip" |
    Sort-Object Name -Descending
Write-Output "[INFO] 保持中の世代: $($remaining.Count) 個"
foreach ($f in $remaining) {
    $sizeMB = $f.Length / 1MB
    Write-Output "  - $($f.Name) ($($sizeMB.ToString('F1')) MB)"
}

Write-Output "[OK] backup 完了: $ZipPath"
exit 0
