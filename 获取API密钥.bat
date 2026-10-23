@echo off
chcp 936 >nul
setlocal

rem ============================================================
rem  一键获取 API Key（给局域网 API / 手机 App 用）
rem
rem  做了什么：
rem    1. 检查 llama.cpp（11450）和网关（11435），不在就按顺序起（2026-10-22 明确为完整入口）；
rem    2. 把口令复制到**剪贴板**（直接粘到手机的 App 里就行）；
rem    3. 打开自带网页 -- 上面也能看 Key、还能当场测一次对话。
rem
rem  注意：口令存在 _备份\ollama网关口令.txt，不入仓库；
rem        想换一个新口令：python ollama_gateway.py --new-token
rem ============================================================

title 获取 API Key

rem 2026-10-22（GPT 复核第 6 条）：本脚本是**完整启动入口** —— 先确保 llama.cpp（11450）
rem   在跑，再确保网关（11435）在跑；两个缺哪个补哪个。只想取 Key 的话，两个都已运行时会直达。
netstat -ano | findstr /r /c:"LISTENING" | findstr /c:":11450" >nul 2>&1
if not errorlevel 1 goto checkgw

echo.
echo   llama.cpp（11450）没在跑，先把它起来（约 10~30 秒）...
python "%~dp0workbench.py" --ensure-llama
if errorlevel 1 goto llamafail

:checkgw
netstat -ano | findstr /r /c:"LISTENING" | findstr /c:":11435" >nul 2>&1
if errorlevel 1 goto startgw

goto getkey

:startgw
echo.
echo   网关（11435）没在跑，正在帮你启动...
start "gateway" /min python "%~dp0ollama_gateway.py" --upstream llamacpp --llamacpp-port 11450 --llamacpp-alias lc-35b
echo   等它起来（约 6 秒）...
timeout /t 6 /nobreak >nul
netstat -ano | findstr /r /c:"LISTENING" | findstr /c:":11435" >nul 2>&1
if errorlevel 1 goto gatewayfail

:getkey
echo.
for /f "usebackq delims=" %%k in (`python "%~dp0ollama_gateway.py" --show-token`) do set "KEY=%%k"

if "%KEY%"=="" goto bad

echo(%KEY%| clip
echo   ============================================================
echo    API Key 已经复制到剪贴板啦，直接粘到手机的 App 里
echo   ============================================================
echo.
echo    API 地址             : http://^<本机局域网IP^>:11435/v1（ipconfig 查看）
echo    模型                : lc-35b
echo    联网查资料          : 消息以「搜」开头就会去搜，例如  搜 今天有什么新闻
echo.
for /f "usebackq delims=" %%a in (`python "%~dp0ollama_gateway.py" --show-access-code`) do set "ACODE=%%a"
echo    网页访问码          : %ACODE%   ^<- 手机第一次打开网页输它（输一次长期有效）
echo    口令文件            : %~dp0_备份\ollama网关口令.txt
echo    访问码文件          : %~dp0_备份\网关访问码.txt
echo    查看口令（不复制）  : python %~dp0ollama_gateway.py --show-token
echo    换一个新口令        : python %~dp0ollama_gateway.py --new-token
echo.
echo   正在打开网页（也能看 Key、还能当场测一次对话）...
start "" "http://127.0.0.1:11435/"
echo.
pause
exit /b 0

:llamafail
echo.
echo   [X] llama.cpp 没启动成功，请检查上方错误信息。
pause
exit /b 1

:gatewayfail
echo.
echo   [X] 网关启动失败，请检查最小化窗口中的错误信息。
pause
exit /b 1

:bad
echo.
echo   [X] 没取到口令。可能是：
echo       * 网关卡住了或启动失败（看那个最小化的窗口有没有报错）
echo       * Python 不在 PATH 里（命令行跑 python --version 试一下）
echo.
pause
exit /b 1
