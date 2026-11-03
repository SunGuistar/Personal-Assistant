' Personal Hub silent launcher (invoked by start_hub.bat)
' Runs launch.py through the Conda agent env; falls back to pythonw on PATH.
' NOTE: keep this file pure ASCII - the VBScript engine reads it in the
' system ANSI codepage (GBK on zh-CN Windows) and UTF-8 Chinese bytes break
' parsing with misleading runtime errors (same rule as .bat/.ini).
Option Explicit
Dim shell, fso, launcher, rootDir, condaBat, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
rootDir = fso.GetAbsolutePathName(fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), ".."))
launcher = fso.GetAbsolutePathName(fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "launch.py"))

' Conda discovery: PH_CONDA_BAT env var > common per-user installs > D: drives
condaBat = ""
Dim candidates(3), phConda
phConda = shell.ExpandEnvironmentStrings("%PH_CONDA_BAT%")
If phConda <> "%PH_CONDA_BAT%" And phConda <> "" Then
    candidates(0) = phConda
Else
    candidates(0) = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\miniconda3\condabin\conda.bat"
End If
candidates(1) = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\anaconda3\condabin\conda.bat"
candidates(2) = "D:\miniconda\condabin\conda.bat"
candidates(3) = "D:\anaconda3\condabin\conda.bat"

Dim i
For i = 0 To UBound(candidates)
    If fso.FileExists(candidates(i)) Then
        condaBat = candidates(i)
        Exit For
    End If
Next

If condaBat <> "" Then
    ' cmd /c needs the whole command wrapped when the first token is quoted
    cmd = "cmd /c """ & """" & condaBat & """ run -n agent --no-capture-output python """ & launcher & """"""
Else
    cmd = "pythonw.exe """ & launcher & """"
End If
shell.CurrentDirectory = rootDir
shell.Run cmd, 0, False
