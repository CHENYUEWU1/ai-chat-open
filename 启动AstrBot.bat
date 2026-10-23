@echo off
chcp 936 >nul
title 助手 · AstrBot
setlocal

REM ============================================================
REM  ASTRBOT_ROOT 必须在这里设死，不能只靠用户级环境变量（见 02 坑）。
REM ============================================================
set "ASTRBOT_ROOT=%~dp0AstrBotData"

REM 2026-10-22：**不再启动 Ollama**（用户只留 llama.cpp，9B 已删）。
REM   AstrBot 原来用 Ollama 提供商；现在模型要从网关的 OpenAI 兼容口进：
REM     Base URL : http://127.0.0.1:11435/v1
REM     API Key  : 随便填（网关默认不强制 Key；要强制就 --require-key）
REM     模型名   : lc-35b
REM   这一项要在 AstrBot 的 WebUI「服务提供商」里改，本脚本只负责把服务起好。

set "ASTRBOT_CRON_TOOLS=0"
set "ASTRBOT_GENUI=0"
set "CURL=C:\Windows\System32\curl.exe"

cls
echo ==================================================
echo    助手  ·  AstrBot Desktop
echo    数据目录 : %ASTRBOT_ROOT%
echo    WebUI    : http://127.0.0.1:6185
echo ==================================================
echo.

echo [1/4] 启动 llama.cpp 35B（11450）...
python "%~dp0workbench.py" --ensure-llama
if errorlevel 1 (
    echo    [失败] llama.cpp 没启动，后续服务无法使用模型。
    pause
    exit /b 1
)

echo [2/4] 启动网关（11435，OpenAI 兼容口给 AstrBot 用）...
start "gateway" /min python "%~dp0ollama_gateway.py" --host 127.0.0.1 --port 11435 --upstream llamacpp --llamacpp-port 11450 --llamacpp-alias lc-35b
ping -n 4 127.0.0.1 >nul

echo [3/4] 启动 AstrBot ...
tasklist /FI "IMAGENAME eq AstrBot.exe" 2>nul | find /I "AstrBot.exe" >nul
if errorlevel 1 (
    start "" "%~dp0AstrBot\AstrBot_4.28.1_windows_amd64_portable\AstrBot.exe"
) else (
    echo       AstrBot 已在运行
)

echo [4/4] 等界面就绪并打开浏览器 ...
set /a n=0
:wait
ping -n 3 127.0.0.1 >nul
set /a n+=1
"%CURL%" -s -o nul --max-time 2 http://127.0.0.1:6185
if not errorlevel 1 goto ready
if %n% lss 25 goto wait
echo       [警告] 等超时了，手动开 http://127.0.0.1:6185
goto done
:ready
explorer "http://127.0.0.1:6185"
:done

echo.
echo ==================================================
echo   如果 AstrBot 报"模型不存在"：
echo     进 WebUI「服务提供商」，改成 OpenAI 兼容：
echo       Base URL = http://127.0.0.1:11435/v1 ，模型名 = lc-35b
echo   换人格：双击「切换人格.bat」
echo   玩游戏前：双击「停止模型.bat」释放显存和内存
echo ==================================================
echo.
echo 本窗口 5 秒后自动关闭...
ping -n 6 127.0.0.1 >nul
endlocal