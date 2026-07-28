@echo off
REM iMakHarvest Yodobashi stock snapshot generator (daily 06:00/14:00/22:00, before LOW cycles).
REM Inventory looks up yodobashi_stock_snapshot.json by model KEY for M-min.
REM NOTE: keep this .cmd ASCII-only (cmd.exe misreads UTF-8 Japanese in REM lines).
cd /d C:\dev\iMak_harvest\iMakHarvest
set PYTHONIOENCODING=utf-8
set PYW="C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
set LOG=debug\snapshot_cron.log
set FLAG=debug\CRON_FAILED_snapshot.flag
echo ==== %DATE% %TIME% START ==== >> %LOG%
%PYW% -u build_yodobashi_snapshot.py >> %LOG% 2>&1
if errorlevel 1 (
  echo ==== %DATE% %TIME% FAILED exit=%errorlevel% -- REQUIRES ATTENTION ==== >> %LOG%
  echo FAILED %DATE% %TIME% exit=%errorlevel% > %FLAG%
) else (
  echo ==== %DATE% %TIME% OK ==== >> %LOG%
  if exist %FLAG% del %FLAG%
)
