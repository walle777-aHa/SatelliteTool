@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if not errorlevel 1 (
  python app.py --open
  goto :done
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 app.py --open
  goto :done
)

echo Python 3.9 or newer was not found.
echo Install Python from https://www.python.org/downloads/ and try again.

:done
if errorlevel 1 pause
endlocal
