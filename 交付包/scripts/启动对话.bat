@echo off
chcp 936 >nul
title 本地 AI 助手 - 小九（无审查版）
setlocal

set "OLLAMA_MODELS=E:\本地ai\models"
set "OLLAMA_FLASH_ATTENTION=1"
set "OLLAMA_KV_CACHE_TYPE=q8_0"
set "OLLAMA_HOST=127.0.0.1:11434"

REM ============================================================
REM  2026-09-29 加：模型菜单（原来模型名写死在最后一行，没法切）
REM  这份 .bat 必须存成 GBK + CRLF（见 02 坑 5）；
REM  分支一律用 goto，别把 goto 写进括号块内部（见 02 坑 16）。
REM ============================================================
echo ============================================
echo    本地 AI 助手 - 小九
echo ============================================
echo.
echo   选模型：
echo.
echo     1) 9B    Qwen3.5-9B-Uncensored   快，全在显存，第一条约 1 秒
echo     2) 35B   Qwen3.6-35B-A3B         更聪明，第一条要等 30-60 秒
echo     3) 退出
echo.
set "pick="
set /p "pick=输入编号（1/2/3），直接回车=1 : "
if "%pick%"=="2" goto use35b
if "%pick%"=="3" goto quit
goto use9b

:use9b
set "MODEL=xiaojiu9b"
set "MTEXT=Qwen3.5-9B-Uncensored"
goto start_ollama

:use35b
set "MODEL=qwen36-35b-uncensored"
set "MTEXT=Qwen3.6-35B-A3B (MoE)"
goto start_ollama

:quit
echo.
echo 已退出。
goto end

:start_ollama
echo.
REM 若服务未运行则启动
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if not errorlevel 1 goto ready
echo [启动] Ollama 服务...
start "" /B "E:\本地ai\ollama\ollama.exe" serve
ping -n 7 127.0.0.1 >nul

:ready
echo ============================================
echo    本地 AI 助手 - 小九
echo    模型: %MTEXT%
echo ============================================
echo.
echo [就绪] 直接打字聊天，输入 /bye 退出
if "%MODEL%"=="xiaojiu9b" echo [提示] 已关闭思考模式，响应约 1 秒
if not "%MODEL%"=="xiaojiu9b" echo [提示] 35B 第一条要读提示，等 30-60 秒是正常的
echo.
"E:\本地ai\ollama\ollama.exe" run %MODEL% --think=false

:end
endlocal
