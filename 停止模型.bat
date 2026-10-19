@echo off
chcp 936 >nul
title 停止 助手
setlocal

echo ==================================================
echo   停止 助手 · 本地 AI 助手
echo ==================================================
echo.

echo [1/3] 停止 Ollama 推理服务（释放显存）...
taskkill /F /IM ollama.exe >nul 2>&1
if errorlevel 1 (echo       没有正在运行的服务) else (echo       已停止)

echo [2/3] 清理 llama-server 子进程（释放内存）...
REM ★ 关键：ollama.exe 被杀掉后，它拉起的 llama-server.exe 不会跟着死，
REM   会继续占着好几 GB 内存。实测见过两个孤儿占 7.5 GB，
REM   把 15.7 GB 的系统内存吃到只剩 2 GB，然后所有东西都开始卡。
taskkill /F /T /IM llama-server.exe >nul 2>&1
if errorlevel 1 (echo       没有残留) else (echo       已清理)

echo [3/3] 关闭 AstrBot（释放内存）...
REM /T 连子进程一起结束 —— 后端 python 是它的子进程
taskkill /F /T /IM AstrBot.exe >nul 2>&1
if errorlevel 1 (echo       没在运行) else (echo       已关闭)

echo.
echo 全部已停止。
echo.
echo 残留检查（下面应该什么都不显示）：
tasklist /FI "IMAGENAME eq llama-server.exe" 2>nul | find /I "llama-server.exe"
tasklist /FI "IMAGENAME eq AstrBot.exe" 2>nul | find /I "AstrBot.exe"
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe"
echo.
echo 想继续聊：双击「启动AstrBot.bat」
echo   浏览器打开 http://127.0.0.1:6185
echo.
ping -n 6 127.0.0.1 >nul
endlocal
