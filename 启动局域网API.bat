@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python 3 is not installed or is not on PATH.
    echo Install Python 3.12 or newer, then reopen this window.
    pause
    exit /b 1
)

where ollama >nul 2>&1
if errorlevel 1 (
    echo Ollama is not installed or is not on PATH.
    echo Install Ollama and download a model first.
    pause
    exit /b 1
)

if not defined LOCAL_AI_DATA_DIR set "LOCAL_AI_DATA_DIR=%LOCALAPPDATA%\LocalAI-Assistant"
ollama list >nul 2>&1
if errorlevel 1 (
    echo Ollama is not running. Start Ollama from the Start menu, then try again.
    pause
    exit /b 1
)

echo Starting the LAN gateway on port 11435.
echo Keep this window open while using the gateway.
echo Only use it on a trusted private network; do not expose this port to the internet.
echo.
python "%~dp0ollama_gateway.py" --host 0.0.0.0 --port 11435 %*
pause
