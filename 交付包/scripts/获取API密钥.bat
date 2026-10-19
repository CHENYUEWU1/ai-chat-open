@echo off
chcp 936 >nul
setlocal

rem ============================================================
rem  一键获取 API Key（给局域网 API / 手机 App 用）
rem
rem  做了什么：
rem    1. 检查网关（11435）在不在跑，不在就顺手帮你起一个；
rem    2. 把口令复制到**剪贴板**（直接粘到手机的 App 里就行）；
rem    3. 打开自带网页 -- 上面也能看 Key、还能当场测一次对话。
rem
rem  注意：口令存在 _备份\ollama网关口令.txt，不入仓库；
rem        想换一个新口令：python ollama_gateway.py --new-token
rem ============================================================

title 获取 API Key

netstat -ano | findstr /r /c:"LISTENING" | findstr /c:":11435" >nul 2>&1
if errorlevel 1 goto startgw

goto getkey

:startgw
echo.
echo   网关（11435）没在跑，正在帮你启动...
start "ollama gateway" /min python "C:\LocalAI-Assistant\ollama_gateway.py"
echo   等它起来（约 6 秒）...
timeout /t 6 /nobreak >nul

:getkey
echo.
for /f "usebackq delims=" %%k in (`python "C:\LocalAI-Assistant\ollama_gateway.py" --show-token`) do set "KEY=%%k"

if "%KEY%"=="" goto bad

echo(%KEY%| clip
echo   ============================================================
echo    API Key 已经复制到剪贴板啦，直接粘到手机的 App 里
echo   ============================================================
echo.
echo    地址（手机 App 里填）: http://<你的电脑IP>:11435/v1
echo    模型                : local-assistant-9b:latest  或  local-assistant-35b:latest
echo    联网查资料          : 消息以「搜」开头就会去搜，例如  搜 今天有什么新闻
echo.
for /f "usebackq delims=" %%a in (`python "C:\LocalAI-Assistant\ollama_gateway.py" --show-access-code`) do set "ACODE=%%a"
echo    网页访问码          : %ACODE%   ^<- 手机第一次打开网页输它（输一次长期有效）
echo    口令文件            : C:\LocalAI-Assistant\_备份\ollama网关口令.txt
echo    访问码文件          : C:\LocalAI-Assistant\_备份\网关访问码.txt
echo    查看口令（不复制）  : python C:\LocalAI-Assistant\ollama_gateway.py --show-token
echo    换一个新口令        : python C:\LocalAI-Assistant\ollama_gateway.py --new-token
echo.
echo   正在打开网页（也能看 Key、还能当场测一次对话）...
start "" "http://127.0.0.1:11435/"
echo.
pause
exit /b 0

:bad
echo.
echo   [X] 没取到口令。可能是：
echo       * 网关卡住了或启动失败（看那个最小化的窗口有没有报错）
echo       * Python 不在 PATH 里（命令行跑 python --version 试一下）
echo.
pause
exit /b 1
