@echo off
chcp 65001 >nul
title Snow Console - SSH Login
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0ssh\control.ps1" -Action Login
if errorlevel 1 pause
