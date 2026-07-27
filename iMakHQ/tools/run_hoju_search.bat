@echo off
REM ---------------------------------------------------------------------------
REM 補URL 候補の定期ストック (2026-07-28)。
REM   slice2(検索)= 候補を psa_research_cache.json に貯めるだけ。補URL列には触らない。
REM   → 「🩹 補URL補強(昼確認)」ボタンは **キャッシュを読むだけ**なので即 HTML が出る。
REM 定期化しないとキャッシュが枯れ、ボタンを押しても 0件になる(2026-07-28 実測: 未取得47件)。
REM
REM 1回 30件 = BAN リスク回避のコツコツ運用 (nightly-batch-slow-and-steady)。
REM Google Sheets API は 503 を返すことがあるので最大3回リトライ。
REM ---------------------------------------------------------------------------
setlocal
set PYTHONIOENCODING=utf-8
cd /d C:\dev\iMak\iMakHQ\tools

for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set TODAY=%%a-%%b-%%c
set LOG=C:\dev\iMak\iMakHQ\review_logs\hoju_search_cron_%TODAY%.log
if not exist C:\dev\iMak\iMakHQ\review_logs mkdir C:\dev\iMak\iMakHQ\review_logs

for %%i in (1 2 3) do (
    echo [try %%i] %date% %time% >> "%LOG%"
    python -u psa_hoju_fill.py search --limit=30 >> "%LOG%" 2>&1
    if not errorlevel 1 goto :done
    echo [try %%i] failed, retry in 120s >> "%LOG%"
    timeout /t 120 /nobreak > nul
)
:done
echo [end] %date% %time% >> "%LOG%"
endlocal
