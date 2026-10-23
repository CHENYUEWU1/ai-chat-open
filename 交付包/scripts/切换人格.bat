@echo off
chcp 936 >nul
title 切换人格 · 助手
setlocal

set "ASTRBOT_ROOT=%~dp0AstrBotData"
set "CURL=C:\Windows\System32\curl.exe"

echo ==================================================
echo   切换人格 · 助手
echo ==================================================
echo.

REM ---------- 找 Python ----------
set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
    if exist "D:\Python312\python.exe" (
        set "PY=D:\Python312\python.exe"
    ) else (
        echo [错误] 找不到 python，请先装 Python 3.10+
        pause
        exit /b 1
    )
)

REM ---------- 1. 关 AstrBot ----------
echo [1/3] 关闭 AstrBot ...
taskkill /F /T /IM AstrBot.exe >nul 2>&1
if errorlevel 1 (echo       没在运行) else (echo       已关闭)
ping -n 3 127.0.0.1 >nul

REM ---------- 2. 选人格 ----------
echo.
echo [2/3] 选择人格 ...
echo.
"%PY%" "%~dp0astrbot_setup.py" --pick
if errorlevel 1 (
    echo.
    echo 切换失败，AstrBot 不会重启。
    pause
    exit /b 1
)

REM ---------- 3. 重启 ----------
echo.
echo [3/3] 重启 AstrBot ...
start "" "%~dp0AstrBot\AstrBot_4.28.1_windows_amd64_portable\AstrBot.exe"
set /a n=0
:wait
ping -n 3 127.0.0.1 >nul
set /a n+=1
"%CURL%" -s -o nul --max-time 2 http://127.0.0.1:6185
if not errorlevel 1 goto ready
if %n% lss 25 goto wait
echo       等超时了，手动开 http://127.0.0.1:6185
goto done
:ready
echo       就绪，正在打开浏览器
explorer "http://127.0.0.1:6185"
:done

echo.
echo 完成。新人格已生效。
echo.
ping -n 5 127.0.0.1 >nul
endlocal
