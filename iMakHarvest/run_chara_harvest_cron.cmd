@echo off
REM iMakHarvest chara-axis treasure hunt (weekly). Full 184 keywords, no narrowing (user confirmed 2026-09-24).
REM Writes to mercari_psa10_chara tab. If chara_market.csv is empty/missing, script does nothing.
REM NOTE: keep this .cmd ASCII-only (cmd.exe misreads UTF-8 Japanese in REM lines).
cd /d C:\dev\iMak_harvest\iMakHarvest
set PYTHONIOENCODING=utf-8
set PYW="C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
set LOG=debug\cron_chara_harvest.log
set FLAG=debug\CRON_FAILED_chara_harvest.flag
echo ==== %DATE% %TIME% START ==== >> %LOG%
%PYW% -u run_harvest_mercari_chara.py >> %LOG% 2>&1
if errorlevel 1 (
  echo ==== %DATE% %TIME% FAILED exit=%errorlevel% -- REQUIRES ATTENTION ==== >> %LOG%
  echo FAILED %DATE% %TIME% exit=%errorlevel% > %FLAG%
) else (
  echo ==== %DATE% %TIME% OK ==== >> %LOG%
  if exist %FLAG% del %FLAG%
)
