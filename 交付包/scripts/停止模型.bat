@echo off
chcp 936 >nul
title 停止 助手
setlocal

echo ==================================================
echo   停止 助手 · 本地 AI 助手
echo ==================================================
echo.

echo [1/4] 停止 Ollama（2026-10-22 起默认不启动；有残留就顺手清掉）...
taskkill /F /IM ollama.exe >nul 2>&1
if errorlevel 1 (echo       没有正在运行的服务) else (echo       已停止)

echo [2/4] 停止 llama.cpp（llama-server.exe，释放 9 GB 内存 + 7 GB 显存）...
REM ★ 关键：ollama.exe 被杀掉后，它拉起的 llama-server.exe 不会跟着死，
REM   会继续占着好几 GB 内存。实测见过两个孤儿占 7.5 GB，
REM   把 15.7 GB 的系统内存吃到只剩 2 GB，然后所有东西都开始卡。
taskkill /F /T /IM llama-server.exe >nul 2>&1
if errorlevel 1 (echo       没有残留) else (echo       已清理)

echo [3/4] 关闭 AstrBot（释放内存）...
REM /T 连子进程一起结束 —— 后端 python 是它的子进程
taskkill /F /T /IM AstrBot.exe >nul 2>&1
if errorlevel 1 (echo       没在运行) else (echo       已关闭)

echo.
echo [4/4] 停止网关(11435) 与 网页聊天台(11437)...
REM 2026-10-20 加：这两个是 python.exe，按名字杀会误伤别的 Python ? 按端口找 PID 再杀。
REM 实测过：旧脚本跑完 ollama 停了，但 11435/11437 还活着空转（网页能开、一发消息就报错）。
set "HAD="
netstat -ano | findstr ":11435 " | findstr LISTENING >nul && set "HAD=1"
netstat -ano | findstr ":11437 " | findstr LISTENING >nul && set "HAD=1"
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 11435,11437 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }" >nul 2>&1
REM 用 ping 代替 timeout：timeout 在输入被重定向时会直接报错（实测）
ping -n 2 127.0.0.1 >nul
if defined HAD (echo       已停止) else (echo       没在运行)
echo 全部已停止。
echo.
echo 残留检查（下面应该什么都不显示）：
tasklist /FI "IMAGENAME eq llama-server.exe" 2>nul | find /I "llama-server.exe"
tasklist /FI "IMAGENAME eq AstrBot.exe" 2>nul | find /I "AstrBot.exe"
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe"
netstat -ano | findstr ":11435 " | findstr LISTENING
netstat -ano | findstr ":11437 " | findstr LISTENING
echo.
echo 想继续聊：双击「启动局域网API.bat」（网页聊天台），或「启动AstrBot.bat」
echo   浏览器打开 http://127.0.0.1:6185
echo.
ping -n 6 127.0.0.1 >nul
endlocal
