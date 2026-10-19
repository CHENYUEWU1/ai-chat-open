@echo off
chcp 936 >nul
title 修复 Ollama
setlocal

cd /d "E:\本地ai"

echo ==================================================
echo   修复 Ollama（结束卡住的进程 + 重新拉起）
echo ==================================================
echo.
echo   这个脚本**不会**关掉 AstrBot。
echo.

python "E:\本地ai\fix_ollama.py"

echo.
echo 退出码：%ERRORLEVEL%
echo.
pause
endlocal
