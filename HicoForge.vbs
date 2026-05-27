' HicoForge.vbs — silent launcher
' Launches the venv Python on main.py with no console window flashing.

Set fso  = CreateObject("Scripting.FileSystemObject")
Set sh   = CreateObject("WScript.Shell")

' Script lives inside the install folder
installRoot = fso.GetParentFolderName(WScript.ScriptFullName)
pyExe       = installRoot & "\.venv\Scripts\pythonw.exe"
mainPy      = installRoot & "\main.py"

' Fall back to python.exe if pythonw.exe is missing (shouldn't normally happen)
If Not fso.FileExists(pyExe) Then
    pyExe = installRoot & "\.venv\Scripts\python.exe"
End If

If Not fso.FileExists(pyExe) Then
    MsgBox "HicoForge: virtual environment not found." & vbCrLf & _
           "Re-run setup.bat to install dependencies.", vbCritical, "HicoForge"
    WScript.Quit 1
End If

If Not fso.FileExists(mainPy) Then
    MsgBox "HicoForge: main.py not found at " & mainPy, vbCritical, "HicoForge"
    WScript.Quit 1
End If

cmd = """" & pyExe & """ """ & mainPy & """"
' 0 = hidden console; we still need to set the working dir so relative paths work.
sh.CurrentDirectory = installRoot
sh.Run cmd, 0, False
