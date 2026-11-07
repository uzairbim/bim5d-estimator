@echo off
REM BIM 5D Estimator - double-click to start.
REM Needs Python 3.10 - 3.14 (64-bit) from python.org; tick "Add python.exe to PATH" when installing.
setlocal
cd /d "%~dp0"
title BIM 5D Estimator

if not exist "%~dp0requirements.txt" (
  echo.
  echo  Please unzip the folder first: right-click the .zip file, choose "Extract All",
  echo  then open the extracted folder and double-click start-windows.bat there.
  echo.
  pause
  exit /b 1
)

REM Find a real Python (the Microsoft Store shortcut "python" does not count).
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo  Python was not found.
  echo  1. Install Python 3.12 or newer from https://www.python.org/downloads/
  echo  2. On the first screen tick "Add python.exe to PATH", then Install Now.
  echo  3. Double-click this file again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\installed.ok" (
  echo.
  echo  First start: installing the parts it needs. This takes 2-5 minutes and needs internet.
  echo.
  if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
  if errorlevel 1 goto :fail
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :fail
  echo ok> ".venv\installed.ok"
)

".venv\Scripts\python.exe" run.py
pause
exit /b 0

:fail
echo.
echo  Installation did not finish. Check the internet connection and run this file again.
echo  If it keeps failing, delete the .venv folder and try again.
echo  Use 64-bit Python 3.10 - 3.14 from python.org (the 32-bit version cannot read IFC files).
echo.
pause
exit /b 1
