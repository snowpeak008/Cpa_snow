@echo off
chcp 65001 >nul
title Snow Console - Start Tunnel
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0ssh\control.ps1" -Action Start
if errorlevel 1 pause
