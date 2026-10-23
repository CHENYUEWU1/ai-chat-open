@echo off
chcp 936 >nul
title 本地 AI 助手 - 网页聊天台
setlocal

REM ============================================================
REM  2026-10-22 重写：**不再用 Ollama**（用户只留 llama.cpp，9B 已删）。
REM  这个脚本原来是"终端里 ollama run 聊天"，现在改成：
REM     1) 起 llama.cpp 35B（11450，参数只在 workbench.py 里有一份）
REM     2) 起网页聊天台（11437）
REM     3) 打开浏览器
REM  文件必须 GBK + CRLF（见 02 坑 5）。
REM ============================================================

echo ============================================
echo    本地 AI 助手 - 网页聊天台
echo ============================================
echo.

echo [1/3] 启动 llama.cpp 35B（约 10~30 秒，会打印"模型加载中 Ns"）...
python "%~dp0workbench.py" --ensure-llama
if errorlevel 1 (
    echo    [失败] llama.cpp 没起来，看上面的提示；网页仍可打开，但发消息会报错。
)

echo [2/3] 启动网页聊天台（11437）...
start "webchat" /min python "%~dp0workbench.py"

echo [3/3] 等它就绪再打开浏览器 ...
set /a n=0
:wait
ping -n 2 127.0.0.1 >nul
set /a n+=1
if %n% gtr 20 goto openany
curl -s -o nul --max-time 2 http://127.0.0.1:11437/wc
if errorlevel 1 goto wait

:openany
explorer "http://127.0.0.1:11437/wc"

echo.
echo 已启动。关掉网页不会停服务；要全部停止请双击「停止模型.bat」。
echo 本窗口 5 秒后自动关闭...
ping -n 6 127.0.0.1 >nul
endlocal