#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
和 Ollama 说话前的**护栏**：先探活、再调用、**超时就快速失败**。

为什么需要这个（真实事故）：
    另一个 AI 窗口在"验证改动"这一步**一直卡住**，用户只能让它别测了。
    原因不是模型慢，是**没有超时**：`test_persona.py` 当时写的是
    `urlopen(..., timeout=300)` —— 一个请求能等 5 分钟，3 个用例就是 15 分钟。
    而 Ollama 偶尔会**整个服务卡死**（`ollama ps` 挂着不返回、显存里没有模型、
    新请求一直排队）。两件事叠起来 = 从窗口外面看就是"卡住了、不知道在干什么"。

解法：
    1. **探活**（`/api/tags`、`/api/ps`）各给几秒超时 —— Ollama 正常时都是**几十毫秒**，
       超时就说明它卡死了，**立刻报错退出并给出复位命令**，绝不干等。
    2. **探 `/api/ps` 顺手知道模型加载了没** —— 没加载的话第一条回复要等 20-60 秒
       （5.6 GB 读进显存），提前说出来，别让调用方以为卡死了。
    3. **调用本身也给硬超时**，超时信息里直接写"下一步跑什么"。

用法（给测试脚本 import）：
    from ollama_guard import ensure_alive, chat

    ensure_alive()                      # 卡死就直接 SystemExit(2)，带复位提示
    text = chat(MODEL, [{"role": "system", "content": p},
                        {"role": "user", "content": q}], timeout=90)
"""
import json
import socket
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:11434"
PROBE_TIMEOUT = 6          # 探活用；正常是几十毫秒，6 秒还没答就是卡死
FIX_HINT = "python E:\\本地ai\\fix_ollama.py"


def _get_json(path: str, timeout: float):
    """GET 一个 JSON 端点。返回 **(ok, data, kind)**。

    ⚠️ 2026-09-29 加 `kind`：原来只返回 (ok, data|错误串)，于是**所有失败都被
        上层说成"Ollama 服务卡死、去复位"** —— 包括：
          · HTTP 500（服务在，是它内部出错）
          · 连接被拒（服务根本没起）
          · 端口被别的程序占着返回 HTML（json 解析失败）
        这三种都**不该复位**，复位也没用，用户只会在"复位了还是卡"里空转。
        kind: "ok" / "http" / "refused" / "timeout" / "notjson" / "other"
    """
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        try:
            return True, json.loads(raw), "ok"
        except ValueError:
            return False, f"返回的不是 JSON（开头：{raw[:60]!r}）", "notjson"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.reason}", "http"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (ConnectionRefusedError,)) or "refused" in str(reason).lower():
            return False, f"连接被拒：{reason}", "refused"
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return False, f"超时：{reason}", "timeout"
        return False, f"{type(reason).__name__}: {reason}", "other"
    except (socket.timeout, TimeoutError) as e:
        return False, f"超时：{e}", "timeout"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}", "other"


def doctor(timeout: float = PROBE_TIMEOUT) -> dict:
    """只读体检：Ollama 活不活、模型加载了没。不加载模型、不占 GPU。

    返回 {'alive': bool, 'loaded': [模型名], 'err': str, 'kind': str, 'ms': int}
    """
    t0 = time.time()
    ok, data, kind = _get_json("/api/tags", timeout)
    ms = int((time.time() - t0) * 1000)
    if not ok:
        return {"alive": False, "loaded": [], "err": str(data), "kind": kind, "ms": ms}

    loaded: list[str] = []
    ok2, data2, _kind2 = _get_json("/api/ps", timeout)
    if ok2:
        loaded = [m.get("name", "?") for m in data2.get("models", [])]
    return {"alive": True, "loaded": loaded, "err": "", "kind": "ok", "ms": ms}


def ensure_alive(timeout: float = PROBE_TIMEOUT, quiet: bool = False) -> list[str]:
    """探活。**探不通就退出**（SystemExit 2），并按**失败类型**给出对症的下一步。

    返回已加载的模型名列表（空列表 = 还没加载，第一条回复会慢）。

    ⚠️ 2026-09-29 重写诊断文案：原来一律说"Ollama 服务卡死 → 复位"，
        而"连接被拒"（服务没起）和"HTTP 500"（服务在、内部出错）
        **复位都不是正解**。现在分四种情况给不同的建议。
    """
    d = doctor(timeout)
    if d["alive"]:
        return d["loaded"]

    print()
    print("=" * 66)
    kind = d.get("kind", "other")
    print(f"[X] 探不通 Ollama（等了 {timeout} 秒：{d['err']}）")
    print()
    if kind == "refused":
        print("    诊断：**Ollama 服务没有在跑**（连接被拒），不是卡死。")
        print("    下一步：双击项目根的「启动AstrBot.bat」（它会拉起 Ollama），")
        print("            或者单独跑：E:\\本地ai\\ollama\\ollama.exe serve")
    elif kind == "http":
        print("    诊断：Ollama **在跑，但它自己报了错**（HTTP 错误）—— 不是卡死。")
        print("    下一步：先看它的窗口/日志里的报错；重启一次通常能好：")
        print(f"            {FIX_HINT}")
    elif kind == "notjson":
        print("    诊断：11434 端口**被别的程序占着**（返回的不是 JSON）。")
        print("    下一步：`Get-NetTCPConnection -LocalPort 11434 -State Listen`")
        print("            看是哪个进程，把冲突的程序关掉或换端口。")
    elif kind == "timeout":
        print("    诊断：**Ollama 服务卡死**了 —— 一个请求发出去会一直排队，")
        print("          所以脚本看起来是'卡住'，其实是永远等不到回答。")
        print("    下一步（复位，一步，AstrBot 不用关）：")
        print(f"            {FIX_HINT}")
        print("            或者双击项目根的「修复Ollama.bat」。")
    else:
        print("    诊断：网络层出错（不是 Ollama 卡死）。")
        print("    下一步：先确认没有代理/VPN 拦了 127.0.0.1，再重启 Ollama：")
        print(f"            {FIX_HINT}")
    print("=" * 66)
    raise SystemExit(2)

    if not quiet:
        if d["loaded"]:
            print(f"[i] Ollama 正常（{d['ms']} ms），已加载：{', '.join(d['loaded'])}")
        else:
            print(f"[i] Ollama 正常（{d['ms']} ms），**模型还没加载** —— "
                  f"第一条回复要等 20–60 秒（5.6 GB 读进显存），不是卡住。")
    return d["loaded"]


def chat_raw(model: str, messages: list, options: dict | None = None,
             timeout: float = 90, label: str = "") -> dict:
    """发一次 /api/chat，**硬超时**，返回**完整响应**（要 prompt_eval_count 用它）。

    超时/失败时抛 SystemExit(2) 并给出下一步。

    ⚠️ 默认 **不传 num_ctx** —— 传了就可能和 AstrBot 那份已加载实例的参数不一致，
    Ollama 会卸载再重载整个模型（多几十秒，而且更容易和 AstrBot 抢显存）。
    """
    body = {"model": model, "stream": False, "messages": messages}
    if options:
        body["options"] = options
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        el = time.time() - t0
        print()
        print(f"[X] {label}调用失败（等了 {el:.0f} 秒，上限 {timeout:.0f} 秒）：{e}")
        print(f"    多半是 Ollama 卡死或正在加载模型。复位：{FIX_HINT}")
        print("    只是嫌慢就把 timeout 调大；想完全不碰 GPU 就别跑模型测试。")
        raise SystemExit(2) from None
    el = time.time() - t0
    if el > timeout * 0.8:
        print(f"    [i] {label}这次用了 {el:.1f} 秒（接近 {timeout:.0f} 秒上限）")
    return data


def chat(model: str, messages: list, options: dict | None = None,
         timeout: float = 90, label: str = "") -> str:
    """同 `chat_raw`，但只返回正文文本。"""
    data = chat_raw(model, messages, options, timeout, label)
    return (data.get("message", {}).get("content") or "").strip()


if __name__ == "__main__":
    # 直接跑就是体检：python ollama_guard.py
    sys.path.insert(0, r"E:\本地ai")
    try:
        from console_utf8 import console_utf8
        console_utf8()
    except Exception:                                   # noqa: BLE001
        pass
    loaded = ensure_alive()
    print(f"已加载模型数：{len(loaded)}")
