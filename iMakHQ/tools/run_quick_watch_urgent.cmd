@echo off
rem Ask the watcher (QUICK) to check urgent PSA listings now (every 2 hours, hidden via run_hidden.vbs). 2026-10-14
cd /d C:\dev\iMak\iMakHQ\tools
"C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\python.exe" -X utf8 quick_watch_request.py urgent >> C:\dev\iMak\iMakHQ\review_logs\quick_watch_request.log 2>&1
