@echo off
REM iMakHarvest Yodobashi collection + GshockMerge, run remotely on KAGOYA (desktop does SSH only).
REM Replaces iMakHarvest_YodobashiHarvest_2100 / iMakHarvest_GshockMerge_2130 (now Disabled).
cd /d C:\dev\iMak_harvest\iMakHarvest
set PYTHONIOENCODING=utf-8
set PYW="C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
set LOG=debug\cron_kagoya_yodobashi.log
set FLAG=debug\CRON_FAILED_kagoya_yodobashi.flag
echo ==== %DATE% %TIME% START ==== >> %LOG%
%PYW% -u tools\kagoya_yodobashi_offload.py cycle >> %LOG% 2>&1
if errorlevel 1 (
  echo ==== %DATE% %TIME% FAILED exit=%errorlevel% -- REQUIRES ATTENTION ==== >> %LOG%
  echo FAILED %DATE% %TIME% exit=%errorlevel% > %FLAG%
) else (
  echo ==== %DATE% %TIME% OK ==== >> %LOG%
  if exist %FLAG% del %FLAG%
)
