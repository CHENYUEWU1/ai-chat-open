#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
抓几条**真实回复**存成 UTF-8 文件，供人逐条读。

为什么需要它（两个理由，都不是"顺手加的"）：
    1. **"像不像人"测不出来。** 关键词命中率能量"有没有写动作"，
       但量不出"这句读起来像不像一个真人在反应"。这一步**必须人读原文**。
       所以要有个东西**把原文完整摆出来**，而不是打印在控制台里。
    2. **中文 Windows 控制台是 GBK**（坑 18）。长段中文正文打在控制台里
       既难读、滚上去就没了。写进文件可以用记事本慢慢看、并排对比改前改后。

默认那几条提示词是**故意挑的"情绪该出来"的场景**（不是动作场景）：
    主观问题、冷淡的一句话、提到别人。这三类最容易暴露
    "贴情绪标签""答非所问""编细节"这些毛病。
    用 `--opening` 则改为固定一句、只换 seed，那是量"开场重复"用的（另见
    `test_persona_opening.py`）。

用法：
    python test_persona_samples.py                 # 当前启用的人格，默认 5 条
    python test_persona_samples.py -n 3            # 3 条
    python test_persona_samples.py -P 病娇-助手-露骨
    python test_persona_samples.py -p "再冷淡一点说" -p "你为什么不理我"
    python test_persona_samples.py --out 改前.txt
    python test_persona_samples.py --opening -n 5   # 固定一句只换 seed

⚠️ 会加载模型、占显存。一条 10–30 秒。只想看项目状态请跑 `check_all.py`。
   卡住不动：`python fix_ollama.py`。
"""
import sys
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

from ollama_guard import chat, ensure_alive   # noqa: E402

PERSONAS = Path(r"C:\LocalAI-Assistant\personas")
ACTIVE = PERSONAS / ".active"
MODEL = "local-assistant-9b:latest"

# 故意挑"情绪该出来"的场景：主观问题 / 冷淡的一句话 / 提到别人 / 极短 / 关于关系
DEFAULT_PROMPTS = [
    "你觉得我这个人怎么样？",
    "我今天不太想说话。",
    "我刚才跟一个朋友聊了挺久。",
    "在干嘛",
    "你喜欢我哪一点？",
]
OPENING_PROMPT = "在干嘛"


def main() -> int:
    args = sys.argv[1:]

    def opt(flag, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    n = int(opt("-n", len(DEFAULT_PROMPTS)))
    out_path = Path(opt("--out", r"C:\LocalAI-Assistant\persona_samples.txt"))
    n_predict = int(opt("--n-predict", 400))
    name = opt("-P")
    if name is None:
        try:
            name = ACTIVE.read_text(encoding="utf-8").strip()
        except Exception:                              # noqa: BLE001
            name = ""

    extra = [args[i + 1] for i, a in enumerate(args) if a == "-p" and i + 1 < len(args)]
    if "--opening" in args:
        prompts = [OPENING_PROMPT] * n
        seeds = list(range(1, n + 1))
    else:
        prompts = (extra + DEFAULT_PROMPTS)[:n]
        seeds = [7] * len(prompts)

    if not name:
        print("[X] 读不到 personas\\.active；用 -P <人格名> 指定")
        return 1
    path = PERSONAS / f"{name}.txt"
    if not path.exists():
        print(f"[X] 没有这份人格：{name}")
        return 1

    persona = path.read_text(encoding="utf-8")
    ensure_alive()
    print(f"人格：{name}（{len(persona)} 字符）")
    print(f"要抓 {len(prompts)} 条，写到 {out_path}")

    chunks = [
        f"人格：{name}（{len(persona)} 字符）",
        f"模型：{MODEL}   num_predict={n_predict}   seed={seeds}",
        "",
        "读这份的时候看四件事：",
        "  ① 有没有**编细节**（他没说过的事）",
        "  ② 主观问题有没有**真的答**（带一件具体的事，不是只给形容词）",
        "  ③ 有没有**给情绪报名字**（酸/委屈/得意 + 感叹号）",
        "  ④ 动作是不是又是那四件套（指尖 / 另一只手 / 眼神 / 鼻尖）",
    ]
    for i, (q, sd) in enumerate(zip(prompts, seeds), 1):
        out = chat(MODEL, [
            {"role": "system", "content": persona},
            {"role": "user", "content": q},
        ], options={"num_predict": n_predict, "seed": sd},
            timeout=120, label=f"样本{i} ")
        chunks.append(
            f"\n{'=' * 72}\n【{i}】用户：{q}   (seed={sd})\n{'-' * 72}\n{out}\n")
        print(f"  样本 {i} 完成（{len(out)} 字）")

    out_path.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    print(f"\n[OK] 已写入 {out_path}")
    print("     用记事本打开读 —— 控制台读不了这么长的中文（坑 18）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
