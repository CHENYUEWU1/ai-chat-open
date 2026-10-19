#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测模型的工具调用能力：能否正确决定何时搜索、并给出合规的调用参数。

默认测 9B（4B 已删除）。可临时指定别的：
    set XIAOJIU_MODEL=xiaojiu9b:latest
"""
import json
import os
import urllib.request

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

API = "http://127.0.0.1:11434/api/chat"
MODEL = os.environ.get("XIAOJIU_MODEL", "xiaojiu9b:latest")

TOOLS = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "搜索互联网获取最新信息。当需要实时数据、新闻、价格、天气或你不确定的事实时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"}
            },
            "required": ["query"],
        },
    },
}]


def ask(prompt, use_tools=True):
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": "你是小九，简体中文助手。需要实时信息时必须调用 web_search 工具。"},
            {"role": "user", "content": prompt},
        ],
    }
    if use_tools:
        body["tools"] = TOOLS
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


CASES = [
    ("需要联网", "帮我查一下今天北京天气怎么样"),
    ("需要联网", "英伟达 RTX 5090 现在什么价格？"),
    ("需要联网", "最近有什么科技新闻？"),
    ("不该联网", "1+1 等于几？"),
    ("不该联网", "用一句话解释什么是递归"),
]

print("=" * 68)
print("工具调用能力实测（judgment：该搜的搜，不该搜的不搜）")
print("=" * 68)

for kind, q in CASES:
    try:
        res = ask(q)
        msg = res.get("message", {})
        calls = msg.get("tool_calls") or []
        if calls:
            fn = calls[0].get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            got = f"✅ 调用 web_search(query={args.get('query')!r})"
        else:
            content = (msg.get("content") or "").strip().replace("\n", " ")
            got = f"— 未调用，直接答: {content[:60]}"
        expect = "应调用" if kind == "需要联网" else "不应调用"
        mark = ""
        if kind == "需要联网" and calls:
            mark = "  ★正确"
        elif kind == "不该联网" and not calls:
            mark = "  ★正确"
        else:
            mark = "  ⚠️可能不对"
        print(f"\n[{kind}] {q}")
        print(f"  期望: {expect}")
        print(f"  实际: {got}{mark}")
    except Exception as e:
        print(f"\n[{kind}] {q}\n  ❌ 请求失败: {e}")
