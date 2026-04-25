@echo off
REM FX rate auto update for profit calc sheet
python "c:\dev\iMak\iMakHQ\update_rates.py"
exit /b %ERRORLEVEL%
