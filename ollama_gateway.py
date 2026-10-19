#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
把本机 Ollama 以**带口令**的方式开放给局域网 —— 只转发聊天，不转发"删模型/拉模型"。

为什么需要这一层（为什么不直接把 Ollama 开到局域网）：
    Ollama 的 API **没有任何认证**。只要把 `OLLAMA_HOST` 改成 `0.0.0.0:11434`，
    同一局域网里**任何设备**（包括蹭 WiFi 的）都能：
      · 调用模型（占用你的显存和内存）
      · `POST /api/pull` 下载新模型（吃满你的磁盘和带宽）
      · `DELETE /api/delete` **删掉你的模型**
      · `GET /api/tags` 看到你装了哪些模型
    所以这里做成：**Ollama 继续只绑 127.0.0.1**（外面碰不到），本脚本监听局域网，
    校验一个口令后**只转发白名单接口**；`/api/pull`、`/api/delete` 一律 403
    （想临时放行用 `--allow-pull`）。

用法：
    python ollama_gateway.py                 # 默认 0.0.0.0:11435 → 转发到 127.0.0.1:11434
    python ollama_gateway.py --port 11435
    python ollama_gateway.py --show-token     # 只看口令（给别的设备填）
    python ollama_gateway.py --allow-pull     # 临时允许拉模型（默认不允许）
    python ollama_gateway.py --new-token      # 重新生成口令（旧口令立刻失效）

排错（2026-10-05 加）：每次请求都会往 `_备份\gateway.log` 记一行"形状" ——
谁、用什么路径、User-Agent、结果几号，外加聊天请求的 model/stream/条数。
**不记口令内容、不记消息正文**（搜索词会记），所以这份日志可以直接贴出来问人。
"手机端连不上 / 输出一串代码"这类问题，就看这个文件里那条请求到底长什么样：
    Get-Content C:\LocalAI-Assistant\_备份\gateway.log -Tail 30
换路径用 `--log-file`，彻底不写用 `--no-log`。

客户端怎么填（自己设备上）：
    API 地址（Base URL）：http://<这台电脑的局域网IP>:11435
    认证：Bearer <口令>          ← 有的软件叫 "API Key"，填同一个口令即可
    ⚠️ 这台电脑的 IP 会变（DHCP）：现在 WLAN 是 <你的电脑IP>、以太网 <你的电脑IP>。
       想固定就在路由器里做 DHCP 保留，或在 Windows 里设静态 IP，否则哪天就连不上了。

安全边界（写清楚，别误以为很安全）：
    · 口令是**明文 HTTP** 传输的 —— 局域网内能抓包的人能看到。家里/自己的网可以接受；
      公共 WiFi、宿舍共享网**不要开**。
    · 口令存在 `_备份\ollama网关口令.txt`（`.gitignore` 已排除 `_备份\`，不会进仓库）。
    · 拿不到口令的人**只能**得到 401/403，调不到模型、也删不了模型。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as _wt
import datetime
import email.parser            # 解析 multipart 上传（2026-10-18）
import hashlib
import html as _html          # 渲染"看最近一条思考"时要转义（2026-10-09）
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gateway_page import PAGE, PAGE_VER, render_plain_page

# ── 本机请求**一律直连**（2026-10-08）──────────────────────────────────
# 为什么需要它：`urllib` 默认会读 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量。
# 如果启动网关的那个 shell 里带着代理（我这台开发机上就有），那么**转发给本机 Ollama**
# 的请求也会被塞进代理 —— 慢，甚至直接连不上模型。这里显式给一个"不走任何代理"的
# opener（empty ProxyHandler ⇒ 连环境变量都不看）。
#
# ⚠️ 只给**本机地址**用它；`--ollama` 指到**别的机器**时仍用系统默认（那种情况可能确实要代理）。
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def opener_for(url: str):
    r"""本机（127.0.0.1 / localhost）⇒ 一定直连；其它地址 ⇒ 系统默认（可能走环境代理）。"""
    host = ((url or "").split("//", 1)[-1].split("/", 1)[0]
            .rsplit("@", 1)[-1].split(":")[0].strip("[]").lower())
    return LOCAL_OPENER if host in ("127.0.0.1", "localhost", "::1") else urllib.request.build_opener()

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from console_utf8 import console_utf8
    console_utf8()
except ModuleNotFoundError:
    pass

TOKEN_FILE = Path(r"C:\LocalAI-Assistant\_备份\ollama网关口令.txt")
# 请求日志（2026-10-05 加，见 ReqLog 的说明）。放 `_备份\`：那儿已被 .gitignore 排除。
DEFAULT_LOG = Path(r"C:\LocalAI-Assistant\_备份\gateway.log")
# 人格正文目录（自带网页的"人格"下拉用；**只读**）。
# 2026-10-05 加：用户要"手机上的网页版也能选人格"。⚠️ 正文**不是随便给的** ——
# 见 `_handle` 里 `/__persona` 那条：本机可以直接读，别的设备必须带上正确的 Key。
PERSONAS_DIR = Path(r"C:\LocalAI-Assistant\personas")

# 允许转发的接口：(路径, 是否允许 GET, 是否允许 POST, 说明)
ALLOW = {
    "/api/chat": (False, True, "对话（主力接口）"),
    "/api/generate": (False, True, "单轮生成"),
    "/api/embeddings": (False, True, "向量（老接口）"),
    "/api/embed": (False, True, "向量"),
    "/api/tags": (True, False, "列出已装模型（客户端选模型要用）"),
    "/api/version": (True, False, "版本号（探活）"),
    "/api/ps": (True, False, "当前加载的模型"),
    "/v1/models": (True, False, "OpenAI 兼容：列模型"),
    "/v1/chat/completions": (False, True, "OpenAI 兼容：对话"),
    "/v1/completions": (False, True, "OpenAI 兼容：补全"),
    "/v1/embeddings": (False, True, "OpenAI 兼容：向量"),
}
# 默认**禁止**的接口（要放行得显式 --allow-pull / --allow-admin）
PULL_PATHS = {"/api/pull", "/api/create", "/api/copy", "/api/push"}
ADMIN_PATHS = {"/api/delete", "/api/blobs"}

MAX_BODY = 8 * 1024 * 1024          # 单次请求体上限 8 MB（够聊天，挡异常大盘）
# ⚠️ 这些头**不转发给 Ollama**：
#   · 逐跳/长度类：由网关自己重新生成，照抄会出错
#   · `Origin` / `Referer` / `Access-Control-Request-*`（2026-10-03 实测踩到的坑）：
#     **Ollama 自己按 Origin 做了白名单**，只放行 `http://localhost` 之类；
#     `chrome-extension://`、`https://example.com`、`null` 一律直接 **403**（空响应体）。
#     表现就是"浏览器插件连不上"。原版 Ollama 的解法是设 `OLLAMA_ORIGINS=*`（全局环境变量）；
#     我们这里**换成网关做 CORS**：浏览器那侧由网关回答，转发给 Ollama 时不带 Origin，
#     于是不用改全局环境、也不用重启，插件直接能用。
#     想保留原样转发：加 `--forward-origin`（那时就得自己设 OLLAMA_ORIGINS=*）。
BAD_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailers", "transfer-encoding", "upgrade", "host",
               "content-length", "authorization"}
BAD_HEADERS_UPSTREAM = BAD_HEADERS | {"origin", "referer",
                                      "access-control-request-method",
                                      "access-control-request-headers",
                                      "access-control-request-private-network"}


def load_token(new: bool = False) -> str:
    if TOKEN_FILE.exists() and not new:
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    t = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(t + "\n", encoding="utf-8")
    return t


# ---------------------------------------------------------------- 系统资源（自带网页用）
# 2026-10-05 加：用户要"网页端能图形化看 CPU / 内存 / 显存 / GPU 占用"。
# **不引任何第三方库**：CPU/内存走 Windows 原生 API（ctypes），显卡走 nvidia-smi。
class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", _wt.DWORD), ("dwHighDateTime", _wt.DWORD)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", _wt.DWORD), ("dwMemoryLoad", _wt.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


_SYS_LOCK = threading.Lock()
_LAST_CPU: dict = {}


def _cpu_raw():
    r"""取一次 `GetSystemTimes` 的原始计数：`(空闲, 总线数)`；失败返回 None。"""
    i, k, u = _FILETIME(), _FILETIME(), _FILETIME()
    try:
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
    except Exception:
        return None
    if not ok:
        return None
    f = lambda v: (v.dwHighDateTime << 32) | v.dwLowDateTime      # noqa: E731
    return (f(i), f(k) + f(u))


def _cpu_between(a, b):
    if not a or not b:
        return None
    di, db = b[0] - a[0], b[1] - a[1]
    if db <= 0:
        return None
    return max(0.0, min(100.0, (1 - di / db) * 100))


def cpu_percent():
    r"""CPU 占用率（%）。用 `GetSystemTimes` 的两次差值算。

    ⚠️ **第一次调用也必须给出数字**（2026-10-05 改，用户报"资源面板一直读取中"）：
    以前第一次没有基准就返回 `None`，结果手机浏览器把**那一次响应**缓存住了 ⇒
    页面永远显示"读取中…"。现在第一次自己 `sleep 0.12` 秒再采一个点，
    **任何一次请求都有数字**（服务端那两行 `Cache-Control: no-store` 是另一半保险）。

    为什么不用 psutil：网关的卖点之一是**纯标准库**（换台机器不用装东西）。
    """
    cur = _cpu_raw()
    with _SYS_LOCK:
        prev = _LAST_CPU.get("v")
        _LAST_CPU["v"] = cur
    if prev is None:
        time.sleep(0.12)
        cur2 = _cpu_raw()
        with _SYS_LOCK:
            _LAST_CPU["v"] = cur2
        return _cpu_between(cur, cur2)
    return _cpu_between(prev, cur)


def mem_info():
    r"""物理内存：已用 / 总量 / 百分比（`GlobalMemoryStatusEx`）。"""
    m = _MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None
    except Exception:
        return None
    gb = float(2 ** 30)
    return {"used_gb": round((m.ullTotalPhys - m.ullAvailPhys) / gb, 2),
            "total_gb": round(m.ullTotalPhys / gb, 2), "pct": int(m.dwMemoryLoad)}


_GPU_CACHE: dict = {"t": 0.0, "v": None}


def gpu_info(ttl: float = 3.5):
    r"""显卡：显存用量 / GPU 占用率 / 温度 —— 靠 `nvidia-smi`（这台机器有）。

    带 TTL 缓存：一次 `nvidia-smi` 实测约 **42 ms**（进程启动占大头）。
    页面每 3 秒轮询、TTL 3.5 秒 ⇒ **大约两次轮询才真起一次进程**：
    常驻开销从"每 3 秒 42 ms"降到"每 6 秒 42 ms"（≈ 0.7% 的一个核心）。
    没有 nvidia-smi / 不是 N 卡 → 返回 None（页面显示"读不到"），不影响其它三项。
    """
    now = time.time()
    if _GPU_CACHE["v"] is not None and now - _GPU_CACHE["t"] < ttl:
        return _GPU_CACHE["v"]
    out = None
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,"
                            "memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8)
        if r.returncode == 0 and (r.stdout or "").strip():
            out = []
            for line in r.stdout.strip().splitlines():
                p = [x.strip() for x in line.split(",")]
                if len(p) >= 6:
                    out.append({"index": p[0], "name": p[1],
                                "util": int(float(p[2])),
                                "mem_used_mb": int(float(p[3])),
                                "mem_total_mb": int(float(p[4])),
                                "temp_c": int(float(p[5]))})
    except Exception:
        out = None
    _GPU_CACHE.update(t=now, v=out)
    return out


def sys_stats() -> dict:
    # `model_loaded` / `last_chat*` 见文件下方同名函数（2026-10-06 傍晚加）：
    # 让面板能直接回答"模型真的被调用了吗 / 现在加载着吗"。
    return {"cpu_pct": cpu_percent(), "mem": mem_info(), "gpu": gpu_info(),
            "think_mode": THINK_MODE,
            "astrbot_think": astrbot_think_state(),
            "model_loaded": loaded_models(),
            "last_chat": dict(LAST_CHAT),
            "last_chat_line": last_chat_line(),
            "strip": ("on" if strip_limit_on() else "off"),   # 长度约束消毒开关
            "tools": ("on" if tools_on() else "off"),        # 工具开关（on=保留）
            "cont": ("on" if continue_on() else "off"),      # 自动续写
            "mode": send_mode(),                             # 发送方式（三选一）
            "compat": ("on" if compat_on() else "off"),      # = mode != raw
            "hist": ("on" if hist_on() else "off"),          # 历史净化
            "md": ("on" if md_on() else "off"),              # 去 markdown 记号
            "streamsan": ("on" if streamsan_on() else "off"),  # 流式洗文本
            "nl": ("on" if nl_on() else "off"),              # 压空行
            "preset": current_preset(),
            "ctx": ctx_usage(),              # 上下文占用（2026-10-18 加）
            "ctx_line": ctx_line(),
            "model_line": model_line(),
            "ts": time.time()}


def render_plain(ok_msg: str = "") -> str:
    """将网关采集到的系统资源交给独立页面模板渲染。"""
    return render_plain_page(sys_stats(), ok_msg)


# 手机 App 安装包（2026-10-06 加）：手机浏览器点一下就能下载安装（不用数据线、不用传文件）。
# ⚠️ 2026-10-06 用户要求：**App 的东西要和本地 AI 部署分开**（别塞在 `C:\LocalAI-Assistant\` 里）
# ⇒ 产物目录放在**独立目录** `E:\手机客户端App\out`（源码 `src\`、工具链 `tools\` 也都在那，
# 全是 ASCII 路径，免得编译工具链吃中文/空格出幺蛾子）。网关只**读**这个目录，不往里写。
# ⚠️ 2026-10-18 加：手机上传的文件落这儿（用户要求："我把回复的文件发给电脑端"）。
# 只做**落地**，不自动处理；大小上限 25 MB；文件名做净化（去掉路径分隔符与控制字符）✓
CHAT_FILES_DIR = Path(r"C:\LocalAI-Assistant\聊天文件")
CHAT_FILES_MAX = 25 * 1024 * 1024
APK_DIR = Path(r"E:\手机客户端App\out")


def apk_info():
    r"""返回最新那个 APK 的信息（`{name, size, mtime, path}`）；没有就 None。"""
    try:
        files = sorted(APK_DIR.glob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return None
    if not files:
        return None
    f = files[0]
    st = f.stat()
    return {"name": f.name, "size": st.st_size, "mtime": st.st_mtime, "path": f}


def apk_zip_bytes(info: dict) -> bytes:
    r"""把最新那个 APK 装进一个 zip 返回（**lazy 生成 + 缓存**，缓存在 `APK_DIR` 里）。

    为什么要有它：有些国产浏览器**完全不让下载 .apk**（点下载就报错），但 `.zip` 是放行的；
    下载 zip 之后用手机自带的「文件管理」解压，再点里面的 apk 就能装。
    缓存比 apk 旧就重建一次（apk 换了要重新打）。
    """
    import zipfile
    apk = info["path"]
    zpath = apk.with_suffix(apk.suffix + ".zip")          # …release.apk.zip
    try:
        if zpath.exists() and zpath.stat().st_mtime >= apk.stat().st_mtime:
            return zpath.read_bytes()
    except Exception:
        pass
    tmp = zpath.with_suffix(zpath.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:   # APK 本身已压缩，存起来即可
        z.write(apk, arcname=apk.name)
    tmp.replace(zpath)
    return zpath.read_bytes()

# 手机授权码（2026-10-05 加）：在电脑上生成一个 4 位码，手机填一次，服务端给手机种一个 cookie
# ⇒ 之后手机上的「停止模型」表单**不用再填 Key**（39 位口令在手机上敲太痛苦，实测他敲不动）。
_TICKETS: dict = {}
TICKET_TTL = 600                 # 10 分钟有效
COOKIE_NAME = "gw_stop"


def new_ticket() -> str:
    r"""生成一个 4 位授权码（10 分钟内有效，用完即弃）。"""
    now = time.time()
    for k in [k for k, v in _TICKETS.items() if v < now]:
        _TICKETS.pop(k, None)
    for _ in range(50):
        code = f"{secrets.randbelow(10000):04d}"
        if code not in _TICKETS:
            _TICKETS[code] = now + TICKET_TTL
            return code
    raise RuntimeError("授权码生成失败")


def use_ticket(code: str) -> bool:
    r"""校验并**消费**一个授权码（一次性）。"""
    now = time.time()
    exp = _TICKETS.get((code or "").strip())
    if not exp or exp < now:
        return False
    _TICKETS.pop((code or "").strip(), None)
    return True


# ── 网页访问授权（2026-10-06 加，用户要求："有人访问这个网页要输一次手机授权码，之后永久可访问"）
#
# 为什么需要：局域网里任何设备都能直接打开控制台网页 —— 实测（无授权、无 Key）能看到
#   资源数据 / 模型清单 / **人格清单**，还能**白用模型**（默认不强制 Key）。
# 这里把"控制台那套路径"（`/`、`/plain`、`/__*`）关起来，**API（`/v1/*`、`/api/*`）不动**
#   —— 手机 App 走的是 API 那条线，不受影响；要连 API 也强制，用原来的 `--require-key`。
# ⚠️ 与「停止模型」的 4 位码**是两套东西**：
#   · 那个：一次性、10 分钟、只为"停服务"这一次动作（`_TICKETS`）；
#   · 这个：长期通行证，输一次种一年 cookie，**换码即全部失效**（见 `access_cookie_value`）。
ACCESS_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关访问码.txt")

# ── 思考模式开关（2026-10-08 加，用户要求"手机上也能切"）──────────────
#
# 背景：网关以前**无条件**把思考关掉（`/api/chat` 写 `think=false`、`/v1` 写
# `reasoning_effort=none`）—— 因为 35B 一旦思考就会把 1024 token 全烧在推理上、
# 正文返回 0 字（实测见 `_handle` 里那段注释）。但手机 App 自带「思考设置」，
# 用户希望能自己控制。
#
# 三档，并**持久化**（重启不丢）：
#   auto（默认）：客户端说了就听客户端的（下面三种字段任一存在即算"说了"）；
#                 没说 ⇒ 按 off 处理（保持老行为，不会突然开始烧 token）
#   off         ：无条件关（老行为）
#   on          ：无条件开（想看它推理时用）
#
# 三种改法：① 启动加 `--think auto|off|on`（`--allow-think` 等价于 auto）
#          ② 自带网页上的「🧠 思考模式」按钮（手机也能点）
#          ③ 删掉这个文件 = 回到 auto
THINK_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关思考模式.txt")
THINK_MODES = ("auto", "off", "on", "local")
THINK_MODE = "auto"                    # 默认 auto
LAST_ASTRBOT_SYNC = ""                 # 最近一次同步 AstrBot 的结果（网页上显示）：客户端说了听客户端的，没说就关（= 以前的行为）
THINK_LABEL = {"auto": "自动 —— 客户端自己带的思考设置优先；它没设就关（默认，推荐）",
               "off": "全局关 —— 永远不思考（省 token、回复快）",
               "on": "全局开 —— 每次都先推理（慢、吃 token，35B 上容易只想不说）",
               "local": "本地思考 —— 先在本机想一遍（过程不外发），只把正式回复发出去"}
# 「本地思考」的过程写到哪儿（只在本机；`_备份\` 已被 .gitignore 排除）
LOCAL_KEEP_ALIVE = "30m"        # local 档给模型的保温时长（见下面 _local_think 开头的说明）
WARM_MODEL_FILE = Path(r"C:\LocalAI-Assistant\_备份\预热模型.txt")   # 网页上选的"开机预热哪个模型"
DEFAULT_WARM_MODEL = "local-assistant-35b:latest"
_WARM_STATE = {"busy": False, "model": "", "t": 0.0, "ok": None, "secs": 0.0}
_LOCAL_FALLBACK = ""            # local 档上次为什么退回普通单轮（页面上显示出来）


TEMPERATURE_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关温度.txt")
TEMPERATURE_CHOICES = ("auto", "0.2", "0.7", "1.0")   # auto = 不动客户端给的温度
TEMPERATURE_DEFAULT = "auto"


def temperature() -> str:
    r"""当前温度设置（`auto` 或具体数字；请求时实时读 ⇒ 改完下一条就生效）。"""
    try:
        v = TEMPERATURE_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in TEMPERATURE_CHOICES:
            return v
    except Exception:
        pass
    return TEMPERATURE_DEFAULT


def save_temperature(v: str) -> str:
    r"""记住用户选的温度。"""
    v = (v or "").strip().lower()
    if v not in TEMPERATURE_CHOICES:
        v = TEMPERATURE_DEFAULT
    try:
        TEMPERATURE_FILE.write_text(v + "\n", encoding="ascii", newline="\n")
    except Exception as e:
        sys.stderr.write(f"  [温度] 写设置失败：{type(e).__name__}\n")
    return temperature()


# 长度约束消毒开关（2026-10-18 加）：`on`/`off`，存文件，网页上可切（下一条消息生效）✓
# 有时用户想保留客户端人设里的「短句聊天」风格 ⇒ 关掉它。默认开（实测 50 字 → 590 字）。
# 工具开关（2026-10-18 加）：`on`=保留客户端带来的 tools，`off`=**剥掉**（客户端就退回纯聊天）。
# 为什么要有它：实测同一提示，不带 tools 出 349 字、带 tools 只出 32 字前言 + finish_reason=tool_calls
# ⇒ 用户看到的"回复越来越短、最后半句截断"，就是模型把正文换成了工具调用。
TOOLS_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关工具开关.txt")
TOOLS_CHOICES = ("on", "off")
TOOLS_DEFAULT = "on"


def tools_on() -> bool:
    r"""是否**保留**客户端发来的 `tools`（实时读 ⇒ 网页上改完下一条就生效）。"""
    try:
        v = TOOLS_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in TOOLS_CHOICES:
            return v == "on"
    except Exception:
        pass
    return TOOLS_DEFAULT == "on"


def save_tools(v: str) -> str:
    v = (v or "").strip().lower()
    if v not in TOOLS_CHOICES:
        v = TOOLS_DEFAULT
    try:
        TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOOLS_FILE.write_text(v + "\n", encoding="ascii", newline="\n")
    except Exception as e:
        sys.stderr.write(f"  [工具开关] 写设置失败：{type(e).__name__}\n")
    return "on" if tools_on() else "off"

STRIP_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关长度消毒.txt")
STRIP_CHOICES = ("on", "off")
STRIP_DEFAULT = "on"


def strip_limit_on() -> bool:
    r"""是否摘掉 system 里「最多N个短句 / 控制在X-Y字」这类长度约束（实时读 ⇒ 改完立即生效）。"""
    try:
        v = STRIP_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in STRIP_CHOICES:
            return v == "on"
    except Exception:
        pass
    return STRIP_DEFAULT == "on"


def save_strip_limit(v: str) -> str:
    r"""记住用户选的开关值。"""
    v = (v or "").strip().lower()
    if v not in STRIP_CHOICES:
        v = STRIP_DEFAULT
    try:
        STRIP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STRIP_FILE.write_text(v + "\n", encoding="ascii", newline="\n")
    except Exception as e:
        sys.stderr.write(f"  [长度消毒] 写设置失败：{type(e).__name__}\n")
    return "on" if strip_limit_on() else "off"


LOCAL_BUDGET_FILE = Path(r"C:\LocalAI-Assistant\_备份\本地思考预算.txt")
LOCAL_BUDGET_DEFAULT = 800          # 默认第一轮思考预算（网页上可改）
LOCAL_BUDGET_CHOICES = (300, 400, 600, 800, 1200)


def local_budget() -> int:
    r"""当前的第一轮思考预算（文件优先；请求时实时读 ⇒ 网页改完下一条就生效）。

    实测（35B + local，同一条消息）：400 ⇒ 12.1 秒 ✓ / 800 ⇒ 21.2 秒（App 超时 20 秒，压线）
    / 1600 ⇒ 25.8 秒 ✗。数字越大想得越细、也越慢。
    """
    try:
        v = int(LOCAL_BUDGET_FILE.read_text(encoding="utf-8-sig").strip())
        if 100 <= v <= 8192:
            return v
    except Exception:
        pass
    return LOCAL_BUDGET_DEFAULT


def save_local_budget(n: int) -> int:
    r"""记住用户选的思考预算。"""
    try:
        LOCAL_BUDGET_FILE.write_text(f"{int(n)}\n", encoding="ascii", newline="\n")
    except Exception as e:
        sys.stderr.write(f"  [本地思考] 写预算失败：{type(e).__name__}\n")
    return local_budget()


def warm_model() -> str:
    r"""当前选的"开机预热"模型（文件优先，没有就用默认）。"""
    try:
        v = WARM_MODEL_FILE.read_text(encoding="utf-8-sig").strip()
        if v:
            return v
    except Exception:
        pass
    return DEFAULT_WARM_MODEL


def save_warm_model(name: str) -> str:
    r"""记住"开机预热哪个模型"。"""
    name = (name or "").strip()
    if not name:
        return warm_model()
    try:
        WARM_MODEL_FILE.write_text(name + "\n", encoding="utf-8", newline="\n")
    except Exception as e:
        sys.stderr.write(f"  [预热] 写选择失败：{type(e).__name__}\n")
    return name


def list_models() -> list:
    r"""本机装了哪些模型（问 Ollama `/api/tags`，失败就返回空）。"""
    try:
        with LOCAL_OPENER.open("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return [m.get("name") for m in (d.get("models") or []) if m.get("name")]
    except Exception:
        return []


def _warm_worker(model: str) -> None:
    r"""后台预热：把模型读进来并保温（和 warmup.py 做的事一样）。"""
    _WARM_STATE.update(busy=True, model=model, t=time.time(), ok=None, secs=0.0)
    t0 = time.time()
    try:
        body = json.dumps({"model": model, "prompt": "hi", "stream": False,
                           "options": {"num_predict": 1},
                           "keep_alive": LOCAL_KEEP_ALIVE or "30m"}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with LOCAL_OPENER.open(req, timeout=1800) as r:
            r.read()
        _WARM_STATE.update(ok=True, secs=time.time() - t0)
        sys.stderr.write(f"  [预热] 网页触发：{model} 就绪，用时 {time.time()-t0:.0f} 秒\n")
    except Exception as e:
        _WARM_STATE.update(ok=False, secs=time.time() - t0)
        sys.stderr.write(f"  [预热] 网页触发失败：{type(e).__name__}\n")
    finally:
        _WARM_STATE["busy"] = False
        sys.stderr.flush()
THOUGHT_LOG = Path(r"C:\LocalAI-Assistant\_备份\思考过程.log")
THOUGHT_LOG_MAX = 2 * 1024 * 1024          # 超过 2 MB 就只留最近的（免得无限长）
THOUGHT_REC_FILE = Path(r"C:\LocalAI-Assistant\_备份\思考过程记录.txt")
THOUGHT_REC = True                         # 要不要把过程写到磁盘（网页上可切）


def load_thought_rec() -> bool:
    r"""读"要不要记录过程"（文件里 on/off；没有就保持当前值）。"""
    global THOUGHT_REC
    try:
        v = THOUGHT_REC_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in ("on", "off"):
            THOUGHT_REC = (v == "on")
    except Exception:
        pass
    return THOUGHT_REC


def save_thought_rec(on: bool) -> bool:
    r"""设置并持久化"要不要记录过程"。"""
    global THOUGHT_REC
    THOUGHT_REC = bool(on)
    try:
        THOUGHT_REC_FILE.write_text("on\n" if on else "off\n",
                                    encoding="ascii", newline="\n")
    except Exception as e:
        sys.stderr.write(f"  [本地思考] 写记录开关失败：{type(e).__name__}\n")
    return THOUGHT_REC


def thought_log_info() -> str:
    r"""过程日志的现状：`"不存在"` / `"12 KB · 3 条"`。"""
    try:
        if not THOUGHT_LOG.exists():
            return "文件不存在（还没用过 local，或已删）"
        kb = THOUGHT_LOG.stat().st_size / 1024
        txt = THOUGHT_LOG.read_text(encoding="utf-8", errors="replace")
        n = txt.count("\n===== ")
        return f"{kb:.0f} KB · {n} 条"
    except Exception as e:
        return f"读不到（{type(e).__name__}）"
# AstrBot 的思考开关（同一个概念的另一个地方）：它**启动时**读这个文件，
# 所以网页上切档后要**重启 AstrBot** 才生效；auto 档不动它（让它按自己的设置走）。
ASTRBOT_CFG = Path(r"C:\LocalAI-Assistant\AstrBotData\data\cmd_config.json")
ASTRBOT_KEY = "ollama_disable_thinking"


def astrbot_running(timeout: float = 0.25) -> bool:
    r"""AstrBot 在不在跑？—— 连一下它的 6185 端口（不看进程名，最省事也最准）。

    为什么要判它（2026-10-08 实测踩到）：AstrBot **自己会写配置**，
    它运行期间我们改 `cmd_config.json`，它一保存就把我们的改动**覆盖**掉。
    """
    try:
        with socket.create_connection(("127.0.0.1", 6185), timeout=timeout):
            return True
    except Exception:
        return False


def astrbot_think_state() -> str:
    r"""AstrBot 现在是"关思考/允许思考/文件不在"（给网页显示用）。"""
    try:
        txt = ASTRBOT_CFG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "未装/找不到配置"
    if f'"{ASTRBOT_KEY}"' not in txt:
        return "配置里没有这个键"
    return "关思考" if f'"{ASTRBOT_KEY}": true' in txt else "允许思考"


def sync_astrbot_think(mode: str) -> str:
    r"""把网关的档位同步到 AstrBot（`auto` 不动它）。

    ⚠️ 只做**单行文本替换**，不整份重写 JSON —— 免得动到 AstrBot 自己的格式/其它键。
    """
    if mode == "auto":
        return "AstrBot 不动（auto = 各自决定）"
    try:
        txt = ASTRBOT_CFG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "AstrBot 配置没找到（没装就忽略）"
    want = "true" if mode == "off" else "false"
    want_human = "关思考" if mode == "off" else "允许思考"
    if f'"{ASTRBOT_KEY}": {want}' in txt:
        return f"AstrBot 已经是「{want_human}」"
    for old in (f'"{ASTRBOT_KEY}": true', f'"{ASTRBOT_KEY}": false'):
        if old in txt:
            try:
                ASTRBOT_CFG.write_text(txt.replace(old, f'"{ASTRBOT_KEY}": {want}', 1),
                                       encoding="utf-8", newline="\n")
                msg = f"AstrBot 已改成「{want_human}」（**重启 AstrBot 生效**）"
                if astrbot_running():
                    msg += ("⚠️ 但 AstrBot **正在运行**，它一保存配置就会把这次改动**覆盖** ⇒ "
                            "稳妥做法是去 AstrBot 界面上改「关闭思考模式」")
                return msg
            except Exception as e:
                return f"AstrBot 写失败：{type(e).__name__}"
    return "AstrBot 配置里没找到那个键（版本不同？）"


def load_think_mode() -> str:
    r"""读持久化的思考模式（文件没有/内容不认识 ⇒ 保持 auto）。"""
    global THINK_MODE
    try:
        v = THINK_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in THINK_MODES:
            THINK_MODE = v
    except Exception:
        pass
    return THINK_MODE


def save_think_mode(mode: str) -> str:
    r"""设置并持久化（启动参数 / 网页按钮都走这里）。"""
    global THINK_MODE
    global LAST_ASTRBOT_SYNC
    mode = (mode or "").strip().lower()
    if mode not in THINK_MODES:
        return THINK_MODE
    THINK_MODE = mode
    try:
        THINK_FILE.write_text(mode + "\n", encoding="ascii", newline="\n")
    except Exception as e:
        sys.stderr.write(f"  [思考模式] 写文件失败（只改了内存）：{e}\n")
    LAST_ASTRBOT_SYNC = sync_astrbot_think(mode)      # 顺手同步 AstrBot
    sys.stderr.write(f"  [思考模式] {mode} —— {LAST_ASTRBOT_SYNC}\n")
    sys.stderr.flush()
    return THINK_MODE


def client_think_intent(payload) -> str:
    r"""客户端自己有没有表达"要不要思考"？⇒ `""`（没说）/ `"on"` / `"off"`。"""
    if not isinstance(payload, dict):
        return ""
    if "think" in payload:
        return "on" if payload.get("think") else "off"
    effort = payload.get("reasoning_effort")
    if isinstance(effort, str) and effort.strip():
        return "off" if effort.strip().lower() in ("none", "off", "0", "false", "minimal") else "on"
    kwargs = payload.get("chat_template_kwargs")
    if isinstance(kwargs, dict) and "enable_thinking" in kwargs:
        return "on" if kwargs.get("enable_thinking") else "off"
    return ""


def apply_think_mode(payload, path: str) -> str:
    r"""按当前模式往 payload 里写思考指令；返回一行说明（进网关日志）。"""
    if path not in ("/api/chat", "/v1/chat/completions") or not isinstance(payload, dict):
        return ""
    # 三档：auto = 听客户端的（没说就关）；off/on = 全局说了算（不看客户端）。
    # 两个接口认的字段不同：`/api/chat` 认 `think`、`/v1` 认 `reasoning_effort`。
    mode, intent = THINK_MODE, client_think_intent(payload)
    if mode == "auto":
        if intent:
            # 客户端表达了意图 ⇒ 翻译成这条链路认的字段；**只补空、不覆盖**它自己写好的值
            if path == "/api/chat":
                if "think" not in payload:
                    payload["think"] = (intent == "on")
            elif not payload.get("reasoning_effort"):
                payload["reasoning_effort"] = "high" if intent == "on" else "none"
            return f" think={intent}(听客户端)"
        mode = "off"                       # 客户端没说 ⇒ 关（与老行为一致）
    if mode == "off":
        if path == "/api/chat":
            payload["think"] = False
        else:
            payload["reasoning_effort"] = "none"
        return " think=off"
    if path == "/api/chat":
        payload["think"] = True
    else:
        payload["reasoning_effort"] = "high"    # `/v1` 上 think=true 无效（实测）
    return " think=on"



ACCESS_COOKIE = "gw_auth"
ACCESS_MAX_AGE = 365 * 24 * 3600     # "永久" = 一年（每次访问会重新续期）
ACCESS_LEN = 6                        # 6 位数字：比 4 位耐猜，手机上也好敲
ACCESS_LOCK_AFTER = 5                 # 连错 5 次开始锁
ACCESS_LOCK_BASE = 300                # 第一次锁 5 分钟，之后每次翻倍
ACCESS_LOCK_MAX = 3600                # 最多锁 1 小时
_FAILS: dict = {}                     # ip -> (错次数, 解锁时间戳)


def load_access_code(new: bool = False) -> str:
    r"""读（或生成）访问码：6 位数字，存在 `_备份\网关访问码.txt`，**重启不变**。

    ⚠️ 读的时候要**去掉 BOM/空白并确认是数字**：2026-10-06 我用 PowerShell 的
    `Set-Content -Encoding UTF8` 手工改过这个文件，**PS 5.1 会写 BOM** ⇒ 服务端读成
    `\ufeff<你的授权码>` ⇒ 手机上敲 `<你的授权码>` 授权失败（一个看不见的字符把码改了）。现在容错。
    """
    if ACCESS_FILE.exists() and not new:
        c = ACCESS_FILE.read_text(encoding="utf-8", errors="replace")
        c = c.lstrip("\ufeff").strip()
        if len(c) >= ACCESS_LEN and c.isdigit():
            _ACCESS_CACHE["code"] = c
            return c
    c = f"{secrets.randbelow(10 ** ACCESS_LEN):0{ACCESS_LEN}d}"
    ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 写文件**不带 BOM**（用 ASCII：内容就是数字）
    ACCESS_FILE.write_text(c + "\n", encoding="ascii")
    _ACCESS_CACHE["code"] = c
    return c


_ACCESS_CACHE: dict = {}


def access_code() -> str:
    r"""当前访问码（进程内缓存一次；`--new-access-code` 会重新生成）。"""
    if not _ACCESS_CACHE.get("code"):
        _ACCESS_CACHE["code"] = load_access_code()
    return _ACCESS_CACHE["code"]


def access_cookie_value(code: str) -> str:
    r"""cookie 的值 = sha256(固定盐 + 访问码)。

    这样**服务端不用存 session**：换访问码 ⇒ 算出来的值变了 ⇒ 之前发出去的
    所有通行证**立即全部失效**（等于"一键踢掉所有设备"）。
    """
    return hashlib.sha256(("ollama-gateway-access-v1|" + (code or "")).encode("utf-8")).hexdigest()[:40]


def access_cookie_ok(raw: str, code: str) -> bool:
    return bool(raw) and secrets.compare_digest((raw or "").strip(), access_cookie_value(code))


def access_locked_for(ip: str) -> int:
    r"""这个 IP 还要被锁多少秒（0 = 没锁）。"""
    st = _FAILS.get(ip)
    if not st:
        return 0
    return max(0, int(st[1] - time.time()))


def note_access_fail(ip: str) -> int:
    r"""记一次输错；返回锁定时长（秒；0 = 还没到锁的门槛）。"""
    fails = (_FAILS.get(ip, (0, 0))[0]) + 1
    lock = 0
    if fails >= ACCESS_LOCK_AFTER:
        lock = min(ACCESS_LOCK_BASE * (2 ** (fails - ACCESS_LOCK_AFTER)), ACCESS_LOCK_MAX)
    _FAILS[ip] = (fails, time.time() + lock)
    return lock


def clear_access_fail(ip: str) -> None:
    _FAILS.pop(ip, None)


# ── 已授权设备（会话表，2026-10-06 下午加：用户要"网页上能管理授权、自由解除"）
#
# 为什么不能再用"码的哈希"当 cookie：那是**无状态**的 —— 服务端没法列出"谁授权了"，
# 也没法单独踢掉某台设备（只能换码把所有人一起踢）。改成**会话表**后：
#   · cookie 里放一个随机 token；服务端在 `_备份\网关授权设备.json` 里查它；
#   · 于是能列出设备（IP / 浏览器 / 首次 / 最后活动）并**逐个解除**；
#   · **入网码与已授权设备解耦**：换码只影响"还没进门的设备"，已授权的照旧。
SESSION_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关授权设备.json")
_SESSIONS: dict = {}          # token -> {"ip","ua","first","last"}
_SESS_LOADED = {"done": False}
_SESS_DIRTY = {"t": 0.0}


def _sessions_load() -> None:
    if _SESS_LOADED["done"]:
        return
    _SESS_LOADED["done"] = True
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _SESSIONS.update({k: v for k, v in data.items() if isinstance(v, dict)})
    except Exception:
        pass


def sessions_save(force: bool = False) -> None:
    r"""把会话表落盘（**最多每 30 秒写一次** —— 每个请求都写会把磁盘写烂）。"""
    now = time.time()
    if not force and now - _SESS_DIRTY["t"] < 30:
        return
    _SESS_DIRTY["t"] = now
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(_SESSIONS, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    except Exception:
        pass


def session_new(ip: str, ua: str) -> str:
    r"""给一台新设备发通行证（token），并记下它是谁、什么时候来的。"""
    _sessions_load()
    tok = secrets.token_hex(16)
    now = time.time()
    _SESSIONS[tok] = {"ip": ip, "ua": (ua or "")[:80], "first": now, "last": now}
    sessions_save(force=True)
    return tok


def session_touch(tok: str) -> bool:
    r"""token 还有效吗？顺手更新"最后活动时间"。"""
    _sessions_load()
    s = _SESSIONS.get((tok or "").strip())
    if not s:
        return False
    s["last"] = time.time()
    sessions_save()
    return True


def session_revoke(tok: str) -> bool:
    _sessions_load()
    if _SESSIONS.pop((tok or "").strip(), None) is not None:
        sessions_save(force=True)
        return True
    return False


def session_revoke_all() -> int:
    _sessions_load()
    n = len(_SESSIONS)
    _SESSIONS.clear()
    sessions_save(force=True)
    return n


def sessions_list() -> list:
    _sessions_load()
    return sorted(({"token": k, **v} for k, v in _SESSIONS.items()),
                  key=lambda s: s.get("first") or 0)


# ── 「最近一次对话」+「模型加载了吗」（2026-10-06 傍晚加）
#
# 用户问："我用客户端发信息了，有回复，但不知道模型有没有被调用，系统资源也不动。"
# 三个原因，所以要给他**能直接看的事实**，而不是让他盯着曲线猜：
#   ① 那种请求可能**根本没走网关**（换了地址/换了提供商/走了手机端侧模型）；
#   ② 面板数字是**瞬时采样**（CPU/GPU 每 3 秒一个点），一次短促推理可能落在两点之间；
#   ③ 他手机那个浏览器**不跑内联脚本** ⇒ 主页面根本不刷新，看着就像"不动"
#      （要看会动的数字就去 `/plain`：那一页靠 meta refresh 自己重载）。
LAST_CHAT: dict = {}
CHAT_PATHS = ("/v1/chat/completions", "/v1/completions", "/api/chat", "/api/generate")
_PS_CACHE: dict = {"t": 0.0, "v": []}


def note_chat(model: str, msgs: int, ip: str, ua: str, path: str) -> None:
    r"""记下"最近一次真正到达网关的对话"。

    ⚠️ 2026-10-18：**这里故意不把 `ptok/ttft/total/chars` 清零**。
    原先是新请求一来就清 0，结果页面每 3 秒轮询一次，正好在"清了但还没算完"的
    那几秒读到 `首字 0.0s / 提示 0 tok`（假数据、看着像坏了）✗
    现在保留上一轮的值 ⇒ 面板永远显示**最近一次完成的**那轮用量 ✓
    """
    LAST_CHAT.update({"t": time.time(), "model": model or "", "msgs": int(msgs or 0),
                      "ip": ip or "", "ua": (ua or "")[:40], "path": path or "",
                      "pending": True})


# ---- 「最后一条回复」原文抓取（2026-10-18 加，**只留内存里一条**）-------------
# 起因：用户报「手机端回复被截断，没有完整版」，而日志只有字数、没法判断
# "是撞上限 / 是客户端断开 / 还是模型自己就写这么短"。
# ⇒ 这里把最后一轮的**正文尾部 + 结尾标记 + 有没有收到 `[DONE]`** 存下来，
#    通过本机专用的 `/__peek_reply` 读出来（`./__` 端点本来就要授权，手机是读不到的）✓
LAST_REPLY: dict = {}
LAST_REPLIES: list = []


# ⚠️ 2026-10-18 加：「把 system 里『只能写短』的约束摘掉」（默认开，`--no-strip-limit` 关）
#    起因：用户报「手机端回复被截断，没有完整版」。实测抓到 `finish_reason=stop`、
#    `[DONE]` 正常、只用了 60~90/2048 token ⇒ **不是截断**，是模型按 system 里
#    「最多 5 个短句 / 控制在 15-50 字」自己收尾了。A/B（同句同 seed，35B）：
#        带那几条规则 → 32 token / **50 字**
#        摘掉那几条 → 345 token / **597 字**（10 倍）
#    而"在末尾加一句要求写长"只有 +21%（`02` 坑 43 实测）⇒ **加要求是弱杠杆，删规则才有效** ✓
#    只匹配**明确**的长度/留白表述；人格与其它规则一个不动 ✓
_LEN_LIMIT_PATTERNS = (
    r"[^\n。；]*最多\s*\d+\s*个?短句[^\n。；]*[。；]?",
    r"[^\n。；]*控制在\s*\d+\s*[-~—]\s*\d+\s*字[^\n。；]*[。；]?",
    r"[^\n。；]*不要每轮都把话题答完答满[^\n。；]*[。；]?",
    r"[^\n。；]*可以只回一点[^\n。；]*[。；]?",
    r"[^\n。；]*不要答满[^\n。；]*[。；]?",
    r"[^\n。；]*空行[^\n。；]*[。；]?",
)


# ⚠️ 2026-10-18 加：**历史净化**（防"越聊越短"自我强化）。
#    实测依据（用户那条 32 条消息的真实请求，原样重放）：
#      原样 → **1~3 字**；删掉残缺 assistant → 25 字；只留健康回合 → 56 字；
#      而"只留最后一句"（干净对话）→ **364~393 字** ✅
#    ⇒ 病根是历史里连着好几条"2~12 字、断在半句"的 assistant 回复（还夹着一次失败的
#      `read_file` 工具调用，模型把它编造成"我找到了文件"）。模型会**照抄自己的退化风格**。
#    策略（保守）：**只有当"最近 4 条 assistant 里 ≥2 条是短且无句末标点"时才动手**，
#    把这些残缺条目删掉、并丢掉孤立的 `role:tool` 消息。孤立的一条短回复不动 ✓
_HIST_END = ("。", "！", "？", "!", "?", "…", "～", "~", "」", "』", "）", ")", "】", "]", "\"")

# ⚠️ 2026-10-18 加：**"播报句"识别** —— 实测模型会只写开场白就停：
#   '好的，这就为你呈现完整的设定。'（15 字）
#   '我已经生成了完整的人设卡，现在将其呈现给你看。以下便是这个角色的全部设定：'（67 字）
#   '我已经整理好了这个版本的内容。…形成了一份完整的设定集。'（44 字）
#   这些话**结尾有句号**，所以老的"结尾无标点才算没写完"判不出来 ✗
#   ⇒ 这里单独认：**短 + 含"这就/以下/接下来/呈现/整理/稍等/给你看"** ⇒ 当成"还没写正文"✓
_ANNOUNCE_RE = re.compile(
    r"(这就|马上|稍等|以下|接下来|下面|立刻|立即)[^\n]{0,24}?"
    r"(呈现|整理|生成|展示|列出|写出|发给你|给你看|如下)|"
    r"(以下|下面)(便是|就是|是)[^\n]{0,20}|"
    r"(请稍等|稍等一下|马上就好)")
_ANNOUNCE_MAX = 90          # 只有"短回复"才当成播报（长回复里出现这些词是正常的）


def is_announcement(text: str) -> bool:
    r"""这段是不是"只播报不干活"（短 + 命中"播报"特征）✓

    实测要认**两类**（都带句号、看起来"说完了"，其实没有正文）：
      ① "好的，**这就**为你**呈现**完整的设定。"
      ② "我**已经整理好**了这个版本的内容。…形成了一份完整的**设定集**。"
         （没有"这就/以下"，但"已经…整理好 + 提到内容/版本/设定"）
    ⚠️ 真内容（带【】/换行/长文本）不会被误判 —— 有长度限制 ✓
    """
    s = (text or "").strip()
    if not s or len(s) > _ANNOUNCE_MAX:
        return False
    _hit = bool(_ANNOUNCE_RE.search(s))
    if not _hit:
        _hit = bool(len(s) <= 70
                    and re.search(r"(已经|我)(把)?(整理|生成|准备|写|做|合并)(好|完|了)?", s)
                    and re.search(r"(内容|版本|设定|卡片|人设|资料|文档|要素)", s))
    if not _hit:
        return False
    # ⚠️ 2026-10-18（按 GPT 第二次验收意见）：**收紧误判** —— 下面这些都算"已经有正文"，
    #    不能当成播报句（否则 '下面是答案：42。' 会被续写一次、还会被历史净化删掉）✗
    #    ① 冒号后面还有实际内容（≥2 字）
    _parts = re.split(r"[：:]", s, maxsplit=1)
    # ⚠️ 2026-10-18：阈值从 2 改成 **1** —— '下面是答案：2' 冒号后只有 1 个字，
    #    原来会被判成播报句 ⇒ 续写一次、还重复了整句（实测 '下面是答案：2下面是答案：2'）✗
    if len(_parts) == 2 and len(_parts[1].strip(" \n。！？!?…～~")) >= 1:
        return False
    #    ② 带【】字段结构
    if "【" in s or "】" in s:
        return False
    #    ③ 带分点结构（1. / 2、/ 一、/ 换行列表）
    if re.search(r"(^|\n)\s*([0-9]+[.、）)]|[一二三四五六七八九十]+[、.）)])", s):
        return False
    return True


def _dedupe_overlap(base: str, cont: str) -> str:
    r"""续写结果去重：模型被喂回自己的半句时，常把开头**重复一遍**。

    实测：base='下面是答案：2' ⇒ 续写回来又是 '下面是答案：2' ⇒ 拼成
    '下面是答案：2下面是答案：2' ✗
    做法：找 base 的后缀与 cont 的最长重叠，砍掉 cont 那一段 ✓
    """
    base = base or ""
    cont = cont or ""
    if not base or not cont:
        return cont
    for k in range(min(len(base), len(cont)), 0, -1):
        if base.endswith(cont[:k]):
            return cont[k:]
    return cont


def _is_broken_reply(m) -> bool:
    r"""assistant 的"残缺回复"：短且结尾不是句末标点（"好的。""嗯嗯～"这类正常短回复不算）"""
    if (m.get("role") or "").lower() != "assistant":
        return False
    c = str(m.get("content") or "").strip()
    if not c:
        return False
    # ⚠️ 2026-10-18：**播报句也删**（"我这就给你呈现…"这种，结尾有句号但没正文）
    if is_announcement(c):
        return True
    return len(c) < 30 and not c.endswith(_HIST_END)


# 自动续写（2026-10-18 加）：模型偶发"半句就 EOS"（实测 `completion_tokens=67`、
# finish_reason=stop、文本停在 `「异` 这种半个词上）⇒ 网关补一次"接着写完"再缝回去 ✓
CONTINUE_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关自动续写.txt")
CONTINUE_CHOICES = ("on", "off")
CONTINUE_DEFAULT = "on"
# 句末标点（落到这些字符上就算"说完了"，不再续写）
_SENT_END = ("。", "！", "？", "!", "?", "…", "～", "~", "」", "』", "）", ")", "】", "]", "\"", "…")
# 语气词收尾（"好的呀""知道了啦"）算正常短回复，不触发续写 ✓
_SOFT_END = ("吧", "啊", "呢", "哦", "哈", "嘛", "啦", "呀", "嗯", "噢", "喔", "哒")


def continue_on() -> bool:
    try:
        v = CONTINUE_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in CONTINUE_CHOICES:
            return v == "on"
    except Exception:
        pass
    return CONTINUE_DEFAULT == "on"


def save_continue(v: str) -> str:
    v = (v or "").strip().lower()
    if v not in CONTINUE_CHOICES:
        v = CONTINUE_DEFAULT
    try:
        CONTINUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONTINUE_FILE.write_text(v + "\n", encoding="ascii", newline="\n")
    except Exception:
        pass
    return "on" if continue_on() else "off"


# 兼容模式（2026-10-18 加）：把整段回复**先收完 → 洗成纯文本 → 一次性发**。
# 起因：用户那个客户端**不渲染 markdown**（`**` 原样显示），而且会在空行/表格处截断
# （实测网关回了 120 字，屏幕只剩 17 字）。整段一次性发就没有"分块被吞"的问题 ✓
COMPAT_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关兼容模式.txt")
COMPAT_CHOICES = ("on", "off")
COMPAT_DEFAULT = "off"


# ⚠️ 2026-10-18：**把两个互相牵扯的开关合并成一个三选一**（用户要求"只能一开一个关"）。
#   原来 `compat`（走不走洗文本路径）和 `streamsan`（边流洗还是整段缓冲）是隐式优先关系：
#   streamsan 开着就压过缓冲 ⇒ 能配出"看起来矛盾"的组合，用户没法一眼看懂。
#   现在只有**一个**取值：
#     raw    逐字流式、一个字都不改（原 conpat=off）
#     stream 边流边洗（默认，原 compat=on + streamsan=on）
#     buffer 整段收完再洗再发（原 compat=on + streamsan=off）
SENDMODE_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关发送方式.txt")
SENDMODE_CHOICES = ("raw", "stream", "buffer")
SENDMODE_LABEL = {"raw": "逐字原样", "stream": "边流边洗", "buffer": "整段洗好"}
SENDMODE_TIP = {
    "raw": "逐字流式、**不改写**（客户端能正确渲染 markdown 时用）",
    "stream": "**边流边洗**（默认；首字节 ~1 秒，不会让客户端超时）",
    "buffer": "**整段收完再洗再发**（长回复首字节 15~60 秒，老做法）",
}


def send_mode() -> str:
    try:
        v = SENDMODE_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in SENDMODE_CHOICES:
            return v
    except Exception:
        pass
    return "stream"


def save_send_mode(v: str) -> str:
    v = (v or "").strip().lower()
    if v not in SENDMODE_CHOICES:
        v = "stream"
    try:
        SENDMODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SENDMODE_FILE.write_text(v + "\n", encoding="ascii", newline="\n")
    except Exception:
        pass
    return send_mode()


def compat_on() -> bool:
    r"""走不走"洗文本"路径 —— 由三选一决定（`raw` 时不走）✓"""
    return send_mode() != "raw"


def save_compat(v: str) -> str:
    r"""老端点 `/__compat` 的兼容映射：off→raw、on→stream（原本是 buffer 就保持 buffer）✓"""
    v = (v or "").strip().lower()
    if v == "off":
        save_send_mode("raw")
    elif send_mode() == "raw":
        save_send_mode("stream")
    return "on" if compat_on() else "off"


# 历史净化开关（2026-10-18 加）：给"干活档"关掉用 —— 编码对话里短回复是正常的，
# 不该被当成"退化连发"删掉 ✓
HIST_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关历史净化.txt")


def hist_on() -> bool:
    try:
        v = HIST_FILE.read_text(encoding="utf-8-sig").strip().lower()
        if v in ("on", "off"):
            return v == "on"
    except Exception:
        pass
    return True


def save_hist(v: str) -> str:
    v = "on" if (v or "").strip().lower() != "off" else "off"
    try:
        HIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        HIST_FILE.write_text(v + "\n", encoding="ascii", newline="\n")
    except Exception:
        pass
    return v


# ---- 一键档位（2026-10-18 加）：用户要在同一个网关上接"聊天客户端"和"干活客户端"----
# 💬 聊天档（那个不渲染 markdown、会吞字的客户端）：工具剥掉 + 兼容模式开 + 续写开 + 历史净化开
# 🛠 干活档（DSH / 编码代理）：**工具保留** + 兼容模式关（要流式与 markdown）
#      + 自动续写关（代码以 ``` 结尾会被误判"没写完"）+ 历史净化关
PRESET_CHOICES = ("chat", "work")
PRESET_LABEL = {"chat": "💬 聊天档", "work": "🛠 干活档"}


def apply_preset(name: str) -> str:
    v = (name or "").strip().lower()
    if v not in PRESET_CHOICES:
        v = "chat"
    if v == "work":
        save_tools("on")
        save_compat("off")
        save_continue("off")
        save_hist("off")
        save_strip_limit("off")
        save_md("off")
        save_nl("off")
        save_send_mode("raw")
    else:
        save_tools("off")
        save_compat("on")
        save_continue("on")
        save_hist("on")
        save_strip_limit("off")
        save_md("on")
        save_nl("on")
        save_send_mode("stream")
    return v


def current_preset() -> str:
    r"""当前四个开关像哪一档；都不像就返回 `custom` ✓"""
    if (not tools_on() and compat_on() and continue_on() and hist_on()
            and md_on() and nl_on()):
        return "chat"
    if (tools_on() and not compat_on() and not continue_on() and not hist_on()
            and not md_on() and not nl_on()):
        return "work"
    return "custom"

MD_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关去记号.txt")
NL_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关压空行.txt")


def _flag_on(path: Path, default: bool = True) -> bool:
    try:
        v = path.read_text(encoding="utf-8-sig").strip().lower()
        if v in ("on", "off"):
            return v == "on"
    except Exception:
        pass
    return default


def _flag_save(path: Path, v: str, default: bool = True) -> str:
    v = "on" if (v or "").strip().lower() != "off" else "off"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(v + "\n", encoding="ascii", newline="\n")
    except Exception:
        pass
    return v


def md_on() -> bool:
    r"""是否把 markdown 记号（`**` / `|` 表格 / `#` / 反引号 / `- `）洗成纯文本。
    ⚠️ 只影响**回复文本**，且只在「兼容模式」开的时候生效 ✓"""
    return _flag_on(MD_FILE, True)


def save_md(v: str) -> str:
    return _flag_save(MD_FILE, v)


def nl_on() -> bool:
    r"""是否把回复里的**双空行压成单换行**（实测那个客户端在 `\n\n` 处会吞字）✓"""
    return _flag_on(NL_FILE, True)


def save_nl(v: str) -> str:
    return _flag_save(NL_FILE, v)


def strip_md(t: str) -> str:
    r"""去掉 markdown 记号（内容一个字不删）✓"""
    if not t:
        return t
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = t.replace("**", "")
    t = re.sub(r"__(.+?)__", r"\1", t)
    t = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s+", "· ", t, flags=re.M)

    def _pipes(m):
        line = m.group(0)
        if line.count("|") < 2:
            return line
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c and not set(c) <= set("-: ")]
        return " ｜ ".join(cells)
    t = re.sub(r"^.*\|.*$", _pipes, t, flags=re.M)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</?(b|i|u|em|strong|p|div|span|table|tr|td|th)\b[^>]*>", "", t, flags=re.I)
    return t


def collapse_blank(t: str) -> str:
    r"""双空行（及以上）压成单换行 ✓"""
    return re.sub(r"\n{2,}", "\n", t or "")


def _sw_row(label: str, cur: bool, action: str, tip: str = "") -> str:
    r"""一个独立开关的一行（开/关两个表单按钮 + 当前值 + 说明）✓"""
    btns = "".join(
        (f"<form method=\"post\" action=\"{action}\" style=\"margin:0 4px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if (v == 'on') == cur else ''}\">"
         f"{'开' if v == 'on' else '关'}</button></form>")
        for v in ("on", "off"))
    return (f"<div style=\"margin:5px 0\"><b>{label}</b>：{'开' if cur else '关'} {btns}"
            f"<span class=\"hint\">{tip}</span></div>")


def switches_html() -> str:
    r"""面板上的**独立开关表**（2026-10-18 加；用户要求"全部独立开关"）✓"""
    return "".join([
        _sw_row("🔧 工具（tools）", tools_on(), "/__tools",
                "关掉=把客户端带来的 tools 丢掉，客户端退回纯聊天"),
        # 🔀 发送方式：**三选一**（互斥）—— 原来「兼容模式」+「流式洗文本」有隐式优先级，
        #    能配出矛盾组合；合成单选后物理上不可能矛盾 ✓
        "<div style=\"margin:6px 0\"><b>🔀 发送方式（三选一）</b>："
        + "".join(
            (f"<form method=\"post\" action=\"/__mode\" style=\"margin:0 4px 0 0;display:inline\">"
             f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
             f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if v == send_mode() else ''}\">"
             f"{'● ' if v == send_mode() else ''}{SENDMODE_LABEL[v]}</button></form>")
            for v in SENDMODE_CHOICES)
        + "</div>"
        + "<div class=\"hint\" style=\"margin:-2px 0 6px 0\">"
        + " ／ ".join(f"<b>{SENDMODE_LABEL[v]}</b> = {SENDMODE_TIP[v]}" for v in SENDMODE_CHOICES)
        + "（⚠️ 原来的「兼容模式」「流式洗文本」已合并到这里）</div>",
        _sw_row("🎨 去 markdown 记号", md_on(), "/__md",
                "`**` `|` `#` 反引号 → 纯文本（发送方式=逐字原样时不生效）"),
        _sw_row("↩️ 压空行", nl_on(), "/__nl",
                "双空行 → 单换行（发送方式=逐字原样时不生效）"),
        _sw_row("🔁 自动续写", continue_on(), "/__cont",
                "模型半句就停时补写一次并缝回同一条回复"),
        _sw_row("🧹 历史净化", hist_on(), "/__hist",
                "删掉历史里「退化连发」的残缺回复"),
        _sw_row("✂️ 长度约束消毒", strip_limit_on(), "/__strip",
                "删掉 system 里「最多N个短句 / 控制在X-Y字」这类限制"),
    ])

STREAMSAN_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关流式洗文本.txt")


def streamsan_on() -> bool:
    r"""是否**边流边洗**（不攒整段）—— 等于"发送方式 == stream" ✓"""
    return send_mode() == "stream"


def save_streamsan(v: str) -> str:
    r"""老端点 `/__streamsan` 的兼容映射：on→stream、off→buffer（关掉流式就等于整段缓冲）✓"""
    save_send_mode("stream" if (v or "").strip().lower() != "off" else "buffer")
    return "on" if streamsan_on() else "off"


_SS_LINE_END = ("\n",)


class _StreamSanitizer:
    r"""**流式**版的 plainify：边喂边吐，跨分块也能正确处理。

    处理项（与 plainify 对齐，但**不能回头改已发出的内容**）：
      · `\n{2,}` → 单个 `\n`（客户端在双空行处会吞字）
      · `**` 去掉（含只写开头不闭合的）
      · `` ` `` 反引号去掉
      · `|` → `｜`（表格竖线换全角，逐字符安全）
      · 行首的 `#` 标题记号去掉
      · `<br>` / `<br/>` → `\n`；其它简单 HTML 标签去掉
    状态：
      · `_nl`     上一个已发字符是不是换行（用来压空行）
      · `_star`   挂着一个未配对的 `*`
      · `_lt`     `<` 之后还没见到 `>` 的缓冲（限 40 字，超了就原样放出）
    """

    def __init__(self) -> None:
        self._nl = True          # 位置：开头当行首
        self._star = False
        self._lt = ""
        # ⚠️ 2026-10-18：缓存"只由 ｜ - : 空格 组成"的片段 —— 用来识别表格分隔行
        self._sep = ""
        # 本行是否已经输出过正文（用来区分"整行是分隔行"和"数据行末尾的 ｜"）
        self._line_has_text = False

    def feed(self, s: str) -> str:
        out = []
        for ch in s:
            # ① 未闭合的 `<...`
            if self._lt:
                self._lt += ch
                low = self._lt.lower()
                if ch == ">":
                    tag = low
                    if tag.startswith("<br"):
                        out.append("\n")
                        self._nl = False
                    # 其它标签直接丢掉
                    self._lt = ""
                elif len(self._lt) > 40:
                    out.append(self._lt)
                    self._lt = ""
                continue
            if ch == "<":
                self._lt = "<"
                continue
            # ② 反引号：整段丢掉
            if ch == "`":
                continue
            # ③ `**`：先挂一个，成对就一起丢
            if ch == "*":
                if self._star:
                    self._star = False
                else:
                    self._star = True
                continue
            if self._star:                    # 单个 `*` 原样放回
                self._star = False
                out.append("*")
            # ④ 竖线换全角（先进分隔缓存，见下）
            if ch == "|":
                ch = "｜"
            # ④b 分隔行候选字符：先缓存；一旦来了别的字符，就把缓存原样冲出
            if ch in "｜-: \t":
                self._sep += ch
                continue
            if self._sep and ch != "\n":      # ⚠️ 换行交给 ⑤ 分支判定分隔行，别在这里先冲出
                out.append(self._sep)
                self._sep = ""
                self._nl = False
                self._line_has_text = True
            # ⑤ 换行：先把分隔缓存处理掉，再压空行
            if ch == "\n":
                if self._sep:
                    # ⚠️ 只有"整行都是 ｜ - : 空格"才是表格分隔行 ⇒ 丢掉；
                    #    数据行末尾的 `｜` 必须保留（否则表格右边框会缺一格）✗
                    if self._line_has_text or self._sep.strip("｜-: \t"):
                        out.append(self._sep)
                    self._sep = ""
                self._line_has_text = False
                if not self._nl:
                    out.append("\n")
                    self._nl = True
                continue
            # ⑥ 行首 `#` 标题记号
            if ch == "#" and self._nl:
                continue
            if ch == " " and self._nl:
                continue
            out.append(ch)
            self._nl = False
        return "".join(out)

    def flush(self) -> str:
        r"""把挂着的尾巴放出来（`<` / `*` / 分隔缓存）✓"""
        tail = ""
        if self._sep:
            tail += self._sep
            self._sep = ""
        if self._star:
            tail += "*"
            self._star = False
        if self._lt:
            tail += self._lt
            self._lt = ""
        return tail


def _sse_rewrite(buf: bytes, san: "_StreamSanitizer", sink: list) -> bytes:
    r"""把一段**完整 SSE 事件**里的 `delta.content` 洗一遍，其它帧原样返回。

    返回要写回客户端的字节；洗出来的正文同时追加到 `sink` ✓
    """
    out = bytearray()
    for ev in buf.split(b"\n\n"):
        if not ev.strip():
            continue
        if not ev.startswith(b"data:"):
            out += ev + b"\n\n"
            continue
        body = ev[5:].strip()
        if body == b"[DONE]":
            out += ev + b"\n\n"
            continue
        try:
            d = json.loads(body)
        except Exception:
            out += ev + b"\n\n"
            continue
        changed = False
        for ch_ in d.get("choices") or []:
            delta = ch_.get("delta") or {}
            txt = delta.get("content")
            if isinstance(txt, str) and txt:
                clean = san.feed(txt)
                sink.append(clean)
                delta["content"] = clean
                changed = True
        if changed:
            out += b"data: " + json.dumps(d, ensure_ascii=False).encode("utf-8") + b"\n\n"
        else:
            out += ev + b"\n\n"
    return bytes(out)


def plainify(t: str) -> str:
    r"""把 markdown 洗成纯文本（给"不渲染 markdown、会在空行处截断"的客户端用）✓

    · `**粗体**` / `__x__` / 反引号 → 去掉记号
    · `# 标题` → 去 `#`
    · `- 列表` → `· `
    · `| a | b |` 表格 → `a ｜ b`
    · 双空行及以上 → 单换行（实测那个客户端在 `\n\n` 处就断）
    """
    if not t:
        return t
    if md_on():
        t = strip_md(t)
    if nl_on():
        t = collapse_blank(t)
    return t.strip()

def looks_unfinished(text: str) -> bool:
    r"""这一段是不是"没写完"：非空、长度 ≥15、结尾不是句末标点 ✓"""
    s = (text or "").rstrip()
    if not s:
        return False
    # ⚠️ 2026-10-18（按 GPT 验收意见改）：
    #    ① **先认播报**——原来是先判 `len < 15` 直接返回 False，导致 11~12 字的
    #       '好了，我仔' / '嘿嘿，看' 这种残句**根本进不来**；`is_announcement` 自带
    #       ≤90 字上限，所以这里不必再套长度门槛 ✓
    #    ② 普通残句的门槛从 15 降到 **8**（实测那两条截断都在 11~12 字）✓
    #    ③ 但"吧/啊/呢/哦/哈/嘛/啦/呀/嗯"这类语气词收尾的多是**正常短回复**，
    #       不续写（否则每句"好的呀"都会被补写）✓
    if is_announcement(s):
        return True
    # ⚠️ 2026-10-18（GPT 验收补充）：**结构性信号**也要认 —— 实测出现过只回
    #    「角色：名字」（5 字）就停：低于 8 字门槛、也没有句末标点，
    #    但它明显是"字段列表刚开头" ⇒ 这类必须续写 ✓
    if s.endswith(("：", ":", "【", "「", "（", "(", "，", ",", "、", "—", "-")):
        return True
    # ⚠️ 2026-10-18：**撤掉"短 + 含冒号"这条** —— 它本是为「角色：名字」加的，
    #    但实测会误伤 '下面是答案:2' 这种完整短回复（触发续写、还补出垃圾"的后面"）✗
    #    代价：5 个字的「角色：名字」不再补写（无可靠信号，宁可漏也不要误补）✓
    if len(s) < 8:
        return False
    if s.endswith(_SOFT_END + _SENT_END):
        return False
    return not s.endswith(_SENT_END)

def sanitize_history(msgs: list):
    r"""删掉"退化连发"的残缺 assistant 回复与孤立 tool 消息 ⇒ 返回 `(新表, 删了几条)`。

    ⚠️ 触发条件刻意保守：**最近 4 条 assistant 里至少 2 条残缺**才动手。
    单条短回复（正常聊天里的"嗯嗯"）不会被删 ✓
    """
    if not isinstance(msgs, list) or len(msgs) < 4:
        return msgs, 0
    assistants = [m for m in msgs if (m.get("role") or "").lower() == "assistant"]
    recent = assistants[-4:]
    bad_recent = sum(1 for m in recent if _is_broken_reply(m))
    if bad_recent < 2:
        return msgs, 0
    out, dropped = [], 0
    for m in msgs:
        role = (m.get("role") or "").lower()
        if role == "tool":
            dropped += 1
            continue
        if _is_broken_reply(m):
            dropped += 1
            continue
        out.append(m)
    if not out or all((m.get("role") or "") != "user" for m in out):
        return msgs, 0          # 别把消息表搞成"没有 user" ⇒ Ollama 会 400
    return out, dropped

def strip_length_limits(text: str):
    r"""摘掉 system 里"只能写短"的约束 ⇒ 返回 `(新文本, 摘掉几处)`。

    ⚠️ 安全阀：删完若剩余**不足原文 60%**，判定为误删 ⇒ **整体回滚**（人格不能被吃掉）✓
    """
    if not isinstance(text, str) or len(text) < 8:
        return text, 0
    orig = text
    n = 0
    for pat in _LEN_LIMIT_PATTERNS:
        text, k = re.subn(pat, "", text)
        n += k
    if not n:
        return orig, 0
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < len(orig) * 0.6:
        return orig, 0
    return text, n


def _finish_marks(raw: bytes) -> str:
    r"""从响应尾部找出 `finish_reason` / `done_reason` 的取值（判断"为什么停"）✓"""
    txt = raw.decode("utf-8", "replace")
    bits = []
    for pat, name in ((r'"finish_reason"\s*:\s*"([a-z_]+)"', "finish"),
                      (r'"done_reason"\s*:\s*"([a-z_]+)"', "done")):
        vals = re.findall(pat, txt)
        if vals:
            bits.append(f"{name}={vals[-1]}")
    return ",".join(bits) or "（无 finish_reason/done_reason）"


def note_reply(path: str, text: str, raw: bytes, req=None) -> None:
    r"""记下最后一轮的正文尾部与结尾标记（供 `/__peek_reply` 诊断）✓

    ⚠️ 2026-10-18 补：把**请求侧**的关键参数也带上 —— 用户报「回复被截断」，
    光看响应只能知道 `finish_reason=stop`，看不出"是不是客户端塞了 stop 序列"✓
    """
    try:
        rq = req if isinstance(req, dict) else {}
        opts = rq.get("options") if isinstance(rq.get("options"), dict) else {}
        # ⚠️ 2026-10-18 补：数一下请求里**带了几张图** —— "识别文档"很可能是把文档
        #    当图片发过来（`content:[{type:image_url}...]`），而这个模型**没有视觉**（无 mmproj）
        #    ⇒ Ollama 会忽略图片、模型只看到文字 ⇒ 回答又短又不对 ✓
        _imgs = 0
        for _m in (rq.get("messages") or []):
            if not isinstance(_m, dict):
                continue
            _c = _m.get("content")
            if isinstance(_c, list):
                _imgs += sum(1 for _p in _c
                             if isinstance(_p, dict) and _p.get("type") in ("image_url", "image"))
            if isinstance(_m.get("images"), list):
                _imgs += len(_m["images"])
        LAST_REPLY.update({
            "ip": (LAST_CHAT.get("ip") or ""),
            "ua": (LAST_CHAT.get("ua") or ""),
            "req_images": _imgs,
            "t": time.time(),
            "when": time.strftime("%H:%M:%S"),
            "path": path or "",
            "chars": len(text or ""),
            "text_tail": (text or "")[-300:],
            "text_full": (text or "")[:1500],
            "finish": _finish_marks(raw),
            "got_done": b"[DONE]" in raw,
            "raw_tail": raw[-500:].decode("utf-8", "replace"),
            "msg_tokens": int(LAST_CHAT.get("ptok") or 0),
            "ttft": round(float(LAST_CHAT.get("ttft") or 0.0), 2),
            "total": round(float(LAST_CHAT.get("total") or 0.0), 2),
            # ---- 请求侧（判断"谁让它停的"）----
            # ⚠️ 2026-10-18：把 system 里**和长度有关**的行抽出来（只抽含 字/句/短/长/简/言/段
            #    的行，不落地整份人设）—— 用来定位"是哪条规则让模型只写 10 个字" ✓
            "req_sys_len": sum(len(m.get("content") or "") for m in
                               (rq.get("messages") or [])
                               if isinstance(m, dict) and (m.get("role") or "") == "system"),
            # ⚠️ 2026-10-18（按 GPT 验收意见）：原来这里存了 system 里"含 字/句/短/长…"的
            #    **整行文字**（等于把人格卡片段留在内存里）⇒ 改成**只报数量和有无**，不留正文 ✓
            "req_sys_limit_lines": sum(
                1 for m in (rq.get("messages") or [])
                if isinstance(m, dict) and (m.get("role") or "") == "system"
                for ln in str(m.get("content") or "").splitlines()
                if any(k in ln for k in ("最多", "控制在", "不要答满", "不要空行", "短句"))),
            "req_stop": rq.get("stop"),
            "req_max": rq.get("max_tokens") if rq.get("max_tokens") is not None
                       else opts.get("num_predict"),
            "req_temp": rq.get("temperature") if rq.get("temperature") is not None
                        else opts.get("temperature"),
            "req_tools": len(rq.get("tools") or []),
            "req_reasoning": rq.get("reasoning_effort"),
            "req_stream": rq.get("stream"),
            "req_msgs": len(rq.get("messages") or []) if isinstance(rq.get("messages"), list) else 0,
            # ⚠️ 2026-10-18（按 GPT 验收意见）：**不再保存消息正文**。
            #    原来存了 `req_msgs_full`（完整 messages，可能含 system/人格）和
            #    `req_last_user`（用户那句话）⇒ 等于把人格卡和聊天内容留在内存里。
            #    现在只留**摘要**：角色序列、条数、每条长度、最后一条长度 ✓
            "req_roles": "/".join(str(m.get("role") or "")[:9]
                                  for m in (rq.get("messages") or [])
                                  if isinstance(m, dict))[:160],
            "req_lens": [len(str(m.get("content") or ""))
                         for m in (rq.get("messages") or [])
                         if isinstance(m, dict)][-12:],
        })
        # ⚠️ 2026-10-18：**留最近 5 条**（原来只留 1 条，会被我自己的测试请求冲掉，
        #    用户那边"点一次"就白点了）⇒ `/__peek_reply` 返回 `recent` 列表 ✓
        LAST_REPLIES.append(dict(LAST_REPLY))
        del LAST_REPLIES[:-5]
    except Exception:
        pass


def _ctx_overflow_msg(detail: bytes) -> str:
    r"""上游 400 若是"超窗"（exceed_context_size_error），翻成中文可读的一句话。

    2026-10-18 实测：模型窗口 **65,536 token**（Ollama 原话 `n_ctx: 65536`），
    88,537 字（63,417 token）能过，91,557 字（65,604 token）就 400。
    原文长这样（还是一层套一层的 JSON）：
      {"error":"{\"error\":{\"code\":400,\"message\":\"request (65604 tokens) exceeds ...\"}}"}
    ⚠️ 目的只是**让人看懂**：告诉他是文档太长、超了多少、怎么处理 ✓
    """
    txt = detail.decode("utf-8", "replace")
    if "exceed_context_size_error" not in txt and "exceeds the available context size" not in txt:
        return ""
    n = n_ctx = 0
    # ⚠️ 内层 JSON 是被转义过的（`\"n_prompt_tokens\":126150`）⇒ 正则必须容忍反斜杠 ✓
    m = re.search(r'\\?"n_prompt_tokens\\?"\s*:\s*(\d+)', txt)
    if m:
        n = int(m.group(1))
    m = re.search(r'\\?"n_ctx\\?"\s*:\s*(\d+)', txt)
    if m:
        n_ctx = int(m.group(1))
    if not n_ctx:
        m = re.search(r"context size \((\d+) tokens\)", txt)
        if m:
            n_ctx = int(m.group(1))
    if n and n_ctx:
        return (f"文档/上下文太长：这次需要 {n:,} token，但模型窗口只有 {n_ctx:,} token"
                f"（超了 {n - n_ctx:,}）。请把文档分两次问，或先让它总结前一半再说了剩下的。")
    return "文档/上下文太长，超过模型窗口了。请分两次问，或先让它总结前一半。"

def loaded_models(ttl: float = 3.0) -> list:
    r"""Ollama 里现在加载了哪些模型（`/api/ps`；带 3 秒缓存 —— 面板本来就每 3 秒问一次）。"""
    now = time.time()
    if now - _PS_CACHE["t"] < ttl:
        return _PS_CACHE["v"]
    out: list = []
    try:
        with LOCAL_OPENER.open("http://127.0.0.1:11434/api/ps", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        for m in (data.get("models") or []):
            out.append({"name": (m.get("name") or m.get("model") or ""),
                        "size_gb": round((m.get("size") or 0) / 1073741824, 2),
                        # ⚠️ 2026-10-18 加：`/api/ps` 里有 context_length（实测 65536）——
                        #    "上下文快满了吗"要拿它当分母，不能写死 ✓
                        "context_length": int(m.get("context_length") or 0)})
    except Exception:
        pass
    _PS_CACHE.update({"t": now, "v": out})
    return out


def last_chat_line() -> str:
    r"""给页面用的一行字（**服务端渲染** ⇒ 手机上不跑 JS 的浏览器也看得到）。"""
    if not LAST_CHAT:
        return "网关启动以来<strong>还没收到过</strong>对话请求"
    ago = max(0, int(time.time() - (LAST_CHAT.get("t") or 0)))
    line = (f"{time.strftime('%H:%M:%S', time.localtime(LAST_CHAT.get('t') or 0))}"
            f"（{ago} 秒前）· <code>{(LAST_CHAT.get('model') or '?').replace(':latest', '')}</code>"
            f" · 带 {LAST_CHAT.get('msgs')} 条消息 · 来自 {LAST_CHAT.get('ip')}")
    # ⚠️ 2026-10-18 加：**这一轮到底等了多久**。
    #    起因：用户报「上传文档后只输出一半，或者干脆不出」——
    #    实测 2.9 万字的文档，光把提示词读进去就要 34.9 秒（19856 token / 约 1800 tok/s），
    #    客户端超时（常见 60 秒）一到就把连接掐了 ⇒ 表现就是"流到一半没有"。
    #    所以把「首字几秒 / 总共几秒 / 提示词多少 token / 回复多少字」直接摆到面板上 ✓
    if LAST_CHAT.get("aborted"):
        line += (" · <b style='color:#c00'>⚠️ 客户端中途断开</b>"
                 "（多半是客户端超时，不是网关的问题；把超时调大或减少文档长度）")
    if LAST_CHAT.get("total"):
        line += (f" · <b>首字 {LAST_CHAT.get('ttft', 0.0):.1f}s</b> / 总 {LAST_CHAT['total']:.1f}s"
                 f" · 提示 {LAST_CHAT.get('ptok', 0)} tok · 回复 {LAST_CHAT.get('chars', 0)} 字")
    # 这一轮还在跑时说明一下（否则读者会以为"这一轮只花了上一轮的 1.9 秒"）✓
    if LAST_CHAT.get("pending"):
        line = "⏳（新的一轮还在跑，下面是上一轮的数字）" + line
    return line


# ---- 上下文占用（2026-10-18 加，用户问「快超载了吗」）-------------------------
# 回答"够不够用"需要两个数：**这一轮实际塞进去多少** / **窗口总量**。
# 窗口从 `/api/ps` 的 `context_length` 读（实测 65536，别写死）；用量取模型自己报的
# `prompt_eval_count`（`LAST_CHAT['ptok']`）。
# ⚠️ 流式 `/v1/chat/completions` **不报 usage**（末行就是 `data: [DONE]`）⇒ 那时退回**估算**，
#    估算用实测比值 **0.715 token/字**（2026-10-18 用 12.5K/31K/62K/81K/88K 字实测，
#    0.712~0.715 很稳定；早期写 0.65 会**低估约 10%** ⇒ 面板把 65,604 显示成 59,000 ✗）
#    ⚠️ 别用 `_msg_tokens()` 那套 1.5 tok/字 —— 那是给压缩阈值用的保守值，
#    拿来显示会把 2 万字文档估成 3 万 token，看着像"快满了" ✗
CTX_TOK_PER_CHAR = 0.715
CTX_WARN_PCT = 70.0        # ≥70% 提醒
CTX_CRIT_PCT = 88.0        # ≥88% 快满了（Ollama 会从前面截断）


def ctx_usage() -> dict:
    r"""这一轮用了多少上下文（提示 token / 模型窗口）。返回值给 `/__stats` 用 ✓"""
    total = 0
    try:
        for m in loaded_models():
            if m.get("context_length"):
                total = int(m["context_length"])
                break
    except Exception:
        pass
    total = total or 65536
    used = int(LAST_CHAT.get("ptok") or 0)
    pct = round(used * 100.0 / total, 1) if total else 0.0
    if used <= 0:
        level = "none"
    elif pct >= CTX_CRIT_PCT:
        level = "crit"
    elif pct >= CTX_WARN_PCT:
        level = "warn"
    else:
        level = "ok"
    return {"used": used, "total": total, "pct": pct, "level": level,
            "left": max(0, total - used), "est": bool(LAST_CHAT.get("ptok_est"))}


def upload_hint() -> str:
    r"""页面上那行小字：最近一次上传 + 目录里有多少文件（2026-10-18 加）✓"""
    try:
        files = sorted(CHAT_FILES_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if CHAT_FILES_DIR.exists() else []
        if not files:
            return f"还没有文件。传到 <code>{CHAT_FILES_DIR}</code> 后，最近 5 个会列在下面。"
        last = files[0]
        return (f"最近一次：<code>{last.name}</code>"
                f"（{last.stat().st_size / 1024:.0f} KB，"
                f"{time.strftime('%m-%d %H:%M', time.localtime(last.stat().st_mtime))}）"
                f" · 目录里共 {len(files)} 个文件")
    except Exception:
        return ""

def ctx_line() -> str:
    r"""给页面的一行字（**服务端渲染** ⇒ 手机上不跑 JS 也看得见）✓"""
    c = ctx_usage()
    if not c["used"]:
        return (f"窗口 <b>{c['total']:,}</b> token；最近一轮<strong>没测到</strong>输入量"
                f"（流式 `/v1` 不报 usage ⇒ 用 `/api/chat` 或非流式才有准数）")
    approx = "≈" if c["est"] else ""
    label = {"ok": "还宽裕 ✅",
             "warn": "<b style='color:#c80'>⚠️ 偏高了</b>",
             "crit": "<b style='color:#c00'>⚠️ 快满了，再大就会被从前面截断</b>"}[c["level"]]
    line = (f"这一轮 {approx}<b>{c['used']:,}</b> / 窗口 {c['total']:,} token"
            f"（<b>{c['pct']:.1f}%</b>）· 还剩 {c['left']:,} · {label}")
    if LAST_CHAT.get("pending"):
        line = "⏳（下面是上一轮）" + line
    return line


def model_line() -> str:
    ms = loaded_models()
    if not ms:
        return ("<strong>没加载</strong>（空闲会被自动卸载 —— 正常；下次对话自动重载，"
                "35B 冷启动 20~40 秒）")
    return "、".join(f"<code>{m['name'].replace(':latest', '')}</code>（{m['size_gb']} GB）"
                    for m in ms)


def think_admin_block(h=None) -> str:
    r"""「🧠 思考模式」开关块（服务端渲染 + 表单 ⇒ 手机那个不跑 JS 的浏览器也能点）。

    和授权块一样，**只依赖 HTML 表单**：点一下 = POST `/__think` ⇒ 改内存 + 写
    `_备份\网关思考模式.txt` ⇒ 重启也记得。
    """
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query) if h is not None else {}
    tip = ("✅ 已切换。" if (q.get("ok") or [""])[0] == "think" else "")
    _tnow = temperature()
    _temp_btns = "".join(
        (f"<form method=\"post\" action=\"/__temp\" style=\"margin:0 6px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if v == _tnow else ''}\">"
         f"{v}{' ●' if v == _tnow else ''}</button></form>") for v in TEMPERATURE_CHOICES)
    _strip_now = "on" if strip_limit_on() else "off"
    _strip_btns = "".join(
        (f"<form method=\"post\" action=\"/__strip\" style=\"margin:0 6px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if v == _strip_now else ''}\">"
         f"{'开' if v == 'on' else '关'}{' ●' if v == _strip_now else ''}</button></form>")
        for v in STRIP_CHOICES)
    _cur_ps = current_preset()
    _ps_btns = "".join(
        (f"<form method=\"post\" action=\"/__preset\" style=\"margin:0 6px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if v == _cur_ps else ''}\">"
         f"{PRESET_LABEL[v]}{' ●' if v == _cur_ps else ''}</button></form>")
        for v in PRESET_CHOICES)
    _compat_now = "on" if compat_on() else "off"
    _compat_btns = "".join(
        (f"<form method=\"post\" action=\"/__compat\" style=\"margin:0 6px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if v == _compat_now else ''}\">"
         f"{'开' if v == 'on' else '关'}{' ●' if v == _compat_now else ''}</button></form>")
        for v in COMPAT_CHOICES)
    _cont_now = "on" if continue_on() else "off"
    _cont_btns = "".join(
        (f"<form method=\"post\" action=\"/__cont\" style=\"margin:0 6px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if v == _cont_now else ''}\">"
         f"{'开' if v == 'on' else '关'}{' ●' if v == _cont_now else ''}</button></form>")
        for v in CONTINUE_CHOICES)
    _tools_now = "on" if tools_on() else "off"
    _tools_btns = "".join(
        (f"<form method=\"post\" action=\"/__tools\" style=\"margin:0 6px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"v\" value=\"{v}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if v == _tools_now else ''}\">"
         f"{'保留' if v == 'on' else '剥掉'}{' ●' if v == _tools_now else ''}</button></form>")
        for v in TOOLS_CHOICES)
    _bud = local_budget()
    _bud_btns = "".join(
        (f"<form method=\"post\" action=\"/__budget\" style=\"margin:0 6px 0 0;display:inline\">"
         f"<input type=\"hidden\" name=\"n\" value=\"{n}\">"
         f"<button style=\"{'background:#2f6df6;color:#fff;border-color:#2f6df6' if n == _bud else ''}\">"
         f"{n}{' ●' if n == _bud else ''}</button></form>") for n in LOCAL_BUDGET_CHOICES)
    if THINK_MODE == "local" and _LOCAL_FALLBACK:
        tip += (f"<br>⚠️ <b>本地思考上次没跑成</b>：{_LOCAL_FALLBACK}<br>"
                f"（想让它真的思考 ⇒ 用会思考的模型，如 35B；小模型不会思考 ✓）")
    btns = []
    for mode in THINK_MODES:
        mark = " ●" if mode == THINK_MODE else ""
        style = ("background:#2f6df6;color:#fff;border-color:#2f6df6" if mode == THINK_MODE else "")
        btns.append(f"<form method=\"post\" action=\"/__think\" style=\"margin:0;display:inline\">"
                    f"<input type=\"hidden\" name=\"mode\" value=\"{mode}\">"
                    f"<button style=\"{style}\">{mode}{mark}</button></form>")
    _warm_now = warm_model()
    _warm_loaded = [m["name"] for m in loaded_models()]
    _warm_btns = []
    for name in (list_models() or [_warm_now]):
        mark = " ●" if name == _warm_now else ""
        style = ("background:#2f6df6;color:#fff;border-color:#2f6df6" if name == _warm_now else "")
        _warm_btns.append(f"<form method=\"post\" action=\"/__warm\" style=\"margin:0 6px 0 0;display:inline\">"
                    f"<input type=\"hidden\" name=\"model\" value=\"{name}\">"
                    f"<button style=\"{style}\">{name}{mark}</button></form>")
    if _WARM_STATE["busy"]:
        _warm_line = (f"⏳ 正在预热 <b>{_WARM_STATE['model']}</b>…"
                      f"（{int(time.time()-_WARM_STATE['t'])} 秒了，别关窗口）")
    elif _WARM_STATE["ok"] is True:
        _warm_line = f"✅ 预热完成（用时 {_WARM_STATE['secs']:.0f} 秒，保温 {LOCAL_KEEP_ALIVE or '30m'}）"
    elif _WARM_STATE["ok"] is False:
        _warm_line = "⚠️ 上次预热失败（看日志 `_备份\\gw_boot_err.txt`）"
    else:
        _warm_line = "（还没在网页上预热过）"
    _warm_html = (f"<hr style=\"border:0;border-top:1px solid #333;margin:8px 0\">"
                  f"<b>🔥 开机预热用哪个模型</b>（**只预热选中的那一个**；点别的 = 改选并立刻预热）<br>"
                  f"当前选中：<b>{_warm_now}</b><br>"
                  f"现在已加载：{'、'.join(_warm_loaded) if _warm_loaded else '（没有）'}<br>"
                  f"<div style=\"margin-top:6px\">{''.join(_warm_btns)}</div>"
                  f"<div class=\"hint\">{_warm_line}<br>"
                  f"· 选择会写进 `_备份\\预热模型.txt` ⇒ 下次双击启动脚本就预热它 ✓<br>"
                  f"· · 想改预热时长：启动脚本里的 `OLLAMA_KEEP_ALIVE`（现在 30m）</div>")
    _rec = "开" if THOUGHT_REC else "关"
    _rec_btn = ("<form method=\"post\" action=\"/__thinklog\" style=\"margin:0;display:inline\">"
                "<input type=\"hidden\" name=\"act\" value=\"%s\">"
                "<button>%s</button></form>") % (
                    "rec_off" if THOUGHT_REC else "rec_on",
                    "⏸ 不记录过程" if THOUGHT_REC else "▶ 开始记录过程")
    _peek_btn = ("<a href=\"/__peek?n=1\" style=\"display:inline-block;margin:0 0 0 6px;"
                 "padding:3px 9px;border:1px solid #555;border-radius:6px;text-decoration:none;"
                 "color:#6cf\">👀 看最近一条思考</a>")
    _log_btns = ("<form method=\"post\" action=\"/__thinklog\" style=\"margin:0;display:inline\">"
                 "<input type=\"hidden\" name=\"act\" value=\"clear\">"
                 "<button>🧹 清空内容</button></form>"
                 "<form method=\"post\" action=\"/__thinklog\" style=\"margin:0 0 0 6px;display:inline\">"
                 "<input type=\"hidden\" name=\"act\" value=\"delete\">"
                 "<button>🗑 删除文件</button></form>")
    return (f"<div class=\"card\"><div class=\"lbl\">🧠 思考模式</div>"
            f"<div style=\"margin:6px 0\">{' '.join(btns)}</div>"
            f"<div class=\"hint\">当前：<b>{THINK_MODE}</b> —— {THINK_LABEL.get(THINK_MODE, '')}<br>"
            f"· 切 <b>off</b>/<b>on</b> = 全局说了算（客户端自己的思考参数会被忽略）<br>"
            f"· 切 <b>auto</b> = 由客户端决定（手机 App 自带思考设置时用它）<br>"
            f"· 切 <b>local</b> = 先在本机想一遍，<b>过程只写本地日志、不进回复</b>"
            f"（两段式；只支持非流式客户端）。过程写 `_备份\\思考过程.log`，"
            f"超过 2 MB 自动只留最近的；**不想落盘**就用 `--no-thought-log` 启动<br>"
            f"· 第一轮思考预算：现在 <b>{_bud}</b>（实测 400≈12 秒 / 800≈21 秒 / 1600≈26 秒；"
            f"App 超时 20 秒）<br>"
            f"<div style=\"margin:6px 0\">{_bud_btns}</div>"
            f"· 🌡 温度：现在 <b>{temperature()}</b>"
            f"（<b>整理表格/抄数据点 0.2</b>；日常聊天用 auto ✓。注意：**不影响 AstrBot**，"
            f"它直连 Ollama）<br>"
            f"<div style=\"margin:6px 0\">{_temp_btns}</div>"
            f"· 🎛 **一键档位**：现在 <b>{PRESET_LABEL.get(_cur_ps, '自定义')}</b>"
            f"（💬 聊天档 = 工具剥掉 + 兼容模式开 + 去记号 + 压空行；"
            f"🛠 干活档 = 工具保留 + 兼容模式关 + 原样 markdown）<br>"
            f"<div style=\"margin:6px 0\">{_ps_btns}</div>"
            f"· ⚙️ **独立开关**（每个都能单独点，互不牵连）：<br>"
            + switches_html() +
            f"<div class=\"hint\" style=\"margin-top:4px\">"
            f"「🎨 去记号」「↩️ 压空行」**只在「🧩 兼容模式 = 开」时生效**"
            f"（因为只有兼容模式会先把整段收回来洗）；兼容模式关着的时候，"
            f"回复是按流式原样转发的，没有任何改写 ✓</div>"
            f"· 顺手同步 AstrBot：<b>{astrbot_think_state()}</b>"
            f"（off/on 会改它，auto 不动它；它**启动时读配置** ⇒ 要重启 AstrBot 才生效）<br>"
            + ("⚠️ <b>AstrBot 正在运行</b> —— 在这里切 off/on 很可能被它**覆盖**："
               "它自己会写那份配置。AstrBot 那条线请去<b>它的界面</b>里改「关闭思考模式」"
               "（勾上 = 关思考），或者先把 AstrBot 关掉再点这里。<br>"
               if astrbot_running() else
               "✅ AstrBot 没在运行 ⇒ 在这里切会正常写进它的配置，下次启动生效。<br>")
            + f"{tip}"
            f"<hr style=\"border:0;border-top:1px solid #333;margin:8px 0\">"
            f"<b>🧹 思考过程（只在本机，不上网页）</b><br>"
            f"记录：<b>{_rec}</b> ｜ 现在：{thought_log_info()}<br>"
            f"<div style=\"margin-top:6px\">{_rec_btn} {_log_btns} {_peek_btn}</div>"
            f"{_warm_html}"
            f"</div></div>")


def access_admin_block(h) -> str:
    r""""访问授权"管理块的 HTML（给自带网页 / `/plain` 共用）。

    **服务端渲染、按钮都是表单** —— 用户那个 vivo 浏览器会删掉内联脚本，
    所以这块功能一点 JS 都不能依赖。

    显示：当前入网码 +「📱 生成手机授权码」+ 已授权设备表（IP/浏览器/首次/最后/解除）+ 解除全部。
    """
    def esc(s) -> str:
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query) if h is not None else {}
    msg = {"1": "✅ 这台设备已授权，以后不用再输。",
           "newcode": "🔁 已生成新入网码（**已授权的设备不受影响**）。",
           "revoked": "✅ 已解除那台设备。",
           "all": "✅ 已解除全部设备（各设备下次打开会重新要码）。",
           "notfound": "⚠️ 那台设备已经不在了（可能刚被解除）。"}.get((q.get("ok") or [""])[0])
    try:
        devs = sessions_list()
    except Exception:
        devs = []

    rows = []
    for s in devs:
        f = time.strftime("%m-%d %H:%M", time.localtime(s.get("first") or 0))
        l = time.strftime("%m-%d %H:%M", time.localtime(s.get("last") or 0))
        rows.append(
            "<tr>"
            f"<td>{esc(s.get('ip'))}</td>"
            f"<td class='ua'>{esc((s.get('ua') or '')[:52])}</td>"
            f"<td>{f}</td><td>{l}</td>"
            "<td><form method='post' action='/__revoke' style='margin:0'>"
            f"<input type='hidden' name='tok' value='{esc(s.get('token'))}'>"
            "<button type='submit' class='mini'>解除</button></form></td>"
            "</tr>")
    table = ("<table class='dev'><tr><th>IP</th><th>客户端</th><th>首次</th><th>最后活动</th><th></th></tr>"
             + "".join(rows) + "</table>") if rows else \
            "<div class='hint'>还没有别的设备授权过（本机不算）。</div>"

    return f"""{'<div class="hint" style="color:#9ff0b8">' + msg + '</div>' if msg else ''}
<div class="row" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
  <span class="hint">入网授权码</span>
  <span class="code">{esc(access_code())}</span>
  <form method="post" action="/__newcode" style="margin:0">
    <button type="submit" class="mini">📱 生成手机授权码</button>
  </form>
  <a class="mini" href="/__auth?out=1" style="text-decoration:none;padding:3px 9px;
     border:1px solid #3a4353;border-radius:6px;color:#e6e6e6">退出授权</a>
</div>
<div class="hint" style="margin-top:6px">
  手机第一次打开网页输上面这个码，之后**长期有效**（种一年 cookie）。
  换新码只影响还没进门的设备；要踢人用下面的「解除」。
</div>
<div style="margin-top:8px"><b>已授权设备（{len(devs)}）</b>
  <form method="post" action="/__revoke" style="margin:6px 0 0;display:inline">
    <input type="hidden" name="all" value="1">
    <button type="submit" class="mini">解除全部设备</button>
  </form>
</div>
{table}"""


def access_page(err: str = "", locked: int = 0) -> str:
    r"""没授权时看到的页面：**只有输入框**，不含任何模型/人格/资源数据。"""
    if locked > 0:
        tip = f'<p class="warn">输错太多次，请等 <b>{locked // 60 + 1} 分钟</b>后再试。</p>'
    elif err:
        tip = f'<p class="warn">{err}</p>'
    else:
        tip = ('<p class="hint">这台电脑上的网关只对已授权的设备开放。<br>'
               '授权码在<b>电脑</b>上查看：<code>E:\\本地ai\\获取API密钥.bat</code>，'
               '或看网关窗口第一屏。</p>')
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>需要授权</title>
<style>
 body{{font:16px/1.7 system-ui,'Microsoft YaHei',sans-serif;background:#0f1115;color:#e6e6e6;
      margin:0;padding:28px 18px;display:flex;justify-content:center}}
 .box{{width:min(420px,100%);background:#161a22;border:1px solid #262b36;border-radius:12px;padding:20px}}
 h1{{font-size:19px;margin:0 0 4px}} .sub{{color:#9aa4b2;font-size:13px;margin:0 0 16px}}
 input{{width:100%;box-sizing:border-box;font-size:22px;letter-spacing:6px;text-align:center;
        padding:12px;border-radius:9px;border:1px solid #333a48;background:#0f1115;color:#fff}}
 button{{width:100%;margin-top:12px;padding:12px;border:0;border-radius:9px;background:#2f6df6;
        color:#fff;font-size:16px;cursor:pointer}}
 .warn{{color:#ff9a9a}} .hint{{color:#9aa4b2;font-size:13px}}
 code{{background:#0f1115;border:1px solid #2a3140;border-radius:5px;padding:1px 5px;font-size:12px}}
</style></head><body><div class="box">
<h1>🔒 需要授权</h1>
<p class="sub">局域网访问 · 输一次就长期有效</p>
{tip}
<form method="post" action="/__auth">
  <input name="code" inputmode="numeric" autocomplete="one-time-code" placeholder="授权码" autofocus>
  <button type="submit">进入</button>
</form>
</div></body></html>"""


def render_page(h=None) -> str:
    r"""把当前占用数字**服务端渲染**进页面。

    为什么（2026-10-05）：用户手机上的浏览器**不执行内联脚本**，前端填的数字永远不出现。
    服务端直接写进 HTML，再靠 `<noscript>` 里的 `meta refresh` 每 5 秒重载一次 ——
    **"脚本被拦掉"也能看到会动的数字**。JS 正常时这些值会被前端覆盖，互不冲突。
    """
    try:
        st = sys_stats()
    except Exception:
        st = {}
    cpu = st.get("cpu_pct")
    mem = st.get("mem") or {}
    g = (st.get("gpu") or [{}])[0]

    def bar(p):
        return "" if p is None else f"width:{max(0.0, min(100.0, p)):.1f}%;background:#2f6df6"

    rep = {
        "<!--SRV:ver-->": PAGE_VER,
        "<!--SRV:cpu-->": "读取中…" if cpu is None else f"{cpu:.1f}%",
        "<!--SRV:cpu_w-->": bar(cpu),
        "<!--SRV:mem-->": "" if not mem else
            f"{mem['used_gb']} / {mem['total_gb']} GB（{mem['pct']}%）",
        "<!--SRV:mem_w-->": bar(mem.get("pct")),
        "<!--SRV:vram-->": "" if not g.get("mem_total_mb") else
            f"{g['mem_used_mb'] / 1024:.2f} / {g['mem_total_mb'] / 1024:.2f} GB",
        "<!--SRV:vram_w-->": bar(None if not g.get("mem_total_mb")
                                 else g["mem_used_mb"] / g["mem_total_mb"] * 100),
        "<!--SRV:gpu-->": "" if not g else f"{g.get('util')}%　{g.get('temp_c')}°C",
        "<!--SRV:gpu_w-->": bar(g.get("util")),
        # 「模型是否加载」+「最近一次对话」（2026-10-06 傍晚加，见 LAST_CHAT 那段注释）
        "<!--SRV:model-->": model_line(),
        "<!--SRV:lastchat-->": last_chat_line(),
        "<!--SRV:ctx-->": ctx_line(),
        "<!--SRV:upload-->": upload_hint(),
    }
    # 手机 App 安装包（自己编译那份）的信息；没有就把整张卡片藏掉
    # （服务端渲染 ⇒ 浏览器不跑 JS 也生效，`<!--SRV:apk-card-->` 是 card 的 style）
    _apk = apk_info()
    if _apk:
        rep["<!--SRV:apk-->"] = (f"{_apk['name']} · {_apk['size'] / 1048576:.1f} MB · "
                                 f"{time.strftime('%m-%d %H:%M', time.localtime(_apk['mtime']))}")
        # ⚠️ 链接**必须带 .apk 后缀**（2026-10-06 踩到：只给 /apk 时，国产浏览器的下载器
        # 会拿 URL 最后一段当文件名 ⇒ 存成没有后缀的 "apk" ⇒ 手机报"不支持应用类型"）
        rep["<!--SRV:apk-url-->"] = "/" + urllib.parse.quote(_apk["name"])
        rep["<!--SRV:apk-zip-url-->"] = "/" + urllib.parse.quote(_apk["name"]) + ".zip"
        rep["<!--SRV:apk-card-->"] = ""
    else:
        rep["<!--SRV:apk-->"] = "（还没放安装包）"
        rep["<!--SRV:apk-url-->"] = rep["<!--SRV:apk-zip-url-->"] = "/apk"
        rep["<!--SRV:apk-card-->"] = "display:none"
    # 访问授权（2026-10-06）：整块管理界面**服务端渲染**（手机浏览器会删脚本）
    try:
        if h is not None and not getattr(h.server, "open_access", False):
            rep["<!--SRV:access-->"] = access_admin_block(h) + think_admin_block(h)
            rep["<!--SRV:access-card-->"] = ""
        else:
            rep["<!--SRV:access-->"] = ""
            rep["<!--SRV:access-card-->"] = "display:none"
    except Exception:
        rep["<!--SRV:access-->"] = ""
        rep["<!--SRV:access-card-->"] = "display:none"
    out = PAGE
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


def kill_gateway_later(delay: float = 5.0) -> None:
    r"""**延迟结束网关自己**（以及任何别的 `ollama_gateway.py` 实例）。

    用户 2026-10-05 的要求原话："我点停止模型，那个局域网那个也停了吧，
    就是停止模型 5 秒后关闭关于助手的所有进程"。

    为什么延迟 5 秒：HTTP 响应要先发出去，页面才能把"已停止"显示给人看；
    立刻 `os._exit` 的话浏览器只会看到连接被重置（看起来像"点了没反应"）。
    为什么连**别的实例**一起杀：重复启动留下的实例会继续占着端口。

    退回旧行为（点了只停模型、网关留着）：启动加 `--keep-gateway`。
    """
    me = os.getpid()

    def go():
        t0 = time.time()
        try:
            ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object {{ $_.CommandLine -like '*ollama_gateway*' "
                  "-and $_.ProcessId -ne {me} }} | "
                  "ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}").format(me=me)
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=40)
        except Exception:
            pass                    # 杀别的实例失败也不能挡住"关掉自己"
        # ⚠️ 睡到"从收到请求算起满 delay 秒"为止 —— 起 PowerShell 要 1~2 秒，
        #    如果直接 sleep(delay) 再退出，实测会变成 **7 秒**（页面上写着 5 秒，对不上）。
        time.sleep(max(0.0, delay - (time.time() - t0)))
        os._exit(0)                 # 自己是最后一个

    threading.Thread(target=go, daemon=True, name="kill-gateway").start()


def stop_local-assistant(dry: bool = False) -> list:
    r"""把"助手"停下来 —— 干的事**和 `停止模型.bat` 一模一样**（三步）。

    顺序和理由照抄那个 .bat（`02` 坑 17 有实测）：
      1. `ollama.exe` —— 停推理服务，**释放显存**
      2. `llama-server.exe` **带 /T** —— `ollama.exe` 被杀后它拉起的 llama-server **不会跟着死**，
         实测见过两个孤儿占 7.5 GB 内存，把 15.7 GB 吃到只剩 2 GB（`02` 坑 17）
      3. `AstrBot.exe` **带 /T** —— 连它的后端 python 子进程一起结束

    **网关自己**由 `kill_gateway_later()` 延迟 5 秒结束（用户要"所有进程都关"）——
    这样这次 HTTP 响应能先把结果送到页面手上。
    ⚠️ 启动加 `--keep-gateway` 可以保留旧行为（只停模型，网关留着）。

    `dry=True`：只**查**哪些进程在跑、不杀（测试和页面预览用）。
    """
    steps = [("Ollama 推理服务（释放显存）", "ollama.exe", False),
             ("llama-server 残留（释放内存）", "llama-server.exe", True),
             ("AstrBot", "AstrBot.exe", True)]
    out = []
    for what, image, tree in steps:
        try:
            if dry:
                q = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                                   capture_output=True, text=True, errors="replace",
                                   timeout=15)
                running = image.lower() in (q.stdout or "").lower()
                out.append({"what": what,
                            "result": "在跑（停止时会杀掉）" if running else "没在跑"})
                continue
            cmd = ["taskkill", "/F"] + (["/T"] if tree else []) + ["/IM", image]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               errors="replace", timeout=15)
            out.append({"what": what,
                        "result": "已停止" if r.returncode == 0 else "本来就没在跑"})
        except Exception as e:
            out.append({"what": what, "result": f"{type(e).__name__}: {e}"})
    return out


# ---------------------------------------------------------------- 人格（自带网页用，只读）
def list_personas() -> list:
    r"""列出 `personas\*.txt`：**只有名字和字数**（正文另外取，见 `read_persona`）。

    自带网页那个"人格"下拉用它。名字/大小不算敏感，局域网里谁打开网页都能看；
    **正文**（敏感的部分）走 `/__persona`，要本机、或者带上正确的 Key。
    """
    out = []
    if not PERSONAS_DIR.is_dir():
        return out
    active = ""
    try:
        active = (PERSONAS_DIR / ".active").read_text(encoding="utf-8").strip()
    except Exception:
        pass
    for p in sorted(PERSONAS_DIR.glob("*.txt")):
        try:
            chars = len(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            chars = 0
        out.append({"name": p.stem, "chars": chars, "active": p.stem == active})
    return out


def read_persona(name: str):
    r"""读一份人格正文；名字不合法或不存在 → None。

    ⚠️ 名字只当"纯文件名"用：挡掉 `..`、`\`、`/`、`.` 之类，
    否则 `?name=../../settings` 就能读别人的文件。
    """
    name = (name or "").strip()
    if not name or any(c in name for c in "\\/.:*?\"<>|"):
        return None
    f = PERSONAS_DIR / f"{name}.txt"
    if not f.is_file():
        return None
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return {"name": name, "chars": len(text), "content": text}


def _split_multimodal(parts: list) -> tuple:
    r"""把 OpenAI 那种 `content` 数组拆成 `(纯文本, 图片 base64 列表)`。

    **为什么需要它（2026-10-05 晚，用户问"可以视觉模型吗"）**：
    `_tidy()` 原来把数组 content 直接 `" ".join(p["text"])` —— 于是
    `{"type":"image_url", ...}` 那一段**被静默丢掉**：视觉请求过网关就变成"纯文字"，
    用户看到的就是"模型看不懂图"。
    Ollama 的原生接口（`/api/chat`）要的是 `images: [base64…]`（**不带** `data:image/...;base64,` 前缀），
    而 OpenAI 兼容接口（`/v1`）本来就吃数组 —— 所以这里只负责拆，交给调用方决定用哪种形状。
    """
    text_parts, images = [], []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "text" or ("text" in p and t is None):
            v = p.get("text")
            if isinstance(v, str):
                text_parts.append(v)
        elif t in ("image_url", "image"):
            u = p.get("image_url")
            u = u.get("url") if isinstance(u, dict) else (u if isinstance(u, str) else None)
            if not isinstance(u, str):
                continue
            if u.startswith("data:") and ";base64," in u:
                images.append(u.split(";base64,", 1)[1])
            elif u.startswith("http"):
                images.append(u)          # 交给 Ollama 自己抓（能不能成功取决于它）
    return " ".join(text_parts), images


def _content_key(c):
    r"""给"去重"用的可比较键：字符串直接用，数组用它的 JSON（视觉消息原来比不了）。"""
    if isinstance(c, str):
        return c
    return json.dumps(c, ensure_ascii=False, sort_keys=True)


def _tidy(msgs: list, path: str = "") -> list:
    r"""把消息表收拾成"Ollama 肯收、模型不照抄"的形状（2026-10-05 实测加）。

    两个真原因，都在手机上踩到了：

    1. **连着两条一模一样的消息**（尤其 assistant）会让模型**照着重复一遍**。
       手机那条会话里就出现了 `[8][9]`、`[17][18]` 两对完全相同的回复 ——
       因为客户端会把它自己那份 assistant 历史也发过来，而网关又在后面补了一条。
       用户报的"一句话重复发两遍"就是这个。
    2. **结尾有 ≥2 条 assistant 会被 Ollama 直接 400**，实测原文：
       `Cannot have 2 or more assistant messages at the end of the list.`
       （手机 12:37:28~33 连着 **6 次 400** 就是它 —— 客户端那次的消息表以
       `assistant, system` 结尾，拼装后尾巴上留了不止一条 assistant。）
       另外实测 `content: null` 也是硬 400（`invalid message content type: <nil>`）。

    做三件事：丢掉角色不合法的、丢掉 content 空/非字符串（**数组除外，见下**）的、
    去掉"连着完全一样"的那条，并保证**结尾只留一条 assistant**。
    其余字段（name / tool_calls / images …）原样保留。

    ⚠️ **视觉（多模态）消息必须原样保留**（2026-10-05 晚加，用户问"可以视觉模型吗"）：
    `content` 是数组时**以前会被拍平成纯文本**，图片就被丢了。现在按接口分开处理：
      · `/v1*`（OpenAI 兼容）：**数组原样留着** —— 那本来就是 OpenAI 的多模态写法，Ollama 认；
      · `/api/chat`（Ollama 原生）：文字拍平成字符串，图片挪进 `images: [base64…]`。
    """
    out = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "").lower()
        # ⚠️ 2026-10-14 改：这一行原来写的是「未知角色（tool / function…）一律丢：这个网关
        #    不支持工具」。后来实测证明**模型和 Ollama 都支持工具调用**（`/api/chat`、`/v1`
        #    都正确返回 tool_calls，流式 SSE 增量里也带），唯一拦路的就是这一行：
        #    它把 `role:"tool"`（工具**结果**）丢掉 ⇒ "模型发起调用 → 客户端执行 → 回传结果"
        #    这条链**断在网关**，模型看不到结果、只能猜或触发自动搜索。
        #    实测证据：日志里 `msgs=3 roles=user,assistant,tool ⇒ 消息表3→1`，最终回答里的
        #    数据跟工具返回的对不上 ✓
        #    现在放行 `tool`；`function`（老式 OpenAI 写法）仍丢 —— Ollama 模板不认它，
        #    留着只会 400 ✓
        if role not in ("system", "user", "assistant", "tool"):
            continue
        c = m.get("content")
        if isinstance(c, list):                    # 客户端把 content 发成数组（多模态）
            text, images = _split_multimodal(c)
            m = {**m, "role": role}
            if path.startswith("/v1"):
                m["content"] = c                   # 原样保留（OpenAI 多模态）
            else:
                m["content"] = text
                if images:
                    m["images"] = list(m.get("images") or []) + images
            if not _msg_text(m).strip() and not m.get("images"):
                # 数组里既没文字也没图片 —— 这种空消息留着只会占位
                if not isinstance(m.get("content"), str) or not m["content"]:
                    continue
        elif not isinstance(c, str):
            # content 为 `None` 是硬 400（实测 `invalid message content type: <nil>`）；
            # 但**空字符串要留着** —— 有的客户端用空消息表示"继续"，丢掉它反而会
            # 让消息表变成"没有 user"，撞上模板的 `No user query found in messages.`
            #
            # ⚠️ 2026-10-14 例外：assistant 的**工具调用消息**按 OpenAI 规范就是
            #    `content: null` + `tool_calls` —— 必须留着，否则模型不知道它自己调用过
            #    什么工具、参数是什么（回传结果时就对不上了）✓
            if c is None and m.get("tool_calls"):
                out.append({**m, "role": role})
            continue
        if (out and out[-1].get("role") == role
                and _content_key(out[-1].get("content")) == _content_key(m.get("content"))
                and not m.get("images")
                and role != "tool" and not m.get("tool_calls")):
            continue          # ⚠️ 连着两条完全一样 → 只留一条（"重复"的根就在这）
                              #    但 `tool` 结果 / 带 tool_calls 的消息**不参与去重** ——
                              #    两次工具调用可能返回一模一样的文本，去掉一条会让模型
                              #    以为只调了一次 ✓
        out.append({**m, "role": role})
    tail = len(out)
    while tail > 0 and out[tail - 1].get("role") == "assistant":
        tail -= 1
    if len(out) - tail >= 2:                      # 结尾 ≥2 条 assistant → Ollama 400
        del out[tail + 1:]
    return out


class ReqLog:
    r"""把每个请求的**形状**记一行到文件（默认 `_备份\gateway.log`）。

    为什么加它（2026-10-05）：用户报"手机端输出一串代码"，而网关以前**只有控制台 stderr** ——
    窗口一关、进程一重启，那次请求的**路径 / 格式 / User-Agent** 就永久没了。
    前面一轮排查正是卡在这里（"手机那条链路一次都没看到过"，只能靠猜）。
    有了文件日志，"让手机再发一句"就能直接看出它请求的是 `/v1/chat/completions`
    还是 `/api/chat`、地址是不是填错了 —— 那两条 404 就是"屏幕上出现一串代码"最常见的来源。

    ⚠️ 两条纪律（这份日志是**可以直接贴给别人看**的）：
      1. **绝不记口令内容** —— 只记形状，如 `Key=Authorization Bearer(len=32)` / `Key=无`；
      2. **不记消息正文** —— 只记条数/角色/有没有 system/是否流式；**搜索词会记**
         （那是排错的关键：能立刻分辨"是不是只有加了「搜」才这样"）。

    超过 MAX 自动轮转一份 `.1`（只留一份，省地方）。
    """
    MAX = 5 * 1024 * 1024

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, line: str) -> None:
        if not self.path:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.lock:
                if self.path.exists() and self.path.stat().st_size > self.MAX:
                    bak = self.path.with_name(self.path.name + ".1")
                    if bak.exists():
                        bak.unlink()
                    self.path.rename(bak)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(f"{stamp} | {line}\n")
        except Exception:
            pass          # 日志写不进去也不能影响转发（磁盘满/权限）


# ---------------------------------------------------------------- 会话记忆 + 滚动摘要
#
# 为什么加（2026-10-05）：网关转发的是**裸模型**，而 OpenAI/Ollama 的客户端**只发当轮**，
# 于是"聊久了就忘了前面" —— 长期角色扮演里最要命（早期定下的剧情说没就没）。
# 参考《上下文压缩》：滑动窗口会丢长期信息，**摘要式压缩**才是正解，且要配合
# Recency Bias（近期保原文、早期压成摘要）。
#
# 做法：
#   · 按会话（默认按来源 IP）记住**最近的 messages** 和一段**滚动摘要**；
#   · 每轮把 `摘要 + 最近几轮` 一起发给模型（摘要永远排在最前，作为 system 消息）；
#   · 上一轮的 `prompt_eval_count`（Ollama 真报的输入 token 数，最准）超过阈值时，
#     调一个**小模型**把"摘要 + 被挤出去的那些轮"重写成新摘要（旧的摘要也一起并进去，
#     所以记忆是滚动的、不会因为多次压缩而丢）。
#   · 摘要写在 `_备份\gateway_sessions.json`（`_备份\` 已 gitignore）。
#
# ⚠️ 摘要提示词里**明确禁编造**，并要求保留"剧情推进 / 人物状态 / 承诺与设定 / 情绪基调"。
SESSION_DEFAULT = "ip"          # 会话键：ip（默认）或 header:<名字>（客户端可用头区分会话）
# 摘要模型解析不出来时的兜底（正常情况用"跟当前会话同一个模型"，见 --compress-model）
DEFAULT_COMPRESS_MODEL = "local-assistant-9b:latest"
COMPRESS_PROMPT = (
    "你是对话记录的压缩器。把下面的对话历史压缩成一段**简洁但信息完整**的中文摘要，"
    "供另一个 AI 继续对话时当作长期记忆使用。\n"
    "**必须保留**：\n"
    "1. 剧情推进到哪一步（发生了什么、做到哪里、停在什么动作上）；\n"
    "2. 人物状态（身体状态、情绪、态度变化、关系进展）；\n"
    "3. 双方说过的关键话、约定、称呼、偏好、设定（尤其「我说过 / 我喜欢 / 不要」这类）；\n"
    "4. 未完成的线头（还欠着什么、下一步该接哪里）。\n"
    "**规则**：只写历史里**真实出现过**的内容；**绝对不许编造**没发生的事、没说过的话、"
    "没出现的人；不确定就略过。用第三人称、条目式、别写对话原文，控制在 600 字以内。\n"
    "如果前面已经有一段【旧摘要】，把它和下面的新对话**合并成一段**新摘要（别丢掉旧摘要里的信息）。"
)


def _pieces(d) -> list:
    r"""从一个 JSON 分片里取出"模型说了什么"（Ollama 与 OpenAI 两种形态都认）。

    ⚠️ 2026-10-05 踩过：第一版**只存了 user、没存 assistant**，于是记忆里历史是残缺的
    （连着两条用户话、没有模型回过什么），压缩出来的摘要也就缺了"AI 说了什么"那一半。
      · Ollama：流式每行 `{"message":{"content":"…"}}`；非流式一个大 JSON；
      · OpenAI：`choices[0].message.content`（含流式分片 `choices[0].delta.content`）。
    """
    out = []
    m = d.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), str):
        out.append(m["content"])
    ch = d.get("choices")
    if isinstance(ch, list) and ch:
        c0 = ch[0] if isinstance(ch[0], dict) else {}
        msg = c0.get("message") if isinstance(c0.get("message"), dict) else {}
        if isinstance(msg.get("content"), str):
            out.append(msg["content"])
        delta = c0.get("delta") if isinstance(c0.get("delta"), dict) else {}
        if isinstance(delta.get("content"), str):
            out.append(delta["content"])
    return out


def _assistant_text(raw: bytes) -> str:
    r"""从**一整段**响应里抽出模型这一轮说了什么（非流式走这里；流式走 `_ReplyCollector`）。"""
    text = raw.decode("utf-8", "replace")
    parts = []
    whole = None
    try:
        whole = json.loads(text.strip())
    except Exception:
        whole = None
    if isinstance(whole, dict):                 # 非流式：整体一个对象
        parts += _pieces(whole)
    else:                                       # 流式：逐行
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):        # OpenAI SSE 分片
                line = line[5:].strip()
            if not line.startswith("{"):
                continue
            try:
                parts += _pieces(json.loads(line))
            except Exception:
                continue
    return "".join(parts).strip()


class _ReplyCollector:
    r"""边收边抽"模型这轮说了什么" —— 不缓存整个响应，也不受 64 KB 限制。

    ⚠️ 2026-10-05 **实测**踩到（这就是"记忆丢开头"那个 bug）：原来只在"响应尾部 64 KB"
    里抽正文 —— 而那 64 KB 本来是留给 `_usage_from_tail` 解析 token 数的。Ollama 流式是
    **一个字一个 JSON 行**（每字约 60~83 B）⇒ 64 KB 只装得下约 800 字。实测数据：

        回复   2 字 → 记忆存    2 字 ✅ ；423 字 → 423 字 ✅ ；
        回复 1154 字 → 记忆只存 803 字，**开头 351 字被切掉** ❌

    而记忆是给下一轮当"长期记忆"用的，**开头恰恰最重要**（场景/动作的起点在那里）。

    做法：按行切（流式每行一个完整 JSON），只对**完整行** `json.loads`，把 content 分片
    拼起来；单行上限 1 MB（畸形响应保护）；`finish()` 处理最后没有换行的那一行
    —— 非流式那种"整段一个大 JSON"正是从这里出去。
    """

    LINE_MAX = 1 << 20

    def __init__(self):
        self._buf = ""
        self._parts = []

    def feed(self, chunk: bytes) -> None:
        self._buf += chunk.decode("utf-8", "replace")
        if "\n" not in self._buf:
            if len(self._buf) > self.LINE_MAX:      # 畸形：一行装不下 → 丢掉，别吃内存
                self._buf = ""
            return
        *lines, self._buf = self._buf.split("\n")
        for ln in lines:
            self._line(ln)

    def _line(self, ln: str) -> None:
        ln = ln.strip()
        if ln.startswith("data:"):                  # OpenAI SSE 分片
            ln = ln[5:].strip()
        if not ln.startswith("{"):
            return
        try:
            self._parts += _pieces(json.loads(ln))
        except Exception:
            return

    def finish(self) -> str:
        if self._buf.strip():
            self._line(self._buf)
            self._buf = ""
        return "".join(self._parts).strip()


def _split_openai_reply(b: bytes):
    r"""从一条非流式 `/v1/chat/completions` 响应里取出（正文, 推理）。"""
    try:
        d = json.loads(b.decode("utf-8", "replace"))
    except Exception:
        return "", ""
    m = ((d.get("choices") or [{}])[0].get("message") or {})
    return (m.get("content") or ""), (m.get("reasoning") or m.get("reasoning_content") or "")


def _replace_openai_content(b: bytes, content: str) -> bytes:
    r"""把响应里的正文换成另一段（空回复兜底用）。"""
    try:
        d = json.loads(b.decode("utf-8", "replace"))
        ch = (d.get("choices") or [{}])[0]
        msg = ch.get("message")
        msg = msg if isinstance(msg, dict) else {}
        msg["content"] = content
        ch["message"] = msg
        if ch.get("finish_reason") in (None, "length"):
            ch["finish_reason"] = "stop"
        return json.dumps(d, ensure_ascii=False).encode("utf-8")
    except Exception:
        return b


def _openai_json_to_sse(b: bytes) -> bytes:
    r"""把一条非流式 OpenAI 响应**合成**成 SSE 流（客户端要 stream 时用）。"""
    try:
        d = json.loads(b.decode("utf-8", "replace"))
    except Exception:
        return b"data: [DONE]\n\n"
    base = {k: d[k] for k in ("id", "object", "created", "model") if k in d}
    base["object"] = "chat.completion.chunk"
    ch = (d.get("choices") or [{}])[0]
    text = ((ch.get("message") or {}).get("content")) or ""
    out = []
    step = 40                       # 按 40 字切帧：客户端体验接近真流式，也避免一帧过大
    for i in range(0, max(step, len(text)), step):
        piece = text[i:i + step]
        delta = {}
        if i == 0:
            delta["role"] = "assistant"
        if piece:
            delta["content"] = piece
        frame = dict(base)
        frame["choices"] = [{"index": 0, "delta": delta, "finish_reason": None}]
        out.append("data: " + json.dumps(frame, ensure_ascii=False) + "\n\n")
    last = dict(base)
    last["choices"] = [{"index": 0, "delta": {},
                        "finish_reason": ch.get("finish_reason") or "stop"}]
    out.append("data: " + json.dumps(last, ensure_ascii=False) + "\n\n")
    out.append("data: [DONE]\n\n")
    return "".join(out).encode("utf-8")


# ⚠️ 2026-10-14 加：「这条回复被输出上限掐断」的痕迹。
#   OpenAI 形状看 `finish_reason`、Ollama 原生形状看 `done_reason` —— 到上限时都是 `length`。
#   为什么要留痕：① 网关在空回复兜底里会把 `length` 改写成 `stop`（`_replace_openai_content`），
#   客户端那边**看不出**这条是被截断的；② 用户看到"回复半句就停"时，只能靠翻日志区分
#   "模型本来就没说完" 还是 "撞了 max_tokens / num_predict" ✓
#   只用于日志留痕，**不改任何行为** ✓
_LENGTH_MARKS = (b'"finish_reason":"length"', b'"done_reason":"length"',
                 b'"finish_reason": "length"', b'"done_reason": "length"')
_LENGTH_NOTE = " ★截断=到输出上限（可能半句就停；调大客户端的 max_tokens / num_predict）"


def _hit_length_limit(raw: bytes) -> bool:
    r"""这段响应字节里有没有"到输出上限停了"的标记（供日志留痕用）✓"""
    return any(m in raw for m in _LENGTH_MARKS)


def _usage_from_tail(raw: bytes) -> int:
    r"""从响应里捞出 `prompt_eval_count`（Ollama 真报的输入 token 数）。

    ⚠️ 2026-10-05 踩过：原来只扫"最后 64 KB"，**非流式响应是一个大 JSON**，
    `prompt_eval_count` 在中间 —— 一大就被截掉，于是永远拿不到 → 压缩永远不触发
    （表现：`tokens` 一直停在旧值、`summary` 永远 0 字）。现在改成：
      1. 先按行找（流式：每行一个 JSON 分片）；
      2. 再整体 `json.loads`（非流式：整个响应一个对象）；
      3. 最后正则兜底（畸形/被截断也尽量捞出来）。
    取不到就返回 0 —— **宁可不压，也不乱压**。
    """
    text = raw.decode("utf-8", "replace")

    def pick(d):
        if isinstance(d.get("prompt_eval_count"), int) and d["prompt_eval_count"] > 0:
            return d["prompt_eval_count"]
        u = d.get("usage")
        if isinstance(u, dict) and isinstance(u.get("prompt_tokens"), int) \
                and u["prompt_tokens"] > 0:
            return u["prompt_tokens"]
        return 0

    # 1) 流式：尾部若干行 JSON
    for line in reversed(text.splitlines()[-40:]):
        line = line.strip()
        if line.startswith("{"):
            try:
                v = pick(json.loads(line))
                if v:
                    return v
            except Exception:
                pass
    # 2) 非流式：整个响应一个 JSON 对象
    try:
        v = pick(json.loads(text.strip()))
        if v:
            return v
    except Exception:
        pass
    # 3) 兜底：正则
    m = re.search(r'"prompt_eval_count"\s*:\s*(\d+)', text)
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    m = re.search(r'"prompt_tokens"\s*:\s*(\d+)', text)
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    return 0


class SessionStore:
    r"""会话记忆：最近的消息 + 滚动摘要（落盘，进程重启不丢）。

    结构（`_备份\gateway_sessions.json`）：
        {"<会话键>": {"model": "...", "msgs": [...], "summary": "...", "tokens": 12345,
                      "updated": 1770000000.0, "compressed": 2}}
    只给**聊天类**请求用；`/api/tags` 之类不碰。
    """

    MAX_SESSIONS = 50          # 最多记这么多个会话（超了丢最旧的）
    TTL = 24 * 3600            # 超过一天没动的会话清掉
    MAX_MSGS = 200             # 单个会话最多留这么多条消息（兜底，防文件爆）

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.data = {}
        self._load()

    def _load(self):
        if not self.path or not self.path.exists():
            return
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    # ---- 读写 ----
    def get(self, key: str) -> dict:
        with self.lock:
            s = self.data.get(key) or {}
            return {"msgs": list(s.get("msgs") or []), "summary": s.get("summary") or "",
                    "model": s.get("model") or "", "tokens": s.get("tokens") or 0}

    def update(self, key: str, msgs: list, model: str, tokens: int,
               summary: str | None = None):
        with self.lock:
            now = time.time()
            s = self.data.get(key) or {}
            s["msgs"] = msgs[-self.MAX_MSGS:]
            s["model"] = model
            s["tokens"] = tokens
            s["updated"] = now
            if summary is not None:
                s["summary"] = summary
                s["compressed"] = (s.get("compressed") or 0) + 1
            self.data[key] = s
            # 清理：过期的 + 太多的
            for k in [k for k, v in self.data.items()
                      if now - (v.get("updated") or 0) > self.TTL]:
                self.data.pop(k, None)
            if len(self.data) > self.MAX_SESSIONS:
                old = sorted(self.data.items(), key=lambda kv: kv[1].get("updated") or 0)
                for k, _ in old[: len(self.data) - self.MAX_SESSIONS]:
                    self.data.pop(k, None)
            self._save()

    def drop(self, key: str):
        with self.lock:
            self.data.pop(key, None)
            self._save()


def _msg_text(m) -> str:
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c
                        if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _msg_tokens(m) -> int:
    """粗估一条消息的 token 数（中文约 1.4 tok/字，这里按 1.5 保守估）。"""
    return int(len(_msg_text(m)) * 1.5) + 8


def _is_system(m) -> bool:
    return (m.get("role") or "").lower() == "system"


def _strip_old_summary(msgs: list) -> list:
    """去掉上次注入的那条摘要 system 消息（避免每轮叠一层）。"""
    out = []
    for m in msgs:
        if _is_system(m) and _msg_text(m).startswith("[长期记忆：之前对话的摘要]"):
            continue
        out.append(m)
    return out


def compress_session(store: SessionStore, key: str, sess: dict, keep_tokens: int,
                     model: str, ollama: str, log, timeout: float = 300.0) -> dict:
    """把"旧摘要 + 被挤出去的历史"重写成新摘要；保留最近 keep_tokens 的消息原文。"""
    msgs = _strip_old_summary(sess["msgs"])
    # 从后往前留，直到超出 keep_tokens
    kept, used = [], 0
    for m in reversed(msgs):
        t = _msg_tokens(m)
        if used + t > keep_tokens and kept:
            break
        kept.append(m)
        used += t
    kept.reverse()
    dropped = msgs[: len(msgs) - len(kept)]
    if not dropped:
        return sess

    lines = []
    if sess.get("summary"):
        lines.append("【旧摘要】\n" + sess["summary"])
    for m in dropped:
        role = {"user": "对方", "assistant": "AI", "system": "系统"}.get(m.get("role"), m.get("role"))
        lines.append(f"{role}：{_msg_text(m)[:1200]}")
    convo = "\n".join(lines)

    payload = {
        "model": model,
        "prompt": COMPRESS_PROMPT + "\n\n===== 对话历史 =====\n" + convo,
        "stream": False,
        "options": {"num_predict": 700, "temperature": 0.3},
        "keep_alive": "5m",
    }
    req = urllib.request.Request(ollama + "/api/generate",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with opener_for(ollama).open(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        summary = (d.get("response") or "").strip()
    except Exception as e:
        log(f"压缩失败（{type(e).__name__}）—— 本轮不改记忆")
        return sess

    if not summary:
        log("压缩返回空 —— 本轮不改记忆")
        return sess

    out = {"msgs": kept, "summary": summary, "model": sess.get("model") or "",
           "tokens": 0}
    log(f"压缩完成：丢 {len(dropped)} 条 / 留 {len(kept)} 条，摘要 {len(summary)} 字")
    return out


# ---------------------------------------------------------------- 自带网页
# ⚠️ 网页本身是**公开**的（不含密钥），密码只由 `/__key` 下发，而且**只允许本机取**
#    （除非显式 --show-key-lan）。这样"别的设备打开网页"看不到 key，口令才有意义。




# ---------------------------------------------------------------- 联网搜索（可选，关键词触发）
#
# 为什么放在网关里：局域网 API 转发的是**裸模型**，模型自己不会上网；"能查资料"是 AstrBot
# 那边的工具能力。想让手机 App 也能查，就得由**网关**去搜、把结果塞给模型再让它回答。
#
# 接口照抄 AstrBot 的实现（`web_search_tools.py` 的 `_anysearch_search`）：
#     POST https://api.anysearch.com/v1/search
#     不带 Authorization = 匿名模式（每日免费额度）—— 2026-10-03 实测可用（HTTP 200，2.6s）
#     payload: {"query": ..., "max_results": 5, "include_favicon": false}
#     返回: {"code":0, "data":{"results":[{"title","url","snippet","content"}, ...]}}
#
# 触发方式（2026-10-05 改成"三档"，见 `--search-mode`）：
#   auto（默认）：**它自己判断**要不要查 —— 消息里出现"事实/时效类"词（见 SEARCH_AUTO_HINTS）
#                 就自动去搜，不用再打「搜」。另外「搜/查」开头的照旧强制触发。
#   always      ：**每句都先搜**（用户要"完全不限制"时用；代价：每句多 2~6 秒 + 几百 token）
#   keywords    ：老行为，只有「搜/查」开头才搜
# 为什么默认不选 always：这台机器 35B 有一半在 CPU 上，且用户主要在手机上演角色扮演 ——
# 每句都塞搜索结果既拖慢又会把新闻编进剧情。
SEARCH_URL = "https://api.anysearch.com/v1/search"
SEARCH_TRIGGERS = ("搜索一下", "搜索", "搜一下", "搜", "查一下", "查查", "查")
SEARCH_TIMEOUT = 25.0
SEARCH_DEADLINE = 40.0        # 一次搜索的**总预算**（含重试）；到点就放弃，不让用户干等
SEARCH_MAX = 5

# ── 搜索走不走本机代理（2026-10-08 修）────────────────────────────────
#
# **问题**：AnySearch 在墙外。这台机器上 `urllib.request.getproxies()` 是空的，
# 于是 `web_search()` 直连 ⇒ `URLError` ⇒ 搜索始终失败（用户报"无法联网搜索内容"）。
# 实测：本机代理 `127.0.0.1:7897` 通、直连不通。
#
# **为什么不能简单粗暴地设全局代理**（这是这次改动的关键约束）：
#   · `urllib.request.install_opener(...)` / 设 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量，
#     会**影响整个进程的每一次 urllib 请求** —— 包括网关转发给 **本机 Ollama**
#     （`127.0.0.1:11434`）的那些请求。本机流量被塞进代理，轻则绕一圈变慢，
#     重则代理没开/不回环就直接连不上模型。
#   · 所以这里**只给搜索这一次请求**构造一个带 `ProxyHandler` 的 opener：
#     `build_opener()` **不进全局**，用完就丢（缓存起来复用，但只给搜索用）。
#   · 直连时显式给 `ProxyHandler({})` —— **明确不走任何代理**，不去读环境变量，
#     避免"某天环境里多了个 HTTP_PROXY 就把本机请求也带偏"。
#
# 通道选择：`--search-proxy URL` 指定；默认 `http://127.0.0.1:7897`，
# **启动时探测端口**：在听就挂代理，不在听就直连（免得每次搜索白等 25 秒超时）。
# 传 `--search-proxy none` = 永远直连。
SEARCH_PROXY = "http://127.0.0.1:7897"
_SEARCH_PROXY_USE = None      # None=还没探测；""=直连；否则=代理地址
_SEARCH_OPENER_CACHE = {}


def search_proxy_alive(url: str, timeout: float = 0.35) -> bool:
    r"""本机代理端口在不在（只连一下 TCP，0.35 秒；不发任何请求）。"""
    try:
        rest = url.split("//", 1)[-1]
        host, _, port = rest.partition(":")
        with socket.create_connection((host, int(port or "80")), timeout=timeout):
            return True
    except Exception:
        return False


def search_route() -> str:
    r"""这次搜索走哪条路（缓存）：返回 `""`（直连）或代理地址。"""
    global _SEARCH_PROXY_USE
    if _SEARCH_PROXY_USE is None:
        if not SEARCH_PROXY:
            _SEARCH_PROXY_USE = ""
        elif search_proxy_alive(SEARCH_PROXY):
            _SEARCH_PROXY_USE = SEARCH_PROXY
        else:
            _SEARCH_PROXY_USE = ""
            sys.stderr.write(f"  [搜索] 本机代理 {SEARCH_PROXY} 没在监听 ⇒ 直连试试\n")
            sys.stderr.flush()
    return _SEARCH_PROXY_USE


def search_opener(route=None):
    r"""**只给搜索用**的 opener：带代理或不带（`route=""`）。

    ⚠️ 绝不调用 `urllib.request.install_opener()` —— 那会把代理装到全局，
    连转发给本机 Ollama 的请求都会走代理。
    """
    if route is None:
        route = search_route()
    op = _SEARCH_OPENER_CACHE.get(route)
    if op is None:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": route, "https": route} if route else {}))
        op._gw_route = route          # 记一下走的哪条路（日志/自检用）
        _SEARCH_OPENER_CACHE[route] = op
    return op

# `auto` 模式靠这些词判断"这句在问外界的事实"。**分强弱两档**（2026-10-05 调过一轮）：
#   · 强词：本身就说明在问外界（天气/价格/几点/版本/新闻…）→ 命中就搜；
#   · 弱词：时间类（今天/最近/今年…）→ **必须同时是问句**才搜。
# 为什么这么分：第一版把"今天"当强词，实测「你今天真好看」这种角色扮演句也会去搜
# （白等 2~6 秒 + 把新闻编进剧情）。分档后这类句子不再触发，而
# 「今天天气怎么样」「今天有什么新闻吗」照旧会搜（前者靠"天气"、后者带问号）。
SEARCH_AUTO_STRONG = (
    "最新", "实时", "今天天气", "天气", "气温", "温度", "价格", "多少钱", "汇率",
    "股价", "股票", "比价", "比分", "赛程", "排名", "排行", "榜", "几点", "几号",
    "日期", "星期几", "版本", "更新了", "更新日志", "发布了", "发售", "上映", "开售",
    "官网", "教程", "怎么用", "怎么装", "怎么下载", "在哪", "多远", "哪一年", "哪年",
    "是谁", "有多少", "多少个", "新闻", "报错", "错误码", "怎么解决",
)
SEARCH_AUTO_WEAK = (
    "今天", "今日", "昨天", "明天", "最近", "近期", "今年", "这个月", "本周", "这周", "上个月",
)
# 弱词要配这些才算"在问"（问号 / 疑问词）。
# ⚠️ 这里**故意不放「怎么/如何/什么」** —— 它们最容易出现在角色扮演句里
# （实测：「你今天怎么这么坏」会因此误触发）。
SEARCH_QUESTIONISH = ("？", "?", "吗", "呢", "多少", "哪", "谁", "几", "是不是",
                      "有没有", "能不能")

SEARCH_INSTRUCTION = (
    "\n\n[联网搜索结果 —— 来自本机网关的实时检索]\n"
    "下面是刚刚从网上搜到的内容。规则：\n"
    "1. 只要问题涉及**实时信息**（今天/最近/现在/新闻/价格/天气/版本号/比分等），"
    "**必须优先用这些结果回答**，不要凭记忆猜。\n"
    "2. 用结果回答时**带上来源**（标题或网址）；结果之间互相矛盾时以更新的为准，并说明有分歧。\n"
    "3. 结果里找不到答案就直说「没搜到相关结果」，**绝对不许编造**来源或数据。\n"
    "4. 不需要把搜索结果原样复述一遍，用你自己的话说，但事实必须是结果里的。\n"
    "5. ⚠️ **如果这些话跟当前对话明显没关系**（用户只是在闲聊、或在角色扮演里说了一句话），"
    "就**当作没看见**，照你平时那样回答 —— **绝对不要把新闻/搜索结果编进剧情或硬扯进来**。\n"
    "6. ⚠️ 用户明确说了「搜/查/找/联网」时：**必须把你查到的具体内容和链接说出来**；"
    "**不要用「我的记忆库里没有」「未在记忆库中找到」这类说法推脱** —— 那是另一套系统的措辞，"
    "现在你已经查过网了，查到什么就说什么；结果不理想也如实说「查到的是这些」，不要只回一句「没找到」。\n"
)

# 「客户端自己的协议消息」长这样（2026-10-05 实测：手机 App 每轮会在历史里塞几条）：
#   `system:未在记忆库中找到关于"…"的内容（已尝试模糊匹配）`
#   `{system:对方暂未回复，请设置下一次回复的时间间隔…}`
# ⚠️ 它们**不是用户问的话**。以前 `always` 档会把它们当成搜索词 ——
# 实测日志里搜的是 `'可以'`、`'{system:对方暂未回复…}'`，而真正该搜的那句被挤掉了。
_PROTOCOL_PREFIXES = ("{system:", "system:", "[system", "{记忆", "{memory", "{System:")


def web_search(query: str, max_results: int = SEARCH_MAX) -> tuple:
    """搜一次。返回 `(给模型看的纯文本, 结果条数)`；失败抛 RuntimeError。

    ⚠️ 2026-10-05 改：以前只返回文本，于是日志里只有"搜了什么"、**看不到"搜到没有"** ——
    用户报"无法联网搜索内容"时无从判断。现在条数一起返回，日志里会写 `结果N条` / `无结果`。
    """
    payload = json.dumps({"query": query, "max_results": max_results,
                          "include_favicon": False}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(SEARCH_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    # 通道路由（2026-10-08）：先按探测结果（代理/直连），**代理失败再直连兜一次**，
    # 并把"最后是哪条路通"写进日志 —— 以后报"搜不到"时一眼能看出是不是代理的问题。
    routes = [search_route()]
    if routes[0]:
        routes.append("")
    d, errs, used = None, [], routes[0]
    # ⚠️ **必须重试**（2026-10-08 实测结论）：到 `api.anysearch.com` 的 TLS 连接是**间歇性被掐**的
    # —— 同一分钟里 curl 直连/代理都报 `SSL: UNEXPECTED_EOF_WHILE_READING`，
    # 而几分钟前同样的请求顺利返回 5 条结果。所以两轮 ×（代理 → 直连）各试一次，
    # 整个搜索给 40 秒总预算（超了就放弃，别让用户干等）。
    rounds = [(SEARCH_TIMEOUT, routes), (min(10.0, SEARCH_TIMEOUT), routes)]
    deadline = time.time() + SEARCH_DEADLINE
    for timeout, route_list in rounds:
        for route in route_list:
            if time.time() > deadline:
                break
            try:
                with search_opener(route).open(req, timeout=timeout) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                used = route
                break
            except Exception as e:
                # 把**每条路各自的原因**都留下来（含 e.reason）—— 只报类型根本没法排错：
                # 实测 "URLError" 既可能是代理没开、也可能是 CONNECT 被拒、TLS 被掐或目标不通。
                why = getattr(e, "reason", "") or ""
                errs.append(f"{'经代理 ' + route if route else '直连'}：{type(e).__name__}"
                            f"{' / ' + str(why)[:80] if why else ''}")
        if d is not None:
            break
    if d is None:
        raise RuntimeError("搜索请求失败（已重试）—— " + "；".join(dict.fromkeys(errs)))
    if routes[0] and used != routes[0]:
        sys.stderr.write("  [搜索] 走代理没通，直连成功（代理可能没开或规则不对）\n")
    sys.stderr.write(f"  [搜索] 通道={'经代理 ' + used if used else '直连'}\n")
    sys.stderr.flush()

    if d.get("code") not in (None, 0):
        raise RuntimeError(f"搜索接口报错：{d.get('message') or d.get('code')}")
    results = (d.get("data") or {}).get("results") or d.get("results") or []
    if not results:
        return f"（搜索「{query}」没有返回结果）", 0

    lines = [f"查询：{query}", f"结果数：{len(results)}"]
    for i, it in enumerate(results, 1):
        title = (it.get("title") or "").strip()
        url = (it.get("url") or "").strip()
        text = (it.get("content") or it.get("snippet") or "").strip()
        text = " ".join(text.split())
        if len(text) > 700:
            text = text[:700] + "…"
        lines.append(f"\n[{i}] {title}\n    {url}\n    {text}")
    return "\n".join(lines), len(results)


def take_search_trigger(text: str):
    """看消息是不是"要搜索"，是就把触发词去掉、返回查询词；不是返回 None。

    ⚠️ 触发词后面**必须是分隔符或结尾** —— 否则「查询一下」会被当成「查」+「询一下」
    这种误触发（实测踩到过）。所以「查一下 xxx」会触发，而「查询一下」不会。
    """
    s = (text or "").lstrip()
    if s.startswith("/"):
        s = s[1:].lstrip()
    for t in SEARCH_TRIGGERS:          # 长词在前，避免"搜索"被"搜"先切掉
        if not s.startswith(t):
            continue
        rest = s[len(t):]
        if rest and rest[0] not in " ：:，,、\t\u3000":
            continue                   # 粘着别的字（查询/查收/搜狗…）→ 不算触发
        q = rest.lstrip(" ：:，,、\t\u3000")
        return q or None
    return None


def auto_search_hit(text: str):
    r"""`auto` 模式：这句要不要联网查？命中返回命中的那个词，否则 None。

    两档（见上面的常量）：
      · **强词**（天气/价格/几点/版本/新闻…）—— 命中就查；
      · **弱词**（今天/最近/今年…）—— **只有同时是问句**（有问号或疑问词）才查，
        免得"你今天怎么这么坏"这种角色扮演句子也去搜。
    想要"每句都搜"用 `--search-mode always`；想回到"只有关键字才搜"用 `keywords`。
    """
    s = (text or "").strip()
    if len(s) < 2:
        return None
    for w in SEARCH_AUTO_STRONG:
        if w in s:
            return w
    if any(q in s for q in SEARCH_QUESTIONISH):
        for w in SEARCH_AUTO_WEAK:
            if w in s:
                return w + "（带问句）"
    return None


# 「反说一半」（2026-10-05 晚加，默认开）：他手机客户端是**手机客户端（手机客户端）** App，
# 它的回复规则**硬编码**在源码里（`AiPromptBuilder.buildPersonaRules`）：
#     「1. 长度：最少1句，最多5个短句。一次说的话不要长，控制在15-50字。」
#     「4. 标点：允许用「？」「...」。」
# ⇒ 表现就是"说一半就省略"（用户报的原话）。App 的 UI 没有开关能改这两条，
#    所以由网关在**它那段之后**补一句，让模型把话说完。
# ⚠️ 2026-10-12 改：这句原来写的是「最多约 150 字」，理由是"App 还会自己截断
#    （`POST_PROCESS_LONG_CUT_THRESHOLD = 150` 字、最多 8 短句，`AiPromptBuilder.kt` 里
#    `cleaned.take(120)` 那几行），超了会被 App 砍"。
#    现在 **App 那两处截断已经删掉了**（本地补丁 #7：`AiPromptBuilder` 的 8 句 / 150 字 /
#    120 字 + `extractDirectReply` 全去掉）⇒ 这里再压着 150 字就只剩副作用。
#    实测（同模型/同 seed/同参数，只差这一句，3 个问题）：有这句共 587 字，
#    没这句共 1853 字（**3.2 倍**；单条最高 201 → 1328 字）✓
#    ⚠️⚠️ **但这句不能整段删**：App 自己那条「最多 5 个短句 / 控制在 15-50 字」还硬编码在
#    源码里（`AiPromptBuilder.buildPersonaRules`），现在**正是靠「以本条为准」把它压过去的**
#    —— 删了这条，App 那条重新生效，回复会变成 15~50 字，**比改之前还短** ✗
#    所以只把"最多约 150 字"换成"不设字数上限"，覆盖效力原样保留 ✓
#    ⚠️ 2026-10-12 第二轮：改完实测只从 587 → **717 字** —— 因为同一句里还有
#    「一次回复可以 **1~8 句**」，8 句自然就是 250~300 字，**句数成了新天花板**
#    （对比：完全不加这句能到 1328 字）。所以把句数上限也去掉，改成**引导式**：
#    「句数和字数都按内容需要来：闲聊可以短，该展开就写详细 —— 不硬凑也不硬截」，
#    这样详细的问题能写长、日常闲聊不会为了凑长度而啰嗦 ✓
#    ⚠️ 2026-10-12 第三轮（用户要求"功能像普通大模型 API 一样"）：把覆盖范围从"只压长度"
#    扩到 **App 全部压制性规则**：除**表情包规则**外，规则 1（15-50 字）、规则 5（
#    "不要答满、只回一点"）、规则 10（"绝对不要空行、必须连成一整段"）都以本条为准。
#    理由：那三条是"人工把回复做短"的，和"用普通 API 拿模型原样输出"是冲突的。
#    唯一保留：**不要 markdown 排版**（# 标题 / - 列表 / ``` 代码块）—— App 的气泡不渲染
#    markdown，写了只会显示成乱符号；这条是排版需要，不是内容限制 ✓
#    表情包规则也保留（`[表情包名称]` 是 App 的功能，覆盖了会发不出表情包）✓
ANTI_ELIDE_LINE = (
    # ⚠️ 2026-10-18：**大幅瘦身**（原来 262 字，实测约 460 token 含时间行）。
    #    起因：用户人设只有 756 字（≈500 token），而我这两段注入比人设还大 ⇒
    #    模型被"抢注意力"：问"介绍一下自己"它答"今天是 2026 年 10 月 18 日…"，
    #    或者干脆只写 2~4 个字就收尾。用户原话"怎么越改越坏"——就是这段造成的 ✗
    #    现在：① 长度限制改由 `strip_length_limits()` **直接删规则**（10 倍杠杆，见上），
    #    不再需要"以本条为准"这种又长又抢戏的覆盖句；② 只留最必要的一句 ✓
    "（补充：句子要写完，别用「…」截断；篇幅按内容需要；不要用 markdown。）"
)


def now_line() -> str:
    r"""给模型看的一行"现在是几点"。

    ⚠️ 为什么要照这个格式写（`02` **坑 19** 的结论）：当年 AstrBot 那边只给 `(CST)`，
    9B 把 `12:30` 读成"一点半" —— 所以这里**显式 UTC 偏移 + 24 小时制 + 中文星期**。

    为什么要注入（2026-10-05 用户实测踩到）：手机网页上问"几点了"，网关**去搜了**，
    可**网上查不到"你的现在几点"**，答出来是错的。裸模型没有表，时间必须由我们给。
    """
    now = datetime.datetime.now().astimezone()
    wd = "一二三四五六日"[now.weekday()]
    off = now.utcoffset() or datetime.timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    hh, mm = divmod(abs(mins), 60)
    tz = f"UTC{sign}{hh}" + (f":{mm:02d}" if mm else "")
    # ⚠️ 措辞要"像背景信息"，别写得像一句要照着念的台词 ——
    #    第一版写「[本机当前时间] … 就用这一行回答：不要搜」，实测模型把整行原样念出来了。
    # ⚠️ 2026-10-18 再瘦身：原来那版带"（系统信息，不用回复这一段…不问就别说）"的解释，
    #    光它就 80 多字；现在只给**信息本身**（仍是显式 UTC 偏移 + 24 小时制 + 中文星期）✓
    return (f"（现在是 {now:%Y-%m-%d} 星期{wd} {now:%H:%M}，{tz}。）")


def _looks_like_time_question(s: str) -> bool:
    r"""是不是在问"现在几点 / 今天几号"这种**本机时间**。

    有注入时这类**不用搜**（省 2~6 秒，而且网上根本查不到"你的现在几点"）；
    但如果同一句里还在问别的事实（天气/价格…），那还是得搜。
    """
    if not any(w in s for w in ("几点", "几号", "星期几", "日期", "几时", "什么时候")):
        return False
    others = [w for w in SEARCH_AUTO_STRONG
              if w not in ("几点", "几号", "日期", "星期几", "什么时候")]
    return not any(w in s for w in others)


def search_query_of(text: str, mode: str = "auto", time_injected: bool = True):
    r"""决定这次搜什么、为什么搜。返回 (查询词, 原因) 或 (None, None)。

    顺序：
      1. **显式触发词**（搜/查…）—— 永远优先，用户说了算（哪怕只是问时间）；
      2. 有本机时间注入时，"纯时间问题"**不搜**（网上查不到你的现在几点）；
      3. `always` 档：整句当查询；
      4. `auto` 档：命中"事实/时效"词就用整句当查询。
    """
    s = (text or "").strip()
    if not s:
        return None, None
    q = take_search_trigger(s)
    if q:
        return q, "触发词"
    if time_injected and _looks_like_time_question(s):
        return None, None
    if mode == "always":
        return s[:200], "always（每句都查）"
    if mode == "auto":
        hit = auto_search_hit(s)
        if hit:
            return s[:200], f"自动命中「{hit}」"
    return None, None


def is_protocol_text(s: str) -> bool:
    r"""这句是不是**客户端自己的协议消息**（不是用户问的话）。见 `_PROTOCOL_PREFIXES`。"""
    t = (s or "").lstrip()
    return any(t.startswith(p) for p in _PROTOCOL_PREFIXES)


def last_real_user_text(messages: list):
    r"""往前找**最后一条"真正是用户说的话"**（跳过客户端塞的协议消息）。

    为什么要跳（2026-10-05 实测）：手机 App 每轮会在历史里塞 `{system:对方暂未回复…}`
    这类协议消息，而 `always` 档原来拿"最后一条 user"当搜索词 ⇒ 搜的是 `'可以'`
    或整段协议文本，**真正该搜的那句反而没搜**（用户看到的就是"无法联网搜索内容"）。
    """
    for m in reversed(messages or []):
        if not isinstance(m, dict) or (m.get("role") or "").lower() != "user":
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c
                         if isinstance(p, dict) and isinstance(p.get("text"), str))
        if isinstance(c, str) and c.strip() and not is_protocol_text(c):
            return c
    return None


def inject_search(messages: list, query: str, explicit: bool = True):
    r"""把搜索结果塞进 messages（有 system 就追加，没有就新建一条）。
    返回 `(新 messages, 一行说明)` —— 说明会进网关日志（`结果5条` / `无结果` / `失败:…`）。

    `explicit`：这次是用户**明确说了「搜」**，还是网关自己判断/`always` 顺手搜的。
    失败时的措辞不一样 —— 顺手搜的那种**不该让模型提这茬**，否则角色扮演里会突然冒出
    "抱歉，没搜到相关结果"（用户没问就要联网时尤其突兀）。
    """
    try:
        found, n = web_search(query)
        block = SEARCH_INSTRUCTION + found
        note = f"结果{n}条" if n else "**无结果**"
    except RuntimeError as e:
        if explicit:
            tail = (f"\n⚠️ 这次搜索失败了（{e}）—— 直接告诉用户没搜到，"
                    "不要凭记忆编造实时信息。\n")
        else:
            tail = (f"\n⚠️ 这次没取到结果（{e}）—— **不要特意提这件事**，"
                    "按你平时那样正常回答即可。\n")
        block = SEARCH_INSTRUCTION + tail
        note = f"**失败：{e}**"
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            m["content"] = (m.get("content") or "") + block
            return out, note
    out.insert(0, {"role": "system", "content": block.lstrip("\n")})
    return out, note


class Handler(BaseHTTPRequestHandler):
    server_version = "ollama-gateway/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 日志：**不打印口令**，路径按原样记 ----
    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("  %s | %s\n" % (self.address_string(), fmt % args))

    # ---- 「HTTPS 打到明文端口」这类错误：默认实现会把原始字节打成满屏乱码 ----
    # 2026-10-06 踩到：用户手机用 https:// 访问 11435，http.server 把 TLS 握手字节
    # 当请求行打出来（`code 400, message Bad request syntax ('\x16\x03\x01…')`），
    # 控制台一屏乱码、日志里只有"└ 400"，根本看不出是谁说了什么。
    # 现在：stderr 只写一行人话，详细一点的那行落进 gateway.log。
    def _looks_like_tls(self) -> bool:
        raw = getattr(self, "raw_requestline", b"") or b""
        # 0x16 = TLS handshake；0x80 = SSLv2 ClientHello
        return raw[:1] in (b"\x16", b"\x80")

    def log_error(self, fmt, *args):  # noqa: A802
        try:
            msg = fmt % args
        except Exception:
            msg = str(fmt)
        who = self.address_string()
        if self._looks_like_tls():
            line = (f"⚠️ {who} 在用 HTTPS 访问本端口（本网关是明文 HTTP）"
                    f"⇒ 请把地址改成 http://…:11435 —— 已回 400，不影响别的客户端")
        elif "Bad request" in msg:
            line = (f"⚠️ {who} 发的不是合法 HTTP（已回 400）："
                    f"{msg.splitlines()[0][:120] if msg else 'Bad request'}")
        else:
            line = f"⚠️ {who} {msg.splitlines()[0][:160] if msg else 'error'}"
        sys.stderr.write("  " + line + "\n")       # 控制台只留一行
        self._log(line)                            # 详细那行进 gateway.log

    def log_request(self, code='-', size='-'):  # noqa: N802
        r"""合法的 HTTP 请求照旧打一行（人能看）；**不是 HTTP 的一律不打原始字节**。

        乱码就是从这儿来的：`send_error` 会调 `log_request`，而它把"请求行"原样打出来，
        TLS 握手那种就是 16 KB 的随机字节 ⇒ 控制台一屏乱码。这种情况上面
        `log_error` / `handle_one_request` 已经写过人话了，这里保持安静。
        """
        if self._looks_like_tls():
            return
        try:
            if not str(getattr(self, "requestline", "") or "").isprintable():
                return
        except Exception:
            return
        super().log_request(code, size)

    def handle_one_request(self):  # noqa: N802
        r"""包一层：请求行不是 HTTP（最典型就是 TLS 握手）时，补一条**看得懂**的日志。

        `BaseHTTPRequestHandler` 自己会回 400，但它的日志是原始字节 ⇒ 这里补一条人话，
        并点明"客户端用了 https://"这个真正的原因。
        """
        try:
            super().handle_one_request()
        finally:
            if self._looks_like_tls():
                try:
                    self._log(f"⚠️ TLS 握手（{self.address_string()}）—— 客户端在试 HTTPS，"
                              f"本网关只认 http://；已回 400")
                except Exception:
                    pass

    # ---- 请求日志：每个请求往文件记一行"形状"（排错用，见 ReqLog）----
    def _log(self, msg: str) -> None:
        try:
            self.server.logger(msg)
        except Exception:
            pass

    def _auth_shape(self) -> str:
        r"""只记"Key 从哪个头传的 + 多长"，**不记内容**。"""
        auth = (self.headers.get("Authorization") or "").strip()
        if auth:
            return "Key=Authorization%s(len=%d)" % (
                " Bearer" if auth.lower().startswith("bearer ") else "", len(auth))
        for h in ("x-api-key", "api-key", "x-goog-api-key", "x-auth-token", "token"):
            v = (self.headers.get(h) or "").strip()
            if v:
                return f"Key={h}(len={len(v)})"
        q = urllib.parse.urlparse(self.path).query
        if q:
            for k, v in urllib.parse.parse_qsl(q):
                if k.lower() in ("api_key", "apikey", "key", "token") and v.strip():
                    return f"Key=?{k}(len={len(v.strip())})"
        return "Key=无"

    def _req_line(self) -> str:
        r"""① 请求行：谁、用什么路径、Key 从哪传的、什么 UA —— **不含正文与口令内容**。"""
        i = self._reqinfo
        bits = [str(i["ip"]), f'{i["method"]} {i["path"]}']
        if i["auth"]:
            bits.append(i["auth"])
        if i["host"]:
            bits.append(f'Host={i["host"]}')
        if i["origin"]:
            bits.append(f'Origin={i["origin"]}')
        ua = (self.headers.get("User-Agent") or "").strip()
        if ua:
            bits.append("UA=" + ua[:70])
        return " | ".join(bits)

    def _summary(self, code) -> str:
        r"""② 结果行：状态码 + 请求体形状（模型/流式/条数/角色）—— 跟在上面的请求行后面。"""
        i = getattr(self, "_reqinfo", None) or {}
        bits = [f"└ {code}"]
        if i.get("payload"):
            bits.append(i["payload"])
        if i.get("search"):
            bits.append(i["search"])
        return " | ".join(bits)

    def send_response(self, code, message=None):  # noqa: N802
        r"""所有响应都从这里出去（含 401/403/404/405 和转发成功那条）→ 在这里记结果行。

        放在 `send_response` 而不是逐个 return 点：**不会漏**，包括
        `BaseHTTPRequestHandler` 自己产生的 400/501。
        """
        super().send_response(code, message)
        try:
            self._log(self._summary(code))
        except Exception:
            pass

    def _note_payload(self, payload) -> None:
        r"""把请求体的**形状**记进 `_reqinfo`，由结果行一并写出 —— 不记正文。

        （形状 = 模型 / 是否流式 / 几条消息 / 最后几个角色 / 有没有 system。
        这几样就够判断"客户端到底按哪种 API 在说话"，而正文一个字都不落盘。）
        """
        try:
            i = getattr(self, "_reqinfo", None)
            if i is None:
                return
            if not isinstance(payload, dict):
                i["payload"] = "请求体不是 JSON 对象"
                return
            msgs = payload.get("messages")
            msgs = msgs if isinstance(msgs, list) else []
            roles = [m.get("role") for m in msgs if isinstance(m, dict)]
            prompt = payload.get("prompt")
            i["payload"] = "model=%s stream=%s msgs=%d roles=%s system=%s%s" % (
                payload.get("model"), payload.get("stream"), len(msgs),
                ",".join(str(r) for r in roles[-4:]) or "-",
                "system" in roles,
                (" prompt=%d字" % len(prompt)) if isinstance(prompt, str) else "")
            # 「最近一次对话」（2026-10-06 傍晚加）：只在真正的对话接口上记。
            # 面板据此显示"X 秒前 · 哪个模型 · 带几条消息 · 来自哪台设备" ——
            # 用来回答"我发了消息，模型到底有没有被调用"。
            if (i.get("path") or "").split("?")[0] in CHAT_PATHS + ("/v1/api/chat",):
                note_chat(payload.get("model") or "", len(msgs),
                          self.client_address[0], self.headers.get("User-Agent") or "",
                          i.get("path") or "")
        except Exception:
            pass

    def _local_think(self, payload: dict, path: str) -> bool:
        r"""「本地思考」两段式：① 本机先想（过程不外发）② 关思考写正式回复。

        回给客户端的**只有第二轮的正文字**；第一轮的推理写进 `_备份\思考过程.log`（只在本机）。
        任何一步失败都返回 False —— 调用方会退回普通转发，请求不会丢。
        仅用于**非流式**（流式没法两段式，见调用处说明）。
        """
        try:
            # ---- 保温（2026-10-08 实测必须）----
            # 手机 App 的请求超时只有 20~30 秒；local 热态 13 秒 ✓，但**模型被卸载后**第一条要 47 秒 ✗
            # （光加载 30 秒）⇒ 所以 local 档给请求带上 keep_alive，聊天期间模型不被卸掉。
            # 第一次（冷启动）仍然可能超时，但 App 自己会重试/下一条就正常了。
            if not payload.get("keep_alive"):
                payload["keep_alive"] = LOCAL_KEEP_ALIVE
            url = f"{self.server.ollama}{path}"
            # ⚠️ 第一轮只用 `--local-think-budget`（默认 1536）：
            #   手机 App 的请求超时只有 20~30 秒，而 4096 的思考预算会把全程拉到 26~35 秒 ⇒
            #   超时被掐、表现成"两句话才回一句"（2026-10-08 实测）。local 只需要"想清楚"，
            #   不需要把答案写完 —— 所以这里比全局的 --think-min-predict 更小。
            budget = max(200, min(4096, local_budget()))

            # ---- 第一轮：放开思考 ----
            # ⚠️ **固定走原生 `/api/chat`**（2026-10-08 实测）：App 走的 `/v1/chat/completions`
            #   **不吃 `max_tokens`**（预算 1024 也照样吐 2949 字推理 ⇒ 参数形同没用 ✗），
            #   而原生接口的 `options.num_predict` 是算数的 ✓。第一轮只要推理文本、不走客户端格式，
            #   所以换接口没有任何兼容问题 ✓。
            p1 = json.loads(json.dumps(payload, ensure_ascii=False))
            p1["stream"] = False
            p1["think"] = True
            opts = p1.get("options")
            opts = dict(opts) if isinstance(opts, dict) else {}
            opts["num_predict"] = budget
            p1["options"] = opts
            for k in ("max_tokens", "reasoning_effort"):
                p1.pop(k, None)
            st1, b1 = self._upstream_post(f"{self.server.ollama}/api/chat", p1)
            thought = self._extract_thought(b1, "/api/chat")
            if not thought:
                # ⚠️ **静默退回**很坑（2026-10-08 实测被绕进去一次）：小模型（如 local-assistant-9b）
                # 根本不支持思考 ⇒ 第一轮不吐 reasoning ⇒ 这里退回普通单轮、**也不会写过程日志**。
                # 所以必须留下痕迹：stderr + 请求备注 + 页面提示。
                global _LOCAL_FALLBACK
                _LOCAL_FALLBACK = (f"模型 {payload.get('model')} 不吐推理（可能不支持思考）"
                                   f"，已退回普通单轮 ⇒ 过程日志不会有内容")
                sys.stderr.write(f"  [本地思考] {_LOCAL_FALLBACK}\n")
                sys.stderr.flush()
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                    " think=local(模型不吐推理→退回普通单轮)"
                return False

            # ---- 第二轮：把推理当内部笔记，关思考、出正文 ----
            p2 = json.loads(json.dumps(payload, ensure_ascii=False))
            p2["stream"] = False
            msgs = list(p2.get("messages") or [])
            note = ("【你刚才在本地推理出的结论 —— 这是给你的内部笔记，"
                    "**不要复述它、不要让用户看到**，直接按它写出给用户的最终回复】\n"
                    + thought[:6000])
            msgs.append({"role": "system", "content": note})
            p2["messages"] = msgs
            if path == "/api/chat":
                p2["think"] = False
            else:
                p2["reasoning_effort"] = "none"
            if not p2.get("max_tokens") and path != "/api/chat":
                p2["max_tokens"] = self.server.num_predict
            # ★ 第二轮必须**跟着客户端的期待走**（2026-10-08 踩到）：
            #   客户端**没写** `stream` 时，Ollama/OpenAI 的默认是**流式（SSE）** —— 这时如果回一整坨
            #   JSON，App 解析不了，表现成"发了消息没有回复" ✗。所以显式判断：
            #   `stream is None`（没写）⇒ 按流式回；写了就照它写。第二轮本身仍然是**关思考**的。
            want_stream = True if payload.get("stream") is None else bool(payload.get("stream"))
            p2["stream"] = want_stream
            self._save_thought(thought, path)
            self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                f" think=local(先想{len(thought)}字→再出正文{'(流式)' if want_stream else ''})"
            if not want_stream:
                st2, b2 = self._upstream_post(url, p2)
                if st2 != 200 or not b2:
                    return False
                self.send_response(st2)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b2)))
                self._cors()
                self.end_headers()
                self.wfile.write(b2)
                return True
            # 流式：边收边发（照抄主转发那段的 chunked 写法，保证和正常路径一模一样）
            req2 = urllib.request.Request(
                url, data=json.dumps(p2, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with opener_for(url).open(req2, timeout=self.server.timeout) as up:
                self.send_response(up.status)
                for k, v in up.headers.items():
                    if k.lower() in BAD_HEADERS:
                        continue
                    self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self._cors()
                self.end_headers()
                while True:
                    chunk = up.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
                if _watch is not None:
                    _txt = (_watch.finish() or '').strip()
                    if not _txt:
                        self._reqinfo['payload'] = (self._reqinfo.get('payload') or '') + \
                            ' ⚠️空正文(已记日志)'
                        self.server.log('[空正文] 这条流式回复整段没有正文（档位看上面那条备注；模型/采样问题，非网关 bug）')
                    elif len(_txt) < 4:
                        self.server.log(f'[短正文] 只有 {len(_txt)} 字：{_txt[:20]!r}')
            return True
        except Exception as e:
            sys.stderr.write(f"  [本地思考] 出错，退回普通转发：{type(e).__name__} {e}\n")
            sys.stderr.flush()
            return False

    def _upstream_post(self, url: str, payload: dict):
        r"""给上游（本机 Ollama）发一次**非流式**请求，返回 `(状态码, 响应字节)`。"""
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with opener_for(url).open(req, timeout=self.server.timeout) as up:
                return up.status, up.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            sys.stderr.write(f"  [本地思考] 上游请求失败：{type(e).__name__}\n")
            return 0, b""

    def _chat_with_empty_retry(self, url, payload, headers, think_on: bool = False) -> bool:
        r"""思考开着时：整段取回 ⇒ 正文空就关思考重发 ⇒ 按客户端要的形状回。

        返回 True 表示"已经回过应答了"。任何异常都返回 False（调用方走原来的转发）。

        ⚠️ **只给非流式客户端用**（`stream:false`）：它本来就不是逐字显示的，
        所以"先整段取回、空了就重发"没有任何体验损失 ✓。
        流式客户端（App 默认）**保持原样**，只在转发时检测空正文并记日志 ✓。
        为什么这么做：推理和正文抢同一份输出上限，或模型"想完就收尾" ⇒ 客户端只收到空 ✗。
        重发一次（这次关思考）几乎必然拿到正文 ✓，而思考档本来就要等十几秒，体验差别很小。
        """
        t0 = time.time()          # 计时起点（2026-10-18：面板要显示这一轮等了多久）✓
        try:
            p1 = json.loads(json.dumps(payload, ensure_ascii=False))
            p1["stream"] = False
            st1, b1 = self._upstream_post(url, p1)
            if st1 != 200 or not b1:
                return False
            content, reasoning = _split_openai_reply(b1)
            # ⚠️ 2026-10-14：这条非流式路径也要留痕（它不走主转发的循环）✓
            if _hit_length_limit(b1):
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + _LENGTH_NOTE
                self.server.log(f"[截断] 这条回复到了输出上限（finish_reason=length，非流式路径）—— "
                                f"把客户端的 max_tokens / num_predict 调大即可 ✓")
            if not content.strip():
                p2 = json.loads(json.dumps(payload, ensure_ascii=False))
                p2["stream"] = False
                if think_on:
                    p2["reasoning_effort"] = "none"     # 思考档：关掉思考，最可能拿到正文
                how = "关思考重发" if think_on else "原样重发"
                st2, b2 = self._upstream_post(url, p2)
                if st2 != 200 or not b2:
                    return False
                c2, _ = _split_openai_reply(b2)
                if not c2.strip():
                    return False            # 第二次还是空 ⇒ 交给原来的转发（至少形状不变）
                b1 = _replace_openai_content(b1, c2)
                note = (f" 空回复兜底({how}：推理{len(reasoning)}字→正文{len(c2)}字)")
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + note
                self.server.log(f"[空回复兜底] 第一次正文为空（推理 {len(reasoning)} 字）"
                                f"⇒ {how}成功（{len(c2)} 字）")
            want_stream = payload.get("stream") is None or bool(payload.get("stream"))
            # ⚠️ 2026-10-18：这条路（非流式 / 思考兜底）**不走主转发的循环**，
            #    所以用时得在这儿自己补记 —— 否则面板上会显示 `首字 0.0s`（假数据）✓
            _ftxt = _split_openai_reply(b1)[0]
            _el = time.time() - t0
            _p = _usage_from_tail(b1)
            if _p <= 0 and isinstance(payload, dict) \
                    and isinstance(payload.get("messages"), list):
                _p = int(sum(len(_msg_text(m)) for m in payload["messages"])
                         * CTX_TOK_PER_CHAR) + 8 * len(payload["messages"])
            # ⚠️ 只在拿到正数时才覆盖 `ptok` —— 否则面板会从 479 掉回 0（看着像坏了）✓
            _d = {"ttft": _el, "total": _el, "chars": len(_ftxt),
                  "aborted": False, "pending": False}
            if _p > 0:
                _d["ptok"] = _p
            LAST_CHAT.update(_d)
            note_reply(self._reqinfo.get("path", ""), _ftxt, b1, payload)
            self.server.log(f"[用时] {self._reqinfo.get('path', '')}（非流式兜底）| 总 {_el:.1f}s | "
                            f"提示 {_p} tok | 回复 {len(_ftxt)} 字"
                            + (" ★慢：超过 20 秒，客户端很容易超时" if _el > 20 else ""))
            if want_stream:
                out = _openai_json_to_sse(b1)
                self.send_response(st1)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Transfer-Encoding", "chunked")
                self._cors()
                self.end_headers()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(out), out))
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            else:
                self.send_response(st1)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b1)))
                self._cors()
                self.end_headers()
                self.wfile.write(b1)
            return True
        except Exception as e:
            sys.stderr.write(f"  [空回复兜底] 出错，退回普通转发：{type(e).__name__} {e}\n")
            sys.stderr.flush()
            return False

    def _extract_thought(self, data: bytes, path: str) -> str:
        r"""从上游响应里取"推理内容"（`/api/chat` 是 `message.thinking`，
        `/v1` 是 `choices[0].message.reasoning`）。"""
        try:
            d = json.loads(data.decode("utf-8", "replace"))
        except Exception:
            return ""
        if path == "/api/chat":
            return ((d.get("message") or {}).get("thinking") or "").strip()
        m = ((d.get("choices") or [{}])[0].get("message") or {})
        return (m.get("reasoning") or m.get("reasoning_content") or "").strip()

    def peek_thoughts(self, n: int = 1) -> str:
        r"""把本地过程日志的最后 n 条渲染成网页（只读本机文件）。"""
        txt = ""
        try:
            if THOUGHT_LOG.exists():
                txt = THOUGHT_LOG.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        parts = [p for p in txt.split("\n===== ") if p.strip()]
        picked = parts[-max(1, min(5, n)):] if parts else []
        out = ["<!doctype html><html><head><meta charset=\"utf-8\">",
               "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
               "<title>最近一条思考</title><style>",
               "body{background:#111;color:#ddd;font:15px/1.7 system-ui;margin:0;padding:14px}",
               "pre{white-space:pre-wrap;word-break:break-word;background:#181818;padding:10px;",
               "border-radius:8px;font:13px/1.6 ui-monospace,Consolas,monospace}",
               "a{color:#6cf}h3,h4{margin:10px 0 4px}code{color:#9c9}",
               "</style></head><body>",
               f"<h3>👀 最近 {len(picked)} 条思考过程</h3>",
               f"<p>来源：<code>{_html.escape(str(THOUGHT_LOG))}</code><br>"
               f"记录里共 <b>{len(parts)}</b> 条 ｜ 记录开关：<b>{'开' if THOUGHT_REC else '关'}</b> ｜ "
               f"思考模式：<b>{THINK_MODE}</b></p>",
               "<p><a href=\"/__peek?n=1\">最近 1 条</a> ｜ <a href=\"/__peek?n=3\">最近 3 条</a>"
               " ｜ <a href=\"/plain\">← 回面板</a></p>"]
        if not picked:
            out.append("<p>还没有内容 ✓ 需要同时满足：<b>思考模式 = local</b>、"
                       "<b>记录 = 开</b>、<b>模型会思考（35B；9B 不会）</b>。</p>")
        for p in picked:
            head, _, rest = p.partition("\n")
            out.append(f"<h4>{_html.escape(head.strip())}</h4>"
                       f"<pre>{_html.escape(rest[:20000])}</pre>")
        out.append("</body></html>")
        return "\n".join(out)

    def _save_thought(self, thought: str, path: str) -> None:
        r"""把推理过程写进本地日志（`_备份\思考过程.log`），只在本机、不进回复。

        清理策略（2026-10-08 按用户问的"怎么清理"改成这样）：
          · 超过 `THOUGHT_LOG_MAX`（2 MB）时 ⇒ **只丢最老的，保留最近的一半**（不是全清）；
          · 想干脆不记录：启动加 `--no-thought-log`（那样连文件都不建）。
        """
        if not THOUGHT_REC or getattr(self.server, "no_thought_log", False):
            return
        try:
            if THOUGHT_LOG.exists() and THOUGHT_LOG.stat().st_size > THOUGHT_LOG_MAX:
                try:
                    keep = THOUGHT_LOG.read_text(encoding="utf-8", errors="replace")
                    THOUGHT_LOG.write_text(
                        "（…更早的过程已自动清理…）\n" + keep[-(THOUGHT_LOG_MAX // 2):],
                        encoding="utf-8")
                except Exception:
                    THOUGHT_LOG.write_text("", encoding="utf-8")
            with THOUGHT_LOG.open("a", encoding="utf-8", newline="\n") as f:
                f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {path}  "
                        f"{len(thought)} 字 =====\n{thought}\n")
            sys.stderr.write(f"  [本地思考] 推理 {len(thought)} 字已写 "
                             f"{THOUGHT_LOG.name}（过程不外发）\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"  [本地思考] 写过程日志失败：{type(e).__name__}\n")

    def _deny(self, code: int, why: str) -> None:
        body = json.dumps({"error": why}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        r"""口令校验 —— **兼容各种客户端传 Key 的方式**（2026-10-03 扩，目标：任何 App 都能接）。

        为什么要兼容这么多种：不同平台把"API Key"塞的地方完全不一样，只认一种就会
        让一半客户端连不上（都会表现成 401）：
          · `Authorization: Bearer <key>`  —— OpenAI 系（Chatbox 选 OpenAI、NextChat…）
          · `Authorization: <key>`         —— 有些客户端不加 Bearer
          · `x-api-key` / `api-key`        —— Anthropic 风格、部分插件
          · `?api_key=` / `?key=`          —— 少数客户端只会在 URL 上带
          · `x-goog-api-key`               —— Google 风格
        另外 **空 Key 也放行**：Ollama 原生 API 本来就没有鉴权，`127.0.0.1` 上的
        AstrBot 就是空 Key 直连的；而"能不能进来"由防火墙 + 只监听本机决定。
        想强制必须带 Key：启动加 `--require-key`（那时空 Key 会 401）。
        """
        if not self.server.token:
            return True
        if not getattr(self.server, "require_key", False) and not self._presented_key():
            return True
        for cand in self._presented_key():
            if secrets.compare_digest(cand, self.server.token):
                return True
        return False

    def _presented_key(self) -> list:
        """把这次请求里所有"可能是 Key"的值收集出来（去重、去空）。"""
        vals = []
        auth = (self.headers.get("Authorization") or "").strip()
        if auth:
            vals.append(auth[7:].strip() if auth.lower().startswith("bearer ") else auth)
        for h in ("x-api-key", "api-key", "x-goog-api-key", "x-auth-token", "token"):
            v = (self.headers.get(h) or "").strip()
            if v:
                vals.append(v)
        q = urllib.parse.urlparse(self.path).query
        if q:
            for k, v in urllib.parse.parse_qsl(q):
                if k.lower() in ("api_key", "apikey", "key", "token") and v.strip():
                    vals.append(v.strip())
        return [v for v in dict.fromkeys(vals) if v]

    def _path(self) -> str:
        return self.path.split("?", 1)[0].split("#", 1)[0]

    def _has_correct_key(self) -> bool:
        r"""这次请求带的口令**真的对不对**（和 `_authed` 的区别：这里**不 fail-open**）。

        为什么要单独一个：`_authed()` 在"没带 Key"时是**放行**的（因为 Ollama 原生 API
        本来就没鉴权、网关默认也不强制口令）。但"读人格正文"这种要经网点的东西不能
        fail-open —— 必须**确实**带对了口令才算数。
        """
        tok = getattr(self.server, "token", "")
        if not tok:
            return False
        return any(secrets.compare_digest(v, tok) for v in self._presented_key())

    def _is_local(self) -> bool:
        """请求是不是从**这台电脑本身**发起的（用于"只给本机看 Key"）。"""
        host = (self.client_address[0] or "").strip()
        return host in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1")

    # ── 访问门（2026-10-06，见文件上方 ACCESS_* 的说明）─────────────────────────
    # 放行的：本机、API（/v1/* /api/*）、APK 下载、授权端点本身；
    # 其余（控制台 /、/plain、/__*）都要通行证。
    ACCESS_OPEN = ("/__auth", "/favicon.ico")
    ACCESS_OPEN_PREFIX = ("/apk",)

    def _cookie(self, name: str) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v.strip()
        return ""

    def _needs_access(self, path: str) -> bool:
        if path in self.ACCESS_OPEN or path.startswith(self.ACCESS_OPEN_PREFIX):
            return False
        # 安装包下载放行：新手机要能先装 App（下载本身不敏感，且地址带 .apk/.apk.zip 后缀）
        if path.endswith(".apk") or path.endswith(".apk.zip"):
            return False
        if path.startswith("/v1/") or path.startswith("/api/"):
            return False              # API 那条线仍走"口令"策略（要强制就 --require-key）
        return True                   # /、/plain、/__* 一律要通行证

    def _access_ok(self) -> bool:
        r"""本机永远放行；否则看通行证（**会话表**里查得到才算）。

        2026-10-06 下午改成会话表（原来是无状态的"码哈希"）—— 因为用户要
        "网页上能管理授权、自由解除"：无状态就没法列出设备、也没法单独踢人。
        """
        if self._is_local():
            return True               # 本机永远放行：否则一旦改错就把自己关在门外
        return session_touch(self._cookie(ACCESS_COOKIE))

    def _gate(self, path: str) -> bool:
        r"""访问门：返回 True = 放行；False = **已经回过应答**，调用方直接 return。"""
        if not self._needs_access(path) or self._access_ok():
            return True
        ip = self.client_address[0]
        locked = access_locked_for(ip)
        self._log(f"🔒 未授权访问被挡：{path}（{ip}）"
                  + (f"｜该 IP 仍在锁定期 {locked} 秒" if locked else ""))
        if self.command == "GET" and path in ("/", "/plain"):
            self._html(200, access_page(locked=locked))     # 200：让手机正常渲染这个页面
        else:
            self._json(403, {"error": "需要授权：先在电脑上查授权码（获取API密钥.bat 或网关窗口），"
                                      "再用手机浏览器打开 http://<电脑IP>:11435/ 输一次（之后长期有效）",
                             "locked_for": locked})
        return False

    def _redirect(self, url: str, cookie: str = "") -> None:
        self.send_response(302)
        self.send_header("Location", url)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _do_peek(self) -> None:
        r"""/__peek：网页上的「👀 看最近一条思考」——**只读本机**那份过程日志。

        单独成方法，是因为 `_do_access_admin` 开头就把非 POST 挡掉了（防 CSRF），
        而查看是纯读取、用 GET 的链接最方便（尤其手机上）。
        """
        n = 1
        try:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            n = int((q.get("n") or ["1"])[0])
        except Exception:
            n = 1
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(self.peek_thoughts(n).encode("utf-8"))
        return

    def _maybe_continue(self, url: str, payload: dict, path: str,
                        text: str, length_hit: bool) -> str:
        r"""看这段是不是"没写完"，必要时**补写一次**；返回补充文本（没有就空串）。

        ⚠️ 2026-10-18 按 GPT 验收意见重构：原来这段代码只写在"普通流式"分支里，
        而**兼容模式分支在它之前就 return 了 ⇒ 兼容模式下续写永远不触发**（实测日志
        里兼容模式仍有 8/16 字的回复、`[续写]` 记录为 0）。现在两个分支都调这一个方法 ✓
        ⚠️ `length_hit=True`（撞 finish_reason=length）时**不补** —— 那是客户端/用户
        刻意设的输出上限，网关不擅自突破 ✓
        """
        if length_hit or not text or not continue_on() or not looks_unfinished(text):
            return ""
        try:
            p3 = json.loads(json.dumps(payload, ensure_ascii=False))
            p3["stream"] = False
            p3.pop("tools", None)
            p3["messages"] = list(p3.get("messages") or []) + [
                {"role": "assistant", "content": text},
                {"role": "user",
                 "content": "（接着上面那句写完，从断掉的地方继续，不要重复前面的内容）"},
            ]
            st3, b3 = self._upstream_post(url, p3)
            if st3 != 200 or not b3:
                return ""
            if path == "/v1/chat/completions":
                cont, _ = _split_openai_reply(b3)
            else:
                cont = "".join(_pieces(json.loads(b3.decode("utf-8", "replace"))))
            return _dedupe_overlap(text, (cont or "").strip()).strip()
        except Exception as e:
            sys.stderr.write(f"  [续写] 出错：{type(e).__name__}\n")
            sys.stderr.flush()
            return ""

    def _write_sse_text(self, text: str) -> None:
        r"""把一段纯文字按 40 字/帧发成 OpenAI SSE 增量（自动续写补发用）✓"""
        try:
            step = 40
            for i in range(0, max(step, len(text)), step):
                piece = text[i:i + step]
                if not piece:
                    continue
                delta = {"content": piece}
                if i == 0:
                    delta["role"] = "assistant"
                frame = json.dumps({"id": "chatcmpl-cont",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()), "model": "",
                                    "choices": [{"index": 0, "delta": delta,
                                                 "finish_reason": None}]},
                                   ensure_ascii=False).encode("utf-8")
                out = b"data: " + frame + b"\n\n"
                self.wfile.write(b"%x\r\n%s\r\n" % (len(out), out))
            self.wfile.flush()
        except Exception:
            pass

    def _do_upload(self) -> None:
        r"""手机上传文件 ⇒ 存 `C:\LocalAI-Assistant\聊天文件\`（2026-10-18 加）。

        纯 HTML 表单（`enctype=multipart/form-data`）⇒ 手机上"会删脚本"的浏览器也能用 ✓
        只做落地：不解析、不喂模型；文件名净化 + 时间戳前缀（同名不覆盖）；
        上限 25 MB。⚠️ 走和其他 `__` 端点同一道授权门（`_gate` 在 `_handle` 最前面已过）✓
        """
        ip = self.client_address[0]
        if self.command != "POST":
            self._html(405, "<h3>上传要用 POST</h3><p>回控制台用表单上传。</p>"
                            "<p><a href='/'>← 回控制台</a></p>")
            return
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in ctype.lower():
            self._html(400, "<h3>上传失败</h3><p>不是 multipart/form-data（是不是用错了表单？）</p>"
                            "<p><a href='/'>← 回控制台</a></p>")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n <= 0:
            self._html(400, "<h3>上传失败</h3><p>没收到数据（Content-Length 缺失或为 0）</p>"
                            "<p><a href='/'>← 回控制台</a></p>")
            return
        if n > CHAT_FILES_MAX:
            self._html(413, f"<h3>文件太大</h3><p>{n / 1048576:.1f} MB &gt; "
                            f"{CHAT_FILES_MAX // 1048576} MB 上限</p>"
                            f"<p><a href='/'>← 回控制台</a></p>")
            return
        raw = b""
        try:
            raw = self.rfile.read(n)
        except Exception as e:
            self._html(400, f"<h3>读数据失败</h3><p>{type(e).__name__}</p>"
                            f"<p><a href='/'>← 回控制台</a></p>")
            return
        fname, data = "", b""
        try:
            msg = email.parser.BytesParser().parsebytes(
                b"Content-Type: " + ctype.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                # ⚠️ 2026-10-18：**文件名直接从原始字节里抓**。
                #    浏览器的中文文件名是**原始 UTF-8 字节**，`email` 库按 latin-1/surrogateescape
                #    解出来就是 "������.txt"，转不回去 ⇒ 干脆正则原始 raw（含 RFC5987 写法）✓
                fn = ""
                m5987 = re.search(rb"filename\*=UTF-8''([^;\r\n]+)", raw, re.I)
                if m5987:
                    fn = urllib.parse.unquote(m5987.group(1).decode("utf-8", "replace"))
                else:
                    mraw = re.search(rb'filename="([^"]*)"', raw)
                    if mraw:
                        fn = mraw.group(1).decode("utf-8", "replace")
                if not fn:
                    fn = part.get_filename() or ""
                if not fn:
                    continue
                payload = part.get_payload(decode=True) or b""
                if payload:
                    fname, data = fn, payload
                    break
        except Exception as e:
            self.server.log(f"[上传] {ip} 解析失败：{type(e).__name__}")
        if not data:
            self._html(400, "<h3>上传失败</h3><p>表单里没找到文件（要选一个文件再点上传）</p>"
                            "<p><a href='/'>← 回控制台</a></p>")
            return
        # 文件名净化：去掉路径/控制字符，限长；加时间戳前缀 ⇒ 同名不覆盖 ✓
        clean = re.sub(r'[\\/:*?"<>|\r\n\t\x00-\x1f]', "_", str(fname)).strip() or "upload.bin"
        clean = os.path.basename(clean)[:120]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = CHAT_FILES_DIR / f"{stamp}-{clean}"
        try:
            CHAT_FILES_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        except Exception as e:
            self._html(500, f"<h3>写盘失败</h3><p>{type(e).__name__}: {e}</p>"
                            f"<p><a href='/'>← 回控制台</a></p>")
            return
        self.server.log(f"[上传] {ip} 存了 {dest.name}（{len(data)} 字节）")
        self._html(200, "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                        "<div style='font:15px/1.7 system-ui,sans-serif;max-width:620px;margin:20px auto;"
                        "padding:0 16px'>"
                        f"<h3>✅ 已存到「聊天文件」</h3><p><code>{dest.name}</code>"
                        f"（{len(data):,} 字节）</p>"
                        f"<p style='color:#888'>完整路径：<code>{dest}</code></p>"
                        "<p><a href='/'>← 回控制台</a></p></div>")

    def _do_access_admin(self, path: str) -> None:
        r"""授权管理：换入网码 / 解除某台或全部设备。

        只认 **POST**：cookie 是 `SameSite=Lax` ⇒ 跨站表单带不上它 ⇒ 天然挡掉 CSRF
        （否则别人做个网页就能让你的浏览器去"解除全部设备"）。
        """
        ip = self.client_address[0]
        if self.command != "POST":
            self._html(405, "<h3>这个操作只能用 POST</h3><p>回控制台点按钮即可。</p>"
                            "<p><a href='/'>← 回控制台</a></p>")
            return
        fields: dict = {}
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(n, 4096)) if 0 < n <= 4096 else b""
            fields = {k: v[0] for k, v in
                      urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}
        except Exception:
            fields = {}

        if path == "/__newcode":
            fresh = load_access_code(new=True)
            self.server.log(f"[访问授权] {ip} 换了入网码（改成 {fresh}）—— "
                            f"已授权的 {len(sessions_list())} 台设备**不受影响**")
            self._redirect("/?ok=newcode")
            return

        if path == "/__temp":
            got = save_temperature((fields.get("v") or "").strip())
            self.server.log(f"[温度] {ip} 把温度设成 {got}（下一条消息生效）")
            self._redirect("/?ok=temp")
            return

        if path == "/__mode":
            got = save_send_mode((fields.get("v") or "").strip())
            self.server.log(f"[发送方式] {ip} 改成 {SENDMODE_LABEL.get(got, got)}（下一条消息生效）")
            self._redirect("/?ok=mode")
            return

        if path == "/__streamsan":
            got = save_streamsan((fields.get("v") or "").strip())
            self.server.log(f"[流式洗文本] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=streamsan")
            return

        if path == "/__md":
            got = save_md((fields.get("v") or "").strip())
            self.server.log(f"[去记号] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=md")
            return

        if path == "/__nl":
            got = save_nl((fields.get("v") or "").strip())
            self.server.log(f"[压空行] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=nl")
            return

        if path == "/__hist":
            got = save_hist((fields.get("v") or "").strip())
            self.server.log(f"[历史净化] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=hist")
            return

        if path == "/__preset":
            got = apply_preset((fields.get("v") or "").strip())
            self.server.log(f"[档位] {ip} 切到 {PRESET_LABEL.get(got, got)}"
                            f"（tools={'on' if tools_on() else 'off'} / "
                            f"compat={'on' if compat_on() else 'off'} / "
                            f"cont={'on' if continue_on() else 'off'} / "
                            f"hist={'on' if hist_on() else 'off'}）")
            self._redirect("/?ok=preset")
            return

        if path == "/__compat":
            got = save_compat((fields.get("v") or "").strip())
            self.server.log(f"[兼容模式] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=compat")
            return

        if path == "/__cont":
            got = save_continue((fields.get("v") or "").strip())
            self.server.log(f"[自动续写] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=cont")
            return

        if path == "/__tools":
            got = save_tools((fields.get("v") or "").strip())
            self.server.log(f"[工具开关] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=tools")
            return

        if path == "/__strip":
            got = save_strip_limit((fields.get("v") or "").strip())
            self.server.log(f"[长度消毒] {ip} 把它设成 {got}（下一条消息生效）")
            self._redirect("/?ok=strip")
            return

        if path == "/__budget":
            try:
                n = int((fields.get("n") or "").strip())
            except Exception:
                n = LOCAL_BUDGET_DEFAULT
            got = save_local_budget(n)
            self.server.log(f"[本地思考] {ip} 把第一轮预算改成 {got}（下一条消息生效）")
            self._redirect("/?ok=budget")
            return

        if path == "/__warm":
            want = (fields.get("model") or "").strip()
            got = save_warm_model(want)
            if not _WARM_STATE["busy"]:
                threading.Thread(target=_warm_worker, args=(got,), daemon=True).start()
            self.server.log(f"[预热] {ip} 选了 {got}，已在后台开始预热")
            self._redirect("/?ok=warm")
            return

        if path == "/__thinklog":
            act = (fields.get("act") or "").strip().lower()
            if act in ("rec_on", "rec_off"):
                save_thought_rec(act == "rec_on")
                self.server.log(f"[思考过程] {ip} 把记录改成 "
                                f"{'开' if THOUGHT_REC else '关'}")
            elif act == "clear":
                n = 0
                try:
                    if THOUGHT_LOG.exists():
                        n = THOUGHT_LOG.stat().st_size
                        THOUGHT_LOG.write_text("", encoding="utf-8")
                except Exception:
                    pass
                self.server.log(f"[思考过程] {ip} 清空了过程日志（释放 {n/1024:.0f} KB）")
            elif act == "delete":
                try:
                    THOUGHT_LOG.unlink(missing_ok=True)
                except Exception:
                    pass
                self.server.log(f"[思考过程] {ip} 删除了过程日志文件")
            self._redirect("/?ok=thinklog")
            return

        if path == "/__think":
            want = (fields.get("mode") or "").strip().lower()
            got = save_think_mode(want)
            self.server.log(f"[思考模式] {ip} 改成 {got}（{THINK_LABEL.get(got, '')}）")
            self._redirect("/?ok=think")
            return

        if str(fields.get("all") or "") in ("1", "true", "yes"):
            n = session_revoke_all()
            self.server.log(f"[访问授权] {ip} 解除了**全部**设备（{n} 台）")
            self._redirect("/?ok=all")
            return

        tok = (fields.get("tok") or "").strip()
        me = self._cookie(ACCESS_COOKIE)
        done = session_revoke(tok)
        if tok and tok == me:                       # 把自己踢了 ⇒ 顺手清掉自己的 cookie
            self.server.log(f"[访问授权] {ip} 解除了**自己这台**设备")
            self._redirect("/", cookie=f"{ACCESS_COOKIE}=; Path=/; Max-Age=0")
            return
        self.server.log(f"[访问授权] {ip} 解除设备 {tok[:8]}…（{'成功' if done else '没找到'}）")
        self._redirect("/?ok=revoked" if done else "/?ok=notfound")

    def _do_auth(self) -> None:
        r"""/__auth：输一次授权码 ⇒ 种一个一年期的 cookie（"永久可访问"）。

        防爆破：连错 5 次开始锁（5 分钟起、翻倍、最多 1 小时），锁定期内连正确码也拒。
        """
        ip = self.client_address[0]
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if self.command == "GET" and (q.get("out") or q.get("logout")):
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{ACCESS_COOKIE}=; Path=/; Max-Age=0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._log(f"🔓 {ip} 主动注销了通行证")
            return

        locked = access_locked_for(ip)
        if locked:
            self._html(429, access_page(locked=locked))
            return

        code_in = (q.get("code") or [""])[0].strip()
        if not code_in and self.command == "POST":
            ctype = (self.headers.get("Content-Type") or "").lower()
            try:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(min(n, 4096)) if 0 < n <= 4096 else b""
                if "application/json" in ctype:
                    code_in = str((json.loads(raw.decode("utf-8", "replace")) or {}).get("code", "")).strip()
                else:
                    code_in = (urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
                               .get("code") or [""])[0].strip()
            except Exception:
                code_in = ""

        if code_in and secrets.compare_digest(code_in, access_code()):
            clear_access_fail(ip)
            tok = session_new(ip, self.headers.get("User-Agent") or "")
            self.send_response(302)
            self.send_header("Location", "/?ok=1")
            self.send_header("Set-Cookie",
                             f"{ACCESS_COOKIE}={tok}; "
                             f"Path=/; Max-Age={ACCESS_MAX_AGE}; HttpOnly; SameSite=Lax")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.server.log(f"[访问授权] {ip} 通过（已发一年期通行证 {tok[:8]}…，"
                            f"当前共 {len(sessions_list())} 台）")
            return

        wait = note_access_fail(ip) if code_in else 0
        self.server.log(f"[访问授权] {ip} 输错授权码"
                        + (f"（连错 {_FAILS[ip][0]} 次，锁 {wait} 秒）" if wait else ""))
        self._html(200, access_page(err="授权码不对，再试一次。" if code_in else "", locked=wait))


    def _html(self, code: int, body: str) -> None:
        r"""给**表单提交/浏览器直接访问**用的极简 HTML 响应（不需要 JS）。"""
        page = ("<!DOCTYPE html><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<style>body{font:16px/1.7 system-ui,'Microsoft YaHei';background:#0f1115;"
                "color:#e6e6e6;padding:24px;max-width:640px;margin:auto}"
                "a{color:#7aa2f7}li{margin:4px 0}</style>" + body)
        raw = page.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # ⚠️ 必须显式禁缓存（2026-10-05 加的，用户报"资源面板一直读取中"）：
        # 这些 GET 响应以前**没有任何缓存指令**，手机浏览器把**第一次**那个
        # `cpu_pct: null` 缓存住了 ⇒ 页面永远显示"读取中…"。别去掉这两行。
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        r"""给浏览器客户端（Page Assist 这类插件）发 CORS 头。

        为什么必须有（2026-10-03 补，起因：读了一篇把 `OLLAMA_ORIGINS=*` 当必做项的教程）：
            浏览器插件是从**网页上下文**发请求的，浏览器会先发一个 `OPTIONS` 预检，
            响应里没有 `Access-Control-Allow-*` 就直接被拦掉 —— 表现就是"插件连不上"。
            原版 Ollama 靠 `OLLAMA_ORIGINS=*` 解决；我们这边是网关，所以由网关发这些头。

        ⚠️ 为什么敢用 `*`：**这个网关有口令**（`Authorization: Bearer`）。CORS 只是让浏览器
        放行脚本发请求，拿不到口令照样 **401**。原版 Ollama 没有认证，才只能靠"少暴露"兜。
        想收紧：加 `--cors-origin http://localhost:3000`（只允许指定来源）。
        """
        allow = self.server.cors_origin or "*"
        origin = self.headers.get("Origin")
        if origin and allow != "*" and origin != allow:
            return                     # 不在白名单：不发头，交给浏览器拦
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         self.headers.get("Access-Control-Request-Headers")
                         or "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        # Chrome 的「私有网络访问」预检（网页 → 局域网设备）需要这个才放行
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _session_key(self) -> str:
        r"""这次请求算哪个会话：**来源 IP + 客户端**（默认），或 `--session-header` 指定的头。

        ⚠️ 2026-10-05 改：原来**只按来源 IP** —— 手机 App（okhttp）和手机浏览器（网页版）
        来自同一个 IP，于是**共用一份记忆**：网页版会拿到 App 那套协议历史
        （一堆 `<add:…>` / `<2s` 标记 + 极短回复），跟着学成"说一半就省略 + 甩标记"。
        实测证据：网页版明明**没发任何 system**，回答里却冒出了 `<add:…>` —— 就是历史教出来的。
        现在按"IP + User-Agent 指纹"分：App、网页版、别的客户端各记各的。
        """
        mode = getattr(self.server, "session_mode", "ip") or "ip"
        if mode.startswith("header:"):
            v = (self.headers.get(mode[7:]) or "").strip()
            if v:
                return f"{mode[7:]}:{v}"
        ip = self.client_address[0]
        ua = (self.headers.get("User-Agent") or "").strip()
        if not ua:
            return f"ip:{ip}"
        tag = hashlib.blake2s(ua.encode("utf-8", "replace"), digest_size=4).hexdigest()
        return f"ip:{ip}#{tag}"

    def _compress_if_needed(self, key: str, sess: dict) -> None:
        r"""(保留但**不在请求路径上**调用了) —— 压缩现在全在响应之后的**后台线程**里做，
        见 `_remember` / `_compress_now`。放后台是为了不拖慢本次回复：
        摘要要跑一次小模型（几秒~十几秒），放前面会让用户等。
        """
        return

    def _handle(self, method: str) -> None:
        path = self._path()

        # 请求日志要用的"形状"（**不记正文、不记口令**）先抓住：
        # ① 请求行在这里立刻落盘；② 结果行由 `send_response` 补上；
        # 于是"手机到底请求了什么"在日志里是一条两行的完整记录。
        self._reqinfo = {
            "method": method,
            "path": self.path,
            "ip": self.client_address[0],
            "host": self.headers.get("Host") or "",
            "origin": self.headers.get("Origin") or "",
            "auth": self._auth_shape(),
            "payload": "",
            "search": "",
        }
        self._log(self._req_line())

        # ---- 访问门（2026-10-06）：局域网上的陌生设备只能看到"输授权码"那一页 ----
        # 放行：本机、API（/v1/* /api/*）、APK 下载、/__auth 本身。详见上方 ACCESS_* 说明。
        if not self._gate(path):
            return
        # ---- /__auth：输授权码 ⇒ 种一年期 cookie（之后"永久"不用再输）----
        if path == "/__auth":
            self._do_auth()
            return
        # ---- 授权管理（2026-10-06 下午加）：换入网码 / 逐个或全部解除设备 ----
        if path == "/__peek":
            self._do_peek()
            return
        # ⚠️ 2026-10-18 加：本机专用 —— 看**最后一次回复的原文尾部 + 结尾标记**
        #    （诊断"手机端回复被截断"用；`./__` 端点本来就要授权，手机读不到）✓
        if path == "/__peek_reply":
            self._json(200, {"last": LAST_REPLY, "recent": LAST_REPLIES} if LAST_REPLY
                           else {"note": "还没抓到回复（先让人发一条）", "recent": []})
            return
        # ⚠️ 2026-10-18：手机上传文件（表单 POST multipart）⇒ 存 `C:\LocalAI-Assistant\聊天文件\` ✓
        if path == "/__upload":
            self._do_upload()
            return
        if path in ("/__newcode", "/__revoke", "/__think", "/__thinklog", "/__warm", "/__budget", "/__temp", "/__strip", "/__tools", "/__cont", "/__compat", "/__preset", "/__md", "/__nl", "/__hist", "/__streamsan", "/__mode"):
            self._do_access_admin(path)
            return

        # `--v1-prefix`：把 Ollama 原生路径也暴露在 /v1 下（`/v1/api/chat`），
        # 给那些把 OpenAI 基址硬编码成 `.../v1` 的客户端 —— 它们才会去请求
        # `/v1/api/chat` 而不是 `/api/chat`。转发时把 `/v1` 去掉。
        forward_path = self.path
        if getattr(self.server, "v1_prefix", False) and path.startswith("/v1/api/"):
            path = path[3:]                      # /v1/api/chat → /api/chat
            forward_path = path + (("?" + urllib.parse.urlparse(self.path).query)
                                   if urllib.parse.urlparse(self.path).query else "")

        # `--debug` 时把方法/路径/来源/关键头记到 stderr（**不打印口令**）。
        # 留着它是因为真用得上：2026-10-03 排查"搜索没生效"就是靠它看出
        # **端口上跑的是旧进程**（新进程起不来、旧的一直占着 11435）。
        if getattr(self.server, "debug", False):
            hdrs = {k.lower(): v for k, v in self.headers.items()
                    if k.lower() in ("origin", "authorization", "access-control-request-method",
                                     "access-control-request-headers", "host", "referer")}
            if "authorization" in hdrs:
                hdrs["authorization"] = "Bearer <len=%d>" % len(hdrs["authorization"])
            sys.stderr.write(f"  [DBG] {method} {self.path} from={self.client_address[0]} "
                             f"local={self._is_local()} hdrs={hdrs}\n")
            sys.stderr.flush()

        # ---- 浏览器预检：直接放行（真正的门是口令，不在 CORS）----
        if method == "OPTIONS":
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # ---- 自带网页（公开，但**不含密钥**）----
        # 「不用脚本版」：给"会删掉内联脚本"的浏览器（vivo 自带浏览器实测就是这样）。
        if path == "/plain":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = (q.get("code") or [""])[0].strip()
            cookie_hdr = None
            ok_msg = ""
            if code:
                if use_ticket(code):
                    cookie_hdr = (f"{COOKIE_NAME}={self.server.token}; Path=/; "
                                  f"Max-Age=2592000; SameSite=Lax")
                    ok_msg = ("✅ 这台手机已授权（30 天内有效）：下面按「⏹ 停止模型」"
                              "**不用再填 Key**。")
                    self.server.log("[授权码] 手机用 4 位码授权成功，已种 cookie")
                else:
                    ok_msg = "❌ 授权码不对或已过期（在电脑上重新生成一个，10 分钟内有效）。"
                    self.server.log("[授权码] 手机填的码不对/过期")
            # 「模型 / 最近一次对话」（2026-10-06 傍晚加）：这一页每 3 秒自己重载，
            # 所以这两行会跟着动 —— 手机上不跑 JS 的浏览器用它看最准。
            ok_msg += (f"<p>模型：{model_line()}</p>"
                       f"<p>最近一次对话：{last_chat_line()}</p>")
            # 访问授权管理块
            if not getattr(self.server, "open_access", False):
                ok_msg += access_admin_block(self) + think_admin_block(self)
            body = render_plain(ok_msg).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            if cookie_hdr:
                self.send_header("Set-Cookie", cookie_hdr)
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            self.server.log(f"GET /plain 发出 {len(body)} 字节（不用脚本版）")
            return
        if path in ("/", "/index.html"):
            body = render_page(self).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # 页面也禁缓存：不然手机拿到的是旧版页面（新按钮/新逻辑看不到）
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            # 记下"这个设备拿到了多大一页" —— 2026-10-05 加：用户手机上看不到新按钮/
            # 新逻辑时，靠这行数字就能判断**他拿到的是新版还是缓存的旧版页面**。
            self.server.log(f"GET / 发出 {len(body)} 字节（这就是他拿到的页面；"
                            f"新版含 clientlog/pstat/PAGE_VER 三个标记）")
            return

        # ---- 取口令：**默认只有本机**能取（否则局域网里谁打开网页都拿到 key = 白设口令）----
        if path == "/__key":
            if not (self._is_local() or self.server.show_key_lan):
                self._json(403, {"error": "只有从这台电脑上打开本页才能取 Key。"
                                          "需要给别的设备看就在网关启动时加 --show-key-lan（有风险）"})
                return
            self._json(200, {"token": self.server.token,
                             "note": "这是访问本机模型的 API Key，请只填进你自己的设备"})
            return

        # ---- 人格（2026-10-05 加，给自带网页的"人格"下拉用）----
        # 列表（只有名字+字数）：谁都能看；正文：**本机，或者带上正确的 Key**。
        # 为什么正文要卡一道：那是用户的角色设定（几千~几万字），不该"局域网里谁打开网页都能读"。
        # 手机上的流程 = 先把 Key 粘进网页输入框（存在手机浏览器里），之后读人格就自动带上。
        if path == "/__personas":
            self._json(200, {"personas": list_personas()})
            return
        # 系统资源（自带网页那个面板用）。公开 —— 只是几个占用数字，不含密钥。
        if path == "/__stats":
            self._json(200, sys_stats())
            return
        # 手机上报（自带网页的 JS 把错误/状态发回来）。
        # 为什么要这个（2026-10-05）：用户在手机上说"还是一样"，可日志里**他手机的页面
        # 一次 `/__stats` 都没发** —— 我看不到他的控制台，只能让页面自己把话带回来。
        # 公开、无 Key（就是日志），单条截断，避免被灌爆。
        # 支持两种形态：① POST JSON（正常路径）；② GET `?m=`（**图片信标**，不依赖 fetch）。
        if path == "/__clientlog":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ua = (self.headers.get("User-Agent") or "")[:40]
            if q.get("m"):
                msg = (q.get("m") or [""])[0][:300]
                ver = (q.get("ver") or [""])[0][:24]
                self.server.log(f"[手机·信标] ver={ver} {ua} | {msg}")
            else:
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(min(n, 4096)) if 0 < n <= 4096 else b"{}"
                    d = json.loads(raw.decode("utf-8", "replace") or "{}")
                except Exception:
                    d = {}
                msg = str(d.get("msg") or "")[:300]
                ver = str(d.get("ver") or "")[:24]
                self.server.log(f"[手机] ver={ver} {ua} | {msg}")
            self._json(200, {"ok": True})
            return
        # 生成"手机授权码"：**只有本机或带对 Key** 才能生成（否则局域网谁都能停服务）。
        # 手机上在 `/plain` 里填这个 4 位码 → 服务端给它种 cookie → 之后免 Key。
        if path == "/__ticket":
            if method != "POST":
                self._deny(405, "/__ticket 只支持 POST")
                return
            if not (self._is_local() or self._has_correct_key()):
                self._json(403, {"error": "生成授权码要在电脑本机上，或先在页面上填好 Key"})
                return
            code = new_ticket()
            self.server.log(f"[授权码] 生成了 {code}（{TICKET_TTL // 60} 分钟内有效，"
                            f"在手机 /plain 页填它即可免 Key 停助手）")
            self._json(200, {"code": code, "ttl": TICKET_TTL})
            return
        # 手机 App 安装包（自己编译出来的那份）。
        # ⚠️ 2026-10-06 踩到的坑：一开始只有 `/apk` 这一个地址 —— 很多国产浏览器的下载器
        # **不看 `Content-Disposition`**，直接拿 URL 最后一段当文件名 ⇒ 存成 "apk"（**没后缀**）
        # ⇒ 系统认不出、提示"不支持应用类型"。所以现在：
        #   · `/任意名字.apk` → 发 APK（名字里的后缀让浏览器存对）；
        #   · `/任意名字.apk.zip` → 发一个装着 APK 的 zip（浏览器彻底不让下 apk 时的兜底）；
        #   · `/apk` → 老地址继续可用（对它做同样的事）。
        # **只发 `APK_DIR` 里最新的那个文件**，请求里的名字一律忽略（防目录穿越）。
        if path == "/apk" or path.endswith(".apk") or path.endswith(".apk.zip"):
            info = apk_info()
            if not info:
                self._html(404, "<h3>📦 还没有安装包</h3><p>把编译好的 APK 放进 "
                                f"<code>{APK_DIR}</code>，再刷新这一页。</p>"
                                "<p><a href='/'>← 返回</a></p>")
                return
            want_zip = path.endswith(".zip")
            src = info["path"]
            try:
                if want_zip:
                    data = apk_zip_bytes(info)          # 装着 APK 的 zip（lazy 生成并缓存）
                    ctype, fname = "application/zip", info["name"] + ".zip"
                else:
                    data = src.read_bytes()
                    ctype, fname = "application/vnd.android.package-archive", info["name"]
            except Exception as e:
                self._html(500, f"<h3>读文件失败</h3><p>{type(e).__name__}: {e}</p>")
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            self.server.log(f"GET {path} 发出 {fname}（{len(data)} 字节）")
            return
        # 不需要 JS 的探针②：**普通图片**（`<img src="/__imgprobe">`，1×1 透明 GIF）。
        # 任何会渲染 HTML 的浏览器都会取它 —— 有它 = "我发的 HTML 真的被渲染了"，
        # 那脚本不跑就只能是被**拦掉/删掉**（CSP、浏览器的网页净化/安全模式）。
        if path == "/__imgprobe":
            ua = (self.headers.get("User-Agent") or "")[:50]
            self.server.log(f"[手机·图片探针] 命中：页面 HTML 正在被渲染 | UA={ua}")
            gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
                   b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
                   b"\x00\x02\x02D\x01\x00;")
            self.send_response(200)
            self.send_header("Content-Type", "image/gif")
            self.send_header("Content-Length", str(len(gif)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(gif)
            return
        # 不需要 JS 的探针③：**CSS 里的背景图**（`body{background-image:url(/__cssprobe)}`）。
        # 只要有 CSS 引擎就会取 —— 即使浏览器的图片被禁也会取（它是样式资源）。
        if path == "/__cssprobe":
            ua = (self.headers.get("User-Agent") or "")[:50]
            self.server.log(f"[手机·CSS探针] 命中：页面样式正在被应用 | UA={ua}")
            body = b"/* css probe */"
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # 不需要 JS 的探针①：`<noscript>` 里挂一张样式表指向这里。
        # **JS 关掉的浏览器才会去取它** ⇒ 日志里出现这行就说明"这设备的 JS 没开"。
        # （2026-10-05 实测：他手机连这个都没取 ⇒ 说明 JS 是**开着**的，只是脚本被拦/被删）
        if path == "/__nojs":
            ua = (self.headers.get("User-Agent") or "")[:60]
            self.server.log(f"[手机·noscript] 命中：**这台设备的 JavaScript 没在执行** | UA={ua}")
            body = b"/* no-js probe */"
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # 停止"助手"（＝ 停止模型.bat 那三步）。
        # 这是唯一一个"会动你进程"的接口，不能让人在局域网里随手把服务停掉。
        # `?dry=1` 只看不杀。
        if path == "/__shutdown":
            if method != "POST":
                self._deny(405, "/__shutdown 只支持 POST")
                return
            # Key 可以放在 Authorization 头里，也可以放在**表单字段**里。
            # 2026-10-05 加表单通道的原因：用户手机上那个浏览器疑似**没执行 JS**
            # （按钮的 onclick 等于空的、页面一条上报都没有），而表单提交**不需要 JS**。
            form_key, is_form, form_dry = "", False, False
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/x-www-form-urlencoded" in ctype:
                is_form = True
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(min(n, 8192)) if 0 < n <= 8192 else b""
                    fields = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
                    form_key = (fields.get("key") or [""])[0].strip()
                    form_dry = (fields.get("dry") or [""])[0] in ("1", "true", "yes")
                except Exception:
                    pass
            tok = self.server.token or ""
            form_ok = bool(form_key) and bool(tok) and secrets.compare_digest(form_key, tok)
            # 也认 cookie：手机用 4 位授权码授权过一次后，`gw_stop` 里就是这个口令
            cookie_ok = False
            if not form_ok:
                ck = ""
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == COOKIE_NAME:
                        ck = v.strip()
                cookie_ok = bool(ck) and bool(tok) and secrets.compare_digest(ck, tok)
            if not (self._is_local() or self._has_correct_key() or form_ok or cookie_ok):
                if is_form:
                    why = "表单里没填 Key，也没授权过这台手机" if not form_key else "填的 Key 不对"
                    self.server.log(f"[停止模型]（表单）被拒：{why}")
                    self._html(403, "<h3>🔒 没能停：需要 Key 或授权</h3>"
                                    f"<p>{why}。</p>"
                                    "<p>两条路：① 在电脑上打开 "
                                    "<a href='http://127.0.0.1:11435/'>http://127.0.0.1:11435/</a> "
                                    "复制 Key，粘进表单再提交；② 在电脑上点「📱 生成手机授权码」，"
                                    "拿到 4 位数字后回到 "
                                    "<a href='/plain'>/plain</a> 页填一次，之后就不用再填了。</p>"
                                    "<p><a href='/plain'>← 回控制台</a></p>")
                else:
                    self._json(403, {"error": "停止模型需要先在页面上填好 Key（点「用这个 Key」），"
                                              "或在电脑本机上操作"})
                return
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            dry = form_dry or (q.get("dry") or ["0"])[0] in ("1", "true", "yes")
            # 「连网关一起停」默认**开**（用户 2026-10-05 要的：点停止模型 ⇒ 5 秒后关掉所有助手进程）。
            # `?all=0` 或启动加 `--keep-gateway` 可以只停模型、把网关留着。
            all_ = (q.get("all") or ["1"])[0] not in ("0", "false", "no")
            if getattr(self.server, "keep_gateway", False):
                all_ = False
            res = stop_local-assistant(dry=dry)
            if all_ and not dry:
                kill_gateway_later()            # 5 秒后（响应先发出去）连网关一起关
                res.append({"what": "网关（局域网 API · 本页）", "result": "5 秒后关闭"})
            self.server.log(f"{'[演练]' if dry else '[停止模型]'}"
                            f"{'（表单）' if is_form else ''} " +
                            "；".join(f"{x['what']}={x['result']}" for x in res))
            tail = ("<p><b>网关（本页）也将在 5 秒后关闭</b> —— 这个页面随后会连不上。"
                    "要重新启动：在电脑上双击 <code>启动局域网API.bat</code>（只起网关）"
                    "或 <code>启动AstrBot.bat</code>（起对话整套）。</p>"
                    if all_ and not dry else
                    "<p>网关（这个页面）还活着。要重新启动：在电脑上双击 "
                    "<code>启动AstrBot.bat</code>。</p>")
            if is_form:
                rows = "".join(f"<li>{x['what']} → <b>{x['result']}</b></li>" for x in res)
                self._html(200, f"<h3>{'🧪 演练结果（什么都没停）' if dry else '✅ 已执行'}</h3>"
                                f"<ul>{rows}</ul>" + tail +
                                "<p><a href='/plain'>← 回控制台</a></p>")
            else:
                self._json(200, {"ok": True, "dry": dry, "detail": res,
                                 "gateway_stops_in": 5 if (all_ and not dry) else 0,
                                 "note": "网关（本页）5 秒后关闭；要重新启动：在电脑上双击 "
                                         "启动局域网API.bat / 启动AstrBot.bat"
                                         if (all_ and not dry) else
                                         "网关（本页）还活着；要重新启动：在电脑上双击 "
                                         "启动AstrBot.bat"})
            return
        if path == "/__persona":
            if not (self._is_local() or self._has_correct_key()):
                self._json(403, {"error": "读人格正文需要：在本机打开本页，"
                                          "或先在页面上把 Key 填好（点「用这个 Key」）"})
                return
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            info = read_persona((q.get("name") or [""])[0])
            if info is None:
                self._json(404, {"error": f"没有这份人格：{(q.get('name') or [''])[0]!r}"})
                return
            self._json(200, info)
            return

        allow = ALLOW.get(path)

        pulled = path in PULL_PATHS and self.server.allow_pull
        admin = path in ADMIN_PATHS and self.server.allow_admin
        if allow is None and not pulled and not admin:
            # 不在白名单：既不是允许的聊天接口，也不是显式放行的拉取/管理接口
            if path in PULL_PATHS or path in ADMIN_PATHS:
                self._deny(403, f"这个接口默认被网关拦住（会改你的模型/磁盘）：{path}。"
                                f"确实需要就重启网关加 --allow-pull / --allow-admin")
            else:
                self._deny(404, f"网关不转发这个路径：{path}")
            return

        if allow is not None:
            get_ok, post_ok, _note = allow
            if (method == "GET" and not get_ok) or (method == "POST" and not post_ok):
                self._deny(405, f"{path} 不支持 {method}")
                return

        if not self._authed():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="ollama-gateway"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"error": "缺口令或口令不对（Authorization: Bearer <口令>）"},
                              ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # ---- 读请求体 ----
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._deny(413, f"请求体太大（{length} 字节）")
            return
        body = self.rfile.read(length) if length else None

        # 解析一次，日志与搜索共用（解析失败不影响转发）
        payload = None
        if body:
            try:
                payload = json.loads(body.decode("utf-8", "replace"))
            except Exception:
                payload = None
            self._note_payload(payload)

        # 思考模式（2026-10-08 改成可切换，见 apply_think_mode）：
        # auto = 客户端说了就听客户端的、没说就关；off = 无条件关；on = 无条件开。
        _think_note = apply_think_mode(payload, path)
        if _think_note:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + _think_note

        # ---- 温度（2026-10-09 加）：auto = 不动；选了数字就**强制覆盖** ----
        # 为什么要它：整理/抄数据这类活，温度 1.0（Modelfile 默认）必出错，
        # 实测降到 0.2 表格就对了 ✓。
        _t = temperature()
        if (_t != "auto" and isinstance(payload, dict)
                and path in ("/api/chat", "/v1/chat/completions")):
            try:
                _tv = float(_t)
                if path == "/api/chat":
                    _o = payload.get("options")
                    _o = dict(_o) if isinstance(_o, dict) else {}
                    _o["temperature"] = _tv
                    payload["options"] = _o
                else:
                    payload["temperature"] = _tv
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                    f" 温度={_t}(覆盖)"
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            except Exception as e:
                sys.stderr.write(f"  [温度] 应用失败：{type(e).__name__}\n")

        # ---- 输出上限兜底（2026-10-05 加，默认 2048）----
        # 为什么：Modelfile 里 35B 的 `num_predict` 是 **1024**（≈870 汉字），而项目自己的
        # 实测记着"12 个样本里 6 个停在半句"（见 `Modelfile.assistant-35b` 的注释）。
        # 网关替客户端兜一个更宽的上限；**客户端自己指定了就不动**。
        # ⚠️ 两个接口认的参数**不一样**（实测）：
        #     /v1/chat/completions → `max_tokens`            ✅（给它 `options.num_predict` 没用）
        #     /api/chat            → `options.num_predict`   ✅
        if (payload is not None and self.server.num_predict
                and path in ("/api/chat", "/v1/chat/completions")):
            n = self.server.num_predict
            # ⭐ 开了思考就必须给足预算（2026-10-08 实测）：
            #   推理和正文**共用同一个输出上限** ⇒ 上限 512 时推理烧掉 1668 字、
            #   `finish_reason=length`、**正文 0 字**（App 那边就是"没反应"）；
            #   1024 就能出正文，4096 更稳。所以思考开着时，把上限抬到
            #   `--think-min-predict`（默认 4096）——**客户端给了更小的值也会被抬**。
            # 直接看 payload 里最终生效的思考设置（不依赖前面的局部变量）
            if path == "/api/chat":
                _think_on = bool(payload.get("think"))
            else:
                _eff = payload.get("reasoning_effort")
                _think_on = bool(_eff) and str(_eff).strip().lower() not in (
                    "none", "off", "0", "false", "minimal")
            if _think_on and n < self.server.think_min_predict:
                n = self.server.think_min_predict
            if path == "/api/chat":
                opts = payload.get("options")
                opts = opts if isinstance(opts, dict) else {}
                _cur = opts.get("num_predict")
                if "num_predict" not in opts or (
                        _think_on and isinstance(_cur, int) and _cur < n):
                    opts["num_predict"] = n
                    payload["options"] = opts
                    self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                        f" num_predict={n}"
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            else:
                _cur = payload.get("max_tokens")
                if "max_tokens" not in payload or (
                        _think_on and isinstance(_cur, int) and _cur < n):
                    payload["max_tokens"] = n
                    self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                        f" max_tokens={n}"
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # ---- 强制关思考（2026-10-05 实测加，默认开）----
        # 起因：手机那条链路是**客户端自己发 system**，此时 35B **会思考** ——
        #   实测 `/v1/chat/completions` 非流式：finish_reason=length、usage=1024 tok、
        #   reasoning 3485 字、**content 0 字**；App 收到的就是"空回复"，或者被截断的短回复
        #   （网关日志里那几条"回复 0 字 / 61 字"就是这么来的）。
        # 为什么平时不思考：Modelfile 里那句 `SYSTEM """/no_think"""` ——
        #   **请求自带 system 时它根本不进上下文**（项目里早记过这个机制，`02` 坑 1 附近）。
        #   AstrBot 那条链路是在 provider 里设了 `ollama_disable_thinking`，只有网关这条路漏了。
        # ⚠️ 两个接口认的参数**不一样**（实测，也对应 `02` 坑 2）：
        #     /api/chat            → "think": false                ✅ 有效（13 tok）
        #     /v1/chat/completions → "reasoning_effort": "none"    ✅ 有效（20 tok）
        #                            "think": false               ❌ 无效（照样 1024 tok 全思考）
        # 想保留思考：启动加 `--allow-think`。

        # ---- 消息表收拾干净（2026-10-05 实测加）----
        # 客户端发来的表里经常有：连着两条一样的消息、结尾两条 assistant、content=null、
        # 结尾两条 assistant。前两样会**让模型照抄上一句**或**被 Ollama 400**。
        # ⚠️ 2026-10-14：`tool` 角色**不再丢**了（见 `_tidy` 里的说明）——
        #    实测 Ollama 与模型都支持工具调用，丢掉工具结果会让"调用工具"这条链断在网关 ✗
        # 这里在转发前统一收拾（不认的键保留，只动"要不要这条"）。见 `_tidy` 的说明。
        if (payload is not None and path in ("/api/chat", "/v1/chat/completions")
                and isinstance(payload.get("messages"), list)):
            before = len(payload["messages"])
            payload["messages"] = _tidy(payload["messages"], path)
            if len(payload["messages"]) != before:
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + (
                    f" 消息表{before}→{len(payload['messages'])}（去重/去尾）")
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # ---- 长度约束消毒（2026-10-18 加，默认开；`--no-strip-limit` 关）----
        # 只摘 system 里"最多 N 个短句 / 控制在 X-Y 字 / 不要答满 / 不要空行"这类**长度**
        # 约束；人格与其它规则一个不动。删完剩余 < 60% 会整体回滚（防误删）✓
        # 实测依据见 `strip_length_limits()` 上面那段注释（50 字 → 597 字）。
        if (payload is not None and getattr(self.server, "strip_limit", True) and strip_limit_on()
                and path in ("/api/chat", "/v1/chat/completions")
                and isinstance(payload.get("messages"), list)):
            _stripped = 0
            for m in payload["messages"]:
                if (isinstance(m, dict) and (m.get("role") or "").lower() == "system"
                        and isinstance(m.get("content"), str)):
                    _new, _k = strip_length_limits(m["content"])
                    if _k:
                        m["content"] = _new
                        _stripped += _k
            if _stripped:
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                    f" 长度约束消毒({_stripped}处)"
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # ---- 给客户端那条 system 末尾补东西（时间 / 反省略）----
        # ① **本机时间**（2026-10-05 加）：起因是用户在手机网页上问"几点了"，网关**去搜了**，
        #    可网上查不到"你的现在几点"，答出来是错的 ⇒ 时间必须由网关给（`02` 坑 19）。
        # ② **反"说一半"**（2026-10-05 晚加，默认开）：他手机客户端是 **手机客户端（手机客户端）**，
        #    那个 App 的回复规则**硬编码**了"最多 5 个短句 / 控制在 15-50 字"、
        #    还允许用「...」（`AiPromptBuilder.buildPersonaRules`），于是回复老是"说一半就省略"。
        #    那两条在 App 里改不了（UI 没这个开关），只能在**网关这一层压过去**：
        #    下面这段加在 App 那段规则**之后**，模型按"后说的为准"就能把话说完。
        #    ⚠️ 2026-10-12：原来这里还写着"约 150 字以内"——因为"超了会被 App 砍"。
        #    现在 App 的截断已删（本地补丁 #7），所以改成**不设字数上限**（见 ANTI_ELIDE_LINE
        #    那里的实测：587 → 1853 字）。但**"以本条为准"必须留着**：App 自己的
        #    「最多 5 个短句 / 15-50 字」还在，靠这句压过去 ✓
        # 每轮都刷新；加在客户端那条 system 末尾（没有 system 就补一条）。
        if (payload is not None
                and (self.server.inject_time or self.server.fix_elision)
                and path in ("/api/chat", "/v1/chat/completions")
                and isinstance(payload.get("messages"), list)):
            extra = []
            # ⚠️ 2026-10-18 改：**时间行只在真问时间时才注入**。
            #    原先每轮都塞 ⇒ 实测副作用很大：问「介绍一下自己」模型答
            #    「今天是 2026 年 10 月 18 日…」；人设越短越明显（用户原话"越改越坏"）✗
            #    只在 `_looks_like_time_question()` 命中时给 ⇒ 既防"问几点答错"，也不抢戏 ✓
            if self.server.inject_time:
                _lu = ""
                for _m in reversed(payload["messages"]):
                    if isinstance(_m, dict) and (_m.get("role") or "").lower() == "user":
                        _lu = _msg_text(_m)
                        break
                if _looks_like_time_question(_lu):
                    extra.append(now_line())
            if self.server.fix_elision:
                extra.append(ANTI_ELIDE_LINE)
            if extra:
                block = "\n\n" + "\n\n".join(extra)
                for m in payload["messages"]:
                    if isinstance(m, dict) and (m.get("role") or "").lower() == "system":
                        m["content"] = (m.get("content") or "") + block
                        break
                else:
                    payload["messages"].insert(0, {"role": "system", "content": block.strip()})
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + (
                    (" 时间注入" if len(extra) > 1 or extra[0].startswith("（现在是") else "")
                    + (" 反省略" if self.server.fix_elision else ""))
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # ---- 会话记忆：注入上一轮的滚动摘要 + 恢复历史（2026-10-05）----
        # 客户端只发当轮 → 这里把"摘要 + 最近几轮"补回去，让裸模型也有长期记忆。
        session_key = None
        full_msgs = None
        if (body and self.server.session_enabled
                and path in ("/api/chat", "/v1/chat/completions")
                and isinstance(payload, dict) and isinstance(payload.get("messages"), list)):
            session_key = self._session_key()
            self.server._last_chat = time.time()   # 后台摘要靠它判断"用户停手了没"
            incoming = [m for m in payload["messages"] if isinstance(m, dict)]
            # 客户端自带的 system（人设等）单独留着，每轮都保
            client_sys = [m for m in incoming if _is_system(m)]
            client_rest = [m for m in incoming if not _is_system(m)]
            sess = self.server.store.get(session_key)

            # ⚠️ `hist` 只取**非 system** 的：客户端那条人设每轮都会重发（下面 `client_sys`），
            #    存进历史就等于每轮再叠一份（2026-10-05 实测：手机那条会话 11 条里 4 条是
            #    重复的 system，占 93% 字符）。这里顺手把老会话文件里的 system 也滤掉，自愈。
            hist = [m for m in _strip_old_summary(sess.get("msgs") or [])
                    if not _is_system(m)]
            # 客户端这轮带来的新消息 = **只取最后一条 user**（这一轮真正要回答的那句）。
            # ⚠️ 2026-10-05 实测踩到：原来写成 `client_rest[last_user_idx:]`（取到最后），
            #    而客户端会把它**自己那份 assistant 历史**也发过来（有时尾巴上还跟着一条
            #    system 状态块）⇒ 拼出来结尾带 1~2 条 assistant，结果：
            #      · 模型照着把那句话**重复一遍**（用户报的"一句话重复发两遍"）；
            #      · 结尾 ≥2 条 assistant 时**被 Ollama 400**（实测原文 `Cannot have 2 or
            #        more assistant messages at the end of the list.`，手机连着 6 次 400）。
            #    只取那一条 user 消息就两个问题都没了 —— 历史由 `hist` 提供，不靠客户端。
            last_user_idx = max((i for i, m in enumerate(client_rest)
                                 if (m.get("role") or "").lower() == "user"), default=None)
            new_part = ([client_rest[last_user_idx]] if last_user_idx is not None else [])

            mem_sys = []
            if sess.get("summary"):
                mem_sys.append({"role": "system",
                                "content": "[长期记忆：之前对话的摘要]\n" + sess["summary"]})
            # ⚠️ 拼装顺序：**整体由网关负责** —— 长期记忆摘要 + 客户端人设 + 已发生的历史
            #    + 客户端这一轮新发的那句。客户端（Chatbox 之类）通常只发当轮，
            #    所以历史必须从记忆里补；它若自己发了完整历史，我们也不再采信（见上）。
            full_msgs = _tidy(mem_sys + client_sys + hist + new_part)
            payload["messages"] = full_msgs
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # ---- 联网搜索（2026-10-05 改：不再"只认触发词"，见 --search-mode）----
        # 只对聊天类接口做，且要能在 --no-search 时整个关掉。
        # 档位：always（默认，每句都查）/ auto（自己判断事实类提问）/ keywords（老行为）
        # ⚠️ 2026-10-14：**带 tools 的请求不自动搜**。模型这一轮的任务是"决定调哪个工具 /
        #    按工具返回的结果回答"，而自动搜索会**同时**塞进一份搜索结果 ⇒ 两份信息打架，
        #    模型可能引用搜索而不是工具结果（用户看到的就是"工具好像没用"）。
        #    实测：问「上海天气」→ 自动命中「天气」强触发词，搜了 5 条，最终回答里的气温
        #    跟工具返回的不一致 ⇒ 带 tools 时跳过自动搜索，要搜就让工具自己搜 ✓
        # ⚠️ 2026-10-18：**工具开关** —— 关掉时把客户端带来的 tools 剥掉。
        #    实测依据：同一提示，不带 tools ⇒ 349 字、finish=stop；
        #    带 tools ⇒ 32 字前言 + finish_reason=tool_calls（用户看到的就是"半句截断"）✓
        if (isinstance(payload, dict) and payload.get("tools") and not tools_on()):
            _nt = len(payload.get("tools") or [])
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
            self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                f" 工具已剥({_nt}个)"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # ⚠️ 2026-10-18：**历史净化**（放在找 tools 之后、_tidy 之前）——
        #    只对"退化连发"动手，日志记 `历史净化(删N条残缺)` ✓
        if (isinstance(payload, dict) and isinstance(payload.get("messages"), list)
                and hist_on() and path in ("/api/chat", "/v1/chat/completions")):
            _new_msgs, _dn = sanitize_history(payload["messages"])
            if _dn:
                payload["messages"] = _new_msgs
                self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + \
                    f" 历史净化(删{_dn}条残缺)"
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # ⚠️ 2026-10-18：**兼容模式** ⇒ 转发时一个字节都不发，整段收完、洗成纯文本再一次性发。
        #    实测那个客户端会在空行/表格处吞字（网关 120 字 → 屏幕 17 字）✓
        #    ⚠️ 这里**不能把 payload["stream"] 改成 False**：那会让请求走"非流式兜底"提前返回，
        #       兼容模式那段就永远执行不到（实测输出 0 帧）✗
        _compat = bool(isinstance(payload, dict)
                       and path in ("/api/chat", "/v1/chat/completions") and compat_on())
        if _compat:
            self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + " 兼容模式(整段发)"
        _has_tools = bool(payload.get("tools")) if isinstance(payload, dict) else False
        if _has_tools:
            self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + " 带tools（不自动搜）"
        if (body and self.server.search_enabled and not _has_tools
                and path in ("/api/chat", "/v1/chat/completions")):
            if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
                # ⚠️ 先看**最后一条**是不是客户端自己的协议消息（`{system:…}` 那种）。
                #    那种回合模型的任务是"回答协议"（比如只回一个 `1h`），**不是回答问题** ——
                #    实测：此时注入搜索结果，模型照样只回 `{interval_unit: min}`。
                #    所以这种回合**不搜**（省 2~6 秒 + 省匿名额度），日志里写明原因。
                msgs = payload["messages"]
                last_c = None
                for m in reversed(msgs):
                    if isinstance(m, dict) and (m.get("role") or "").lower() in ("user", "system"):
                        c = m.get("content")
                        if isinstance(c, list):
                            c = " ".join(p.get("text", "") for p in c
                                         if isinstance(p, dict))
                        last_c = c if isinstance(c, str) else None
                        break
                if last_c and is_protocol_text(last_c):
                    self._reqinfo["search"] = "联网搜索[跳过] 最后一条是客户端协议消息"
                else:
                    # 用**最后一条"真用户说的话"**当搜索词，跳过历史里的协议消息 ——
                    # 否则 always 档会拿 `{system:对方暂未回复…}` 去搜，该搜的那句反而没搜。
                    text = last_real_user_text(msgs)
                    query, why = search_query_of(text or "", self.server.search_mode,
                                                 self.server.inject_time)
                    if query:
                        sys.stderr.write(f"  [搜索] {why}，查询={query!r}\n")
                        sys.stderr.flush()
                        payload["messages"], note = inject_search(
                            payload["messages"], query, explicit=(why == "触发词"))
                        self._reqinfo["search"] = f"联网搜索[{why}] query={query!r} {note}"
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # ---- 「本地思考」两段式（2026-10-08 用户思路）----
        # 过程只在本机跑、只写 `_备份\思考过程.log`；**发给客户端的只有第二轮正文**。
        # ⚠️ 只支持**非流式**（流式没法先想完再发）；流式客户端走原来的路（不会因此出空回复）。
        if (THINK_MODE == "local" and payload is not None and method == "POST"
                and path in ("/api/chat", "/v1/chat/completions")
                and not payload.get("stream")):
            if self._local_think(payload, path):
                return

        # ---- 转发 ----
        url = f"{self.server.ollama}{forward_path}"
        drop = BAD_HEADERS if self.server.forward_origin else BAD_HEADERS_UPSTREAM
        headers = {k: v for k, v in self.headers.items() if k.lower() not in drop}
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        # ---- 空回复兜底（2026-10-09）：思考开着时，模型偶尔只推理不写正文 ----
        # 只碰"思考确实开着 + /v1 聊天"这一种请求；off / auto(没开) / local 一走原路 ✓
        _is_chat = bool(isinstance(payload, dict) and path == "/v1/chat/completions"
                        and method == "POST")
        _think_on = bool(_is_chat and str(payload.get("reasoning_effort") or "").strip().lower()
                         not in ("", "none", "off", "false", "0", "minimal"))
        # 非流式客户端（明确写了 stream:false）⇒ 任何档位都兜；流式客户端**不动**（保逐字显示 ✓）
        _non_stream = bool(_is_chat and payload.get("stream") is False)
        if _is_chat and (_non_stream or _think_on) and not self.server.no_empty_retry:
            if self._chat_with_empty_retry(url, payload, headers, think_on=_think_on):
                return

        # ⚠️ 2026-10-18 加：计时。起因是"上传文档后只输出一半或不出"——
        #   要能回答"这条到底首字等了几秒 / 总共几秒"，而不是靠猜 ✓
        t_req = time.time()
        t_first = None
        _stat = (_ReplyCollector() if path in ("/api/chat", "/v1/chat/completions") else None)
        try:
            with opener_for(url).open(req, timeout=self.server.timeout) as up:
                self.send_response(up.status)
                for k, v in up.headers.items():
                    if k.lower() in BAD_HEADERS:
                        continue
                    self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self._cors()          # ← 成功转发这条路径也必须发 CORS（浏览器才拿得到响应）
                self.end_headers()
                # 流式转发：边收边发（聊天默认 stream=true，不能等整段收完）
                tail = bytearray()     # 只留尾部 64 KB：够解析 usage，**不拿来抽正文**
                rx = _ReplyCollector() if (session_key and full_msgs is not None) else None
                # 空正文检测（2026-10-09 加）：**只看、不改行为** ——
                #   流式路径保持逐字转发 ✓；如果整段一个正文都没有，就记一条日志，
                #   这样"空回复真实发生率"是量出来的，不是猜的 ✓
                _watch = (_ReplyCollector() if (path == "/v1/chat/completions" and rx is None)
                          else None)
                # ⚠️ 2026-10-18 加：**空回复重试**（流式）。
                #    起因：用户手机上出现过整段 0 字（`finish=stop`、流完整），
                #    而网关原来对**流式**只记 `[空正文]` 日志、不补救 ⇒ 客户端就是一片空白。
                #    做法：**首个正文到达之前先攒着不发**（模型都在思考/空转时本就没有可看的字）；
                #    整段结束仍然一个字都没有 ⇒ 用**非流式重发一次**，把拿到的正文当成 SSE 补发 ✓
                #    首个正文一到就切回逐字转发（正常请求的体验**完全不变**）✓
                _retried_text = ""
                _hold = []            # 结尾帧（finish_reason/usage/[DONE]）先攒着
                # 流式洗文本的状态（只在 _compat 且开关打开时用）
                _ss_mode = bool(_compat and streamsan_on())
                _ss_san = _StreamSanitizer()
                _ss_parts: list[str] = []
                _sse_buf = b"\\x00"[:0] if False else b""
                _pending = bytearray() if (_stat is not None
                                           and not getattr(self.server, "no_empty_retry", False)
                                           ) else None
                while True:
                    chunk = up.read(8192)
                    if not chunk:
                        break
                    if t_first is None and b'"content"' in chunk:
                        t_first = time.time()      # ← "首字/首包"到手的时刻（计时用）✓
                    if _stat is not None:
                        _stat.feed(chunk)
                    tail += chunk
                    if len(tail) > 65536:
                        del tail[: len(tail) - 65536]
                    if _pending is not None:
                        if t_first is None:
                            _pending += chunk      # 还没有正文 ⇒ 先攒着，别让客户端看到空流
                        else:
                            # ⚠️ 正文到了 ⇒ 把攒的补发，然后**无条件**切回逐字转发。
                            #    （这里原先把 `_pending = None` 写在 `if _pending:` 里 ⇒
                            #      首个 content 帧到达后 `_pending` 是个空 bytearray、
                            #      既不为真也不是 None ⇒ 后面所有帧都被吞掉 ⇒ 客户端收到 0 字节 ✗）
                            if _pending:
                                self.wfile.write(b"%x\r\n%s\r\n" % (len(_pending),
                                                                    bytes(_pending)))
                                self.wfile.flush()
                            _pending = None
                    # ⚠️ 2026-10-18：**结尾帧先攒住**（finish_reason / usage / [DONE]），
                    #    因为可能要"续写"再补内容 —— 先发 [DONE] 客户端就不会再收了 ✗
                    _is_tail = (b'"finish_reason"' in chunk or b"[DONE]" in chunk
                                or b'"usage"' in chunk)
                    # ⚠️ 2026-10-18：**流式洗文本**优先于"整段缓冲"。
                    #    攒整段会让长回复等 15~60 秒 ⇒ 手机 App 读超时报「API 调用失败」✗
                    #    边流边洗：首字节 ~1 秒、客户端也永远看不到会吞字的空行/表格 ✓
                    if _compat and _ss_mode:
                        _sse_buf += chunk
                        if b"\n\n" in _sse_buf:
                            _head, _rest = _sse_buf.rsplit(b"\n\n", 1)
                            _sse_buf = _rest
                            _payload = _sse_rewrite(_head + b"\n\n", _ss_san, _ss_parts)
                            if _payload:
                                self.wfile.write(b"%x\r\n%s\r\n" % (len(_payload), _payload))
                                self.wfile.flush()
                    elif _compat:
                        pass          # 兼容模式：整段收完再一次性发，循环里一个字节都不发 ✓
                    elif _is_tail:
                        _hold.append(chunk)
                    elif _pending is None:
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                        self.wfile.flush()
                    if rx is not None:
                        rx.feed(chunk)     # ← 正文边收边抽（长回复不再被截掉开头）
                    if _watch is not None:
                        _watch.feed(chunk)
                # ---- 整段 0 字 ⇒ 非流式重发一次，补发给客户端 ----
                if _pending is not None and not _pending:
                    _pending = None            # 一个字节都没有，没什么可补的
                elif _pending is not None:
                    _got = ""
                    try:
                        p2 = json.loads(json.dumps(payload, ensure_ascii=False))
                        p2["stream"] = False
                        st2, b2 = self._upstream_post(url, p2)
                        if st2 == 200 and b2:
                            if path == "/v1/chat/completions":
                                _got, _ = _split_openai_reply(b2)
                                _out = _openai_json_to_sse(b2)
                            else:
                                _got = "".join(_pieces(json.loads(
                                    b2.decode("utf-8", "replace"))))
                                _out = _openai_json_to_sse(json.dumps(
                                    {"choices": [{"index": 0, "message": {
                                        "role": "assistant", "content": _got},
                                        "finish_reason": "stop"}]}).encode("utf-8"))
                    except Exception as e:
                        sys.stderr.write(f"  [空回复重试] 出错：{type(e).__name__}\n")
                        sys.stderr.flush()
                    if _got.strip():
                        _retried_text = _got
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(_out), _out))
                        self.wfile.flush()
                        self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + (
                            f" 空回复重试(补发 {len(_got)} 字)")
                        self.server.log(
                            f"[空回复重试] 流式首轮整段 0 字 ⇒ 非流式重发成功"
                            f"（补发 {len(_got)} 字）⇒ 客户端不再空白 ✓")
                    else:
                        # 重试也是空 ⇒ 把原来攒的（空/无正文的帧）照发，形状不变
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(_pending), bytes(_pending)))
                        self.wfile.flush()
                    _pending = None
                # ---- 兼容模式 ----
                #   · 流式洗文本（_ss_mode）：内容**已经边收边发完了**，这里只收尾
                #   · 否则：整段洗成纯文本，一次性发
                if _compat and _ss_mode:
                    # ① 把状态机挂着的尾巴、SSE 缓冲里剩下的事件发出去
                    _tail_txt = _ss_san.flush()
                    if _sse_buf.strip():
                        _extra = _sse_rewrite(_sse_buf, _ss_san, _ss_parts)
                        _sse_buf = b""
                        if _extra:
                            self.wfile.write(b"%x\r\n%s\r\n" % (len(_extra), _extra))
                        _tail_txt += _ss_san.flush()
                    if _tail_txt:
                        self._write_sse_text(_tail_txt)
                    _all = "".join(_ss_parts)
                    # ② 还是"半句就停"就补写一次（继续流式补）
                    _c1 = self._maybe_continue(url, payload, path, _all,
                                               _hit_length_limit(bytes(tail)))
                    if _c1:
                        _san_c = _ss_san.feed(_c1) + _ss_san.flush()
                        if _san_c:
                            self._write_sse_text(_san_c)
                            _all = _all + _san_c
                        self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + (
                            f" 自动续写(补 {len(_san_c)} 字)")
                        self.server.log(f"[续写] 原回复半句就停 ⇒ 补写 {len(_san_c)} 字 ✓（流式洗文本）")
                    if _hit_length_limit(bytes(tail)):
                        self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + _LENGTH_NOTE
                        self.server.log(
                            f"[截断] 这条回复到了输出上限（finish_reason=length）："
                            f"客户端会看到「半句就停」；把 max_tokens / num_predict 调大即可 ✓")
                    # ③ 结尾帧（之前攒着的）+ 结束块
                    for _c in _hold:
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(_c), _c))
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                    note_reply(path, _all, bytes(tail), payload)
                    LAST_CHAT.update({"ptok": _usage_from_tail(bytes(tail)),
                                      "ttft": round(time.time() - t_req, 2),
                                      "total": round(time.time() - t_req, 2),
                                      "chars": len(_all), "aborted": False, "pending": False})
                    self.server.log(f"[兼容模式] 流式洗文本 {len(_all)} 字（边收边发）✓")
                    return
                if _compat:
                    _all = _retried_text or (_stat.finish() if _stat is not None else "")
                    # ⚠️ 2026-10-18（按 GPT 验收意见）：**兼容模式必须先续写再洗文本**——
                    #    原来这个分支在下面的"自动续写"之前就 return 了，所以兼容模式下
                    #    续写永远不触发（实测日志里兼容模式仍有 8/16 字回复）✗
                    _c1 = self._maybe_continue(url, payload, path, _all,
                                               _hit_length_limit(bytes(tail)))
                    if _c1:
                        _all = _all + _c1
                        self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + (
                            f" 自动续写(补 {len(_c1)} 字)")
                        self.server.log(f"[续写] 原回复半句就停（{len(_all) - len(_c1)} 字，"
                                        f"结尾 {(_all[:len(_all) - len(_c1)])[-12:]!r}）"
                                        f"⇒ 补写 {len(_c1)} 字 ✓（兼容模式）")
                    _pl = plainify(_all)
                    # ⚠️ 2026-10-18：兼容模式分支提前 return，原来把 `[截断]` 留痕跳过了
                    #    （实测 max_tokens=8 时日志里没有 [截断]）⇒ 这里补记一条 ✓
                    if _hit_length_limit(bytes(tail)):
                        self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + _LENGTH_NOTE
                        self.server.log(
                            f"[截断] 这条回复到了输出上限（finish_reason=length，兼容模式）："
                            f"客户端会看到「半句就停」；把 max_tokens / num_predict 调大即可 ✓")
                    # ⚠️ 2026-10-18：**客户端明确要非流式（stream:false）时必须回 JSON**，
                    #    不能回 SSE —— 实测非流式客户端直接解析失败（JSONDecodeError）✗
                    if isinstance(payload, dict) and payload.get("stream") is False:
                        _fin0 = "length" if _hit_length_limit(bytes(tail)) else "stop"
                        _j = json.dumps({
                            "id": "chatcmpl-compat", "object": "chat.completion",
                            "created": int(time.time()),
                            "model": (payload.get("model") or ""),
                            "choices": [{"index": 0, "finish_reason": _fin0,
                                         "message": {"role": "assistant", "content": _pl}}],
                            "usage": {"prompt_tokens": _usage_from_tail(bytes(tail)),
                                      "completion_tokens": 0, "total_tokens": 0},
                        }, ensure_ascii=False).encode("utf-8")
                        # ⚠️ 这里**不能**再 send_response/send_header —— 转发循环开头
                        #    已经发过 200 + `Transfer-Encoding: chunked` 了，再发一次会把
                        #    "HTTP/1.1 200 OK" 写进 body（实测客户端 IncompleteRead）✗
                        #    所以按 chunked 写一个整块 + 结束块 ✓
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(_j), _j))
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                        if _stat is not None:
                            note_reply(path, _pl, bytes(tail), payload)
                        LAST_CHAT.update({"ptok": _usage_from_tail(bytes(tail)),
                                          "ttft": round(time.time() - t_req, 2),
                                          "total": round(time.time() - t_req, 2),
                                          "chars": len(_pl), "aborted": False,
                                          "pending": False})
                        self.server.log(f"[兼容模式] 非流式 {len(_pl)} 字（JSON 返回）✓")
                        return
                    if _pl:
                        self._write_sse_text(_pl)
                    _fin = "length" if _hit_length_limit(bytes(tail)) else "stop"
                    _frm = json.dumps({"id": "chatcmpl-compat",
                                       "object": "chat.completion.chunk",
                                       "created": int(time.time()), "model": "",
                                       "choices": [{"index": 0, "delta": {},
                                                    "finish_reason": _fin}]},
                                      ensure_ascii=False).encode("utf-8")
                    _fb = b"data: " + _frm + b"\n\n"
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(_fb), _fb))
                    _dn = b"data: [DONE]\n\n"
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(_dn), _dn))
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                    if _stat is not None:
                        note_reply(path, _pl, bytes(tail), payload)
                    LAST_CHAT.update({"ptok": _usage_from_tail(bytes(tail)),
                                      "ttft": round(time.time() - t_req, 2),
                                      "total": round(time.time() - t_req, 2),
                                      "chars": len(_pl), "aborted": False, "pending": False})
                    self.server.log(f"[兼容模式] 整段 {len(_pl)} 字一次性发"
                                    f"（去 markdown、双空行压单行）✓")
                    return
                # ---- 自动续写（2026-10-18）：模型"半句就 EOS"时补一次 ----
                #    依据：用户那条真实请求 `completion_tokens=67`、finish=stop、
                #    文本停在「异 这种半个词上 ⇒ 模型自己提前收尾（2bit 量化偶发）✓
                _now_text = _retried_text or (_stat.finish() if _stat is not None else "")
                _cont_text = self._maybe_continue(url, payload, path, _now_text,
                                                  _hit_length_limit(bytes(tail)))
                if _cont_text.strip():
                    _add = _cont_text.strip()
                    _retried_text = _now_text + _add
                    self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + (
                        f" 自动续写(补 {len(_add)} 字)")
                    self.server.log(f"[续写] 原回复半句就停（{len(_now_text)} 字，"
                                    f"结尾 {_now_text[-12:]!r}）⇒ 补写 {len(_add)} 字 ✓")
                    self._write_sse_text(_add)
                # ⚠️ 结尾帧（finish_reason / usage / [DONE]）**必须发出去** ——
                #    上面为了"可能续写"才攒着，忘了发就等于所有流式回复都没有结尾标记 ✗
                for _c in _hold:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(_c), _c))
                self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
                #    流式与非流式都走这个循环，`tail` 里一定有结尾那几个分片 ⇒ 一处就够 ✓
                #    ⚠️ 必须**单独记一条日志**：结果行（`└ 200 | …`）在这之前就写好了，
                #    事后往 `_reqinfo` 里补的备注不会出现在那一行（和"[空正文]"同款处理）✓
                if _hit_length_limit(bytes(tail)):
                    self._reqinfo["payload"] = (self._reqinfo.get("payload") or "") + _LENGTH_NOTE
                    self.server.log(
                        f"[截断] 这条回复到了输出上限（finish_reason=length）："
                        f"{self._reqinfo.get('path', '')} —— 客户端那边会看到「半句就停」；"
                        f"把客户端的 max_tokens / num_predict 调大即可 ✓")
                # ⚠️ 2026-10-18：把"这一轮等了多久"落到日志 + 面板那一行（`last_chat_line`）✓
                #    用途：用户报"上传文档后只输出一半或不出"——
                #    文档一大，光读提示词就要几十秒，客户端超时一掐就断流；
                #    有了这三个数就能一眼判断是"慢"还是"模型坏了" ✓
                _tot = time.time() - t_req
                _ttft = (t_first - t_req) if t_first else _tot
                _reply = (_stat.finish() if _stat is not None else "")
                if not _reply and locals().get("_retried_text"):
                    _reply = _retried_text      # 空回复重试补发的那段也要计入字数/面板 ✓
                _ptok = _usage_from_tail(bytes(tail))
                _est = False
                if _ptok <= 0 and isinstance(payload, dict) \
                        and isinstance(payload.get("messages"), list):
                    # 流式 `/v1` 不报 usage ⇒ 估一个（实测 0.65 token/字 + 每条 8 的模板开销）✓
                    _ptok = int(sum(len(_msg_text(m)) for m in payload["messages"])
                                * CTX_TOK_PER_CHAR) + 8 * len(payload["messages"])
                    _est = True
                # ⚠️ 只在**这一轮真拿到东西**时才覆盖面板数字：空响应 / 上游异常 /
                #    payload 没解析出来（估算被跳过）都会得到 `ptok=0, chars=0`，
                #    把上一轮的好数据冲掉 ⇒ 面板闪 `首字 0.0s / 提示 0 tok`（假数据）✗
                _d = {"ttft": _ttft, "total": _tot, "chars": len(_reply),
                      "aborted": False, "pending": False}
                if _ptok > 0:
                    _d["ptok"] = _ptok
                    _d["ptok_est"] = _est
                if _reply or _ptok > 0:
                    LAST_CHAT.update(_d)
                else:
                    LAST_CHAT["pending"] = False
                if _stat is not None:
                    note_reply(path, _reply, bytes(tail), payload)
                    self.server.log(
                        f"[用时] {path} | 首字 {_ttft:.1f}s | 总 {_tot:.1f}s | "
                        f"提示 {_ptok}{'（估）' if _est else ''} tok | 回复 {len(_reply)} 字"
                        + (" ★慢：首字超过 20 秒，客户端很容易超时"
                           if _ttft > 20 else ""))
                # ---- 记会话记忆（用模型真报的 token 数当阈值信号）----
                # 记的是**这次真正发给模型的完整消息**（含摘要与人设）——
                # 下一轮就在这个基础上追加，客户端不用自己带历史。
                if session_key and full_msgs is not None:
                    self.server._last_chat = time.time()
                    reply = rx.finish()
                    n_tok = _usage_from_tail(bytes(tail))
                    how = "模型报的"
                    if n_tok <= 0:
                        # ⚠️ 2026-10-05 实测：`/v1/chat/completions` **流式不报 usage**
                        #    （末行就是 `data: [DONE]`），只有非流式那条才有
                        #    `usage.prompt_tokens`。而 `/api/chat` 两种都报
                        #    `prompt_eval_count`。没有信号就**永远不压缩** ⇒ 历史无限涨到
                        #    超窗（Ollama 会从 token 层中间截断，见 `02` 坑 27）。
                        #    所以这里按消息长度保守估一个（1.5 tok/字，宁可早压不晚压）。
                        n_tok = sum(_msg_tokens(m) for m in full_msgs)
                        how = "按长度估（这条路不报 usage）"
                    if reply:
                        full_msgs = full_msgs + [{"role": "assistant", "content": reply}]
                    # ⚠️ 存进记忆的**不含客户端那条 system**（下一轮它会再发一次）也不含摘要
                    #    （摘要有自己的字段）。否则每轮都往历史里再叠一份 system 提示词 ——
                    #    2026-10-05 实测手机那条会话：11 条消息里 **4 条是重复的 system**，
                    #    占全部字符的 93%（1500 字 ×4），输入 token 从 ~800 涨到 4471，
                    #    而 35B 有一半在 CPU 上 —— 白烧 prefill、还稀释指令。
                    store_msgs = _tidy(hist + new_part
                                       + ([{"role": "assistant", "content": reply}] if reply else []))
                    self.server.log(
                        f"会话记忆 | {session_key} | 发 {len(full_msgs)} 条 / "
                        f"{sum(len(_msg_text(m)) for m in full_msgs)} 字符 | "
                        f"存 {len(store_msgs)} 条 / "
                        f"{sum(len(_msg_text(m)) for m in store_msgs)} 字符 | "
                        f"输入 {n_tok} tok（{how}）| 回复 {len(reply)} 字")
                    self._remember(session_key, store_msgs, payload.get("model") or "", n_tok)
        except urllib.error.HTTPError as e:
            # ⚠️ 2026-10-18：从 400 放宽到 2000 —— 超窗那条错误体很长，400 字节会把
            #    `n_prompt_tokens` / `n_ctx` 截掉 ⇒ 翻出来的提示里就没数字 ✗
            detail = e.read()[:2000]
            # 上游的错误原文也要落盘 —— 2026-10-05 手机连着 6 次 400，而日志里只有"└ 400"，
            # 得靠猜（真正的原因是 `Cannot have 2 or more assistant messages at the end
            # of the list.`）。现在原文进日志，下次不用再猜。
            # ⚠️ 2026-10-18：**超窗（exceed_context_size_error）翻成人话**再回给客户端 ——
            #    实测 91,557 字（65,604 token）会 400，原文是一串英文 JSON，用户看不懂。
            #    翻完之后客户端会看到：「文档太长，请分两次问」+ 具体数字 ✓
            _ov = _ctx_overflow_msg(detail)
            if _ov:
                self.server.log(f"[超窗] {_ov}")
                detail = json.dumps({"error": {"message": _ov, "type": "context_too_long",
                                               "code": e.code}},
                                    ensure_ascii=False).encode("utf-8")
            try:
                self.server.log(f"上游 {e.code} | {self._reqinfo.get('path', '')} | "
                                f"{detail.decode('utf-8', 'replace')[:300]}")
            except Exception:
                pass
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(detail)))
            self._cors()
            self.end_headers()
            self.wfile.write(detail)
        except urllib.error.URLError as e:
            self._deny(502, f"连不上本机 Ollama（{self.server.ollama}）：{e.reason}。"
                            f"先确认 Ollama 已启动")
        except (BrokenPipeError, ConnectionResetError):
            # ⚠️ 2026-10-18 改：原来这里是 `pass`（"客户端提前断开，很常见"）。
            #    但用户报的"只输出一半"就是这种 —— 客户端超时/切后台把连接断了，
            #    网关这边只看到 BrokenPipe，日志里一个字都没有，事后无从判断 ✓
            #    现在留一条痕，并且写进面板那一行（`last_chat_line`）✓
            try:
                _t0 = locals().get("t_req")
                _el = (time.time() - _t0) if _t0 else 0.0
                if LAST_CHAT:
                    LAST_CHAT.update({"aborted": True, "total": round(_el, 1)})
                self.server.log(
                    f"[中断] 客户端在第 {_el:.1f} 秒断开了连接（客户端超时/切后台/主动取消）"
                    f" —— 文档大时首字就要 30 秒+，把客户端超时调大或减少文档长度 ✓")
            except Exception:
                pass

    def _remember(self, key: str, msgs: list, model: str, tokens: int) -> None:
        r"""把这一轮的结果记进会话记忆；超阈值就在**后台**压缩（不拖慢本次回复）。

        为什么放后台：摘要要模型跑一次。放在回复之后异步做，用户那一条已经发出去了。
        ⚠️ 但不能"立刻"做（2026-10-05 改）：摘要会占住模型、或把另一个模型换进显存，
        用户紧接着发第二条就会被拖住 —— 所以 `_compress_now` 里先**等用户停手**。
        """
        try:
            self.server.store.update(key, msgs, model, tokens)
            if tokens >= self.server.compress_at:
                t = threading.Thread(target=self._compress_now, args=(key,),
                                     daemon=True)
                t.start()
        except Exception as e:
            self.server.log(f"记会话失败（{type(e).__name__}）")

    def _compress_model_for(self, sess: dict) -> str:
        r"""这次摘要用哪个模型。

        默认 `--compress-model same` = **跟当前会话用的模型一致**。为什么改（2026-10-05）：
            这台机器 8 GB 显存 + `OLLAMA_MAX_LOADED_MODELS=1`，而默认主模型是 35B。
            摘要模型若不是同一个（原来是 9B），**每次压缩都会把主模型整个踢出显存**
            （`02` 坑 13 实测过的机理）⇒ 用户下一条要重付 20~40 秒冷启动。
            也就是说 `07` 原来那句"摘要跑在后台，感知不到"在那种配置下**不成立**。
        代价（写清楚，别以为白拿）：同一个模型做摘要会比 9B 慢（35B 一半在 CPU 上）；
        所以配套做了两件事把代价压下去 —— `--keep-tokens` 默认抬高到 40000
        （一次只读约 8K token 的历史，而不是 24K）+ 先等用户停手再跑。
        """
        m = (self.server.compress_model or "").strip()
        if m.lower() in ("", "same", "@same"):
            return (sess.get("model") or "").strip() or DEFAULT_COMPRESS_MODEL
        return m

    def _compress_now(self, key: str) -> None:
        sess = self.server.store.get(key)
        now = time.time()
        if now - (self.server._last_compress.get(key) or 0) < self.server.compress_cooldown:
            return
        # 先等用户停手，再动手（别和他的下一条抢模型）。等到上限也照做 ——
        # 一直不压的话窗口会被吃满，那比"压得不是时候"更糟。
        waited = 0.0
        deadline = now + self.server.compress_idle_max
        while (time.time() < deadline
               and time.time() - self.server._last_chat < self.server.compress_idle):
            time.sleep(1.0)
            waited = time.time() - now
        self.server._last_compress[key] = time.time()
        model = self._compress_model_for(sess)
        self.server.log(f"会话 {key} 开始压缩（摘要模型 {model}，等了 {waited:.0f}s）")
        t0 = time.time()
        new = compress_session(self.server.store, key, sess, self.server.keep_tokens,
                               model, self.server.ollama, self.server.log)
        if new.get("summary"):
            self.server.store.update(key, new["msgs"], sess.get("model") or "",
                                     0, summary=new["summary"])
            self.server.log(f"会话 {key} 压缩完成（上轮 {sess.get('tokens')} tok，"
                            f"耗时 {time.time() - t0:.1f}s）")

    def do_OPTIONS(self):    # noqa: N802  ← 浏览器插件的预检
        self._handle("OPTIONS")

    def do_GET(self):        # noqa: N802
        self._handle("GET")

    def do_POST(self):       # noqa: N802
        self._handle("POST")

    def do_DELETE(self):     # noqa: N802
        self._handle("DELETE")


def main() -> int:
    ap = argparse.ArgumentParser(description="带口令的 Ollama 局域网网关")
    ap.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0 = 局域网可达）")
    ap.add_argument("--port", type=int, default=11435, help="监听端口（默认 11435）")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434", help="本机 Ollama 地址")
    ap.add_argument("--timeout", type=float, default=900.0, help="转发超时秒数（35B 冷启动慢）")
    ap.add_argument("--allow-pull", action="store_true", help="允许 /api/pull 等拉模型接口")
    ap.add_argument("--allow-admin", action="store_true", help="允许 /api/delete 等管理接口（危险）")
    ap.add_argument("--show-key-lan", action="store_true",
                    help="允许局域网设备从网页取口令（默认只有本机能取；开了等于口令公开）")
    ap.add_argument("--cors-origin", default="",
                    help="只允许这个来源的浏览器页面调（默认 * ；给插件用一般不用改）")
    ap.add_argument("--debug", action="store_true", help="打印每个请求的方法/路径/关键头（排错用）")
    ap.add_argument("--forward-origin", action="store_true",
                    help="把浏览器的 Origin 原样转发给 Ollama（默认不转；转了要自己设 "
                         "OLLAMA_ORIGINS=* 否则插件会被 Ollama 403）")
    ap.add_argument("--no-search", action="store_true",
                    help="关掉联网搜索（等于 --search-mode off）")
    ap.add_argument("--search-mode", choices=("auto", "always", "keywords"), default="auto",
                    help="联网搜索什么时候触发（**默认 auto** = 自己判断，用户 2026-10-05 定的）："
                         "auto=消息里出现事实/时效词（最新/天气/价格/几点/版本…）就搜，"
                         "「搜/查」开头照旧强制搜；"
                         "always=每句都搜（每句多 2~6 秒 + 几百 token）；"
                         "keywords=只有「搜/查」开头才搜。"
                         "⚠️ 三种档下：**纯问时间的句子不搜**（本机时间由网关直接注入）、"
                         "**客户端协议消息那一轮也不搜**")
    ap.add_argument("--search-proxy", default=None, metavar="URL|none",
                    help="**只给搜索**用哪个代理（默认 http://127.0.0.1:7897；"
                         "启动时探测该端口，没在听就直连）。传 none = 永远直连。"
                         "⚠️ 这是**每次搜索单独挂**的 ProxyHandler，"
                         "**不会**给整个进程设代理（否则转给本机 Ollama 的请求也会被塞进代理）")
    ap.add_argument("--no-fix-elision", action="store_true",
                    help="不补「把话说完、别用…省略」那条规则。默认**补** —— 手机客户端"
                         "（手机客户端 App）源码里硬编码了「最多 5 个短句 / 15-50 字」，"
                         "表现就是回复「说一半就省略」（它 UI 里没有开关可改）")
    ap.add_argument("--no-inject-time", action="store_true",
                    help="不注入本机时间。默认**注入** —— 裸模型没有表，"
                         "而「几点了」这种事网上根本查不到（用户实测：搜了也是错的）")
    ap.add_argument("--no-empty-retry", action="store_true",
                    help="关掉「空回复兜底」：思考开着的 /v1 聊天，若模型只推理不写正文，"
                         "网关会自动关思考重发一次（默认开）")
    ap.add_argument("--no-thought-log", action="store_true",
                    help="「本地思考」**不把推理过程写到磁盘**（默认写 `_备份\\思考过程.log`，"
                         "只在本机、超过 2 MB 自动只留最近的）")
    ap.add_argument("--local-think-budget", type=int, default=800, metavar="N",
                    help="「本地思考」第一轮的思考预算（默认 800）。**别调太大**："
                         "手机 App 的请求超时只有 20~30 秒，太大就会超时、表现成「没有回复」。"
                         "local 档还会给模型 30 分钟的保温（keep_alive），免得冷启动那条超时"),
    ap.add_argument("--local-keep-alive", default="30m", metavar="DUR",
                    help="local 档的模型保温时长（默认 30m；传 0 表示不保温）")
    ap.add_argument("--think-min-predict", type=int, default=4096, metavar="N",
                    help="**思考开着时**至少给多少输出预算（默认 4096；0 = 不管）。"
                         "为什么要它：推理和正文共用同一个上限，上限 512 时推理就把它烧光、"
                         "正文 0 字（App 那边表现成「没反应」）——实测 1024 能出正文、4096 更稳")
    ap.add_argument("--num-predict", type=int, default=2048,
                    help="给客户端的回复兜一个输出上限（默认 2048 token ≈1600 汉字）。"
                         "Modelfile 里 35B 只有 1024，项目自己的实测是**12 个样本里 6 个停在半句**；"
                         "客户端自己指定了就不动。给 0 = 不兜底")
    ap.add_argument("--think", choices=THINK_MODES, default=None,
                    help="思考模式：auto（默认，客户端自己带设置就听它的、没带就关）/ "
                         "off（全局关）/ on（全局开）。**会写进 `_备份\\网关思考模式.txt`**，"
                         "并**同步 AstrBot**（auto 不动它）—— 网页上那个按钮和它是同一个开关")
    ap.add_argument("--allow-think", action="store_true",
                    help="不强制关思考。默认**强制关** —— 客户端自带 system 时 35B 会思考，"
                         "实测 1024 token 全耗在 reasoning 上、content 返回 0 字（App 看到空回复）")
    ap.add_argument("--no-strip-limit", action="store_true",
                    help="不摘客户端 system 里的「最多N个短句 / 控制在X-Y字」这类长度约束。"
                         "默认**会摘**：实测同一句话 50 字 → 597 字（10 倍），"
                         "用户报的「回复被截断、没有完整版」根因就在这里")
    ap.add_argument("--require-key", action="store_true",
                    help="强制必须带对口令（默认：不带口令也放行 —— Ollama 原生 API 本来就没有鉴权）")
    ap.add_argument("--v1-prefix", action="store_true",
                    help="同时把 /api/* 也暴露在 /v1/* 下（给那些把 OpenAI 路径硬编码的客户端）")
    ap.add_argument("--new-token", action="store_true", help="重新生成口令")
    ap.add_argument("--show-token", action="store_true", help="只打印当前口令后退出")
    ap.add_argument("--show-access-code", action="store_true",
                    help="只打印网页访问码后退出（手机首次打开网页要输它）")
    ap.add_argument("--new-access-code", action="store_true",
                    help="重新生成网页访问码（**所有已授权设备立即失效**）")
    ap.add_argument("--open-access", action="store_true",
                    help="关掉网页访问门（局域网任何设备都能直接打开控制台，默认不开）")
    ap.add_argument("--log-file", default=str(DEFAULT_LOG),
                    help=f"请求日志写哪（默认 {DEFAULT_LOG}；排错用 —— 不记口令、不记正文）")
    ap.add_argument("--no-log", action="store_true", help="完全不写请求日志")
    ap.add_argument("--keep-gateway", action="store_true",
                    help="点「停止模型」时**只停模型/AstrBot，别把网关自己也关掉**。"
                         "默认是「连网关一起停」：响应发出后 **5 秒**结束网关"
                         "（含其它 ollama_gateway 实例）—— 用户 2026-10-05 要的「所有进程都关」。"
                         "（要重新启动：电脑上双击 启动局域网API.bat）")
    ap.add_argument("--memory", action="store_true",
                    help="**打开**网关自己的会话记忆（现在默认**关**）。"
                         "2026-10-05 用户明确：**局域网端不需要** —— 手机 App 自带记忆、"
                         "AstrBot 那条才是记忆/压缩的家。而且网关这份开着会引发一串副作用："
                         "把 App 的协议标记学给网页版、摘要线程抢显存、和客户端历史重复（见 `02` 坑 45/46）")
    ap.add_argument("--no-memory", action="store_true",
                    help="关掉会话记忆（**这就是现在的默认**，留着是为了兼容旧写法）")
    ap.add_argument("--compress-at", type=int, default=48000,
                    help="输入 token 超过这个数就压缩早期对话（默认 48000；两个模型窗口都是 65536）")
    ap.add_argument("--keep-tokens", type=int, default=40000,
                    help="压缩时**保留原文**的 token 预算（默认 40000）。⚠️ 它同时决定"
                         "「一次摘要要读多少历史」：触发点 48000 − 保留 40000 ⇒ 一次只读约 8K，"
                         "摘要又快又省；调小它（比如 24000）会让每次摘要要读 24K，慢得多。")
    ap.add_argument("--compress-model", default="same",
                    help="生成摘要用哪个模型。默认 same = **跟当前会话同一个模型** —— "
                         "8 GB 显存 + OLLAMA_MAX_LOADED_MODELS=1 下，用另一个模型做摘要会把"
                         "主模型整个踢出显存（`02` 坑 13），用户下一条要重付 20~40 秒冷启动。"
                         "想强制用小模型：--compress-model local-assistant-9b:latest（那时就要接受换出）")
    ap.add_argument("--compress-cooldown", type=float, default=180.0,
                    help="同一个会话两次压缩之间至少隔多少秒（默认 180）")
    ap.add_argument("--compress-idle", type=float, default=5.0,
                    help="摘要**等用户停手**这么多秒才跑（默认 5；0 = 不等）。"
                         "别和他的下一条抢模型/显存")
    ap.add_argument("--compress-idle-max", type=float, default=120.0,
                    help="等空闲最多等这么久，超时照样压（默认 120；一直不压窗口会被吃满）")
    ap.add_argument("--session-header", default="",
                    help="用这个 HTTP 头区分会话（默认按来源 IP）")
    ap.add_argument("--session-file", default=str(Path(r"C:\LocalAI-Assistant\_备份\gateway_sessions.json")),
                    help="会话记忆存哪（默认 _备份\\gateway_sessions.json）")
    args = ap.parse_args()

    # 搜索通道（2026-10-08）：`--search-proxy URL` 指定 / `none` 强制直连。
    # ⚠️ 只改**搜索**这一条路（见 SEARCH_PROXY 那段注释），不碰进程全局代理。
    global SEARCH_PROXY
    if args.search_proxy is not None:
        _sp = args.search_proxy.strip()
        SEARCH_PROXY = "" if _sp.lower() in ("none", "-", "off", "") else _sp

    token = load_token(new=args.new_token)
    if args.show_token:
        print(token)
        return 0

    # 访问码（2026-10-06）：`--show-access-code` 只打印后退出；`--new-access-code` 换一个
    # （换码 ⇒ 之前发出去的所有通行证**立即失效**，等于把所有手机踢下线）。
    load_access_code(new=args.new_access_code)
    if args.show_access_code:
        print(_ACCESS_CACHE.get("code") or load_access_code())
        return 0

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.token = token
    srv.logger = ReqLog(None if args.no_log else args.log_file)
    srv.ollama = args.ollama.rstrip("/")
    srv.timeout = args.timeout
    srv.allow_pull = args.allow_pull
    srv.allow_admin = args.allow_admin
    srv.show_key_lan = args.show_key_lan
    srv.cors_origin = args.cors_origin.strip()
    srv.debug = args.debug
    srv.forward_origin = args.forward_origin
    srv.search_enabled = not args.no_search
    # 思考模式：启动参数 > 老参数 --allow-think（等价 auto）> 持久化文件 > 默认 auto
    if args.think:
        save_think_mode(args.think)
    elif args.allow_think:                 # 老参数：含义就是"不强制关" ⇒ auto
        save_think_mode("auto")
    else:
        load_think_mode()
    srv.no_think = (THINK_MODE == "off")        # 兼容旧属性（判断逻辑已归 apply_think_mode）
    srv.require_key = args.require_key
    srv.v1_prefix = args.v1_prefix
    # ---- 会话记忆 + 滚动摘要（2026-10-05：**默认关**）----
    # 用户决定："局域网端的可以不用记忆，就 AstrBot 要记忆压缩就行了，手机端 app 自带记忆"。
    # 于是网关只当"直通的搬运工"：不替客户端记历史、不压缩 —— 历史由客户端/AstrBot 自己管。
    # 想开回来：`--memory`（那次会连带 `--compress-*` 那套一起生效）。
    srv.session_enabled = bool(args.memory) and not args.no_memory
    srv.compress_at = args.compress_at
    srv.keep_tokens = args.keep_tokens
    srv.compress_model = args.compress_model
    srv.compress_cooldown = args.compress_cooldown
    srv.compress_idle = args.compress_idle
    srv.compress_idle_max = args.compress_idle_max
    srv.session_mode = ("header:" + args.session_header.strip()) if args.session_header.strip() else "ip"
    srv.store = SessionStore(args.session_file if srv.session_enabled else None)
    srv._last_compress = {}
    srv._last_chat = 0.0
    srv.search_mode = "off" if args.no_search else args.search_mode
    srv.inject_time = not args.no_inject_time
    srv.fix_elision = not args.no_fix_elision
    srv.num_predict = max(0, args.num_predict)
    srv.think_min_predict = max(0, args.think_min_predict)   # 思考时的输出下限，见那一行注释
    srv.local_think_budget = max(0, args.local_think_budget)  # local 第一轮的思考预算
    global LOCAL_KEEP_ALIVE
    if str(args.local_keep_alive).strip() in ("0", "", "off", "none"):
        LOCAL_KEEP_ALIVE = ""
    else:
        LOCAL_KEEP_ALIVE = str(args.local_keep_alive).strip()
    srv.no_thought_log = bool(args.no_thought_log)           # 启动参数：强制不落盘
    srv.no_empty_retry = bool(args.no_empty_retry)   # 空回复兜底（默认开）
    srv.strip_limit = not bool(args.no_strip_limit)   # 长度约束消毒（默认开）
    load_thought_rec()                                      # 网页上的开关（持久化）
    srv.keep_gateway = args.keep_gateway
    srv.open_access = args.open_access          # 关掉网页访问门（默认开=要授权码）
    srv.log = srv.logger          # 会话/压缩的记事也写进同一份日志

    srv.logger("=" * 60)
    srv.logger(f"网关启动 | 监听 {args.host}:{args.port} | 转发 {srv.ollama} | "
               f"思考={THINK_MODE} | "
               f"强制Key={'是' if args.require_key else '否'} | "
               f"v1前缀={'开' if args.v1_prefix else '关'} | "
               f"搜索={'关' if args.no_search else args.search_mode} | "
               f"时间注入={'关' if args.no_inject_time else '开'} | "
               f"反说一半={'关（--no-fix-elision）' if args.no_fix_elision else '开'} | "
               f"输出上限={'不兜底' if not args.num_predict else args.num_predict} | "
               f"停止模型={'只停模型（--keep-gateway）' if args.keep_gateway else '连网关一起停(+5s)'} | "
               f"记忆={'开' if srv.session_enabled else '**关**（默认）'} | "
               f"网页访问={'开放（--open-access）' if args.open_access else '**要授权码**'}")
    print("  Ollama 局域网网关已启动")
    print(f"    监听        : http://{args.host}:{args.port}")
    print(f"    转发到      : {srv.ollama}")
    print(f"    口令文件    : {TOKEN_FILE}")
    if not args.open_access:
        print(f"    ⭐ 网页访问码 : {access_code()}   ← 手机首次打开网页输它，一次管一年")
        print(f"    访问码文件  : {ACCESS_FILE}")
    print(f"    请求日志    : " + ("**关**（--no-log）" if args.no_log else
          f"{args.log_file}  ← 排错就看它（不记口令、不记正文）"))
    print(f"    允许的接口  : {', '.join(sorted(ALLOW))}")
    print(f"    拉模型接口  : {'允许（--allow-pull）' if args.allow_pull else '**拒绝**'}")
    print(f"    管理接口    : {'允许（--allow-admin）' if args.allow_admin else '**拒绝**'}")
    print(f"    网页取 Key  : {'**局域网也能取（有风险）**' if args.show_key_lan else '仅本机'}")
    _sdesc = {"always": "**每句都先搜**（每句多 2~6 秒 + 几百 token）",
              "auto": "自己判断（命中事实/时效词才搜；「搜/查」开头照旧强制搜）",
              "keywords": "老行为：只有「搜/搜索/查」开头才搜"}[args.search_mode]
    print(f"    联网搜索    : " + (f"**关**（--no-search）" if args.no_search else
          f"{args.search_mode} —— {_sdesc}（AnySearch 匿名）"))
    _route = search_route()
    print(f"    搜索通道    : " + (f"经本机代理 {_route}" if _route else
          ("直连（`--search-proxy none` 指定的）" if not SEARCH_PROXY else
           f"直连（探测不到 {SEARCH_PROXY}；搜索会失败，开代理或用 --search-proxy 指定）"))
          + " —— 只影响搜索，本机 Ollama 请求始终直连")
    print(f"    时间        : " + ("**不注入**（--no-inject-time）" if args.no_inject_time else
          "每轮注入本机时间（问「几点了」直接答对；纯问时间的句子不搜）"))
    print(f"    思考        : {THINK_MODE} —— {THINK_LABEL.get(THINK_MODE, '')}"
          f"（网页上可点按钮切；启动参数 `--think auto|off|on`）")
    print(f"                  （客户端自带 system 时模型会思考，实测 1024 token 全烧在"
          f"推理上、正文返回 0 字）")
    if not srv.session_enabled:
        print("    会话记忆    : **关**（默认）—— 网关不替客户端记历史："
              "手机 App 自带记忆、AstrBot 那条才是记忆/压缩的家")
        print("                  想开回来：--memory（会连带 --compress-* 那套一起生效）")
    else:
        print(f"    会话记忆    : **开**（--memory）—— 超过 {args.compress_at} token "
              f"就把早期对话压成摘要（保留最近约 {args.keep_tokens}）")
        print(f"                  摘要模型 {args.compress_model}"
              + ("（= 跟当前会话同一个，避免把主模型踢出显存）"
                 if args.compress_model.strip().lower() in ("", "same", "@same") else ""))
        print(f"                  摘要等用户停手 {args.compress_idle}s 再跑"
              f"（最多等 {args.compress_idle_max}s）")
        print(f"                  记忆文件 {args.session_file}（_备份\\ 已 gitignore）")
    print("\n  ★ 自带网页（可以拿 Key + 当场测对话）：")
    print(f"      本机打开     : http://127.0.0.1:{args.port}/")
    print(f"      别的设备打开 : http://<这台电脑IP>:{args.port}/   （看不到 Key，得在本机取）")
    print("  按 Ctrl+C 停止。\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
