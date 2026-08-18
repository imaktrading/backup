@echo off
REM ---------------------------------------------------------------------------
REM Nightly PSA cert prefetch, so the pre-slot filters can actually judge cards.
REM
REM ASCII ONLY. cmd.exe reads .bat with the OEM codepage (932); Japanese comments
REM turn into mojibake and get parsed as commands (see run_hoju_search.bat).
REM
REM Why:
REM   psa_to_csv drops "out of scope / not in catalog / no image / already live"
REM   BEFORE picking the day's slots, but that judgement needs PSA data, and PSA
REM   data is fetched AFTER the slots are picked. So a new card cannot be judged,
REM   is kept (correct: never drop on "unknown"), takes a slot, and is removed
REM   later. 2026-08-18: 6 of 20 slots were spent on cards already listed, and
REM   they were removed AFTER a human had eyeballed them.
REM
REM Rate:
REM   40 certs per night, 15s apart (the interval lives in get_psa_data, not here).
REM   Until now PSA was touched ~12 times a day, so this is a deliberate, small
REM   step up. It stops immediately on a Cloudflare challenge (nobody is awake to
REM   solve it) and skips the whole run if the listing tool holds the profile.
REM ---------------------------------------------------------------------------
setlocal
set PYTHONIOENCODING=utf-8
cd /d C:\dev\iMak\iMakTCG

set TODAY=unknown
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set TODAY=%%a-%%b-%%c
set LOG=C:\dev\iMak\iMakHQ\review_logs\psa_cache_warm_%TODAY%.log
if not exist C:\dev\iMak\iMakHQ\review_logs mkdir C:\dev\iMak\iMakHQ\review_logs

echo [start] %date% %time% >> "%LOG%"
python -u psa_cache_warm.py --limit 40 >> "%LOG%" 2>&1
echo [end] %date% %time% >> "%LOG%"
endlocal
