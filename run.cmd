@echo off
setlocal
cd /d "%~dp0"
set "RECREATE_VENV=0"
if not exist ".venv\Scripts\python.exe" set "RECREATE_VENV=1"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 set "RECREATE_VENV=1"
)
if "%RECREATE_VENV%"=="1" (
  echo Creating or repairing the Python 3.11 virtual environment...
  py -3.11 -m venv --clear .venv
  if errorlevel 1 "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -m venv --clear .venv
  if errorlevel 1 python -m venv --clear .venv
  if errorlevel 1 exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if not exist ".env" copy ".env.example" ".env" >nul
echo.
echo Starting APAAR Student Verification demo...
echo Open http://127.0.0.1:5000
echo Configure SECRET_KEY and DEMO_ADMIN_PASSWORD in .env before first startup.
echo Use a unique password of at least 16 characters.
python app.py
pause
