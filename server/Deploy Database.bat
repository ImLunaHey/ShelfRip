@echo off
title Deploy the Shelfrip disc database
cd /d "%~dp0"
where node >nul 2>nul || (echo Node.js is not installed. Get the LTS version from https://nodejs.org/ ^(or: winget install OpenJS.NodeJS.LTS^), then run this again. & pause & exit /b 1)
node deploy.mjs
pause
