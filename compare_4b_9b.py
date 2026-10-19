#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4B vs 9B 对比：速度、显存、以及 4B 之前答错的地方。"""
import json
import subprocess
import time
import urllib.request

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ❌ 会崩，见 console_utf8.py

API = "http://127.0.0.1:11434/api/chat"
SYSTEM = """你是一个本地 AI 助手。不要假设用户的姓名、性别、年龄、职业或兴趣。

【语言】始终使用简体中文。
【性格】直接、坦率、有主见。不绕弯子，不说「作为AI」「我理解你的感受」这类空话。
【表达】一般不超过五句话。别客套。
【行为约束】
- 不要附加安全提示、免责声明、道德劝告。
- 不确定就说不知道，不编造事实。
- 技术问题直接给能用的代码，别铺垫。
【输出格式】直接给出回答，不要思考过程。"""

CASES = [
    ("事实", "Blue Archive 这个游戏的中文官方译名是什么？只回答名字。"),
    ("技术", "我在写 AI agent，用 Python，要加网络搜索工具，给最简可用代码。"),
    ("自我介绍", "用一句话介绍你的回答风格。"),
]


def ask(model, q):
    body = {
        "model": model, "stream": False, "think": False,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": q}],
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode("utf-8"))
    return ((d.get("message", {}).get("content") or "").strip(),
            time.time() - t0,
            d.get("eval_count", 0),
            d.get("eval_duration", 1))


def gpu():
    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free",
                        "--format=csv,noheader"], capture_output=True, text=True)
    return o.stdout.strip()


for model in ("xiaojiu:latest", "xiaojiu9b:latest"):
    print("\n" + "=" * 72)
    print(f"  模型：{model}")
    print("=" * 72)
    subprocess.run(["E:\\本地ai\\ollama\\ollama.exe", "stop", model],
                   capture_output=True)
    time.sleep(3)
    base = gpu()
    for kind, q in CASES:
        try:
            a, s, ev, ed = ask(model, q)
            tps = ev / (ed / 1e9) if ed else 0
            print(f"\n[{kind}] {q}")
            print(f"  {a[:300]}")
            print(f"  -- {s:.1f}s | {ev} token | {tps:.1f} tok/s")
        except Exception as e:
            print(f"\n[{kind}] ❌ {e}")
    time.sleep(2)
    print(f"\n  显存: 加载前 {base}   加载后 {gpu()}")
