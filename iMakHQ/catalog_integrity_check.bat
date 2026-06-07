@echo off
REM カタログ整合 定期監査 (週次想定) — name_en/set_name_ebay/filter_map drift を検出
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i
python "c:\dev\iMak\iMakHQ\tools\catalog_integrity_check.py" %STAMP%
exit /b %ERRORLEVEL%
