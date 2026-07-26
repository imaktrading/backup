@echo off
REM iMakHarvest Yodobashi stock snapshot generator (daily 22:20, 10min before LOW cycle 22:30)
REM Inventory looks up yodobashi_stock_snapshot.json by model KEY for M-min.
REM NOTE: keep this .cmd ASCII-only (cmd.exe misreads UTF-8 Japanese in REM lines).
cd /d C:\dev\iMak_harvest\iMakHarvest
"C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe" -u build_yodobashi_snapshot.py >> debug\snapshot_cron.log 2>&1
