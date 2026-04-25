Dim oShell, oFso, sScriptDir, sPythonw, sStorePy
Set oShell = CreateObject("WScript.Shell")
Set oFso = CreateObject("Scripting.FileSystemObject")
sScriptDir = oFso.GetParentFolderName(WScript.ScriptFullName)
oShell.CurrentDirectory = sScriptDir
sStorePy = oShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\pythonw.exe"
If oFso.FileExists(sStorePy) Then
    sPythonw = sStorePy
Else
    sPythonw = "pythonw"
End If
oShell.Run """" & sPythonw & """ """ & sScriptDir & "\control_panel.py""", 0, False
