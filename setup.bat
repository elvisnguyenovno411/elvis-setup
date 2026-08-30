@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [LOI] Khong tim thay Python Launcher. Hay cai Python 3.11 tro len.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Dang tao moi truong ao...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

echo Dang cai dat thu vien...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :error

set "BOT_TOKEN="
set "OWNER_ID="
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if "%%A"=="DISCORD_TOKEN" set "BOT_TOKEN=%%B"
    if "%%A"=="OWNER_USER_ID" set "OWNER_ID=%%B"
  )
)

if not defined BOT_TOKEN (
  echo.
  echo Cau hinh lan dau. Thong tin nay chi luu tren may cua ban.
  set /p "BOT_TOKEN=Discord bot token: "
)
if not defined OWNER_ID set /p "OWNER_ID=Discord user ID cua Elvis: "

>.env echo DISCORD_TOKEN=%BOT_TOKEN%
>>.env echo OWNER_USER_ID=%OWNER_ID%
>>.env echo LOG_LEVEL=INFO

echo.
echo Cai dat hoan tat. Chay start.bat de mo bot.
pause
exit /b 0

:error
echo.
echo [LOI] Cai dat that bai. Kiem tra Python va ket noi mang.
pause
exit /b 1
