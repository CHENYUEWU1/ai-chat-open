@echo off
chcp 936 >nul
title 助手 · AstrBot
setlocal

REM ============================================================
REM  ASTRBOT_ROOT 必须在这里设死，不能只靠用户级环境变量。
REM  用户级变量写进注册表后，只有"之后新启动"的进程读得到；
REM  父进程环境块是旧的话，子进程继承的还是旧值，
REM  AstrBot 就会悄悄把数据写到 C:\Users\<你>\.astrbot
REM ============================================================
set "ASTRBOT_ROOT=C:\LocalAI-Assistant\AstrBotData"

REM Ollama（模型也在 E 盘）
set "OLLAMA_MODELS=C:\LocalAI-Assistant\models"
set "OLLAMA_FLASH_ATTENTION=1"
set "OLLAMA_KV_CACHE_TYPE=q8_0"
set "OLLAMA_HOST=127.0.0.1:11434"
REM 注意：同时只允许加载一个模型 —— 在 WebUI 里切换模型时，
REM    Ollama 会自动把上一个模型卸载掉，不会两个一起占显存/内存。
set "OLLAMA_MAX_LOADED_MODELS=1"
rem ↓ 保温：模型加载后**空闲 30 分钟**才卸载（默认只有 5 分钟）。
set "OLLAMA_KEEP_ALIVE=30m"

REM 关掉 future_task（定时任务）工具：它的英文说明会让中文人设的模型念英文台词。
REM 由 patch_astrbot_cron.py 配套写入；改回 1 即可恢复（要重启）。
set "ASTRBOT_CRON_TOOLS=0"
REM 关掉 WebUI 的内联 HTML 卡片：英文 GenUI 提示会让模型吐 HTML 而不写台词。
REM 由 patch_astrbot_genui.py 写入；改回 1 即可恢复（要重启）。
set "ASTRBOT_GENUI=0"
set "CURL=C:\Windows\System32\curl.exe"

cls
echo ==================================================
echo    助手  ·  AstrBot Desktop
echo    数据目录 : %ASTRBOT_ROOT%
echo    WebUI    : http://127.0.0.1:6185
echo ==================================================
echo.

REM ---------- 1. Ollama ----------
REM 注意：这里刻意不用 goto 跳进括号块 —— cmd 里那样写会出诡异问题
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if errorlevel 1 (
    echo [1/3] 启动 Ollama 推理服务 ...
    start "Ollama" /MIN "C:\LocalAI-Assistant\ollama\ollama.exe" serve
    ping -n 8 127.0.0.1 >nul
) else (
    echo [1/3] Ollama 已在运行
)

REM ↓ 开机预热（2026-10-08 加，方案 C）：先把模型读进来并保温，聊天时不用等冷启动。
REM   默认预热 35B（约 15~30 秒就绪）；想换热身的模型，改 warmup.py 顶部的 WARM_MODEL。
start "warmup" /min python "C:\LocalAI-Assistant\warmup.py"

REM ---------- 2. AstrBot ----------
tasklist /FI "IMAGENAME eq AstrBot.exe" 2>nul | find /I "AstrBot.exe" >nul
if errorlevel 1 (
    echo [2/3] 启动 AstrBot ...
    start "" "C:\LocalAI-Assistant\AstrBot\AstrBot_4.28.1_windows_amd64_portable\AstrBot.exe"
) else (
    echo [2/3] AstrBot 已在运行
)

REM ---------- 3. 等 WebUI 就绪再开浏览器 ----------
echo [3/3] 等界面就绪 ...
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
echo       就绪，正在打开浏览器
explorer "http://127.0.0.1:6185"
:done

echo.
echo ==================================================
echo   模型应为 local-assistant-9b:latest，人格是助手。
echo   换人格：双击「切换人格.bat」
echo   打游戏前：双击「停止模型.bat」释放 5.6 GB 显存
echo ==================================================
echo.
echo 本窗口 4 秒后自动关闭...
ping -n 5 127.0.0.1 >nul
endlocal
