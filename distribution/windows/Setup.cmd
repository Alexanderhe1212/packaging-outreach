@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
py -3 -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or newer required'"
if errorlevel 1 goto fail
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
if errorlevel 1 goto fail
echo Setup finished. Double-click Start.cmd.
pause
exit /b 0
:fail
echo Setup failed. Install Python 3.11 or newer with the Python Launcher, then retry. No mail was sent.
pause
exit /b 1
