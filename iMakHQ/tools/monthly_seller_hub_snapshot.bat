@echo off
REM iMak Trading Japan - Seller Hub 月次 snapshot (Windows タスクスケジューラ用)
REM
REM 月初 1 日 04:00 に Windows タスクスケジューラで実行する想定 (Inventory cron 4h と被らない時刻)。
REM Active / Ended 両方を全ページ scrape して iMak_data/seller_hub/ に永続保存する。
REM
REM ログ出力: C:\dev\iMak\iMakHQ\logs\monthly_snapshot_<date>.log
REM
REM 依存: iMakInventory chrome_profile_ebay (cookie 永続化済) が必要。
REM       Inventory cron が同時刻に走ると profile lock 衝突するため、時刻を調整すること。

setlocal
cd /d C:\dev\iMak\iMakHQ
set PYTHONIOENCODING=utf-8

REM ログディレクトリ
if not exist logs mkdir logs
set LOGDATE=%date:~0,4%%date:~5,2%%date:~8,2%
set LOGFILE=logs\monthly_snapshot_%LOGDATE%.log

echo === iMak Seller Hub Monthly Snapshot %date% %time% === > "%LOGFILE%"
echo. >> "%LOGFILE%"

REM Ended 全件 (View 含む、90日消失データ防止)
echo [STEP 1/2] Ended 全件 scrape (--all-pages) >> "%LOGFILE%"
python seller_hub_view.py --status ended --all-pages --save --wait 25 >> "%LOGFILE%" 2>&1
echo. >> "%LOGFILE%"

REM Active 全件 (View+Watchers 現在地スナップ)
echo [STEP 2/2] Active 全件 scrape (--all-pages) >> "%LOGFILE%"
python seller_hub_view.py --status active --all-pages --save --wait 25 >> "%LOGFILE%" 2>&1
echo. >> "%LOGFILE%"

echo === DONE %date% %time% === >> "%LOGFILE%"
endlocal
