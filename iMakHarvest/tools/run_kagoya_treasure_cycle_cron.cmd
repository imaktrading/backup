@echo off
REM iMakHarvest Kagoya treasure-hunt offload cycle (hourly). Cheap (SSH only, no Chrome on this PC).
REM Picks up finished results from KAGOYA and writes to mercari_psa10_treasure sheet.
cd /d C:\dev\iMak_harvest\iMakHarvest
set PYTHONIOENCODING=utf-8
set PYW="C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
set LOG=debug\cron_kagoya_treasure.log
set FLAG=debug\CRON_FAILED_kagoya_treasure.flag
echo ==== %DATE% %TIME% START ==== >> %LOG%
%PYW% -u tools\kagoya_treasure_offload.py cycle >> %LOG% 2>&1
if errorlevel 1 (
  echo ==== %DATE% %TIME% FAILED exit=%errorlevel% -- REQUIRES ATTENTION ==== >> %LOG%
  echo FAILED %DATE% %TIME% exit=%errorlevel% > %FLAG%
) else (
  echo ==== %DATE% %TIME% OK ==== >> %LOG%
  if exist %FLAG% del %FLAG%
)
