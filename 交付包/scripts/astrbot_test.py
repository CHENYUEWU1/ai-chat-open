#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AstrBot 端到端自检：登录 → 开新会话 → 真发一条消息 → 把回复抠出来。

不用打开浏览器，直接打 AstrBot 自己的 HTTP API，
所以能在看不到界面的情况下确认「模型接上了、人格生效了」。

⚠️ 要用你在 AstrBot 界面里设的账号密码登录。**密码不写死在脚本里**
   （改过密码之后硬编码就失效了）。

用法：
    python astrbot_test.py --user chen --password 你的密码 "今天有什么新闻"
    python astrbot_test.py                      # 用环境变量里的凭据，默认问一句

或者先设环境变量（一次设好，之后不用重复）：
    $env:ASTRBOT_USER = "chen"
    $env:ASTRBOT_PASS = "你的密码"
    python astrbot_test.py "帮我查一下 XXX"
"""
import json
import sys

from console_utf8 import console_utf8

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:6185"

# 凭据不写死 —— 你在界面里改过密码之后，硬编码的就会失效。
# 优先级：命令行参数 > 环境变量 > 默认值
USER = os.environ.get("ASTRBOT_USER", "astrbot")
PWD = os.environ.get("ASTRBOT_PASS", "")

PROVIDER = "ollama_xiaojiu9b"


def cli_creds() -> None:
    """支持 python astrbot_test.py --user chen --password xxx "问题" """
    global USER, PWD
    args = sys.argv[1:]
    rest = []
    i = 0
    while i < len(args):
        if args[i] in ("--user", "-u") and i + 1 < len(args):
            USER = args[i + 1]; i += 2; continue
        if args[i] in ("--password", "-p") and i + 1 < len(args):
            PWD = args[i + 1]; i += 2; continue
        rest.append(args[i]); i += 1
    sys.argv = [sys.argv[0]] + rest


def call(path, data=None, token=None, method=None, timeout=600):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body,
                                 method=method or ("POST" if body else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def strip_tool_json(s: str) -> str:
    """AstrBot 有时会把工具调用/结果的 JSON 混进可见文本里。
    用括号配对把「含 name 或 result 的完整 JSON 对象」整段抠掉，比正则可靠。"""
    out, i = [], 0
    while i < len(s):
        if s.startswith('{"id"', i) or s.startswith('{"name"', i):
            depth, j, instr, esc = 0, i, False, False
            while j < len(s):
                ch = s[j]
                if instr:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        instr = False
                elif ch == '"':
                    instr = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            blob = s[i:j + 1]
            if '"name"' in blob or '"result"' in blob:
                i = j + 1
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def last_assistant_text() -> str:
    """从消息库里读最后一条 assistant 消息 —— 这才是界面里真正显示的内容，
    比解析 SSE 流可靠得多（工具调用/结果在库里是独立条目，不会混进来）。"""
    import re
    import sqlite3
    try:
        c = sqlite3.connect("file:E:/本地ai/AstrBotData/data/data_v4.db?mode=ro", uri=True)
        c.text_factory = lambda b: b.decode("utf-8", "replace")
        rows = c.execute(
            "SELECT content FROM conversations ORDER BY rowid DESC LIMIT 3").fetchall()
        c.close()
    except Exception as e:
        return f"（读库失败: {e}）"
    for (content,) in rows:
        try:
            msgs = json.loads(content)
        except Exception:
            continue
        for m in reversed(msgs):
            if m.get("role") != "assistant":
                continue
            c2 = m.get("content")
            parts = []
            if isinstance(c2, list):
                parts = [x.get("text", "") for x in c2 if isinstance(x, dict)]
            elif isinstance(c2, str):
                parts = [c2]
            txt = "\n".join(p for p in parts if p).strip()
            if txt:
                txt = re.sub(r"<ref>.*?</ref>", "", txt, flags=re.S)
                return txt.strip()
    return ""


def main() -> int:
    cli_creds()
    msg = sys.argv[1] if len(sys.argv) > 1 else "介绍一下你自己，用你自己的语气。"

    if not PWD:
        print("[X] 没有密码。这个脚本要用你的 AstrBot 账号登录，两种给法：")
        print('      python astrbot_test.py --user 你的用户名 --password 你的密码 "问题"')
        print('      或先设环境变量： $env:ASTRBOT_USER="chen"; $env:ASTRBOT_PASS="..."')
        return 1

    st, raw = call("/api/auth/login", {"username": USER, "password": PWD})
    if st != 200:
        print(f"[X] 登录失败 HTTP {st}: {raw[:200]}")
        if st == 401:
            print("     用户名或密码不对。你在 AstrBot 界面里改过密码的话，")
            print("     用 --user/--password 传新的，或者设 ASTRBOT_USER / ASTRBOT_PASS。")
            print("     忘了密码可以重置：")
            print("       E:\\本地ai\\AstrBot\\AstrBot_4.28.1_windows_amd64_portable\\backend\\python\\python.exe \\")
            print("         E:\\本地ai\\AstrBot\\AstrBot_4.28.1_windows_amd64_portable\\backend\\app\\main.py --reset-password")
        return 1
    token = json.loads(raw)["data"]["token"]
    print(f"[OK] 登录成功（{USER}）")

    st, raw = call("/api/v1/providers?provider_type=chat_completion", token=token)
    if st == 200:
        items = json.loads(raw).get("data") or []
        if isinstance(items, dict):
            items = items.get("providers", [])
        print(f"[OK] 已加载对话提供商 {len(items)} 个")
        for p in items:
            print(f"     id={p.get('id')}  model={p.get('model')}  enable={p.get('enable')}")
    else:
        print(f"[!] 提供商查询 HTTP {st}")

    st, raw = call("/api/v1/chat/sessions/new?platform_id=webchat", token=token)
    if st != 200:
        print(f"[X] 开会话失败 HTTP {st}: {raw[:200]}")
        return 1
    sid = (json.loads(raw).get("data") or {}).get("session_id")
    print(f"[OK] 新会话: {sid}")

    print(f"\n>>> 发送: {msg}\n" + "─" * 60)
    st, raw = call("/api/chat/send",
                   {"message": msg, "session_id": sid,
                    "selected_provider": PROVIDER, "username": USER},
                   token=token)
    if st != 200:
        print(f"[X] HTTP {st}: {raw[:400]}")
        return 1

    # SSE 流里同一段文字会以「增量 delta」和「完整快照」两种形式发来。
    # 稳妥做法：增量各自累积、快照各自留一份，最后取最长的那个。
    deltas, snaps, thinking, tools, final = "", [], [], [], ""
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        t = str(obj.get("type") or obj.get("event") or "")
        d = obj.get("data", obj)

        # AstrBot 最后会发一个 type=complete，里面就是完整答案 —— 最可靠的来源
        if t == "complete":
            final = d if isinstance(d, str) else str(d)
            continue
        if t in ("end", "agent_stats", "message_saved"):
            continue

        # 工具调用 / 工具结果：单独收集，绝不能混进正文
        if isinstance(d, dict) and ("args" in d and "name" in d):
            tools.append(f"call {d.get('name')} {json.dumps(d.get('args'), ensure_ascii=False)[:160]}")
            continue
        if isinstance(d, dict) and "result" in d and "id" in d:
            tools.append(f"result {str(d.get('result'))[:120]}...")
            continue
        if "tool" in t or "reason" in t or "think" in t:
            if isinstance(d, dict):
                thinking.append(str(d.get("text") or d.get("content") or ""))
            continue

        piece = ""
        if isinstance(d, str):
            piece = d
        elif isinstance(d, dict):
            for k in ("text", "content", "message", "delta"):
                v = d.get(k)
                if isinstance(v, str) and v:
                    piece = v
                    break
                if isinstance(v, dict):
                    vv = v.get("content") or v.get("text")
                    if isinstance(vv, str):
                        piece = vv
                        break
        if not piece:
            continue
        if t.endswith("snapshot") or t.endswith("complete") or t.endswith("full"):
            snaps.append(piece)
        else:
            deltas += piece
            snaps.append(deltas)      # 增量也是一种累积快照

    # 优先用 SSE 的 complete 事件；它没有就等落库后读库（落库在流结束之后）
    import time as _t
    out = final.strip()
    if not out:
        _t.sleep(4)
        out = last_assistant_text()
    if not out:
        import re
        out = max(snaps + [deltas], key=len) if (snaps or deltas) else ""
        out = re.sub(r"<br\s*/?>", "\n", out)
        out = re.sub(r"<[^>]+>", "", strip_tool_json(out)).strip()
    if not out:
        print("（完全没拿到回复，原始响应前 2000 字符）")
        print(raw[:2000])
        return 1
    print(out)
    print("─" * 60)
    if tools:
        print(f"\n[调用了工具 {len(tools)} 次]")
        for t in tools[:2]:
            print("  " + t[:150])
    if thinking:
        print(f"\n[[!] 有思考内容 {sum(len(x) for x in thinking)} 字符]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
