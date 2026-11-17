@echo off
setlocal
cd /d "%~dp0"
"artifacts\exe-build-20261108\build-env\Scripts\python.exe" tools\hardware_acceleration.py --benchmark --output-dir "artifacts\hardware-check-%RANDOM%-%RANDOM%"
pause
