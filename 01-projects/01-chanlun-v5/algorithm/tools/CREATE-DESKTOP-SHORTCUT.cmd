@echo off
setlocal
if not exist "%~dp0project\Create-DesktopShortcut.ps1" (
  echo Extract the complete ZIP before creating a shortcut.
  if not "%CHANLUN_NO_PAUSE%"=="1" pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0project\Create-DesktopShortcut.ps1"
if errorlevel 1 (
  if not "%CHANLUN_NO_PAUSE%"=="1" pause
  exit /b 1
)
if not "%CHANLUN_NO_PAUSE%"=="1" pause
exit /b 0
