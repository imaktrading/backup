@echo off
REM Claude Code memory + chat history backup to local
setlocal
set "SRC=C:\Users\imax2\.claude"
set "DST=C:\Users\imax2\backups\.claude_backup"
set "LOG=%DST%\_backup.log"

if not exist "%DST%" mkdir "%DST%"

echo === Backup start: %DATE% %TIME% === >> "%LOG%"

robocopy "%SRC%\projects" "%DST%\projects" /E /XO /R:2 /W:5 /NP >> "%LOG%" 2>&1
robocopy "%SRC%" "%DST%" CLAUDE.md settings.json /R:2 /W:5 /NP >> "%LOG%" 2>&1
if exist "%SRC%\agents" robocopy "%SRC%\agents" "%DST%\agents" /E /XO /R:2 /W:5 /NP >> "%LOG%" 2>&1

python "c:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakHQ\convert_chat_history.py" >> "%LOG%" 2>&1

echo === Backup end: %DATE% %TIME% === >> "%LOG%"
echo. >> "%LOG%"
endlocal
exit /b 0
