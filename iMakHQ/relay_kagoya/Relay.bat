@echo off
rem 2026-10-09 ADV: KAGOYA relay window for the new BRAVO (forwards program bells to BRAVO at home)
title RELAY
set PYTHONUTF8=1
set DISABLE_AUTOUPDATER=1
cd /d C:\dev\iMakRelay
if exist "%USERPROFILE%\.claude\projects\C--dev-iMakRelay\*.jsonl" (
  "C:\Users\Administrator\.local\bin\claude.exe" --continue --remote-control RELAY --remote-control-session-name-prefix RELAY
) else (
  "C:\Users\Administrator\.local\bin\claude.exe" -n RELAY --remote-control RELAY --remote-control-session-name-prefix RELAY
)
