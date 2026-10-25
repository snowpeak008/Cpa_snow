@echo off
chcp 65001 >nul
title Snow Console - Stop Tunnel
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0ssh\control.ps1" -Action Stop
if errorlevel 1 pause
