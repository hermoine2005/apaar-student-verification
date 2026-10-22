@echo off
setlocal
cd /d "%~dp0"
set "ZIP=%~1"
if "%ZIP%"=="" set "ZIP=%CD%\apaar-student-verification-release.zip"
if not exist "%ZIP%" (
  echo ZIP not found: "%ZIP%"
  echo Usage: INTEGRATE_UPDATE.cmd "C:\path\to\apaar-student-verification-release.zip"
  pause
  exit /b 1
)
echo This extracts application files into the current project root.
echo Existing files with matching names may be overwritten.
echo .git and .venv are not included in the ZIP.
set /p CONFIRM=Continue after backing up or committing your current changes? [Y/N]:
if /I not "%CONFIRM%"=="Y" exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%CD%' -Force"
if errorlevel 1 (
  echo Extraction failed.
  pause
  exit /b 1
)
echo Extraction complete. Review changes with git status before committing.
git status
pause
