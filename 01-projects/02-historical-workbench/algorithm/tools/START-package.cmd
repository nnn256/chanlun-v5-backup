@echo off
setlocal
if not exist "%~dp0project\Start-Workbench.ps1" (
  echo Project files are missing. Extract the entire ZIP to one folder.
  echo Do not copy START.cmd to the desktop by itself.
  echo Use CREATE-DESKTOP-SHORTCUT.cmd from the extracted folder.
  if not "%CHANLUN_NO_PAUSE%"=="1" pause
  exit /b 1
)
cd /d "%~dp0project"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0project\Start-Workbench.ps1" -OpenBrowser %*
if errorlevel 1 (
  if not "%CHANLUN_NO_PAUSE%"=="1" pause
  exit /b 1
)
exit /b 0
