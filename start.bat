@echo off
setlocal
cd /d "%~dp0"
set "PQM_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PQM_PYTHON%" goto run
set "PQM_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "%PQM_PYTHON%" "%PQM_PYTHON%" -c "import docx" >nul 2>nul && goto run
where py >nul 2>nul && set "PQM_PYTHON=py" && goto run
where python >nul 2>nul && set "PQM_PYTHON=python" && goto run
echo Python 3.12 is required to run PQM.
echo Install it from https://www.python.org/downloads/windows/
pause
exit /b 1
:run
"%PQM_PYTHON%" -c "import docx" >nul 2>nul
if errorlevel 1 (
  echo Installing the required python-docx package...
  "%PQM_PYTHON%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Failed to install dependencies. Check the Internet connection and try again.
    pause
    exit /b 1
  )
)
"%PQM_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/',timeout=2)" >nul 2>nul
if not errorlevel 1 (
  start "" "http://127.0.0.1:8080/"
  exit /b 0
)
"%PQM_PYTHON%" server.py
if errorlevel 1 (
  echo.
  echo PQM failed to start. Error code: %errorlevel%
  pause
)
