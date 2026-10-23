# 2026-10-22 注意：本脚本面向 Ollama（已弃用，用户只留 llama.cpp）。保留作排错参考；跑之前先起 Ollama。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 AstrBot Desktop 配成本地模型 + 助手人格 + 免密钥联网搜索。

做五件事：
    1. 把 MODELS 表里的模型都建成并列提供商实例（**用哪个见下面"模型怎么选"**）
    2. 把对话模型绑到选中的那个实例
    3. 把 personas\\ 里**全部**人格都写进 AstrBot（界面「人格」页能看到、能切），
       并把当前选中的那份绑成默认
    4. 关掉内置内容安全过滤（AstrBot 默认开着关键词过滤）
    5. 打开联网搜索，用 AnySearch 的匿名模式（免 API 密钥）

[!] 运行前必须先完全退出 AstrBot，否则改动会被它在退出时覆盖。
   用 `切换人格.bat` 双击切换的话，它会自动帮你关和重开。

⭐ **模型怎么选（2026-10-03 校准，别再按旧说法理解）**：
    - `--model 9b|35b` → **明确换**成那个模型
    - **不带 `--model`** → **沿用配置里当前绑定的模型**（`cmd_config.json` 里
      `agent_runner.config.model.provider_id` 是什么就用什么），**不会重置成 9B**
    - `DEFAULT_MODEL`（9B）**只在"配置里还没有模型 / 绑的 provider 不在 MODELS 表里"时兜底**
    ⚠️ 旧版本这里写的是"不加 `--model` 就用默认 9B"，真踩过：用户在 WebUI 切到 35B，
      我们为了导入人格跑了一次本脚本，模型被**静默改回 9B**（用户看到的是"切不了模型"）。

用法：
    python astrbot_setup.py                  # 导入全部人格 + 应用当前选中的那份（模型=沿用配置里的）
    python astrbot_setup.py --list           # 列出所有可选人格
    python astrbot_setup.py --persona 外向-助手        # 换人格并应用
    python astrbot_setup.py --pick           # 交互式菜单选人格
    python astrbot_setup.py --models         # 列出可选模型（只读）
    python astrbot_setup.py --model 35b      # 换对话模型（人格保持不变）
    python astrbot_setup.py --check          # 只看现状，不改

⚠️ **模型和人格是两件独立的事**：
   `--model` 换"用哪个大脑"，`--persona` / `--pick` 换"用哪份人设"。两者可以任意组合，
   互不影响。

⭐ **模型也可以在 AstrBot 界面里切**：本脚本会把 MODELS 里的**每一个**都建成
   并列的提供商实例（`cfg["provider"]` 列表），所以导入一次之后，
   在 WebUI 的模型下拉里就能直接切换，**不需要再跑脚本**。
   （界面和脚本改的是同一份 `cmd_config.json`，不会像人格那样两边打架。）
   ⚠️ 但反过来：**你在界面里手动新建的 provider，下次跑本脚本会被清掉** ——
   想长期保留就把它加进本文件的 MODELS 表。
"""

import json
import shutil
import sqlite3
import sys

from console_utf8 import console_utf8
from safe_write import write_bytes, write_text

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\LocalAI-Assistant\AstrBotData")
CFG = ROOT / "data" / "cmd_config.json"
DB = ROOT / "data" / "data_v4.db"
PERSONAS = Path(r"C:\LocalAI-Assistant\personas")
ACTIVE = PERSONAS / ".active"          # 一行文本，记录当前选的是哪份人格

# ---------------------------------------------------------------- 模型表
# 原来这里是写死的两行（MODEL_ID / MODEL_NAME），**只能跑一个模型** ——
# 换模型得手改代码。2026-09-29 改成一个表 + `--model` 开关。
#
# ⚠️ 关键（2026-09-29 改过一次，别照旧注释理解）：
#    **不加 `--model` 时，沿用【配置里当前那个模型】**，不再硬套 DEFAULT_MODEL。
#    为什么改：用户在 WebUI 里切到 35B，我们为了让人格生效跑 `--persona X`，
#    结果模型被改回 9B **且没有任何提示** —— 用户看到的是"对话那边切换不了模型，还是 9B"。
#    `DEFAULT_MODEL` 现在只在"配置里还没有模型 / 绑的 provider 不在表里"时兜底。
#    明确要换模型就写 `--model 9b` / `--model 35b`（不受影响）。
#
# 每个条目 = (提供商实例 id, Ollama 模型名, 说明, 上下文 num_ctx, 回复预留 num_predict)
#   ⚠️ 后两个数**必须和各模型的 Modelfile 对得上**：
#      9B  Modelfile.assistant-9b : num_predict 768  · num_ctx **65536**
#      35B Modelfile.assistant-35b: num_predict 1024 · num_ctx **65536**
#      （都按 `/api/show` 实测核对，别照抄注释猜。）
#      预留写小了会在"长回复"时被 Ollama 从中间截断（回复半句没了）；
#      写大了则是白白浪费输入窗口。**改 Modelfile 就要同步改这里。**
#
#   ⚠️ **两个都提到 65536**（2026-10-05，用户要求；他退出 DeepSeek 腾了内存）。
#      改动前先实测过（临时变体，测完就删，数字来自 `ollama ps`）：
#        9B  32K → 5.9 GB / **100% GPU**；64K → 7.5 GB / **18% CPU**（+1.6 GB）
#        35B 40K → 50/50；64K → **52% CPU / 48% GPU**，12 GB（+约 1.5 GB 内存）
#        显存峰值：64K 时已用 7269 / 8151 MiB（**只剩 ~620 MiB**）
#      → 溢出部分 **Ollama 会自动挪给 CPU，不会 OOM**，只是速度略降。
#      ⚠️ 前提是**内存有余量**（当天可用 6.5 GB）。内存吃紧就把它降回 32768/40960。
MODELS: dict[str, tuple[str, str, str, int, int]] = {
    "9b": ("ollama_local-assistant-9b", "local-assistant-9b:latest",
           "老模型 Qwen3.5-9B-Uncensored · 快（实测 33.5 tok/s，350 字约 10 秒）",
           65536, 768),
    "35b": ("ollama_local-assistant-35b", "local-assistant-35b:latest",
            "新模型 Qwen3.6-35B-A3B（MoE，每字激活 3B）· 更聪明、无审查 · "
            "代价是冷启动读提示慢（约 20~40 秒）",
            65536, 1024),
}
DEFAULT_MODEL = "9b"

# 当前生效的模型（main() 里可能被 --model 覆盖，或沿用配置里已有的）
MODEL_ID, MODEL_NAME, _, MODEL_NUM_CTX, MODEL_REPLY_RESERVE = MODELS[DEFAULT_MODEL]
SOURCE_ID = "ollama"                   # provider_sources 里的源 id
DEFAULT_PERSONA = "外向-助手"
# ⚠️ 这个常量改过一次（2026-09-26）：原来是 "病娇-助手-露骨"，
#    而它同时出现在"永远保护"名单里（`protected = set(names) | {DEFAULT_PERSONA} | ...`）——
#    所以病娇 6 份被删后，`病娇-助手-露骨` 那条**库里记录永远清不掉**（实测：报了
#    `[!] STALE_IDS 里的 '病娇-助手-露骨' 是现存人格，已跳过`，但磁盘上其实已经没这文件了）。
#    **换了 DEFAULT_PERSONA 之后要记得：它必须是一个真实存在的磁盘文件。**
# 工具循环最大步数。AstrBot 默认 30 —— 对 9B 来说太多，
# 实测它会一直搜/读不收敛。8 步足够"搜一次读两页再回答"。
MAX_AGENT_STEPS = 8
LEGACY_IDS = ("local-assistant",)              # 早期版本用过的固定 persona_id，导入时清掉
# 已经从 personas\ 里删掉、但数据库里还留着旧记录的人格。
# ⚠️ 只往里加【确实删掉的】，别加现存人格 —— 加了就是把人删掉。
STALE_IDS = ("病娇-助手", "病娇-助手-狂化", "病娇-助手-全部",
    "病娇-助手-异物",
    "病娇-助手-玩",
    "病娇-助手-露骨",
    "病娇-助手-男-异物",
    "病娇-助手-男-玩",
    "病娇-助手-男-露骨",
    "测试",
)

# 哪些人格**不挂任何工具**（DB 里 tools 存 []）。
#
# 依据 AstrBot 的判定（core/astr_main_agent.py:602）：
#     tools = NULL  → 挂**全部**工具
#     tools = []    → **一个都不挂**
#
# 为什么加这个：用户 2026-09-23 说"查资料我用不上，查资料就留外向助手"。
# 实测过：只把人格里【关于查资料】那一节删掉**并不管用** ——
# 工具定义还挂在人格上，问"今天天气"照样会调 web_search（5 个问题里 2 次）。
# 要真的关掉，必须在这一层关。
#
# ⚠️ 用**前缀**而不是一个一个列名字 —— 人格会按玩法拆成好几份
#    （病娇-助手-露骨 / -异物 / -玩），列名字必然漏掉新的。
#
# ⚠️ 2026-09-26：病娇 6 份删掉之后，原来那个前缀**已经匹配不到任何现存人格**了 ——
#    于是 7 份人格全部挂**全部工具**（`tools = None`）。
#    这是"前缀失效"而不是"故意配置"。
#
# ⭐ 2026-09-29 用户决定：**"改造版"（角色扮演用）不挂工具，其余不管**
#       `旧版示例` → `示例角色A`、`示例角色C` → `示例角色C`
#       `男版` / `男版精简版` / `示例角色E` → 移到 `不要看\`（不再导入）
#    名单必须跟着改：**名单里留着已经没有的名字，等于这几份人格偷偷挂上了全部工具**
#    （2026-09-26 就出过一次：前缀失效 → 7 份全挂工具）。反过来，新名字漏进名单
#    也会让角色扮演人格重新具备搜索能力。
NO_TOOLS_NAMES = (
    "示例角色B",         # 改造版·男
    "示例角色A",         # 改造版·女（原 `旧版示例`）
    "示例角色C",         # 改造版·女·示例角色C（原 `示例角色C`）
)

# ---------------------------------------------------------------- 上下文窗口
#
# ⚠️ 这两个值必须匹配 Ollama 里模型的真实 `num_ctx`（当前 32768），
#    否则会出现"答上一句 / 重复 / 答非所问"（2026-09-23 查出来的真 bug）。
#
# 原理（AstrBot 的 core/agent/context/manager.py:59-76 有两条路）：
#
#     1. 按轮截断：if enforce_max_turns != -1: truncate_by_turns(...)
#     2. 按 token 压缩：if max_context_tokens > 0 and should_compress(...)
#
#    `max_context_tokens` 怎么来的（core/astr_main_agent.py:1700-1710）：
#        模型不在 AstrBot 的内置元数据里 → 用 config.fallback_max_tokens
#        而它的**默认值是 128000**
#
#    我们这个 `local-assistant-9b:latest` 是自建模型，**不在元数据里**，
#    于是 AstrBot 以为窗口有 128000 —— 永远不压缩；
#    而 Ollama 到 32768 就**静默丢掉最前面的 token（从中间切断）**，
#    模型于是看到一段从半句开始的历史。
#
#    `max_turns = -1` 又把第 1 条路也关了，等于**两条路全关**。
#    所以这里两个都给上：按轮截断 + 按 token 压缩双保险。
# ⚠️ 输入窗口 = num_ctx − 该模型的回复预留（num_predict），**按模型算，不再写死一个数**
#    （2026-10-03 修：原来写死 `32000` 并注释"两份 Modelfile 都是 768"，
#      而 35B 早就改成 num_predict 1024 了 —— 于是 35B 实际被少留了 256 token，
#      长回复贴到上限时会被 Ollama 从中间截断。现在从 MODELS 表里取。
CONTEXT_SAFETY = 256        # 再留一点余量给"模板 / 时间注入 / 工具说明"这类每轮附加物
CONTEXT_TOKENS = MODEL_NUM_CTX - MODEL_REPLY_RESERVE - CONTEXT_SAFETY
# 现值：9B → 32,768−768−256 = **31,744**；35B → 32,768−1024−256 = **31,488**
# 保留最近多少轮。
# ⚠️ 这个值改过三次，每次都是拿一种毛病换另一种，别凭感觉再动：
#    40 → 20（2026-09-23）：用户反馈"越到后面重复的东西越多"。
#        9B 在长上下文里会越来越倾向"照抄自己前面写过的"。压到 20 轮
#        总量约 15K（46%），确实更稳。
#    20 → 40（2026-09-24）：**代价浮出来了** —— 用户反馈"无法衔接上下剧情"。
#        实测那场对话 token_usage=16559 还在涨，每轮 +350~400，
#        正撞在 20 轮这条线上：`truncate_by_turns` 从最老的整轮丢，
#        前面整段场景直接消失 → 模型看不到就接不上。
#        **丢剧情比重复更致命**，所以退到中间值 40。
#    ⚠️ 40 轮 + 人格 8.9K ≈ 24K（73% 窗口），接近但没顶到 32000；
#       真顶到了还有 `fallback_max_tokens` 那条 token 压缩兜底。
#    ⚠️ 合成测试**测不出**这件事（两次结果互相矛盾，见 02 踩坑档案坑 28），
#       只能靠机制 + 用户实际体感，改动后必须问用户"还接得上吗 / 有没有变重复"。
#    40 → **30**（2026-09-24，第四次调）：40 那次的**上限**也撞到了。
#        实测用户 tg 那场涨到 **30470 / 32000**，出现两次异常：
#          · `time_to_first_token` 0.3s → **9.8s**（前缀被改 → KV 缓存全失效 → 重新 prefill）
#          · 用户体感"重复输出两句话/同一段"
#        机制：40 轮 + 人格 9K ≈ **超窗** → `truncate_by_turns` 丢掉最老的整轮
#        → 前缀变了 → 缓存失效 + 模型可能看到半截对话。
#        30 轮 ≈ 21K，**仍在窗口内**（留出余量），把"贴顶被砍"换成"提前留空"。
#        **质量不受影响**：真人聊天很少连着 30 轮不 `/reset`；
#        而且"记忆"靠人格里写死的 `【关于…】`，不靠上下文。
#        用户侧配合：**在聊天里发 `/reset`**（内置命令，已开启）即可手动清零，
#        历史不删、人格不变（`/reset` 与 `/new` 同一实现，见 builtin_commands）。
#    30 → **50**（2026-10-03，第五次调）：**为 35B 加长上下文配套**（用户选 C）。
#        35B 的 num_ctx 提到 40960、输入窗口 37,632 之后，30 轮这条线**先到**了 ——
#        实测会话只涨到 18.5K token（占 31.5K 的 59%）时轮数就已经接近上限，
#        等于"窗口没吃满就先把前面的场景丢了"。抬到 50 轮让 **token 上限**当闸门，
#        而不是轮数：token 上限是硬的（超了真会截断），轮数设宽一点没坏处。
#    50 → **70**（2026-10-05，第六次调）：**两个模型窗口都提到 65536** 之后，
#        50 轮（≈ 25K token）又成了先到的那条线。70 轮 ≈ **35K token**，
#        对两个模型都在窗口内（9B 64K、35B 64K），且仍留 20K 余量。
#        **原则：让 token 上限当闸门，轮数只是"别太频繁丢老剧情"的兜底。**
KEEP_TURNS = 70
# 溢出策略：truncate_by_turns（丢掉最老的几轮）还是 llm_compress（叫模型总结）。
# 选前者：llm_compress 会**用同一个 9B**去总结历史（32 tok/s，慢，而且总结质量差，
# 反而更容易答非所问）。丢几轮老对话更可预测。
# ⚠️ 但 `truncate_by_turns` 有个坑：它**按轮数丢，不看 token**（见上）。
#    所以 `KEEP_TURNS` 不能设太小 —— 设小了就是在剧情还远没吃满窗口时
#    就开始丢前面的场景。
OVERFLOW_STRATEGY = "truncate_by_turns"
# 2026-10-05：用户选了"要记忆压缩"，所以加了开关 `--compression llm_compress`。
#   · 选它 = 装不下时**叫模型把老对话总结成一段摘要**（不再整轮丢掉）。
#   · 代价：总结用的就是**同一条模型**（35B 一半在 CPU），而且是在**请求路径里**跑，
#     喂进去的是历史的大头（`keep_recent_ratio` 默认 0.15 ⇒ 约 85%）—— 触发那一次会明显卡。
#   · 所以这边把 `max_turns` 放到 300（等于"轮数几乎不设限"），让 **token 上限当闸门**，
#     符合本文件一贯的原则（见上面"第五次调"那段）。
#   · 退回丢轮模式：`python astrbot_setup.py --compression truncate`
KEEP_TURNS_LLM = 300


# ---------------------------------------------------------------- 人格选择

def all_personas() -> list[str]:
    return sorted(p.stem for p in PERSONAS.glob("*.txt"))


def get_active() -> str:
    if ACTIVE.exists():
        name = ACTIVE.read_text(encoding="utf-8").strip()
        if (PERSONAS / f"{name}.txt").exists():
            return name
    return DEFAULT_PERSONA


def set_active(name: str) -> None:
    # `newline="\n"` 写死：Windows 上默认会写成 CRLF，而本仓库文本一律 LF（见 .gitattributes）
    write_text(ACTIVE, name + "\n")


def list_personas() -> None:
    cur = get_active()
    print("可用人格：")
    for n in all_personas():
        mark = "  ← 当前" if n == cur else ""
        size = len((PERSONAS / f"{n}.txt").read_text(encoding="utf-8"))
        print(f"  {n:22} {size:5} 字符{mark}")
    print(f"\n换人格： python astrbot_setup.py --persona <名字>")
    print(f"或双击： 切换人格.bat")


def pick() -> str | None:
    """交互式菜单。返回选中的名字；直接回车 = 保持不变。"""
    names = all_personas()
    cur = get_active()
    print("=" * 50)
    print("  选择人格")
    print("=" * 50)
    for i, n in enumerate(names, 1):
        mark = "  ← 当前" if n == cur else ""
        print(f"  [{i}] {n}{mark}")
    print()
    try:
        raw = input(f"输入编号（1-{len(names)}），直接回车保持不变: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return None
    if not raw:
        print(f"保持不变：{cur}")
        return None
    if not raw.isdigit() or not (1 <= int(raw) <= len(names)):
        print(f"[X] 无效编号：{raw}")
        return None
    return names[int(raw) - 1]


# ---------------------------------------------------------------- 基础设施

def running() -> bool:
    import subprocess
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq AstrBot.exe"],
        capture_output=True, text=True, errors="replace").stdout
    return "AstrBot.exe" in out


def read_cfg():
    """AstrBot 写出来的 cmd_config.json 带 UTF-8 BOM，用 utf-8-sig 读。"""
    raw = CFG.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), raw.startswith(b"\xef\xbb\xbf")


def write_cfg(cfg, bom: bool):
    data = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    write_bytes(CFG, ("\ufeff" + data).encode("utf-8") if bom else data.encode("utf-8"))


def diff_personas() -> None:
    """把**磁盘上的人格**和**库里的人格**逐字比一遍。

    为什么需要（这一条踩过）：
        `--check` 原来只报字符数，看不出"改了人格但忘了重导" ——
        因为字符数变了你得自己拿眼睛比。更坑的是它**不会报错**，
        表现只是"我明明改了，它怎么还是老样子"。

    安全性（重要）：
        - **只读**：DB 用 mode=ro 打开，加 3 秒超时，绝不写
        - **不可能崩主流程**：整段包在 try/except 里，异常会打印一行提示并**上报"没查成"**
        - AstrBot 正在运行时也能跑（`--check` 本来就是这么用的）

    返回值（2026-09-29 加）：
        (是否可以判定, 没同步的份数)
        —— 原来这个函数**只打印、不返回**，于是 `--check` 无条件 `return 0`：
        检测到"改了人格没重导"也报成功，而 check_all 只认退出码、通过时还丢弃输出
        ⇒ **整条链路看不见人格漂移**（02 坑 40 那一族：异常/负面情况被吞掉）。
    """
    if not DB.exists():
        return False, 0
    try:
        disk = {p.stem: p.read_text(encoding="utf-8").rstrip()
                for p in sorted(PERSONAS.glob("*.txt"))}
        db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=3)
        try:
            rows = db.execute(
                "SELECT persona_id, system_prompt FROM personas").fetchall()
        finally:
            db.close()
        in_db = {pid: (sp or "").rstrip() for pid, sp in rows}
    except Exception as e:                       # noqa: BLE001 —— 兜住，但**要让调用方知道没查成**
        print(f"      [X] 内容比对**没查成**（{type(e).__name__}: {e}）"
              f" —— 这一项不算通过")
        return False, -1

    bad = []
    for name in sorted(set(disk) | set(in_db)):
        d, s = disk.get(name), in_db.get(name)
        if d is None:
            print(f"      [!] {name}：只在库里，磁盘上没有"
                  f" —— 删人格要删 personas\\{name}.txt，别只在界面里删")
            bad.append(name)
        elif s is None:
            print(f"      [X] {name}：只在磁盘上，库里没有 —— 需要重跑本脚本")
            bad.append(name)
        elif d != s:
            print(f"      [X] {name}：**内容不一致**  磁盘 {len(d)} / 库里 {len(s)} 字符"
                  f"（差 {len(d) - len(s)}）")
            print(f"          → 改了人格没重导。双击 切换人格.bat 或重跑本脚本")
            bad.append(name)

    if not bad:
        print(f"      内容逐字一致（{len(disk)} 份）")
    else:
        print(f"      ⚠️ {len(bad)} 份没同步 —— AstrBot 现在用的是库里那份")
    return True, len(bad)


def show(cfg):
    print("=== 当前状态 ===")
    print(f"  提供商源   : {[s.get('id') for s in cfg.get('provider_sources', [])]}")
    print(f"  提供商实例 : {[p.get('id') for p in cfg.get('provider', [])]}")
    ps = cfg.get("provider_settings", {})
    print(f"  联网搜索   : {ps.get('web_search')}  ({ps.get('websearch_provider')})")
    ar = cfg.get("agent_runner", {}).get("config", {})
    print(f"  对话模型   : {ar.get('model', {}).get('provider_id')!r}")
    print(f"  人格       : {ar.get('persona', {}).get('persona_id')!r}"
          f"  safety_mode={ar.get('persona', {}).get('safety_mode')}")
    cs = cfg.get("content_safety", {})
    print(f"  关键词过滤 : {cs.get('internal_keywords', {}).get('enable')}")
    comp = ar.get("compression", {})
    print(f"  上下文窗口 : 输入 {comp.get('fallback_max_tokens')} token / "
          f"保留 {comp.get('max_turns')} 轮 / {comp.get('overflow_strategy')}")
    print(f"  WebUI 监听 : {cfg.get('dashboard', {}).get('host')}:{cfg.get('dashboard', {}).get('port')}")

    # ---- 上下文一致性检查（2026-10-03 加）----
    # 判据：输入窗口 + 回复预留 + 余量 必须**恰好**等于该模型的 num_ctx。
    # 为什么要有：35B 的 num_predict 从 768 提到 1024 之后，这里还按 768 预留了
    # 一段时间 —— 少留 256 token，长回复贴上限时会被 Ollama 从中间截断，而且
    # **没有任何地方会报错**。现在 `--check` 会当场判红。
    ctx_bad = False
    cur_pid = ar.get("model", {}).get("provider_id")
    eff = next(((k, v) for k, v in MODELS.items() if v[0] == cur_pid), None)
    fb = comp.get("fallback_max_tokens")
    if eff is None:
        print(f"  [!] 上下文一致性: 绑定的提供商 {cur_pid!r} 不在 MODELS 表里，无法核对")
    elif not isinstance(fb, int):
        print(f"  [X] 上下文一致性: fallback_max_tokens={fb!r} 不是整数")
        ctx_bad = True
    else:
        key, (_mid, _mname, _note, num_ctx, reserve) = eff
        want = num_ctx - reserve - CONTEXT_SAFETY
        if fb == want:
            print(f"  [OK] 上下文一致性: {key}  num_ctx {num_ctx} − 预留 {reserve} "
                  f"− 余量 {CONTEXT_SAFETY} = 输入窗口 {fb}")
        else:
            print(f"  [X] 上下文一致性: 配置里输入窗口 {fb}，但按 {key} 的 Modelfile "
                  f"应该是 {want}（num_ctx {num_ctx} − num_predict {reserve} − 余量 {CONTEXT_SAFETY}）")
            print(f"      → 重跑不带 --check 的本脚本可修正；改过 Modelfile 就先改 MODELS 表")
            ctx_bad = True

    name = get_active()
    print(f"  选中的人格 : {name}  ({PERSONAS / (name + '.txt')})")

    if DB.exists():
        db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        rows = db.execute(
            "SELECT persona_id, length(system_prompt), tools FROM personas "
            "ORDER BY persona_id").fetchall()
        print(f"  AstrBot 已导入 {len(rows)} 个人格 :")
        for pid, n, tl in rows:
            mark = "  <== 当前默认" if pid == name else ""
            # tools 列：NULL = 挂全部工具；"[]" = 一个都不挂
            tmark = "[全部工具]" if tl is None else "[无工具]"
            print(f"      - {pid:22} {n:5} 字符 {tmark}{mark}")
        if not rows:
            print("      （空）")
        db.close()
        # 逐字比对磁盘 vs 库（只读）。2026-09-29：把结果传出去，
        # 好让 `--check` 能**用退出码**报告漂移（否则 check_all 只会看到 0=通过）。
        ok_diff, n_bad = diff_personas()
        return 0 if (ok_diff and n_bad == 0 and not ctx_bad) else 1
    return 1 if ctx_bad else 0


# ---------------------------------------------------------------- 主流程

def list_models() -> None:
    """列出可选的对话模型（只读）。

    ⚠️ 解包字段数必须和 MODELS 表一致（现在每项 5 个：id/模型名/说明/num_ctx/回复预留）。
    2026-10-03 这里还按 3 个解包过 → `python astrbot_setup.py --models` 直接
    `ValueError: too many values to unpack` 崩掉。**改 MODELS 的字段数时要顺手改这里。**
    """
    print("可用模型：")
    for key, (mid, mname, note, num_ctx, reserve) in MODELS.items():
        mark = "  ← 默认（仅在没有 --model、且配置里也没绑模型时使用）" \
            if key == DEFAULT_MODEL else ""
        print(f"  {key:<6} {mname:<28}{mark}")
        print(f"         {note}")
        print(f"         提供商实例 id: {mid}")
        print(f"         num_ctx {num_ctx} · 回复预留 num_predict {reserve} "
              f"→ 输入窗口 {num_ctx - reserve - CONTEXT_SAFETY}")
    print("\n换模型： python astrbot_setup.py --model <名字>")
    print("       ⚠️ 不带 --model 跑本脚本时，**沿用配置里当前绑定的模型**，")
    print("          不会重置成上面那个『默认』。")
    print("       （换模型**不影响**人格；人格照旧用 --persona / --pick 切）")


def _retired_guard() -> None:
    # 只读模式（--check / --help / --show）**放行**：check_all 的「AstrBot 配置」项靠它体检，
    # 拦了会让验收变红（2026-10-22 实测）。只有真要写配置时才拦 ✓
    if any(a in ('--check', '-h', '--help', '--show') for a in sys.argv[1:]):
        return
    # 2026-10-22 停用保护：本脚本会写 **Ollama 提供商**（11434 + 旧模型名），但 Ollama 已弃用、
    # 连 11434 都不在了 ⇒ 直接跑会把 AstrBot 指向一个不存在的服务。
    # 必须显式 --i-know-ollama-is-gone 才放行；正确做法是改 AstrBot 的 OpenAI 兼容提供商。
    _RETIRED = '--i-know-ollama-is-gone'
    if _RETIRED not in sys.argv:
        print('[停用] astrbot_setup.py 面向已弃用的 Ollama。现在的做法是：')
        print('  AstrBot 服务提供商改成 OpenAI 兼容 → http://127.0.0.1:11435/v1，模型名 lc-35b。')
        print(f'  确实要按老办法写 Ollama 配置，请加参数 {_RETIRED}。')
        raise SystemExit(2)


def main() -> int:
    _retired_guard()          # 2026-10-22：Ollama 已弃用，见函数里的说明
    global MODEL_ID, MODEL_NAME, MODEL_NUM_CTX, MODEL_REPLY_RESERVE, CONTEXT_TOKENS
    args = sys.argv[1:]

    if "--list" in args:
        list_personas()
        return 0

    if "--models" in args:
        list_models()
        return 0

    # ---- 溢出策略：截断还是摘要压缩（2026-10-05 加，用户选的摘要）----
    # `--compression llm_compress`：装了历史就用**模型总结**代替"丢掉最老的轮"。
    # 代价必须先说清楚（回复里也说了）：总结是**同一条模型**在**请求路径里**跑，
    # 喂进去的是历史的大头（keep_recent_ratio=0.15 ⇒ 约 85%），在这台机器上（35B 一半在 CPU）
    # 触发那一次会**明显卡住**。所以 max_turns 放得很宽（300），让 token 上限当闸门。
    compression = "truncate"
    if "--compression" in args:
        i = args.index("--compression") + 1
        if i >= len(args) or args[i] not in ("truncate", "llm_compress"):
            print("[X] --compression 只接 truncate 或 llm_compress")
            return 1
        compression = args[i]

    # ---- 决定用哪个模型 ----
    # ⚠️ 2026-09-29 改：**不带 --model 时不再硬套 DEFAULT_MODEL，而是沿用配置里现在那个**。
    #    为什么（真踩过）：用户在 WebUI 里把模型切到 35B，然后我们为了让人格生效跑了
    #    `astrbot_setup.py --persona X` —— 它把模型**改回了 9B**，而且**没有任何提示**。
    #    表现就是用户说的"对话那边切换不了模型，还是 9B"。
    #    `--model <名字>` 依然优先，想明确换就用它。
    cur_key = None
    if CFG.exists():
        try:
            _cfg0 = json.loads(CFG.read_bytes().decode("utf-8-sig"))
            cur_id = (_cfg0.get("agent_runner", {}).get("config", {})
                      .get("model", {}).get("provider_id"))
            cur_key = next((k for k, v in MODELS.items() if v[0] == cur_id), None)
            if cur_id and cur_key is None:
                print(f"[!] 配置里绑的提供商 {cur_id!r} 不在 MODELS 表里，"
                      f"本次按默认 {DEFAULT_MODEL} 处理")
        except Exception as e:
            print(f"[!] 读现有模型失败（{e}），本次按默认 {DEFAULT_MODEL} 处理")

    if "--model" in args:
        i = args.index("--model") + 1
        if i >= len(args):
            print("[X] --model 后面要跟模型名，用 --models 看有哪些")
            return 1
        key = args[i]
        if key not in MODELS:
            print(f"[X] 没有这个模型：{key}")
            list_models()
            return 1
        MODEL_ID, MODEL_NAME, _, MODEL_NUM_CTX, MODEL_REPLY_RESERVE = MODELS[key]
        print(f"[OK] 已选模型 → {key}（{MODEL_NAME}）")
    elif cur_key:
        MODEL_ID, MODEL_NAME, _, MODEL_NUM_CTX, MODEL_REPLY_RESERVE = MODELS[cur_key]
        print(f"[OK] 沿用当前模型 → {cur_key}（{MODEL_NAME}）"
              f"（想换：--model { '35b' if cur_key == '9b' else '9b' }）")
    else:
        print(f"[OK] 用默认模型 → {DEFAULT_MODEL}（配置里还没有模型）")

    # 输入窗口按**当前这个模型**算（回复预留跟着模型走，见 MODELS 表）
    CONTEXT_TOKENS = MODEL_NUM_CTX - MODEL_REPLY_RESERVE - CONTEXT_SAFETY

    if not CFG.exists():
        print(f"[X] 找不到 {CFG}\n   AstrBot 至少要先启动过一次。")
        return 1
    cfg, bom = read_cfg()

    if "--check" in args:
        # ⚠️ 2026-09-29 改：原来是 `show(cfg); return 0` —— **无条件成功**。
        #    于是"改了人格没重导 / 新加的人格从没导入"在 check_all 里显示 [OK]
        #    （check_all 只认退出码，且通过时丢弃子脚本输出）。现在漂移/查不成 → 退出码 1。
        return show(cfg)

    # ---- 决定用哪份人格 ----
    chosen = None
    if "--persona" in args:
        i = args.index("--persona") + 1
        if i >= len(args):
            print("[X] --persona 后面要跟人格名字，用 --list 看有哪些")
            return 1
        chosen = args[i]
        if not (PERSONAS / f"{chosen}.txt").exists():
            print(f"[X] 没有这个人格：{chosen}")
            list_personas()
            return 1
    elif "--pick" in args:
        chosen = pick()
        if chosen is None:
            # 没换，就按当前那份重新应用一次
            pass

    if chosen:
        if running():
            print("[X] AstrBot 正在运行，改人格前请先退出（或双击 切换人格.bat，它会自动处理）。")
            return 1
        set_active(chosen)
        print(f"[OK] 已选择人格 → {chosen}")
    else:
        chosen = get_active()
        print(f"使用当前人格 → {chosen}")

    persona_file = PERSONAS / f"{chosen}.txt"
    if not persona_file.exists():
        print(f"[X] 找不到人格文件 {persona_file}")
        return 1

    if running():
        print("[X] AstrBot 正在运行。请先完全退出（含托盘图标），再跑这个脚本。")
        return 1

    # ---------- 备份 ----------
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for p in (CFG, DB):
        if p.exists():
            bak = p.with_name(f"{p.name}.bak-{stamp}")
            shutil.copy2(p, bak)
            print(f"[OK] 已备份 → {bak.name}")

    # ---------- 1. 提供商实例（全部建成并列，便于在 WebUI 里直接切）----------
    src = next((s for s in cfg.get("provider_sources", []) if s.get("id") == SOURCE_ID), None)
    if src is None:
        print(f"[X] provider_sources 里找不到 id={SOURCE_ID}，先在 WebUI 里建一次 Ollama 源")
        return 1
    src["api_base"] = "http://127.0.0.1:11434/v1"
    src["enable"] = True
    src["ollama_disable_thinking"] = True   # 我们的 GGUF 已硬关思考，这里再兜一层

    # ⚠️ 这一行会**替换整个 provider 列表** —— 也就是说，**在 WebUI 里手动新建的
    #    provider 下次跑本脚本会被清掉**（只留下面这几个）。原因见文件头"模型表"。
    # ⚠️ 但**模型选择本身是安全的**：界面和本脚本改的都是 cfg["provider"] /
    #    agent_runner.config.model["provider_id"]（同一个 cmd_config.json），
    #    不像人格那样"界面写库、脚本写盘"两边打架。
    cfg["provider"] = [
        {
            "id": mid,
            "provider_source_id": SOURCE_ID,
            "model": mname,
            "modalities": [],
            "custom_extra_body": {},
            "enable": True,
        }
        for mid, mname, _note, _ctx, _res in MODELS.values()
    ]
    ids = [p["id"] for p in cfg["provider"]]
    print(f"\n[OK] 提供商实例 → {len(ids)} 个（可在 WebUI 里直接切换）：")
    for mid, mname, note, _ctx, _res in MODELS.values():
        mark = "  ← 本次选中" if mid == MODEL_ID else ""
        print(f"     {mname:<30}{mark}")
    if MODEL_ID not in ids:
        print(f"[X] 内部错误：选中的 {MODEL_ID} 不在 provider 列表里")
        return 1

    # ---------- 2. 绑模型 + 人格 ----------
    # persona_id 直接用文件名，这样 AstrBot 界面「人格」页里一眼能认出是哪个
    ar = cfg.setdefault("agent_runner", {}).setdefault("config", {})
    ar.setdefault("model", {})["provider_id"] = MODEL_ID
    ar.setdefault("persona", {})["persona_id"] = chosen
    ar["persona"]["safety_mode"] = False          # AstrBot 默认会给人格套一层安全提示
    comp = ar.setdefault("compression", {})
    if compression == "llm_compress":
        comp["max_turns"] = KEEP_TURNS_LLM              # 放宽轮数：让 token 上限当闸门
        comp["overflow_strategy"] = "llm_compress"      # ← 装了历史就叫模型总结
        comp["fallback_max_tokens"] = CONTEXT_TOKENS    # ← 输入窗口 = num_ctx − 回复预留 − 余量
        print(f"[OK] 上下文窗口 → 输入 {CONTEXT_TOKENS} token / 轮数上限 {KEEP_TURNS_LLM} 轮"
              f"（溢出策略 **llm_compress = 叫模型总结历史**）")
        print("     ⚠️ 触发时那一次会明显变慢（同一条模型要在请求路径里读完历史再总结）；"
              "想退回丢轮：`--compression truncate`")
    else:
        comp["max_turns"] = KEEP_TURNS                  # ← 见文件头"上下文窗口"那段
        comp["fallback_max_tokens"] = CONTEXT_TOKENS    # ← 输入窗口 = num_ctx − 本模型回复预留 − 余量
        comp["overflow_strategy"] = OVERFLOW_STRATEGY
        print(f"[OK] 上下文窗口 → 输入 {CONTEXT_TOKENS} token / 保留最近 {KEEP_TURNS} 轮"
              f"（溢出策略 {OVERFLOW_STRATEGY}）")
    print(f"     ⚠️ 该模型的 num_ctx={MODEL_NUM_CTX}、回复预留 num_predict={MODEL_REPLY_RESERVE}，"
          f"再加 {CONTEXT_SAFETY} 余量 = 输入窗口 {CONTEXT_TOKENS}")
    print(f"        改任何一个 Modelfile 的 num_predict / num_ctx，都要同步改本脚本的 MODELS 表")
    ar.setdefault("misc", {})["max_steps"] = MAX_AGENT_STEPS
    ps0 = cfg.setdefault("provider_settings", {})
    ps0["max_agent_step"] = MAX_AGENT_STEPS
    print(f"[OK] 对话模型 → {MODEL_ID}")
    print(f"[OK] 默认人格 → {chosen}，safety_mode 已关闭")
    print(f"[OK] 工具循环上限 → {MAX_AGENT_STEPS} 步（原默认 30，9B 会不收敛）")

    # ---------- 3. 关内容安全 ----------
    cs = cfg.setdefault("content_safety", {})
    cs["also_use_in_response"] = False
    cs.setdefault("internal_keywords", {})["enable"] = False
    cs.setdefault("baidu_aip", {})["enable"] = False
    print("[OK] 内置关键词过滤 + 百度内容审核 已关闭")

    # ---------- 4. 联网搜索（AnySearch 匿名，免密钥）----------
    ps = cfg.setdefault("provider_settings", {})
    ps["web_search"] = True
    ps["websearch_provider"] = "anysearch"   # 唯一支持匿名免密钥的
    ps["web_search_link"] = False
    ps["display_reasoning_text"] = False
    ps["streaming_response"] = True          # 本地小模型，流式体感快很多
    print("[OK] 联网搜索 → anysearch（匿名模式，每日免费额度，不需要 API Key）")

    # ---------- 5. WebUI 只监听本机 ----------
    dash = cfg.setdefault("dashboard", {})
    dash["host"] = "127.0.0.1"
    print(f"[OK] WebUI 监听 → 127.0.0.1:{dash.get('port', 6185)}（局域网不可达）")

    write_cfg(cfg, bom)
    print(f"\n[OK] 配置已写入 {CFG.name}（{'保留 BOM' if bom else '无 BOM'}）")

    # ---------- 6. 把 personas\ 里全部人格都导入 ----------
    names = all_personas()
    if not names:
        print(f"[X] {PERSONAS} 里一个 .txt 都没有")
        return 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    db = sqlite3.connect(str(DB))
    c = db.cursor()
    for old in LEGACY_IDS:                      # 清掉早期版本的固定 id
        c.execute("DELETE FROM personas WHERE persona_id = ?", (old,))
    for n in names:
        text = (PERSONAS / f"{n}.txt").read_text(encoding="utf-8").rstrip()
        c.execute("DELETE FROM personas WHERE persona_id = ?", (n,))
        # tools = [] → 一个工具都不挂；NULL → 挂全部（见 NO_TOOLS_NAMES 的说明）
        tools = "[]" if n in NO_TOOLS_NAMES else None
        c.execute(
            'INSERT INTO personas (created_at, updated_at, persona_id, system_prompt, '
            'begin_dialogs, tools, skills, custom_error_message, folder_id, sort_order) '
            # skills 必须是 []（空列表 = 不用任何技能）。
            # 留 NULL 表示"启用全部技能"，AstrBot 会把技能描述（含本地文件路径）
            # 一起塞进系统提示，小模型会把这些路径当正文念出来。
            'VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, NULL, 0)',
            (now, now, n, text, tools, "[]"),
        )

    # 清掉 personas\ 里已经删掉、但库里还留着的旧人格记录。
    # 用白名单 STALE_IDS，绝不用"库里有、磁盘上没有"来推断 ——
    # 那种写法会在 personas 目录读不全的时候把好人格一起删了。
    # 永远保护的 id：现存三套 + DEFAULT_PERSONA + LEGACY_IDS。
    protected = set(names) | {DEFAULT_PERSONA} | set(LEGACY_IDS)
    stale_targets = [pid for pid in STALE_IDS if pid not in protected]
    removed = []
    for pid in stale_targets:
        hit = c.execute("SELECT COUNT(*) FROM personas WHERE persona_id = ?", (pid,)).fetchone()[0]
        if hit:
            c.execute("DELETE FROM personas WHERE persona_id = ?", (pid,))
            removed.append((pid, hit))
    db.commit()

    if removed:
        print(f"\n[OK] 已清理库里的旧人格记录：")
        for pid, hit in removed:
            print(f"       - {pid}（{hit} 行）")
    for pid in STALE_IDS:
        if pid in protected:
            print(f"[!] STALE_IDS 里的 {pid!r} 是现存人格，已跳过（请修正脚本常量）")

    rows = c.execute("SELECT persona_id, length(system_prompt) FROM personas "
                     "ORDER BY persona_id").fetchall()
    for pid in stale_targets:
        if pid in [r[0] for r in rows]:
            print(f"[!] {pid!r} 清理后仍在库里，请手动查")
    db.close()

    # ⚠️ 这里打印的是**库里现有的全部行数**，不是"本次导入了几份" ——
    #    2026-10-03 差点被自己误导：personas\ 只剩 4 份，这里却印"已导入 9 个人格"
    #    （因为库里还留着没清理的旧人格）。措辞写清楚，免得下次又误判。
    print(f"\n[OK] 现在库里共有 {len(rows)} 个人格（含本次导入的 {len(names)} 份，"
          f"其余是库里原有的）：")
    for pid, n in rows:
        mark = "  <== 当前默认" if pid == chosen else ""
        print(f"       - {pid:22} {n:5} 字符{mark}")
    print("\n     界面「人格」页里能看到这些，也可以直接在那儿切。")

    print("\n=== 回读校验 ===")
    show(read_cfg()[0])
    print("\n[!] 重开 AstrBot 才生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
