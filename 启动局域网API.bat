@echo off
chcp 936 >nul
setlocal

rem ============================================================
rem  把本机 Ollama 以**带口令**的方式开放给局域网（给"自己别的设备"用）
rem
rem  做了什么：
rem    1. 用项目里的参数起 ollama serve，但 **OLLAMA_HOST 仍是 127.0.0.1**
rem       —— 外网/局域网**碰不到** Ollama 本体；
rem    2. 另起 ollama_gateway.py 监听 0.0.0.0:11435，校验口令后只转发聊天类接口；
rem    3. /api/pull、/api/delete 默认一律 403（删不了、下不了你的模型）。
rem
rem  别的设备上填：
rem     Base URL : http://<这台电脑的IP>:11435
rem     口令     : 在本窗口跑一次  python ollama_gateway.py --show-token
rem     现在这台电脑的地址：WLAN <你的电脑IP> / 以太网 <你的电脑IP>
rem     注意: IP 会变（DHCP），想长期稳定就在路由器里做 DHCP 保留。
rem
rem  停止：关掉这个窗口（或按 Ctrl+C）
rem ============================================================

set "OLLAMA_MODELS=C:\LocalAI-Assistant\models"
set "OLLAMA_FLASH_ATTENTION=1"
set "OLLAMA_KV_CACHE_TYPE=q8_0"
set "OLLAMA_MAX_LOADED_MODELS=1"
rem ↓ 保温：模型加载后**空闲 30 分钟**才卸载（默认只有 5 分钟）。
set "OLLAMA_KEEP_ALIVE=30m"
rem ↓ 这一行是**安全关键**：只绑本机，局域网里没人能直接访问 Ollama
set "OLLAMA_HOST=127.0.0.1:11434"

echo.
echo   [1/2] 启动 Ollama（只听 127.0.0.1:11434，外面碰不到）...
start "ollama" /min "C:\LocalAI-Assistant\ollama\ollama.exe" serve
timeout /t 6 /nobreak >nul

rem ↓ 开机预热（2026-10-08 加，方案 C）：先把模型读进来并保温，聊天时就不用等冷启动。
rem   默认预热 35B（约 30 秒就绪）；想换热身的模型，改 warmup.py 顶部的 WARM_MODEL。
start "warmup" /min python "C:\LocalAI-Assistant\warmup.py"

echo   [2/2] 启动局域网网关（0.0.0.0:11435，要口令）...
echo.
echo   ================================================================
echo    别的设备上填： http://^<这台电脑的IP^>:11435
echo    看口令：       在本窗口 Ctrl+C 停掉后跑
echo                   python C:\LocalAI-Assistant\ollama_gateway.py --show-token
echo    防火墙若没放行过，先（管理员）跑一次：
echo      New-NetFirewallRule -DisplayName "Ollama 网关(局域网)" -Direction Inbound ^
echo        -Action Allow -Protocol TCP -LocalPort 11435 -RemoteAddress LocalSubnet
echo   ================================================================
echo.

python "C:\LocalAI-Assistant\ollama_gateway.py" --host 0.0.0.0 --port 11435

echo.
echo   网关已退出。Ollama 可能还在后台跑（要停就关掉那个最小化的 ollama 窗口）。
pause
