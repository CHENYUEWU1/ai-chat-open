# 2026-10-22 注意：本脚本面向 Ollama（已弃用，用户只留 llama.cpp）。保留作排错参考；跑之前先起 Ollama。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
量每份人格**真实**吃多少 token —— 别用字符数乘系数。

为什么要单独有个脚本（02 坑 29）：
    文档里长期写着"≈1.17 token/字符"这个手估的换算系数，
    而**同一节的表格自己算出来是 1.32**，两者矛盾了两个月没人发现。
    系数错了会静默污染之后每一个判断（偏小 12% → 少算 900 token ≈ 3% 窗口）。

    所以：**人格大小一律现场量，不折算。**

用法：
    python test_persona_tokens.py              # 量 personas\ 里全部
    python test_persona_tokens.py 病娇-助手-露骨   # 只量指定几份
    python test_persona_tokens.py --ratio       # 额外打印 tok/字符

原理：
    直接把人格全文当 system 发一次 `/api/chat`，读返回的 `prompt_eval_count`。
    它包含：人格 + 聊天模板 + 一句 "你好"（合计约 23 token 的固定开销）。
    要算"人格净重"就减 23 —— **不要**用别的东西做减法去推（坑 27 的同款错误）。

⚠️ 需要 Ollama 在跑（`http://127.0.0.1:11434`）。
    **这个脚本会加载模型、占显存**，第一次约 20–60 秒；之后每份都是秒级。
    只想看项目状态别跑它 —— 跑 `python check_all.py`（只读、不碰 GPU）。
    卡住不动的话：`python fix_ollama.py`（复位 Ollama，AstrBot 不用关）。
"""
import sys
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

from ollama_guard import chat_raw, ensure_alive   # noqa: E402

PERSONAS = Path(r"C:\LocalAI-Assistant\personas")
MODEL = "local-assistant-9b:latest"
CHAT_TIMEOUT = 60.0   # 量 token 只需要生成 1 个 token，60 秒足够（含加载）
WINDOW = 32768        # 只用来算"占几成"，不往请求里传（原因见 probe()）
OVERHEAD = 23         # 聊天模板 + 那句"你好"的固定开销（实测，不是推的）


def probe(text: str) -> int:
    r"""量一次。返回 prompt_eval_count（含 OVERHEAD）。

    ⚠️ **故意不传 num_ctx** —— 传了会和 AstrBot 那份已加载实例的参数不一致，
    Ollama 于是卸载再重载 5.6 GB 模型（多几十秒，还容易抢显存）。
    `prompt_eval_count` 只跟提示词有关，跟 num_ctx 无关，所以不传没有损失。
    """
    data = chat_raw(MODEL, [
        {"role": "system", "content": text},
        {"role": "user", "content": "你好"},
    ], options={"num_predict": 1}, timeout=CHAT_TIMEOUT, label="量 token ")
    return int(data["prompt_eval_count"])


def targets(args: list[str]) -> list[Path]:
    wanted = [a for a in args if not a.startswith("-")]
    if not wanted:
        return sorted(PERSONAS.glob("*.txt"))
    out = []
    for w in wanted:
        p = PERSONAS / f"{w}.txt"
        if not p.exists():
            print(f"[!] 没有这份人格，跳过：{w}")
            continue
        out.append(p)
    return out


def main() -> int:
    args = sys.argv[1:]
    show_ratio = "--ratio" in args
    files = targets(args)
    if not files:
        print(f"[X] {PERSONAS} 里没有可量的人格")
        return 1

    ensure_alive()          # 卡死就直接退出，不干等

    head = f"{'人格':<22}{'字符':>7}{'实测 token':>12}{'占 32K':>9}{'留给对话':>10}"
    if show_ratio:
        head += f"{'tok/字符':>10}"
    print(head)
    print("-" * len(head))

    for p in files:
        text = p.read_text(encoding="utf-8")
        chars = len(text)
        try:
            tok = probe(text)
        except SystemExit as e:
            # 护栏已经把原因和复位命令打出来了，直接把它传上去
            print(f"\n[X] 停在 {p.stem} —— 不是模型的问题，见上面的提示。")
            return int(e.code or 2)
        net = tok - OVERHEAD
        row = (f"{p.stem:<22}{chars:>7}{tok:>12}"
               f"{tok / WINDOW * 100:>8.1f}%{WINDOW - tok:>10}")
        if show_ratio:
            row += f"{net / chars:>10.3f}"
        print(row)

    print(f"\n（token 里含约 {OVERHEAD} 的模板 + 那句「你好」的固定开销；"
          f"tok/字符 是**扣掉这 {OVERHEAD} 之后**算的）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
