@echo off
REM Weekly: refresh our SOLD (90 days, eBay GetOrders) and rebuild chara_market.csv
REM (the chara list that Harvest's chara collection reads). 2026-10-10 user OK.
REM Only the list is rebuilt. The chara collection run itself stays on request only.
REM ASCII-only to avoid cp932 mojibake under Task Scheduler / cmd.
setlocal
set LOG=C:\dev\iMak_data\hq\market_sold\chara_targets_weekly.log
echo.>> "%LOG%"
echo ==== chara targets weekly START %DATE% %TIME% ====>> "%LOG%"

python "C:\dev\iMak\iMakHQ\tools\our_sold_fetch.py" >> "%LOG%" 2>&1
set STEP1=%ERRORLEVEL%
echo [step1 our_sold_fetch] exit=%STEP1% >> "%LOG%"
if not "%STEP1%"=="0" goto done

python "C:\dev\iMak\iMakHQ\tools\chara_targets_build.py" >> "%LOG%" 2>&1
set STEP2=%ERRORLEVEL%
echo [step2 chara_targets_build] exit=%STEP2% >> "%LOG%"

:done
set RC=%STEP1%
if "%RC%"=="0" set RC=%STEP2%
echo ==== chara targets weekly DONE rc=%RC% ====>> "%LOG%"
endlocal & exit /b %RC%
