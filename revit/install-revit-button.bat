@echo off
REM Installs the "Send to BIM 5D" button into Revit (needs pyRevit, free: https://pyrevitlabs.io).
setlocal
set "SRC=%~dp0BIM5D.extension"
set "DST=%APPDATA%\pyRevit\Extensions\BIM5D.extension"
if not exist "%SRC%" (
  echo  Unzip the whole BIM 5D folder first, then run this file from its revit folder.
  pause
  exit /b 1
)
if not exist "%APPDATA%\pyRevit\Extensions" mkdir "%APPDATA%\pyRevit\Extensions"
xcopy "%SRC%" "%DST%\" /E /I /Y >nul
if errorlevel 1 (
  echo  Copying the button failed.
  pause
  exit /b 1
)
echo.
echo  Done. The button is installed in: %DST%
echo.
echo  If pyRevit is not installed yet, install it first (free): https://pyrevitlabs.io
echo  Then open Revit: a "BIM5D" tab appears with the "Send to BIM 5D" button.
echo  If Revit was already open, click pyRevit ^> Reload.
echo.
pause
