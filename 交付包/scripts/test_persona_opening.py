#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
量「回复开场重复」—— 把 `06` §6 里那个指标变成能跑的。

为什么要单独有个脚本：
    "每次都用同一个词起手"是用户反复反馈的问题（"输出的话会重复"）。
    但这个问题**只能量，不能感觉** —— 实测里凭印象判断错过好几次。
    这个脚本固定提示词、只换 seed，把每条回复的**开头若干字**打出来，
    并统计首字分布 + 命中「开场禁词表」的次数。

用法：
    python test_persona_opening.py                    # 当前启用的人格，默认 5 个样本
    python test_persona_opening.py -n 8               # 8 个样本
    python test_persona_opening.py -p "在干嘛"         # 换提示词
    python test_persona_opening.py -P 病娇-助手-露骨   # 换人格
    python test_persona_opening.py --full             # 连正文一起打

判读：
    - **首字分布**集中在少数几个字 → 开场在重复
    - **命中开场禁词表**（好/嗯/行/对/是/知/来/在）→ 违反人格里那条明文规则
    - ⚠️ **先看原文再看计数**：实测把「"好」「"好香」「"好痒」都算成同一个起手，
      报了 6/10，其实只有一个字面重复。所以下面两个都打。
    - ⚠️ 样本数 <3 别下结论（小模型方差极大）。

⚠️ 要 Ollama 在跑。**这个脚本会加载模型、占显存**：
   第一次约 20–60 秒，之后每样本 10–25 秒。
   **只想看项目状态别跑它** —— 跑 `python check_all.py`（只读、不碰 GPU）。
   卡住不动：`python fix_ollama.py`（复位 Ollama，AstrBot 不用关）。
"""
import re
import sys
from collections import Counter
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

from ollama_guard import chat, ensure_alive   # noqa: E402

PERSONAS = Path(r"C:\LocalAI-Assistant\personas")
ACTIVE = PERSONAS / ".active"
MODEL = "local-assistant-9b:latest"
CHAT_TIMEOUT = 90.0    # 单条回复的硬上限（含模型加载时会更久，护栏会提示）

DEFAULT_PROMPT = "在干嘛"
DEFAULT_N = 5
HEAD_LEN = 12          # 打印开头多少字

# 人格 `【⭐ 进阶内容】` ⑤ 那条明文的开场禁词表。
# ⚠️ 改动人格里那张表时，**这里要跟着改**（否则量的是旧规则）。
BANNED_OPENERS = "好嗯行对是知来在"


def active_persona() -> str:
    try:
        return ACTIVE.read_text(encoding="utf-8").strip()
    except Exception:                                  # noqa: BLE001
        return ""


def ask(persona: str, user: str, seed: int, n_predict: int) -> str:
    # 不传 num_ctx：和 AstrBot 那份缓存参数不一致会触发整模型重载
    return chat(MODEL, [
        {"role": "system", "content": persona},
        {"role": "user", "content": user},
    ], options={"num_predict": n_predict, "seed": seed},
        timeout=CHAT_TIMEOUT, label=f"seed={seed} ")


def first_visible(text: str) -> str:
    """去掉开头的引号/空白/换行，取第一段可见文字。"""
    t = text.strip()
    t = re.sub(r'^["“”\'‘’「『\s]+', "", t)
    return t


def main() -> int:
    args = sys.argv[1:]

    def opt(flag: str, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    n = int(opt("-n", DEFAULT_N))
    prompt = opt("-p", DEFAULT_PROMPT)
    name = opt("-P", active_persona())
    n_predict = int(opt("--n-predict", 768))
    full = "--full" in args

    if not name:
        print("[X] 读不到 personas\\.active；用 -P <人格名> 指定")
        return 1
    path = PERSONAS / f"{name}.txt"
    if not path.exists():
        print(f"[X] 没有这份人格：{name}")
        return 1

    persona = path.read_text(encoding="utf-8")
    print(f"人格：{name}（{len(persona)} 字符）")
    print(f"提示词：「{prompt}」（固定），只换 seed 1..{n}")
    print("=" * 68)

    ensure_alive()          # 卡死就直接退出，不干等

    heads: list[str] = []
    banned_hits = 0
    for seed in range(1, n + 1):
        try:
            out = ask(persona, prompt, seed, n_predict)
        except SystemExit as e:
            print(f"\n[X] 停在 seed={seed} —— 见上面的提示（不是模型的问题）。")
            return int(e.code or 2)
        head = first_visible(out)
        heads.append(head)
        mark = ""
        if head and head[0] in BANNED_OPENERS:
            mark = f"   ← [!] 命中开场禁词「{head[0]}」"
            banned_hits += 1
        print(f"\nseed={seed}  {len(out):>4} 字  开头：{head[:HEAD_LEN]!r}{mark}")
        if full:
            print("-" * 68)
            print(out)
            print("-" * 68)

    print("\n" + "=" * 68)
    dist = Counter(h[0] for h in heads if h)
    print(f"首字分布：{dict(dist)}")
    print(f"前 2 字分布：{dict(Counter(h[:2] for h in heads if h))}")
    print(f"命中开场禁词表（{BANNED_OPENERS}）：{banned_hits} / {n}")
    print()
    print("判读：首字集中在少数几个字 = 开场在重复。")
    print("⚠️ 先看上面的原文再信计数；样本 <3 别下结论。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
