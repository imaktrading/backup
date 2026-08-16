@echo off
REM ---------------------------------------------------------------------------
REM Nightly stock of aux-supply-URL candidates (slice2 search only).
REM
REM ASCII ONLY. Do not write Japanese in this file.
REM   2026-07-30: this batch was saved as UTF-8 with Japanese comments. cmd.exe
REM   reads .bat with the OEM codepage (932), so the comments turned into mojibake
REM   and were parsed as commands ("'do' is not recognized ..."). The for-loop was
REM   destroyed, nothing ran, no log was written, and the task still reported
REM   exit code 0 = "success". It had never run since it was created on 07-28.
REM   Keeping this file ASCII-only makes it codepage-independent.
REM
REM What it does (step 0 writes the KEY column; the rest only caches candidates):
REM   0) fill blank canonical KEY  : key_backfill_live.py
REM   1) zero-backup listings first  : search --limit=30
REM   2) top-up (1 backup)           : search --max-backups=2 --limit=10
REM   3) restock prefetch            : search-restock --limit=20
REM   4) ichibankuji prefetch        : ichibankuji_restock.py prefetch 10
REM   5) ichibankuji live aux        : ichibankuji_restock.py prefetch-live 10
REM   30 items per run = slow and steady, to keep the BAN risk low.
REM   Google Sheets API can return 503, so step 1 retries up to 3 times.
REM ---------------------------------------------------------------------------
setlocal
set PYTHONIOENCODING=utf-8
cd /d C:\dev\iMak\iMakHQ\tools

REM Build YYYY-MM-DD from %date% (e.g. 2026/07/30). Fall back to "unknown" if the
REM locale format is unexpected, so the log path is always valid.
set TODAY=unknown
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set TODAY=%%a-%%b-%%c
set LOG=C:\dev\iMak\iMakHQ\review_logs\hoju_search_cron_%TODAY%.log
if not exist C:\dev\iMak\iMakHQ\review_logs mkdir C:\dev\iMak\iMakHQ\review_logs

echo [start] %date% %time% >> "%LOG%"

REM --- 0) fill the canonical KEY of live listings that are still blank.
REM        2026-08-16: KEY was only filled for rows in that day's CSV, so a row
REM        missed at listing time stayed blank forever. A blank KEY makes the
REM        aux-URL search skip the row ("no card number") and disables the
REM        duplicate check. The value comes from the cert (already confirmed by
REM        a human at listing time), so no review is needed. fail-closed: it
REM        writes nothing when the cert cannot be resolved.
echo [keyfill] %date% %time% >> "%LOG%"
python -u key_backfill_live.py >> "%LOG%" 2>&1

REM --- 1) zero-backup listings (a listing whose only supplier died = instant death)
for %%i in (1 2 3) do (
    echo [try %%i] zero-backup %date% %time% >> "%LOG%"
    python -u psa_hoju_fill.py search --limit=30 >> "%LOG%" 2>&1
    if not errorlevel 1 goto :topup
    echo [try %%i] failed, retry in 120s >> "%LOG%"
    timeout /t 120 /nobreak > nul
)
echo [warn] zero-backup step failed 3 times >> "%LOG%"
goto :done

:topup
REM --- 2) keep stocking listings that have only one backup, so we never run dry
echo [topup] max-backups=2 %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py search --max-backups=2 --limit=10 >> "%LOG%" 2>&1

REM --- 3) prefetch for the RESTOCK gate (shares psa_research_cache, makes the
REM        button answer instantly and cuts re-scraping)
echo [restock] prefetch %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py search-restock --limit=20 >> "%LOG%" 2>&1

REM --- 4) prefetch for ichibankuji aux URLs (candidates only, no UI, no sheet)
echo [ichibankuji] prefetch %date% %time% >> "%LOG%"
python -u ichibankuji_restock.py prefetch 10 >> "%LOG%" 2>&1

REM --- 5) prefetch for ichibankuji LIVE listings that are thin on aux URLs
REM        2026-08-16: step 4 fills out-of-stock rows first and there are ~50 of
REM        them, so live listings never got a slot. Aux URLs are insurance and
REM        must be stocked BEFORE the supplier dies, so give live its own step.
echo [ichibankuji] prefetch-live %date% %time% >> "%LOG%"
python -u ichibankuji_restock.py prefetch-live 10 >> "%LOG%" 2>&1

REM --- 5b) pre-open the candidate detail pages (condition / shipping / seller
REM         reviews). 2026-08-16: this was most of the 22 minutes the ichibankuji
REM         restock button took (9 items x 10 candidates, 3s wait each). Those
REM         fields never change, so cache them here and the button only shows.
echo [ichibankuji] prefetch-detail %date% %time% >> "%LOG%"
python -u ichibankuji_restock.py prefetch-detail 120 >> "%LOG%" 2>&1

REM --- 6) warm the daytime review screen (candidates -> ref image -> art match).
REM        2026-08-16: pressing the daytime button spent ~7 of its 8 minutes
REM        assembling the screen (fetch the listing image and AI-compare the art
REM        for every target), and only ~10 rows survived. None of that needs a
REM        human, so do it here. --dry-run does the same assembly but opens no
REM        browser and writes nothing; both caches (listing image / art match)
REM        are on disk, so the daytime run is then near-instant.
echo [confirm-warm] %date% %time% >> "%LOG%"
python -u psa_hoju_fill.py confirm --dry-run >> "%LOG%" 2>&1

:done
echo [end] %date% %time% >> "%LOG%"
endlocal
