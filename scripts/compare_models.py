#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""两个本地模型的同人格对比实测（9B vs 35B）。

干什么：
    同一份人格、同一批输入、各若干样本，分别跑 9B 和 35B，记录
    **读提示耗时 / 整轮耗时 / tok/s / 输出长度 / 表情符号数**，并把**逐条原文**
    写进 `_备份\模型对比-原始输出.txt` 供人读。

    2026-09-29 用它得出的结论（写在 交付包\给AI看的\参考-模型对比实测.md）：
    35B 回复质量更好、第二句起更快（37.9 vs 27.9 tok/s），
    但**每场对话第一条慢**（读提示 22.6 s，整轮约 58 s）。

⚠️ 为什么必须分两次跑：
    两个模型**不能同时驻留**（`OLLAMA_MAX_LOADED_MODELS=1`，8 GB 显存装不下）。
    跑完一个要 `ollama stop` 卸载，再跑另一个。

⚠️ 这是 **GPU 测试**（每个模型 14 次请求，9B 约 4 分钟、35B 约 10 分钟）。
    跑之前先 `python fix_ollama.py --check` 探活；卡住超过 2 分钟就跑 `fix_ollama.py` 复位。

用法：
    python compare_models.py 9b            # 只测 9B
    E:\本地ai\ollama\ollama.exe stop xiaojiu9b:latest
    python compare_models.py 35b           # 再测 35B

参数为什么不同（9B 0.7 / 35B 1.0）：那是两个模型各自 Modelfile 里的出厂推荐值，
强行统一会对其中一方不公平。**换人格 / 改 num_predict 后结论要重测。**
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

from safe_write import read_text_raw, write_text

# ⚠️ 2026-10-03：用户把人格改名/归档了（`示例角色E` → `不要看\历史版本\`，
#    女版现在叫 `示例角色A`）。这里**从 personas\.active 读当前人格**，
#    别再写死一个名字 —— 写死的话下次改名它又会指向一个不存在的文件。
_PERSONAS = Path(r"E:\本地ai\personas")
_ACTIVE = _PERSONAS / ".active"
_name = (_ACTIVE.read_text(encoding="utf-8").strip() if _ACTIVE.exists() else "")
PERSONA = _PERSONAS / f"{_name}.txt"
if not PERSONA.exists():
    raise SystemExit(f"[X] 读不到当前人格：{PERSONA}\n"
                     f"    先确认 personas\\.active 里写的是现存人格名")
BASE = "http://127.0.0.1:11434/api/chat"
OUT = Path(r"E:\本地ai\_备份\模型对比-原始输出.txt")

# 各自的 Modelfile 参数（9B: temp 0.7 / 35B: temp 1.0，都是各自出厂推荐值）
CFG = {
    "9b":  ("xiaojiu9b:latest",              0.7),
    "35b": ("qwen36-35b-uncensored:latest",  1.0),
}
OPT = {"top_p": 0.95, "top_k": 20, "repeat_penalty": 1.15,
       "repeat_last_n": 1024, "num_predict": 300, "num_ctx": 32768}

PROMPTS = [
    "来亲亲",
    "今天有点累，陪我说会儿话",
    "（把手搭在你腰上）今天没心思，别闹",
    "我刚回来",
]
N_SAMPLE = 3


def call(model, temp, messages, seed):
    opts = dict(OPT)
    opts["temperature"] = temp
    opts["seed"] = seed
    body = json.dumps({"model": model, "messages": messages, "stream": False,
                       "think": False, "options": opts}).encode()
    req = urllib.request.Request(BASE, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    wall = time.time() - t0
    ev = d.get("eval_count") or 0
    evd = (d.get("eval_duration") or 1) / 1e9
    txt = d["message"]["content"] or ""
    return {
        "ttft_ms": round((d.get("prompt_eval_duration") or 0) / 1e6),
        "wall_s": round(wall, 1),
        "tok_s": round(ev / evd, 1) if evd else 0,
        "out_tok": ev,
        "chars": len(txt),
        "emoji": sum(1 for c in txt if ord(c) > 0x1F000),
        "text": txt,
    }


def main() -> int:
    key = (sys.argv[1] if len(sys.argv) > 1 else "9b").lower()
    if key not in CFG:
        print(f"[X] 只认 9b / 35b，收到 {key}")
        return 1
    model, temp = CFG[key]
    if not PERSONA.exists():
        print(f"[X] 找不到人格文件 {PERSONA}")
        return 1
    persona = read_text_raw(PERSONA)

    lines = [f"########## {key}  ({model}, temp={temp}) ##########", "",
             "== 时间：冷启动 vs 第二句 =="]
    msgs = [{"role": "system", "content": persona}]
    for i, q in enumerate(["来亲亲", "我亲了上去"], 1):
        msgs.append({"role": "user", "content": q})
        r = call(model, temp, msgs, 1000 + i)
        msgs.append({"role": "assistant", "content": r["text"]})
        tag = "第一条(冷)" if i == 1 else "第二条(热)"
        lines.append(f"  {tag}: 读提示 {r['ttft_ms']} ms · 整轮 {r['wall_s']} s · "
                     f"{r['tok_s']} tok/s · 输出 {r['out_tok']} tok")
        print(lines[-1], flush=True)

    rows = []
    for q in PROMPTS:
        lines += ["", "=" * 72, f"【输入】{q}", "=" * 72]
        for j in range(N_SAMPLE):
            seed = 2000 + j
            r = call(model, temp, [{"role": "system", "content": persona},
                                   {"role": "user", "content": q}], seed)
            rows.append({k: r[k] for k in ("wall_s", "tok_s", "out_tok", "chars", "emoji")})
            lines += [f"--- 样本{j+1} (seed={seed})  {r['wall_s']}s · {r['tok_s']} tok/s · "
                      f"{r['chars']} 字 · 表情 {r['emoji']} 个", r["text"], ""]
            print(f"  [{q[:8]}] 样本{j+1}: {r['wall_s']}s {r['chars']}字 表情{r['emoji']}",
                  flush=True)

    n = len(rows)
    avg = lambda k: round(sum(r[k] for r in rows) / n, 1)
    lines += ["", "== 汇总 ==",
              f"  平均整轮 {avg('wall_s')} s · 平均 {avg('tok_s')} tok/s · "
              f"平均输出 {avg('out_tok')} tok / {avg('chars')} 字 · 平均表情 {avg('emoji')} 个",
              f"  表情符号总数 {sum(r['emoji'] for r in rows)} 个 / {n} 条"]
    print("\n".join(lines[-2:]))

    text = "\n".join(lines)
    if OUT.exists():                      # 两次跑追加到同一份文件，方便并排看
        text = read_text_raw(OUT) + "\n\n" + text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_text(OUT, text)
    print(f"\n[OK] 原文已写入 {OUT}")
    print("     并排读：全量对比结论见 交付包\\给AI看的\\参考-模型对比实测.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
