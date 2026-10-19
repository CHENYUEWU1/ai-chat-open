#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重建「单文件版-全内容.md」—— 把交付包里的所有文档 + 人格 + Modelfile
合并成一个可以直接丢给 AI 的大文件。

为什么需要脚本：
    以前这个文件是手工拼的，改完 01~04 之后忘了同步，它就悄悄过期了。
    跑一次这个脚本，单文件版永远和分章节的版本一致。

用法：
    python build_single_file.py            # 重建「单文件版-全内容.md」（含人格正文）
    python build_single_file.py --eng      # 重建「单文件版-工程版.md」（不含人格正文，给 AI 接手用）
    python build_single_file.py <交付包目录>
"""
import re
import sys
from datetime import datetime
from pathlib import Path

from console_utf8 import console_utf8
from safe_write import write_text

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

_args = [a for a in sys.argv[1:] if not a.startswith("--")]


def find_project_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "启动AstrBot.bat").is_file():
            return parent
    return Path(__file__).resolve().parent


ROOT = find_project_root(Path(__file__).resolve().parent)
PKG = Path(_args[0]).resolve() if _args else ROOT / "交付包"

# 工程文档都在这个子文件夹里（由 organize_package.py 分栏）
AIDIR = "给AI看的"

# ⚠️ 派生物也要放进 `给AI看的\` —— 放包根的话，`organize_package.py --check`
#    会报"老旧位置还在"（实测被抓过一次）。**产物路径要和分栏约定一致。**
OUT = PKG / AIDIR / "单文件版-全内容.md"

# 当前启用的人格记在项目根的 personas\.active（不进包，所以单独指个绝对路径）
ACTIVE_FILE = ROOT / "personas" / ".active"

# (章标题, 源文件) —— 路径相对 交付包\
CHAPTERS = [
    ("第 0 章 · 给 AI 的完整说明书（先读这个）",  f"{AIDIR}/给AI的完整说明书.md"),
    ("第 1 章 · 状态快照",                      f"{AIDIR}/00-新窗口从这里开始.md"),
    ("第 1.5 章 · 总入口",                      "README.md"),
    ("第 2 章 · 系统总览",                      f"{AIDIR}/01-系统总览.md"),
    ("第 3 章 · 技术踩坑档案（最值钱）",         f"{AIDIR}/02-技术踩坑档案.md"),
    ("第 4 章 · 文件与脚本说明",                f"{AIDIR}/03-文件与脚本说明.md"),
    ("第 5 章 · AI 迭代交接",                   f"{AIDIR}/04-AI迭代交接.md"),
    ("第 5.5 章 · 人格迭代交接（怎么改人格、怎么写方案）",
                                                f"{AIDIR}/06-人格迭代交接.md"),
    ("第 6 章 · AstrBot 界面（当前前端）",       f"{AIDIR}/05-AstrBot界面.md"),
]

MODELFILES = ["Modelfile.assistant-9b", "Modelfile.assistant"]
MODELFILES.append("Modelfile.assistant-35b")


def current_modelfile() -> str:
    r"""当前**实际在用**的那份 Modelfile 文件名。

    做法：读 AstrBot 配置里 `agent_runner.config.model.provider_id`，
    再到 `astrbot_setup.MODELS` 里查出对应的 Ollama 模型名，映射成 Modelfile。

    为什么不写死（2026-09-29 踩过）：
        这里原来硬编码 `Modelfile.assistant-9b`，而 09-29 把模型换成了 35B
        ⇒ 单文件版里"当前在用的模型定义"其实是**旧的 9B**，而没有任何东西会报错。
        又是"改了 A 没改 B"（坑 24 / 26 / 36 那个病）。
    取不到时回退到 9B（并明确打印，别静默）。
    """
    import json as _json
    root = PKG.parent                       # 交付包\ 的上级 = 项目根
    cfg = root / "AstrBotData" / "data" / "cmd_config.json"
    try:
        data = _json.loads(cfg.read_text(encoding="utf-8-sig"))
        pid = data.get("agent_runner", {}).get("config", {}).get("model", {}).get("provider_id")
        sys.path.insert(0, str(root))
        from astrbot_setup import MODELS           # 模型表是唯一真相来源
        # ⚠️ 2026-10-05：这里原来写 `for _key, (mid, _mname, _note) in MODELS.items()`，
        #    而 MODELS 早在 09-29 就加到了 5 个字段（provider_id, 模型名, 说明,
        #    num_ctx, 回复预留）⇒ **解包直接抛 ValueError**，被下面那个
        #    `except` 吞掉、悄悄回退成 9B。表现：附录 B 明明写着"当前实际绑定的模型"，
        #    却永远印 9B（当时配置是 35B）—— 「假绿」的同一个病：**报错被兜底吃掉**。
        #    修法：只按需取字段，不再按固定长度解包（以后加字段也不会再炸）。
        for _key, _entry in MODELS.items():
            mid = _entry[0]
            if mid == pid:
                guess = f"Modelfile.assistant-{_key}"
                if (PKG / "model-config" / guess).exists():
                    return guess
        print(f"  [!] 从 provider_id={pid!r} 推不出 Modelfile，回退到 9B")
    except Exception as e:
        print(f"  [!] 读配置失败（{type(e).__name__}: {e}），Modelfile 回退到 9B")
    return "Modelfile.assistant-9b"

# 工程版（`--eng`）要砍掉的东西。
#
# 为什么要单独出一个「工程版」：
#     全量版里带**附录 A（人格正文）**，而 `03` 的「五、人格文件格式」那节
#     还引用了成人向人格的写法示例。用户把全量版丢给**别的 AI 窗口**时，
#     对方经常直接拒答（"无法生成/违规"），于是连打包、改配置这些
#     跟内容无关的工程活也一起不干了。
#     工程版 = 去掉这些内容，只留工程档案 —— 新窗口接手用这份。
#
# 怎么砍：
#     1. 不输出附录 A / 附录 B
#     2. `03-文件与脚本说明.md` 从 `## 五、人格文件格式` 起整段截断
#        （那一节到文件末尾，所以直接切尾）
CUT_FROM = {
    "03-文件与脚本说明.md": "## 五、人格文件格式",
}

# ⚠️⚠️ 这两个常量**按文件名匹配，不按路径**。
#     实测踩过（2026-09-22）：文档分栏之后 CHAPTERS 里的路径变成了
#     `给AI看的/03-文件与脚本说明.md`，而这里还是裸文件名 ——
#     `CUT_FROM.get("给AI看的/03-...")` 永远返回 None，
#     于是**截断和脱敏双双静默失效**，工程版里又带回了 79 个成人向词
#     和 3 个人格小节标题，而构建过程一句提示都没有。
#     所以：一律用 `Path(fname).name` 取文件名再匹配，并且**构建后必须校验**
#     （见 verify_eng()，跑不过就直接报错退出）。

# 工程版还要把几处"只是描述、但字眼很刺激"的说法换成中性的。
# 这些出现在状态快照 / 界面文档的**变更清单**里（"加了某某那一节"），
# 本身不含内容，但足以让一个新窗口一上来就警惕。
# ⚠️ 只改工程版的**输出**，磁盘上的原文一个字都不动。
ENG_SCRUB = (
    # ⚠️ 开源版：原本是本项目私用的"措辞→中性词"替换表；
    #    换成你自己的词表即可（左 = 不想出现的词，右 = 替代说法）。
    ("示例敏感词A", "中性说法A"),
    ("示例敏感词B", "中性说法B"),
)

# 只在一部分文件上做替换（章节正文），别去动第 0 章说明书
# （说明书里"露骨"是用户原话引用 —— "帮我改人格 / 写得更露骨"，
#   那是给 AI 看的"该拒绝什么"，改了反而看不懂）
ENG_SCRUB_FILES = {"00-新窗口从这里开始.md", "02-技术踩坑档案.md",
                   "04-AI迭代交接.md", "05-AstrBot界面.md"}

ENG_OUT = PKG / AIDIR / "单文件版-工程版.md"


def active_persona() -> str:
    """当前启用的人格文件名（不带 .txt）。读不到就返回空串。"""
    try:
        return ACTIVE_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def persona_files() -> list[tuple[str, str]]:
    """⚠️ 动态扫描 personas/ 目录，不要写死列表 ——
    写死的话，新加的人格不会出现在单文件版里，而且不报错。"""
    cur = active_persona()
    files = sorted((PKG / "personas").glob("*.txt"))
    out = [(p.name, "当前启用" if p.stem == cur else "") for p in files]
    # 当前启用的排到最前面
    out.sort(key=lambda t: (t[1] == "", t[0]))
    return out


def strip_title(text: str) -> str:
    """去掉文件自己的第一行 `# 标题`，章标题由本脚本统一给。"""
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).rstrip()


def cut_for_eng(fname: str, body: str) -> str:
    """工程版：截掉带成人向示例的那一节，并把刺激字眼换成中性说法。

    ⚠️ `fname` 可能是 `给AI看的/xxx.md` 这种带文件夹的路径，
    所以**必须取 basename 再匹配常量** —— 直接用整串匹配会静默失效（实测踩过）。
    """
    key = Path(fname).name
    marker = CUT_FROM.get(key)
    if marker:
        i = body.find(marker)
        if i >= 0:
            body = (body[:i].rstrip()
                    + "\n\n> （本节已从**工程版**移除：它是人格正文的写作指导，含成人向示例。\n"
                      "> 需要看的话，打开全量版 `单文件版-全内容.md`，或 `03-文件与脚本说明.md` 第五节。)\n")
    if key in ENG_SCRUB_FILES:
        for a, b in ENG_SCRUB:
            body = body.replace(a, b)
    return body


# 工程版里**绝不允许出现**的人格小节标题。
# ⚠️ 按**行首**匹配（用 re.M）—— 因为 02 的技术踩坑档案里会**引用**
#    `## 五、人格文件格式` 当例子解释"工程版砍了什么"（那行以 `-` 开头），
#    子串匹配会把这种合法引用误判成泄漏，天天报假警 → 人就不看校验了。
ENG_FORBIDDEN = (r"^#{1,3} 五、人格文件格式", r"^【你是谁】", r"^【用户个人资料】",
                 r"^【⭐ 说话方式", r"^【⭐ 进阶内容", r"^【进阶玩法",
                 r"^【硬约束】", r"^【输出格式】")
# 只是"提醒"，不作为失败条件（技术语境下可能合法出现）。
# ⚠️ 只放**多字、不歧义**的词 —— 单字会误报：
#    第一版放了「射」和「裸」，结果 `映射` 里的「射」天天报警，
#    而假警会让人干脆不看校验输出（等于没校验）。
ENG_SMELL = (
    # ⚠️ 开源版：原本是"成人向措辞"关键词表（工程版输出时提醒用）；
    #    换成你自己的词表，留空 = 不做这项提醒。
    "示例词1", "示例词2",
)

# 工程版**必须在场**的小节（2026-10-11 加）。
#
# ⚠️ 为什么需要这一类检查：`CUT_FROM` 是**纯文本 `find()`** 截尾。只要正文里
#    **原样提到**那个标题（哪怕只是引用、包在反引号里当例子），`find()` 就提前命中，
#    把 `03` 的第三节 / 第四节整块切掉 —— 而 `ENG_FORBIDDEN` 查的是"**多了什么**"，
#    **查不出"少了什么"**，于是内容截短了照样一路绿灯。
#    2026-10-11 实测就这么丢过约 9.8 KB（工程版 234,194 → 226,193 字符，
#    「三、重建顺序」「四、配置文件位置」两节整块消失，构建过程一句提示都没有）。
#    所以这里补一条**正向**断言：这几节必须在场，少一个就判错、不写盘 ✓
#
# ⚠️ 2026-10-11 拆成两组：`ENG_REQUIRED_SRC`（**源文件**里就该有的小节标题，
#    `organize_package.py --check` 的预检拿它扫 `03`）+ `ENG_REQUIRED_OUT`
#    （只存在于**产物**里的章标题 / 截断标记，只有 `verify_eng()` 能断言）。
#    实测踩过：一开始只有合并版，预检拿它去扫源文件，立刻误报「缺 # 第 4 章 …」——
#    预检第一次跑就抓到了这个设计错误（这正是它该干的活）✓
ENG_REQUIRED_SRC = (
    # 这几条必须在**源文件** `03-文件与脚本说明.md` 里就存在（= 截断点**之前**的小节标题）。
    # `organize_package.py --check` 的预检用这一组：跑 check_all 就能提前发现 ✓
    # ⚠️ 判据是**子串**（`in`）：改名到不含原串（`三、重建步骤`）会报；
    #    只在后面加个后缀（`三、重建顺序（2026-10-11 重写）`）**不会**报 ——
    #    那时小节还在、截断点也没动，不该报假警（假警多了人就干脆不看校验了）✓
    "## 一、目录结构",
    "## 二、脚本清单",
    "## 三、重建顺序",
    "## 四、配置文件位置",
)
ENG_REQUIRED_OUT = (
    # 这几条只存在于**构建产物**里（章标题由本脚本加、截断标记由 cut_for_eng 插），
    # 源文件里当然没有 ⇒ 只能拿组装好的工程版去断言（verify_eng 用）✓
    "# 第 4 章 · 文件与脚本说明",
    "本节已从**工程版**移除",          # 截断标记本身也必须在（说明真截过）
)
# 全量：verify_eng() 拿组装好的工程版断言（源小节 + 章标题 + 截断标记都该在）
ENG_REQUIRED = ENG_REQUIRED_SRC + ENG_REQUIRED_OUT


def eng_chapter4_headings(text: str) -> str:
    r"""列出工程版**第 4 章里实际出现的小节标题**（`## `/`### `）。

    为什么要有：`ENG_REQUIRED` 报"缺了 X"时，光看名字不知道**现在到底是什么样** ——
    改了小节名的人得自己回去翻。把实际标题打出来，差在哪一眼就看见 ✓
    （只列第 4 章这一段：所有 CUT_FROM 截断问题都落在这一章，全文标题太长没人看）
    """
    i = text.find("# 第 4 章 · 文件与脚本说明")
    if i < 0:
        return "（连「第 4 章」这个章标题都不在 ⇒ 章节列表或 CUT_FROM 出问题了）"
    j = text.find("\n# 第 ", i + 1)          # 下一个章标题 = 本章结束
    seg = text[i:j if j > 0 else len(text)]
    hs = [ln.strip() for ln in seg.splitlines() if re.match(r"^#{2,3} \S", ln)]
    if not hs:
        return "（这一章里一个小节标题都没有 ⇒ 整章被切掉了）"
    return " ｜ ".join(hs)


def verify_eng(text: str) -> int:
    """构建后**回读校验**工程版：这是防止"静默失效"的唯一办法。

    背景：上面那两处匹配失效过一次，当时**什么提示都没有**，
    工程版带着成人向内容照样生成、照样打进 zip。
    所以这里做三类检查：
        - 结构性的（人格小节标题，行首匹配）→ **出现就报错**，那必然是漏截
        - 结构性的（`ENG_REQUIRED` 必备小节）→ **少一个就报错**，那必然是截短了
          （2026-10-11 加：`CUT_FROM` 是纯文本 find()，正文里提到那个标题就会提前截断，
            而"少了什么"这一类 ENG_FORBIDDEN 是查不出来的）
        - 词表性的（成人向词）              → 只**警告**并报数，人工判断
    """
    lack = [r for r in ENG_REQUIRED if r not in text]
    if lack:
        print(f"\n❌ 工程版校验失败：缺少必须在场的小节/标记 {lack}")
        print(f"   第 4 章里**实际找到**的小节标题：{eng_chapter4_headings(text)}")
        print("   两种可能，按顺序排：")
        print("     ① CUT_FROM 的截断点**提前命中**了 —— 正文里原样提到了那个标题"
              "（见文件头注释与 03 的 📌）⇒ 把正文里那处引用改掉")
        print("     ② 你**改了 `03` 里的小节名**（比如「三、重建顺序」改了名）"
              "⇒ 同步改本文件的 `ENG_REQUIRED`")
        return 1
    bad = [p for p in ENG_FORBIDDEN if re.search(p, text, re.M)]
    if bad:
        print(f"\n❌ 工程版校验失败：出现了不该有的人格标记 {bad}")
        print("   多半是 CUT_FROM / ENG_SCRUB_FILES 的匹配又失效了（见文件头注释）")
        return 1
    # ⚠️ 先把行内代码（`` `...` ``）挖掉再数 —— 人格**文件名**是合法出现的
    #    （`示例人格X` 这种），而文件名里的词会天天误报。
    #    误报的后果很具体：看多了就干脆不看校验输出了，等于没校验
    #    （ENG_SMELL 上面那段注释已经为「射 / 裸」踩过一次同样的坑）。
    #
    # ⚠️⚠️ **必须逐行剥，不能对全文剥。** 实测踩过：全文用
    #    `re.sub(r"`[^`]*`", "", text)` 时，`[^`]` 是**能跨行**的，
    #    于是只要文档里任何一处反引号不配对（markdown 里很常见），
    #    **后面所有反引号的配对就整体错开一格** —— 本该被剥掉的
    #    `示例人格X` 反而露出来被算成"成人向措辞"。
    #    行内代码按定义不跨行，所以逐行剥既更准、也不受全局配对影响。
    #
    # ⚠️ 还要先整段挖掉 **围栏代码块**（``` ... ```）——
    #    里面是真实路径 / JSON / 命令（`--persona 示例人格X`、
    #    `personas\_源文件\玩法-进阶示例.txt`），**必须原样出现**，
    #    不算"描述性提及"。行首的 ``` 才当围栏（行内反引号不受影响）。
    no_fence = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    prose = "\n".join(re.sub(r"`[^`]*`", "", ln) for ln in no_fence.splitlines())
    hits = {w: prose.count(w) for w in ENG_SMELL if w in prose}
    n = sum(hits.values())
    if n:
        print(f"\n⚠️  工程版仍有 {n} 处成人向措辞（结构上没漏，只是描述性提及）")
        print(f"   {hits}")
        print("   在意的话把这些词加进 ENG_SCRUB / ENG_SCRUB_FILES")
    else:
        print("\n✅ 工程版校验通过：无成人向措辞、无人格正文标记")
    return 0


def main() -> int:
    if not PKG.is_dir():
        print(f"❌ 找不到交付包目录: {PKG}")
        return 1

    eng = "--eng" in sys.argv[1:]          # 工程版：不带人格正文
    out_path = ENG_OUT if eng else OUT

    stamp = datetime.now().strftime("%Y-%m-%d")
    if eng:
        out = [
            "# 本地 AI 助手「小九」· 工程档案（单文件版 · **工程版**）",
            "",
            "> ⭐ **这一份是给「接手迭代的 AI 窗口」的** —— "
            "**已剔除人格正文与其写作示例**，只留工程内容。",
            "> 用它接手，就不会因为内容问题卡住；打包、改配置、排错、写文档都能正常干。",
            f"> 打包时间：{stamp} ｜ 原始项目目录：项目根目录",
            "",
            "**包含**：⭐给 AI 的完整说明书 → 状态快照 → 总入口 → 系统总览 → "
            "技术踩坑档案 → 文件与脚本说明（不含第五节）→ AI 迭代交接 → "
            "**人格迭代交接** → AstrBot 界面",
            "",
            "**已移除**：附录 A（人格正文）、`03` 第五节（人格写作指导）。",
            "**附录 B 只放当前在用的那份 Modelfile** —— `Modelfile.assistant`（4B 的）不放。",
            "**需要完整档案时**：打开 `单文件版-全内容.md`。",
            "",
            "**先读「第 0 章 · 给 AI 的完整说明书」，再读「技术踩坑档案」。**",
            "**要改人格 / 写改动方案：直接看「第 5.5 章 · 人格迭代交接」。**",
            "",
            "> ⚠️ **你手上这份就是「单文件版」**，所以文档里任何一句"
            "「不要读 `单文件版-*.md`」都**不适用于你** —— 那说的是"
            "「同时有分章节文档时别重复读」。你只有这一份，**就按它干活**。",
            "",
            "---",
            "",
        ]
    else:
        out = [
            "# 本地 AI 助手「小九」· 完整交付档案（单文件版）",
            "",
            "> 本文件由交付包内所有文档 + 人格 + 配置合并而成，"
            "**可直接整体上传给 AI 用于接手迭代**。",
            "> ⚠️ 里面**含人格正文和成人向写作示例** —— "
            "只想让 AI 干工程活，请改用 `单文件版-工程版.md`（已剔除这些内容，不易被拒答）。",
            f"> 打包时间：{stamp} ｜ 原始项目目录：项目根目录",
            "",
            "**包含**：⭐给 AI 的完整说明书 → 状态快照 → 总入口 → 系统总览 → "
            "技术踩坑档案 → 文件与脚本说明 → AI 迭代交接 → AstrBot 界面 → 全部人格 → 模型定义",
            "",
            "**要接手迭代，先读「第 0 章 · 给 AI 的完整说明书」，再读「技术踩坑档案」。**",
            "",
            "---",
            "",
        ]

    missing = []
    cut_problems = []
    for title, fname in CHAPTERS:
        p = PKG / fname
        if not p.exists():
            missing.append(fname)
            continue
        body = strip_title(p.read_text(encoding="utf-8"))
        if eng:
            # ⚠️ 截断标记在**源文件**里必须**正好出现 1 次**（就是那个真标题）。
            #    出现两次 = 正文里又原样提了一次 ⇒ `cut_for_eng` 的 `find()` 提前命中，
            #    中间几节会被静默切掉。这里先查，别等它切完再猜 ✓
            mk = CUT_FROM.get(Path(fname).name)
            if mk:
                n = body.count(mk)
                if n != 1:
                    cut_problems.append(
                        f"{fname}：截断标记出现 {n} 次（必须正好 1 次）—— 正文里是不是"
                        f"又原样提到了 `{mk}`？")
            body = cut_for_eng(fname, body)
        out += [f"# {title}", "", body, "", "---", ""]
        print(f"  ✅ {fname:26} → {title}")

    if not eng:
        # ---- 附录 A：人格 ----
        plist = persona_files()
        out += ["---", "", "# 附录 A · 人格文件（{} 套，可直接编辑复用）".format(len(plist)), ""]
        out += ["修改后双击项目根的 `切换人格.bat` 即可应用（`scripts\\切换人格.bat` 在交付包里；"
                "Cherry 时期的 `apply_persona.py` 已归档、跑不了）。"
                "⚠️ 人格文件可能包含个人资料；公开分享前请先检查并删除敏感内容。", ""]
        for fname, mark in plist:
            p = PKG / "personas" / fname
            if not p.exists():
                missing.append(f"personas/{fname}")
                continue
            txt = p.read_text(encoding="utf-8").rstrip()
            tag = f"  【{mark}】" if mark else ""
            out += [f"## {p.stem}{tag}  （{len(txt)} 字符）", "", "```text", txt, "```", ""]
            print(f"  ✅ personas/{fname:22} ({len(txt)} 字符)")

    # ---- 附录 B：模型定义 ----
    # ⚠️ 工程版**只放当前在用的那份**。
    #    `Modelfile.assistant` 是已删除的 4B 模型留下的历史文件，
    #    里面还带着旧版的大段 SYSTEM（可能含用户个人资料），
    #    放进"给 AI 看的干净版"里既没用、又会让新窗口看到人格式内容。
    #    实测踩过：校验直接报出个人资料标题 / `【输出格式】` 就来自它。
    #
    # ⚠️ 2026-09-29 修：这里原来硬编码 `Modelfile.assistant-9b`，
    #    而**当前在用的是 35B**（`astrbot_setup.MODELS["35b"]` → `Modelfile.assistant-35b`）
    #    ⇒ 交付档案里根本没有当前在用的模型定义，"只放当前在用的那份"成了假话，
    #    "从交付包重建一台机器"会拿到错的定义。现在从 astrbot_setup 的模型表推导。
    eng_pick = current_modelfile()
    modelfiles = [eng_pick] if eng else MODELFILES
    out += ["---", "", "# 附录 B · 模型定义（Modelfile）", ""]
    for fname in modelfiles:
        p = PKG / "model-config" / fname
        if not p.exists():
            missing.append(f"model-config/{fname}")
            continue
        txt = p.read_text(encoding="utf-8").rstrip()
        out += [f"## {fname}", "", "```dockerfile", txt, "```", ""]
        print(f"  ✅ model-config/{fname}")

    # ⚠️ 2026-09-29 改：**先校验、再写盘**。
    #    原来顺序是"写盘 → 读回来 → verify_eng"，于是校验失败时
    #    **带毒产物已经覆盖了好文件**，而派生文件（单文件版-*.md）又被所有
    #    `--check` 跳过（organize_package 的 GENERATED 正则）⇒ 下一次
    #    `build_package_zip.py` 直接把它打进 zip 发出去。
    #    现在：先在内存里拼好、跑校验，过了才落盘。
    body = "\n".join(out) + "\n"
    if cut_problems:
        print(f"\n[X] 截断标记不对（{len(cut_problems)} 处），**不写盘**：")
        for m in cut_problems:
            print(f"     - {m}")
        print(f"   第 4 章里**实际找到**的小节标题：{eng_chapter4_headings(body)}")
        print("   说明：`CUT_FROM` 用的是纯文本 `find()`，正文里提到那个标题就会提前截断，"
              "把中间几节一起切掉（见 03 那条 📌 与 build_single_file.py 文件头注释）")
        return 1
    if missing:
        print(f"\n[X] 有 {len(missing)} 个章节/附录缺失，**不写盘**（避免把带毒版本留在盘上）：")
        for m in missing:
            print(f"     - {m}")
        return 1
    if eng:
        rc = verify_eng(body)
        if rc:
            print("\n[X] 工程版校验没过，**不写盘**（旧文件保持原样）")
            return rc

    # ⚠️ `newline="\n"` 必须写死：Windows 上 `write_text` 默认会把 `\n` 翻译成 `\r\n`，
    #    而本仓库的 `.md` 一律是 LF（见 `.gitattributes` 的说明）。
    #    实测（2026-09-26）：不加这个参数，这两份派生物每次重建都会变回 CRLF，
    #    于是 git diff 里每个 `.md` 都显示"整篇全改"，真实改动被淹没。
    write_text(out_path, body)

    n_chars = len(body)
    print(f"\n✅ 已重建 {out_path.name}")
    print(f"   {n_chars:,} 字符 / {out_path.stat().st_size/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
