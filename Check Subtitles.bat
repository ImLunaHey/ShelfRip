@echo off
title Shelfrip subtitle check
cd /d "%~dp0"
rem Reads only: checks rips against their subtitles. See subcheck.py for options.
rem   Check Subtitles.bat                 every rip folder not filed yet
rem   Check Subtitles.bat --filed Middle  filed discs whose folder name contains Middle
where python >nul 2>nul
if %errorlevel%==0 (python subcheck.py %*) else (py subcheck.py %*)
pause
