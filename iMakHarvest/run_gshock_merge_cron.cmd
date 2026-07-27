@echo off
REM iMakHarvest G-shock merge (daily 21:30). After collection(21:00), before snapshot(22:00).
REM Idempotent: appends Yodobashi supp URLs to LOW AC-AG + updates Q(FLG). D column untouched.
REM NOTE: keep this .cmd ASCII-only (cmd.exe misreads UTF-8 Japanese in REM lines).
cd /d C:\dev\iMak_harvest\iMakHarvest
set PYTHONIOENCODING=utf-8
set PYW="C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
set LOG=debug\cron_gshock_merge.log
set FLAG=debug\CRON_FAILED_gshock_merge.flag
echo ==== %DATE% %TIME% START ==== >> %LOG%
%PYW% -u run_gshock_merge.py >> %LOG% 2>&1
if errorlevel 1 (
  echo ==== %DATE% %TIME% FAILED exit=%errorlevel% -- REQUIRES ATTENTION ==== >> %LOG%
  echo FAILED %DATE% %TIME% exit=%errorlevel% > %FLAG%
) else (
  echo ==== %DATE% %TIME% OK ==== >> %LOG%
  if exist %FLAG% del %FLAG%
)
