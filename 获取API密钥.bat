@echo off
setlocal
cd /d "%~dp0"
if not defined LOCAL_AI_DATA_DIR set "LOCAL_AI_DATA_DIR=%LOCALAPPDATA%\LocalAI-Assistant"

where python >nul 2>&1
if errorlevel 1 (
    echo Python 3 is not installed or is not on PATH.
    pause
    exit /b 1
)

echo Browser authorization code:
python "%~dp0ollama_gateway.py" --show-access-code
echo.
echo API token (required by LAN API clients by default):
python "%~dp0ollama_gateway.py" --show-token
echo.
echo Local browser: http://127.0.0.1:11435/
echo The API token is private. Do not paste it into public chats or issues.
pause
