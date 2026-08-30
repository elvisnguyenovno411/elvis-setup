@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Chua cai dat du an. Dang mo setup.bat...
  call setup.bat
  if errorlevel 1 exit /b 1
)

if not exist ".env" (
  echo [LOI] Thieu file .env. Hay chay setup.bat.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo.
  echo Bot da dung do gap loi. Xem logs\elvis-setup.log de biet chi tiet.
  pause
)

