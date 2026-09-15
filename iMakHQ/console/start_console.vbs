' 出品くん Console を開く (2026-09-15)。サーバーが動いていれば窓だけ開く。
' 今の出品くん (control_panel.py) とは別。両方同時に使える。
Set sh = CreateObject("WScript.Shell")
sh.Run "pythonw ""C:\dev\iMak\iMakHQ\console\server.py""", 0, False
