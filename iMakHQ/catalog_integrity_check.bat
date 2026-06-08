@echo off
REM Catalog integrity weekly audit (name_en / set_name raw / filter_map drift)
REM ASCII-only to avoid cp932 mojibake under Task Scheduler / cmd.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i
python "c:\dev\iMak\iMakHQ\tools\catalog_integrity_check.py" %STAMP%
exit /b %ERRORLEVEL%
