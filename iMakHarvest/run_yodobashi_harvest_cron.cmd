@echo off
REM iMakHarvest Yodobashi collection (daily 21:00). Before merge(21:30) -> snapshot(22:00) -> LOW(22:45).
REM Refreshes yodobashi_gshock tab (idempotent append by product_id).
REM NOTE: keep this .cmd ASCII-only (cmd.exe misreads UTF-8 Japanese in REM lines).
cd /d C:\dev\iMak_harvest\iMakHarvest
set PYTHONIOENCODING=utf-8
set PYW="C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
set LOG=debug\cron_yodobashi_harvest.log
set FLAG=debug\CRON_FAILED_yodobashi_harvest.flag
echo ==== %DATE% %TIME% START ==== >> %LOG%
%PYW% -u run_harvest_yodobashi.py >> %LOG% 2>&1
if errorlevel 1 (
  echo ==== %DATE% %TIME% FAILED exit=%errorlevel% -- REQUIRES ATTENTION ==== >> %LOG%
  echo FAILED %DATE% %TIME% exit=%errorlevel% > %FLAG%
) else (
  echo ==== %DATE% %TIME% OK ==== >> %LOG%
  if exist %FLAG% del %FLAG%
)
