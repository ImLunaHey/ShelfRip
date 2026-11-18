@echo off
title Shelfrip
cd /d "%~dp0"
rem pythonw runs Shelfrip without a console window; its messages go to %APPDATA%\Shelfrip\shelfrip.log
where pythonw >nul 2>nul && (start "" pythonw app.py & exit /b 0)
start "Shelfrip" /min python app.py
