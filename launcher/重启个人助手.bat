@echo off
REM Restart the service configured by launcher.ini.
start "" /min "wscript.exe" "%~dp0start_hub.vbs" restart
