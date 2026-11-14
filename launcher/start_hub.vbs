' Personal Assistant silent launcher (invoked by the .bat wrapper)
' Runs launch.py through the Conda agent env; falls back to pythonw on PATH.
' NOTE: keep this file pure ASCII - the VBScript engine reads it in the
' system ANSI codepage (GBK on zh-CN Windows) and UTF-8 Chinese bytes break
' parsing with misleading runtime errors (same rule as .bat/.ini).
Option Explicit
Dim shell, fso, launcher, rootDir, condaBat, cmd, action, exitCode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Dim bootAt
bootAt = Now
shell.Environment("PROCESS")("PH_LAUNCH_BOOTSTRAP_AT") = Year(bootAt) & "-" & Right("0" & Month(bootAt), 2) & "-" & Right("0" & Day(bootAt), 2) & "T" & Right("0" & Hour(bootAt), 2) & ":" & Right("0" & Minute(bootAt), 2) & ":" & Right("0" & Second(bootAt), 2)
rootDir = fso.GetAbsolutePathName(fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), ".."))
launcher = fso.GetAbsolutePathName(fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "launch.py"))
action = "start"
If WScript.Arguments.Unnamed.Count > 0 Then action = WScript.Arguments.Unnamed(0)
If action <> "start" And action <> "stop" And action <> "restart" Then
    MsgBox "Invalid launcher action.", 16, "Personal Assistant"
    WScript.Quit 1
End If

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
    cmd = "cmd /c """ & """" & condaBat & """ run -n agent --no-capture-output python """ & launcher & """ --action " & action & """"
Else
    cmd = "pythonw.exe """ & launcher & """ --action " & action
End If
shell.CurrentDirectory = rootDir
If WScript.Arguments.Named.Exists("check") Then
    WScript.Echo cmd
    WScript.Quit 0
End If
exitCode = shell.Run(cmd, 0, True)
If exitCode <> 0 Then
    MsgBox "Action failed. See launcher\logs\launcher.log for details.", 16, "Personal Assistant"
End If
