@echo off
cd /d "%~dp0"
if exist "C:\Program Files\Python312\pythonw.exe" (
  start "" "C:\Program Files\Python312\pythonw.exe" "%~dp0app.py"
  exit /b
)
echo Python 3.12 was not found in C:\Program Files\Python312.
echo Please run app.py with an installed Python 3.12+ containing Tkinter.
pause
