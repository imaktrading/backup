@echo off
title Window ALPHA jisou OFF
echo.
echo  ============================================================
echo   ‘‹Œû ALPHA ‚Ì©‘–‚ğ OFF ‚É‚µ‚Ü‚·
echo  ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Unregister-ScheduledTask -TaskName 'iMakHQ_DeskAutorun_ALPHA' -Confirm:$false -ErrorAction Stop; Write-Host '  stopped' } catch { Write-Host '  not registered' }"
echo.
echo   ‘–s’†‚Ì1Œ‚ÍÅŒã‚Ü‚Å‚â‚èØ‚Á‚Ä‚©‚ç~‚Ü‚è‚Ü‚· (“r’†‚Å‰ó‚³‚È‚¢‚½‚ß)B
echo.
pause
exit /b 0
