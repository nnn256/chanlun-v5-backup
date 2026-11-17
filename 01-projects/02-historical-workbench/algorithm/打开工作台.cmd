@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0Start-Workbench.ps1" (
  echo Project files are missing beside this CMD.
  echo Keep this CMD inside the project folder. Use Create-DesktopShortcut.ps1 for a desktop shortcut.
  if not "%CHANLUN_NO_PAUSE%"=="1" pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Workbench.ps1" -OpenBrowser %*
if errorlevel 1 (
  if not "%CHANLUN_NO_PAUSE%"=="1" pause
  exit /b 1
)
exit /b 0
