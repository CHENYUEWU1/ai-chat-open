@echo off
chcp 936 >nul
setlocal

rem ============================================================
rem  把本地模型以**带口令**的方式开放给局域网（给"自己别的设备"用）
rem
rem  做了什么：
rem    1. 起 llama.cpp（BeeLlama，端口 11450），只绑 127.0.0.1 —— 外网/局域网**碰不到**模型本体；
rem    2. 另起 ollama_gateway.py 监听 0.0.0.0:11435，校验口令后只转发聊天类接口；
rem    3. /api/pull、/api/delete 默认一律 403（删不了、下不了你的模型）。
rem
rem  别的设备上填：
rem     Base URL : http://<这台电脑的IP>:11435
rem     口令     : 在本窗口跑一次  python ollama_gateway.py --show-token
rem     当前 IP 用 ipconfig 查看；DHCP 地址可能变化，想稳定可在路由器里做 DHCP 保留。
rem
rem  停止：关掉这个窗口（或按 Ctrl+C）
rem ============================================================

rem ↓ 这一行是**安全关键**：模型服务只绑本机，局域网设备只能经过网关访问

echo.
rem  2026-10-22：**不再启动 Ollama**（用户已弃用，9B 也删了）。
rem  现在只跑 llama.cpp（BeeLlama CUDA 13.3，端口 11450），参数只在 workbench.py 里有一份。
echo   [1/3] 启动 llama.cpp 35B（11450，加载约 10~30 秒）...
rem 2026-10-22：**同步调用**（不是 start）。原因：用 start 起一个新窗口时，本脚本被
rem   `cmd /c > log` 之类方式调用，新窗口拿不到有效控制台 ? 那一步静默失败（实测 11450 一直不起）。
rem   同步调用的好处：它自己会等到 /health 就绪再返回（10~30 秒），日志直接打在这个窗口里。
python "%~dp0workbench.py" --ensure-llama
if errorlevel 1 (
    echo    [失败] llama.cpp 没启动，后续服务无法使用模型。
    pause
    exit /b 1
)

echo   [2/3] 启动局域网网关（0.0.0.0:11435，要口令）...
echo.
echo   ================================================================
echo    别的设备上填： http://^<这台电脑的IP^>:11435
echo    看口令：       在本窗口 Ctrl+C 停掉后跑
echo                   python %~dp0ollama_gateway.py --show-token
echo    防火墙若没放行过，先（管理员）跑一次：
echo      New-NetFirewallRule -DisplayName "Ollama 网关(局域网)" -Direction Inbound ^
echo        -Action Allow -Protocol TCP -LocalPort 11435 -RemoteAddress LocalSubnet
echo   ================================================================
echo.


rem ---- 网页聊天台（2026-10-20 加）：独立进程 11437。已在跑时 workbench.py 会自己安静退出 ----
echo   [3/3] 启动网页聊天台（11437，独立于网关）...
start "webchat" /min python "%~dp0workbench.py"

python "%~dp0ollama_gateway.py" --host 0.0.0.0 --port 11435 --upstream llamacpp --llamacpp-port 11450 --llamacpp-alias lc-35b

echo.
echo   网关已退出。llama.cpp 进程若还在（任务管理器里的 llama-server.exe），双击 停止模型.bat 一起收掉。
pause
