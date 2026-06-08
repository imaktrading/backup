@echo off
REM Catalog weekly maintenance: integrity audit (report) + spreadsheet refresh.
REM ASCII-only to avoid cp932 mojibake under Task Scheduler / cmd.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i
REM 1) integrity audit -> writes dated report to tools\_audit_reports\
python "c:\dev\iMak\iMakHQ\tools\catalog_integrity_check.py" %STAMP%
REM 2) refresh catalog visualization spreadsheet with latest (corrected) catalog
python "c:\dev\iMak\iMakHQ\tools\catalog_to_sheet.py"
exit /b %ERRORLEVEL%
