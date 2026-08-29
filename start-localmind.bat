@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "API_DIR=%ROOT%services\api"
set "WEB_DIR=%ROOT%apps\web"
set "PYTHON=%API_DIR%\.venv\Scripts\python.exe"
set "MODEL=qwen2.5-coder:7b"

title LocalMind launcher
echo.
echo  Starting LocalMind...
echo.

where ollama >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Ollama is not installed or is not on PATH.
  echo Install it from https://ollama.com, then run this file again.
  pause
  exit /b 1
)

ollama list >nul 2>&1
if errorlevel 1 (
  echo [1/5] Starting Ollama...
  start "LocalMind - Ollama" /min cmd /c "ollama serve"
  timeout /t 3 /nobreak >nul
  ollama list >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Ollama did not start. Check the Ollama window and try again.
    pause
    exit /b 1
  )
) else (
  echo [1/5] Ollama is already running.
)

ollama show %MODEL% >nul 2>&1
if errorlevel 1 (
  echo [2/5] Downloading %MODEL%...
  ollama pull %MODEL%
  if errorlevel 1 (
    echo [ERROR] The Ollama model could not be downloaded.
    pause
    exit /b 1
  )
) else (
  echo [2/5] %MODEL% is ready.
)

if not exist "%PYTHON%" (
  echo [3/5] Creating the Python environment...
  where py >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Python is not installed or is not on PATH.
    pause
    exit /b 1
  )
  py -3 -m venv "%API_DIR%\.venv"
  if errorlevel 1 (
    echo [ERROR] Could not create the Python environment.
    pause
    exit /b 1
  )
  "%PYTHON%" -m pip install -r "%API_DIR%\requirements.txt"
  if errorlevel 1 (
    echo [ERROR] Could not install API dependencies.
    pause
    exit /b 1
  )
) else (
  echo [3/5] Python environment is ready.
)

echo [4/5] Preparing the sales dataset...
pushd "%API_DIR%"
"%PYTHON%" load_data.py
if errorlevel 1 (
  popd
  echo [ERROR] Could not prepare the sales dataset.
  pause
  exit /b 1
)
popd

netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if errorlevel 1 (
  start "LocalMind API" /D "%API_DIR%" "%PYTHON%" -m uvicorn app.main:app --reload
) else (
  echo      API is already listening on port 8000.
)

netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul
if errorlevel 1 (
  if not exist "%WEB_DIR%\node_modules" (
    echo [5/5] Installing web dependencies...
    pushd "%WEB_DIR%"
    call npm.cmd install
    if errorlevel 1 (
      popd
      echo [ERROR] Could not install web dependencies.
      pause
      exit /b 1
    )
    popd
  ) else (
    echo [5/5] Starting the web app...
  )
  start "LocalMind Web" /D "%WEB_DIR%" npm.cmd run dev
  timeout /t 5 /nobreak >nul
  start "" "http://localhost:3000"
) else (
  echo [5/5] Web app is already listening on port 3000.
  start "" "http://localhost:3000"
)

echo.
echo LocalMind is launching. Keep the API and Web windows open while using the app.
timeout /t 3 /nobreak >nul
exit /b 0
