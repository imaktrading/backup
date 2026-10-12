@echo off
rem 売れたカードの仕入元の見張り (card_watch.py) を10分おきに。窓なし (run_hidden.vbs から呼ぶ)
cd /d C:\dev\iMak\iMakHQ\tools
"C:\Users\imax2\AppData\Local\Microsoft\WindowsApps\python.exe" card_watch.py >> C:\dev\iMak\iMakHQ\review_logs\card_watch_stdout.log 2>&1
