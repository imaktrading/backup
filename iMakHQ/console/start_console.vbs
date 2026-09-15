' Shuppin-kun Console launcher (2026-09-15). Keep this file ASCII only:
' VBScript reads it in the ANSI codepage and a UTF-8 Japanese comment swallowed the next line.
' Opens the Edge app window; if the server is already running it only opens the window.
Dim oShell, oFso, sDir, sPythonw, sStorePy
Set oShell = CreateObject("WScript.Shell")
Set oFso = CreateObject("Scripting.FileSystemObject")
sDir = oFso.GetParentFolderName(WScript.ScriptFullName)
oShell.CurrentDirectory = sDir
sStorePy = oShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
If oFso.FileExists(sStorePy) Then
    sPythonw = sStorePy
Else
    sPythonw = "pythonw"
End If
oShell.Run """" & sPythonw & """ """ & sDir & "\server.py""", 0, False
