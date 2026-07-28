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

REM --- ① 補URL 0本 (= 仕入元1本が死んだら即死する行) を最優先で 30件 ---
for %%i in (1 2 3) do (
    echo [try %%i] zero-backup %date% %time% >> "%LOG%"
    python -u psa_hoju_fill.py search --limit=30 >> "%LOG%" 2>&1
    if not errorlevel 1 goto :topup
    echo [try %%i] failed, retry in 120s >> "%LOG%"
    timeout /t 120 /nobreak > nul
)
goto :done

REM --- ② 積み増し: 補1本しか無い行にも候補を貯めておく (0本が捌けても走る先が尽きないように) ---
REM     「候補は常にストックしておいてほしい」(2026-07-28 ユーザー指示)。
REM     ①より件数を絞る = 危険度順に配分し、総アクセス量を抑える (BAN リスク)。
:topup
echo [topup] max-backups=2 %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py search --max-backups=2 --limit=10 >> "%LOG%" 2>&1

REM --- ③ 再仕入れ候補(ファネル RESTOCK∩PSA10)の先読み ---
REM     「🃏 PSA再仕入れ照合」は押してから探すので待たされる。同じ psa_research_cache を
REM     共有しているので夜に温めておけば当日キャッシュが効き、ボタンが即答になる。
REM     スプシにも補URL列にも書かない (判定は従来どおり有人ゲート)。
echo [restock] prefetch %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py search-restock --limit=20 >> "%LOG%" 2>&1

:done
echo [end] %date% %time% >> "%LOG%"
endlocal
