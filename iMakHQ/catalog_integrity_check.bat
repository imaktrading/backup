@echo off
REM Catalog weekly maintenance: integrity audit (report) + spreadsheet refresh.
REM ASCII-only to avoid cp932 mojibake under Task Scheduler / cmd.
REM
REM 2026-07-31: this task had returned 255 on 2026-07-27 with NO evidence left behind.
REM   Two structural defects were fixed here:
REM     (a) "exit /b %%ERRORLEVEL%%" returned only the LAST script's code, so step 1
REM         detecting anomalies (exit 1 by design) was silently swallowed = fail-OPEN.
REM     (b) no redirect at all, so a Task Scheduler failure left no log to diagnose.
REM   Now: every step logs stdout/stderr and its own exit code, and the task result
REM   distinguishes "anomalies found" (10) from "a step actually failed" (its raw code).
setlocal
set LOG=C:\dev\iMak_data\catalog\integrity_weekly.log
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i

echo.>> "%LOG%"
echo ==== integrity weekly START %DATE% %TIME% ====>> "%LOG%"
set RC=0
set ANOMALY=0

REM 1) integrity audit -> writes dated report to tools\_audit_reports\
REM    exit 1 = anomalies detected (by design, NOT a crash)
python "c:\dev\iMak\iMakHQ\tools\catalog_integrity_check.py" %STAMP% >> "%LOG%" 2>&1
set STEP1=%ERRORLEVEL%
echo [step1 catalog_integrity_check] exit=%STEP1%>> "%LOG%"
if "%STEP1%"=="1" set ANOMALY=1
if not "%STEP1%"=="0" if not "%STEP1%"=="1" set RC=%STEP1%

REM 1b) hand whitelist vs eBay official filter drift (value drift detection)
python "c:\dev\iMak\iMakHQ\tools\whitelist_official_drift.py" >> "%LOG%" 2>&1
set STEP2=%ERRORLEVEL%
echo [step2 whitelist_official_drift] exit=%STEP2%>> "%LOG%"
if not "%STEP2%"=="0" if "%RC%"=="0" set RC=%STEP2%

REM 2) refresh catalog visualization spreadsheet with latest (corrected) catalog
python "c:\dev\iMak\iMakHQ\tools\catalog_to_sheet.py" >> "%LOG%" 2>&1
set STEP3=%ERRORLEVEL%
echo [step3 catalog_to_sheet] exit=%STEP3%>> "%LOG%"
if not "%STEP3%"=="0" if "%RC%"=="0" set RC=%STEP3%

REM anomalies alone must not look like a crash, but must not look like "clean" either
if "%RC%"=="0" if "%ANOMALY%"=="1" set RC=10

echo ==== integrity weekly DONE rc=%RC% (step1=%STEP1% step2=%STEP2% step3=%STEP3% anomaly=%ANOMALY%) ====>> "%LOG%"
endlocal & exit /b %RC%
