#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长上下文真实性验证：大海捞针测试。
在长文本开头埋一个事实，末尾提问，看模型能否想起来。
"""
import json
import os
import time
import urllib.request

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

API = "http://127.0.0.1:11434/api/chat"
MODEL = os.environ.get("LOCAL_ASSISTANT_MODEL", "local-assistant-9b:latest")

FILLER = (
    "这是一段用于测试长上下文记忆的填充文本。"
    "蝴蝶在花园里飞舞，溪水潺潺流过石头，远处山峦叠嶂。"
    "镇上的集市每周三开张，卖鱼的老王总爱讲他年轻时的故事。"
)


def build_prompt(repeats: int) -> str:
    """把「针」放在最开头，后面塞大量填充文本。"""
    needle = "【重要信息】我家的 WiFi 密码是：Blue-Falcon-7742。"
    body = FILLER * repeats
    return needle + "\n\n" + body


def ask(text: str):
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": "你是助手，简洁回答，只给答案。"},
            {"role": "user", "content": text + "\n\n问题：我家的 WiFi 密码是什么？只回答密码本身。"},
        ],
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data, time.time() - t0


print("=" * 66)
print("大海捞针：密码藏在长文本【开头】，问题在【末尾】")
print("=" * 66)

for repeats in (30, 150, 400):
    text = build_prompt(repeats)
    approx_tokens = len(text) // 2  # 中文约 2 字符/token 粗估
    try:
        data, secs = ask(text)
        content = (data.get("message", {}).get("content") or "").strip()
        hit = "Blue-Falcon-7742" in content
        # Ollama 返回的 prompt_eval_count 是真实 token 数
        pe = data.get("prompt_eval_count", "?")
        ev = data.get("eval_count", "?")
        print(f"\n填充 {repeats} 段  (~{len(text)} 字符)")
        print(f"  实际 prompt token : {pe}")
        print(f"  耗时              : {secs:.1f}s  (输出 {ev} token)")
        print(f"  回答              : {content[:80]}")
        print(f"  捞到针了吗        : {'✅ 是' if hit else '❌ 否 —— 上下文没记住'}")
    except Exception as e:
        print(f"\n填充 {repeats} 段 → ❌ 失败: {e}")
