#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""验证人格的实际效果。默认直接读当前启用的那份人格文件，不存副本。

⚠️ 这个脚本会**加载模型、占显存**，而且慢（一条 10–25 秒）。
   只想看项目状态别跑它 —— 跑 `python check_all.py`（只读、不碰 GPU）。

   原来这里写的是 `urlopen(..., timeout=300)`：一个请求能等 5 分钟，
   3 个用例就是 15 分钟。Ollama 一卡死，从外面看就是"卡住了"。
   现在统一走 `ollama_guard`：先探活、再调用、**超时快速失败并给出复位命令**。
"""
import os
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ❌ 会崩，见 console_utf8.py

from ollama_guard import chat, ensure_alive   # noqa: E402

MODEL = os.environ.get("XIAOJIU_MODEL", "xiaojiu9b:latest")

# 测哪份人格：默认「示例人格Y」，可用 XIAOJIU_PERSONA 覆盖（不带 .txt）
PERSONA = Path(r"E:\本地ai\personas") / (
    os.environ.get("XIAOJIU_PERSONA", "示例人格Y") + ".txt")
if not PERSONA.exists():
    raise SystemExit(f"❌ 找不到人格文件: {PERSONA}")
SYSTEM = PERSONA.read_text(encoding="utf-8").rstrip()
print(f"人格: {PERSONA.name}  ({len(SYSTEM)} 字符)   模型: {MODEL}\n")

CASES = [
    "你还记得我叫什么吗？我平时都在干嘛？",
    "我在写一个 AI agent，用 Python，想加个网络搜索工具，给我最简的代码。",
    "今天不想写代码，推荐个二次元相关的游戏。",
]

# 每条回复的硬上限。模型加载另算（ensure_alive 会提前告诉你）。
TIMEOUT = float(os.environ.get("XIAOJIU_TIMEOUT", "90"))


def main() -> int:
    ensure_alive()          # 卡死就直接退出，不干等

    print("=" * 68)
    for q in CASES:
        print(f"\n【问】{q}")
        try:
            a = chat(MODEL, [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": q},
            ], timeout=TIMEOUT, label="人格测试 ")
        except SystemExit as e:
            # 护栏已经打清楚了，这里不再堆栈；把退出码传出去
            return int(e.code or 2)
        print(f"【答】{a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
