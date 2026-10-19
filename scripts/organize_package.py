#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
把 `交付包\` 的文档分成两个**用途明确**的文件夹：

    交付包\
    ├── README.md              总入口
    ├── 给我看的\              ← 用户自己看：日常操作 / 写人格 / 选型记录
    ├── 给AI看的\              ← 丢给 AI 窗口：工程档案 + 两个单文件版
    ├── scripts\  personas\  model-config\  plugins\     ← 材料（不是文档）
    └── setup_paths.py  改路径.bat

为什么需要脚本（而不是手工拖文件）：
    交付包里文档互相引用，引用有两种写法：
        交付包\02-技术踩坑档案.md        ← 带路径
        02-技术踩坑档案.md               ← 裸文件名
    手工拖完，那几十处引用就全指向不存在的位置了 —— 而且**不会报错**。
    这和坑 23（文件从项目根消失）、坑 24（副本悄悄落后一版）是同一个病：
    **改了结构，但没有任何东西会校验引用还成不成立。**

所以本脚本干三件事：
    1. 移动文件（幂等，已经移过就跳过）
    2. 重写全部 .md 里的**带路径引用**（`交付包\xxx.md` → `交付包\给AI看的\xxx.md`），
       以及改名文件的**裸文件名引用**；**跳过 ASCII 目录树行**
    3. `--check` 校验：文件在位 + 没有残留的旧引用

为什么**裸文件名不加文件夹前缀**：
    包里同名文件不可能有两个，`02-技术踩坑档案.md` 本身就唯一。
    加前缀反而在子文件夹的文档里要写成 `..\给AI看的\...`，更容易错。
    所以约定：**裸文件名表示"本交付包里的某个文件"**，
    带路径的写法一律相对 `交付包\`。

⚠️ 不改的东西：
    - `单文件版-*.md`（派生物，由 build_single_file.py 重新生成）
    - 各文档里 ASCII 目录树的**排版**（那要人手工改，脚本只跳过不破坏）

用法：
    python organize_package.py            # 重组 + 重写引用
    python organize_package.py --check    # 只校验，不写
"""
import filecmp
import re
import shutil
import sys
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

PKG = Path(r"E:\本地ai\交付包")
ROOT = Path(r"E:\本地ai")

# 哪个文件进哪个文件夹。**文件名保持不变**，只换位置。
LAYOUT = {
    "给我看的": [
        "操作手册.md",
        "本地AI部署方案.md",
        "06-人格写作模板.md",
        "愿望清单与升级路线.md",
        "项目文件索引.md",
    ],
    "给AI看的": [
        "给AI的完整说明书.md",
        "单文件版-工程版.md",
        "单文件版-全内容.md",
        "00-新窗口从这里开始.md",
        "01-系统总览.md",
        "02-技术踩坑档案.md",
        "03-文件与脚本说明.md",
        "04-AI迭代交接.md",
        "05-AstrBot界面.md",
        "06-人格迭代交接.md",
        "07-局域网API.md",
        "08-当前阶段.md",
        "参考-病娇提示词形态.md",
        "参考-模型对比实测.md",
        "压缩规则-人格文件.md",
        "重构必读-改前先看.md",
        "09-交接-20261009.md",],
}

# 放在包根、不动的文档
STAY = ["README.md"]

# 交付包里的文档 → 项目根的同名快照。
#
# ⚠️ 为什么需要这一条：项目根也放了几份文档的拷贝（用户在那儿直接抓起来用），
#    但它们**没有任何东西校验** —— 实测就漂了：包内的说明书已经更新到"文档分栏"，
#    项目根那份还停在分栏之前（16.1 KB vs 17.3 KB，差 39 行）。
#    这和坑 23 / 坑 24 是同一个病。**主副本一律是交付包里那份**，根目录是快照。
#
# 不镜像的：README.md —— 项目根那份是完整版（首页），
#          交付包那份是给"拿到 zip 的人"的精简版，**故意不同**。
MIRROR_DOCS = {
    "给AI看的/给AI的完整说明书.md": "给AI的完整说明书.md",
    "给AI看的/07-局域网API.md":     "07-局域网API.md",
    "给AI看的/08-当前阶段.md":      "08-当前阶段.md",
    "给AI看的/重构必读-改前先看.md": "重构必读-改前先看.md",
    "给AI看的/09-交接-20261009.md": "09-交接-20261009.md",   # 2026-10-09 交接   # 2026-10-09 新增：重构前必读   # 2026-10-03 新增，登到项目根方便找
    "给我看的/人格写作模板.md":     "人格写作模板.md",
    "给我看的/操作手册.md":         "操作手册.md",
    "给我看的/本地AI部署方案.md":   "本地AI部署方案.md",
    "给我看的/愿望清单与升级路线.md": "愿望清单与升级路线.md",   # 2026-10-08 新增：升级路线
}

# 只改位置、不改名的除外（要改名的写在这里）
RENAME: dict[str, str] = {"06-人格写作模板.md": "人格写作模板.md"}

GENERATED = re.compile(r"^单文件版-.*\.md$")      # 派生物，不碰
TREE_LINE = re.compile(r"^\s*[│├└┌─┐┘┴┬┤╭╰╯╮|`+\-]{0,6}\s*[│├└┌]")   # ASCII 目录树

# `交付包\xxx` 或 `交付包/xxx` 到行尾/空白为止的一段路径
PKG_REF = re.compile(r"交付包[\\/][^\s`)\]|,，。；;]*")


def normalize_sep(line: str) -> str:
    """修掉 `交付包/给AI看的\\xxx.md` 这种混用分隔符。

    为什么必须修：markdown 链接 `](交付包/给AI看的\\xxx.md)` 在
    GitHub / VS Code 里**点不开**（反斜杠不是分隔符）。
    规则：分隔符跟着「交付包」后面那个走 —— 用了 `/` 就整条都用 `/`。
    """
    def fix(m: re.Match) -> str:
        s = m.group(0)
        return s.replace("\\", "/") if s[len("交付包")] == "/" else s
    return PKG_REF.sub(fix, line)


def target_of(name: str) -> tuple[str, str] | None:
    """返回 (文件夹, 新文件名)；不在 LAYOUT 里就返回 None。"""
    for folder, names in LAYOUT.items():
        if name in names:
            return folder, RENAME.get(name, name)
    return None


def ref_patterns(name: str) -> list[tuple[str, str]]:
    """返回 [(正则, 替换成)]。带路径的加文件夹前缀；裸文件名只在改名时替换。"""
    t = target_of(name)
    if not t:
        return []
    folder, newname = t
    out = [(rf"交付包([\\/]){re.escape(name)}",
            "交付包\\1" + folder + "\\\\" + newname)]
    if newname != name:
        out.append((rf"(?<![\w\\/]){re.escape(name)}", newname))
    return out


def scannable_lines(text: str):
    """逐行产出 (行号, 行内容)，**跳过围栏代码块内部**。

    为什么要跳：坑 26 那一节为了讲清楚"手工拖会坏什么"，把旧路径
    （`交付包\\02-技术踩坑档案.md`）当**例子**贴在了代码块里。
    校验器要是把它当成残留引用，就会一直报假警 —— 而假警会让人
    干脆不看 `--check` 的输出，**等于没有校验**。
    """
    inside = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            continue
        yield i, line


# ---------------------------------------------------------------- 移动

def move() -> int:
    moved, skipped, bad = [], [], []
    for folder, names in LAYOUT.items():
        (PKG / folder).mkdir(exist_ok=True)
        for name in names:
            newname = RENAME.get(name, name)
            src = PKG / name
            dst = PKG / folder / newname
            if dst.exists():
                skipped.append(f"{folder}\\{newname}")
                continue
            if not src.exists():
                bad.append(name)
                continue
            shutil.move(str(src), str(dst))
            moved.append(f"{name}  →  {folder}\\{newname}")
    for m in moved:
        print(f"  [移] {m}")
    if skipped:
        print(f"  [=] 已在目标位置: {len(skipped)} 个")
    for b in bad:
        print(f"  [X] 找不到源文件: {b}")
    return 1 if bad else 0


# ---------------------------------------------------------------- 引用重写

def rewrite_refs() -> int:
    files = [p for p in list(PKG.rglob("*.md")) + list(ROOT.glob("*.md"))
             if not GENERATED.match(p.name) and "cherry-legacy" not in p.parts]
    touched = 0
    for p in files:
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        out, changed = [], 0
        inside = False
        for line in lines:
            if line.lstrip().startswith("```"):
                inside = not inside
                out.append(line)
                continue
            if inside or TREE_LINE.match(line):   # 代码块 / 目录树：只跳过，不破坏
                out.append(line)
                continue
            new = line
            for folder, names in LAYOUT.items():
                for name in names:
                    for pat, rep in ref_patterns(name):
                        new = re.sub(pat, rep, new)
            new = normalize_sep(new)
            if new != line:
                changed += 1
            out.append(new)
        if changed:
            # ⚠️ `newline="\n"` 必须写死：Windows 上默认会把 `\n` 翻译成 `\r\n`，
            #    而本仓库的 `.md` 一律 LF（见 `.gitattributes` 的说明）。
            #    不写死的话，"只改 1 行引用"会变成"整篇 220 行全改"的假 diff。
            p.write_text("".join(out), encoding="utf-8", newline="\n")
            touched += 1
            print(f"  [改] {p.relative_to(ROOT)}  （{changed} 行）")
    if not touched:
        print("  [=] 没有需要改的引用")
    return 0


# ---------------------------------------------------------------- 先读我

READ_ME_HUMAN = """# 给我看的

> 这一份是**给你自己**的。另一个文件夹 `给AI看的\\` 是丢给 AI 窗口的。

## 你大概只会用到七件事

| 我想 | 打开哪个 |
|---|---|
| **启动 / 停止 / 换人格 / 排障** | `操作手册.md` —— 日常操作全在这 |
| **想改它的性格/说话方式，但不知道怎么说** | `操作手册.md` 的 **§6「怎么提问才能拿到你想要的效果」** —— 有一张照抄的表 |
| **自己写一个人格** | `人格写作模板.md` —— 照骨架填空，十几分钟一个 |
| **当初为什么选这个模型/这个界面** | `本地AI部署方案.md` —— 前期调研记录 |
| **以后有钱了想升级配置** | `愿望清单与升级路线.md` —— ⭐ **我要什么、现在卡在哪、加内存/换显卡各能解锁什么**（照着加就行）|
| **看整个项目的工程档案** | [`../给AI看的/单文件版-工程版.md`](../给AI看的/单文件版-工程版.md) —— ⭐ **那份是干净的**（无 18+ 内容、无人格正文），你想看也能看 |
| **让 AI 帮我干活** | 去 `..\\给AI看的\\`，先传 `给AI的完整说明书.md` |

> **`单文件版-工程版.md` 为什么你可以放心看**：它把人格正文、以及人格写作指导
> 整节剔除，成人向措辞**实测 0 命中**（剩下的"露骨"4 处是文件名和
> "该拒绝什么"的说明）。所以它既能给 AI，也能给你。

## 快捷键

- **开始聊天**：双击项目根的 `启动AstrBot.bat` → 浏览器 `http://127.0.0.1:6185`
- **打游戏前**：双击 `停止小九.bat`（释放约 5.6 GB 显存）
- **换人格**：双击 `切换人格.bat` → 编号菜单

## 三条最容易踩的

1. **别直接双击 `AstrBot.exe`** —— 必须走 `启动AstrBot.bat`，否则数据写到 C 盘
2. **改完人格要双击 `切换人格.bat`** 才生效（在界面里改完也要）
   —— 忘了会有提示：`python astrbot_setup.py --check` 现在会逐字比对，
   报"内容不一致"就是没重导
3. **不想用的人格**：删掉 `personas\\` 里那个 `.txt`，**光在界面里删会被撤销**
"""

READ_ME_AI = """# 给AI看的

> 这一份是**丢给 AI 窗口**的。你自己看的在 `..\\给我看的\\`。

## 按这个顺序传

| 顺序 | 传什么 | 为什么 |
|---|---|---|
| **1** | `给AI的完整说明书.md` || **1.5** | `09-交接-20261009.md` | **最新状态**（界面拆分 / 空回复兜底 / 温度 / 预热 / 预算 / smoke_test / 回滚点）—— 比 `08-当前阶段.md` 新，接手先看它 |
 先让它知道**该干什么、不该碰什么**。不先给这份，新窗口看到成人向内容会**直接拒答**，连打包、改配置也一起不干（已实测）|
| **2** | `单文件版-工程版.md` | 全部工程上下文（架构 / 踩坑记录 / 命令 / 脚本 / **人格迭代方法**）|
| **3** | 正常提要求 | —— |

> ⭐ **最少也要传第 1 份** —— 就 17 KB，但它决定了对方肯不肯干活。
>
> ⭐ **要它帮忙改人格 / 写改动方案**：工程版里有
> **第 5.5 章 · 人格迭代交接**，直接说"按 5.5 章 §3 的格式给我一份改动方案"。
> 那一章的开头（§11）还有一段**可直接复制粘贴的开场白**。

## 看状态只跑一条命令

```powershell
python scripts\\check_all.py        # 只读校验，不碰 GPU，AstrBot 开着也能跑（项数以脚本输出为准）
```

以前得一条一条猜有哪些脚本、猜输出算不算"正常" ——
那正是"每次都跑很久、而且看不出它在干什么"的来源。

## 测试卡住了怎么办

**GPU 测试是"要判断行为"时才跑的，不是每轮都跑。**
只读校验（上面那条）永远不碰 GPU、不会卡。

```powershell
python scripts\\fix_ollama.py --check   # 1 秒，只读：Ollama 活不活 + 模型加载了没
python scripts\\fix_ollama.py           # 复位 Ollama（AstrBot 不用关）
```

症状：`ollama ps` 挂着不返回、显存里没有模型、脚本"卡住"没有任何输出。
**卡住超过 2 分钟不要继续等**，直接复位。详见 `06-人格迭代交接.md` §10.5。

## 文件清单

| 文件 | 是什么 | 优先级 |
|---|---|---|
| `给AI的完整说明书.md` | 技术描述 + 全部命令 + 硬约束 + 「哪些活不用你碰」 | ⭐⭐ 必传 |
| `单文件版-工程版.md` | 上面那些文档全合并成一个文件 | ⭐ 推荐 |
| `06-人格迭代交接.md` | ⭐ **怎么改人格、怎么写改动方案**（结构 / 工艺规则 / 度量 / 模板）| ⭐ 改人格时必传 |
| `07-局域网API.md` | ⭐ **局域网网关那一条线**：接口 / 鉴权 / 搜索三档 / 时间注入 / 反"说一半" / 资源面板 / 停止小九 / **网页访问授权（6 位入网码 + 已授权设备管理）** / APK 下载 / 请求日志 | 要开局域网、或手机 App 连不上时必传 |
| `08-当前阶段.md` | ⭐ **当前状态 + 已修问题清单**（含实测数字；新窗口先看这个）| ⭐ |
| `压缩规则-人格文件.md` | ⭐ **要压缩人格时必传**：无损压缩的允许/禁止清单、高危词表核对、自检清单 | ⭐ 压缩时必传 |
| `00-新窗口从这里开始.md` | 状态快照：现在什么样、做过什么、还剩什么 | ⭐ |
| `02-技术踩坑档案.md` | **全部踩坑记录**（每条都有排查过程和实测数据）| ⭐ |
| `01-系统总览.md` | 需求、硬件实测、选型理由 | |
| `03-文件与脚本说明.md` | 文件清单、脚本用法、从零重建顺序 | |
| `04-AI迭代交接.md` | 迭代约束与维护范围 | |
| `05-AstrBot界面.md` | 当前前端：安装、配置、插件、Telegram、专属坑 | |
| `单文件版-全内容.md` | ⚠️ **含人格正文，别传给新窗口**（用它会被拒答）—— 自存档用 | ⚠️ |

## 一句话交代（可直接复制给对方）

```text
这是一个本地部署的私人 AI 助手项目（Ollama + 本地模型 + AstrBot 前端 + 自写局域网网关），
模型推理、聊天记录、日志都在本机；**只有"联网搜索 / 读网页"会出网**（走本机代理）。
附件是这个项目的完整技术档案，请先读完再动手。

要注意的一点：项目里 personas\\ 下是使用者自己的私人角色设定文件。
那部分正文由他自己写，你不用生成也不用复述。

我需要你做的是把它当一个工程产物来维护：
- 改结构、调配比、瘦身（把冗余规则合并掉）
- 改行为规则（长度、语气、开场、代词、什么时候停）
- 做度量：token 体积、关键词命中率、开场重复率（单样本不算，至少 3 个）
- 每次动手前先交一份「改动方案」（格式见档案第 06 章 §3），我说可以你再改文件

三条硬要求（照做能省很多时间）：
1. 只读分章节的文档（00~06），**不要读 `单文件版-*.md`** ——
   那两份是它们拼出来的，读一遍等于把同样内容读两遍。
2. 每做一步先用一行说你要干什么、为什么。**不要静默连续跑命令。**
3. 看状态用一条命令：`python scripts\\check_all.py`（只读校验，不碰 GPU，项数以脚本输出为准）。
   **只读的时候不要重建**单文件版和 zip。

测试分两类，别混（上一轮就是卡在这里）：
- **每次都跑**：`python scripts\\check_all.py` —— 不碰 GPU、不会卡。
- **不要自己跑**：`test_persona*.py` / `test_longctx.py` / `test_tools.py` ——
  要加载 5.6 GB 模型。要跑就先 `python scripts\\fix_ollama.py --check`，
  再说清楚跑哪个、几个样本，等我说可以；卡住超过 2 分钟就跑
  `python scripts\\fix_ollama.py` 复位，**不要继续等**。

请从档案第 06 章「人格迭代交接」开始读，读完告诉我你打算先查什么。
```

> 只想让它干**纯工程活**（跑脚本、改配置、打包）时，把上面这段换成
> `给AI的完整说明书.md` 开头那段"工程部分"的交代即可。
"""


def write_readme() -> None:
    for folder, text in (("给我看的", READ_ME_HUMAN), ("给AI看的", READ_ME_AI)):
        p = PKG / folder / "先读我.md"
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"  [写] {folder}\\先读我.md")


# ---------------------------------------------------------------- 根目录快照

def mirror_root_docs(write: bool) -> int:
    """交付包里的文档 → 项目根的同名快照。返回不一致的个数。

    ⚠️ 这里用的是**逐字节**比较（`filecmp.cmp(shallow=False)`），这是故意的：
        行尾不同也要算漂移，否则会出现"根目录那份其实不一样、但检查全绿"。
        代价是**两份的行尾必须真的逐字节相同**，所以写过去的时候顺手把 CRLF
        归一成 LF —— 否则只要有一份是 CRLF、另一份是 LF，
        每次都会报"根目录副本过期"，而人看了会以为内容真变了。
    """
    drift = 0
    for rel, rootname in MIRROR_DOCS.items():
        src, dst = PKG / rel, ROOT / rootname
        if not src.exists():
            print(f"  [X] 缺源文件: 交付包\\{rel.replace('/', chr(92))}")
            drift += 1
            continue
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        drift += 1
        if write:
            shutil.copy2(src, dst)
            raw = dst.read_bytes()
            if b"\r\n" in raw:                      # 归一成 LF（本仓库 .md 一律 LF）
                dst.write_bytes(raw.replace(b"\r\n", b"\n"))
            print(f"  [同步] 交付包\\{rel.replace('/', chr(92))}  →  {rootname}")
        else:
            print(f"  [X] 根目录副本过期: {rootname}")
    return drift


# ---------------------------------------------------------------- 校验

def check_eng_sections() -> bool:
    r"""`03-文件与脚本说明.md` 的**必备小节在不在场**（= `build_single_file.py --eng` 预检）。

    返回 True = 有问题。

    ⚠️ 为什么查这一条（2026-10-11 实测踩到）：
        `build_single_file.py` 的 `CUT_FROM["03-文件与脚本说明.md"]` 是**纯文本 find()** 截尾。
        正文里只要**原样提到**那个标题（哪怕只是引用、包在反引号里），`find()` 就提前命中，
        把「三、重建顺序」「四、配置文件位置」整块切掉 —— 而且**一句报错都没有**：
        工程版单文件是递给接手 AI 的，静默缺小节 = 新窗口在残缺上下文里干活。

    ⚠️ 为什么挂在**本脚本**里，而不是给 `check_all.py` 加第 16 项：
        `check_all.py` 的「文档分栏」那一项跑的就是本脚本 `--check`
        ⇒ 挂在这里 = 跑 `python check_all.py` 就会报，不用等 `--eng`；
        而「**15 项**」被 8 处文档当契约引用（其中 08 / CHANGELOG 是**历史快照**、
        按规矩不能改），加一项会让那堆数字集体过期 —— 得不偿失 ✓
    """
    try:
        import build_single_file as bsf          # 只取常量，不重建任何东西
        # ⚠️ 用 **SRC** 那一组：只有"源文件里就该有的小节标题"才能拿源文件去扫。
        #    `ENG_REQUIRED_OUT`（章标题 / 截断标记）只存在于构建产物里，扫源文件必然误报
        #    —— 这个错 2026-10-11 真踩过，预检第一次跑就报出来了 ✓
        required = list(bsf.ENG_REQUIRED_SRC)
        cut = bsf.CUT_FROM.get("03-文件与脚本说明.md")
    except Exception as e:                       # noqa: BLE001 —— 校验脚本自己别把 check_all 炸了
        print(f"  [X] 读不到 build_single_file.ENG_REQUIRED_SRC：{type(e).__name__}: {e}")
        return True

    p = PKG / "给AI看的" / "03-文件与脚本说明.md"
    if not p.exists():
        print("  [X] 找不到 给AI看的\\03-文件与脚本说明.md（ENG_REQUIRED 预检跑不了）")
        return True

    text = p.read_text(encoding="utf-8")
    lack = [r for r in required if r not in text]
    n_cut = text.count(cut) if cut else 0
    if lack:
        print(f"  [X] 03 缺这些必备小节/标记：{lack}")
        print("      ⇒ `build_single_file.py --eng` 会切错或切短（工程版少内容而没人发现）")
        print("      ⇒ 要么把小节加回来，要么同步改 build_single_file.py 的 ENG_REQUIRED")
    if n_cut != 1:
        print(f"  [X] 03 里截断标记 {cut!r} 出现 {n_cut} 次（必须正好 1 次）")
        print("      ⇒ 正文里是不是又原样提了一次那个标题？`--eng` 会**提前截断**，")
        print("        把中间几节静默切掉 ⇒ 改掉正文里那处引用")
    if lack or n_cut != 1:
        return True
    print(f"  [OK] 03 必备小节在场（ENG_REQUIRED_SRC {len(required)} 条）+ 截断标记 1 次"
          f"（--eng 预检）")
    return False


def check() -> int:
    bad = False
    for folder, names in LAYOUT.items():
        want = {RENAME.get(n, n) for n in names} | {"先读我.md"}
        for name in names:
            newname = RENAME.get(name, name)
            if not (PKG / folder / newname).exists():
                print(f"  [X] 缺文件: {folder}\\{newname}")
                bad = True
            if (PKG / name).exists():
                print(f"  [X] 老旧位置还在: 交付包\\{name}")
                bad = True
        # 多出来的文件：这两个文件夹是脚本托管的，出现预期外的文件就是出事了。
        # 实测踩过：`给我看的\` 里凭空多出一个 200 KB 的旧「单文件版-全内容.md」，
        # 而当时所有 `--check` 都是绿的 —— 因为**没人检查"多出来的"**。
        #
        # ⚠️ 2026-09-29 改：原来只查**直接子文件**，于是 `给我看的\备份\` 里
        #    12 份已删除人格的旧版本**逃过检查**（zip 照打）。
        #    现在递归查；`备份\` 是**故意保留的历史**（用户要求备份进仓库），
        #    所以显式放行 —— 但**打印出来**，不静默忽略。
        #    想让历史也回到"无人校验的副本"状态，就把下面这行删掉。
        ALLOW_SUBDIR = {"备份"}
        _pkg_folder = PKG / folder
        if _pkg_folder.is_dir():
            for p in sorted(_pkg_folder.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(_pkg_folder)
                if rel.parts and rel.parts[0] in ALLOW_SUBDIR:
                    continue
                if len(rel.parts) > 1 or rel.name not in want:
                    print(f"  [X] {folder}\\ 里有预期外的文件: "
                          f"{str(rel).replace(chr(92), '/')}"
                          f"（{p.stat().st_size/1024:.1f} KB）")
                    bad = True
            # 放行的目录：报个数，让人知道那里面有多少东西
            for sub in sorted(ALLOW_SUBDIR):
                d = _pkg_folder / sub
                if d.is_dir():
                    n = len([x for x in d.rglob("*") if x.is_file()])
                    print(f"  [i] {folder}\\{sub}\\ 是故意保留的历史（{n} 个文件），"
                          f"不参与「预期外」检查")
        if not (PKG / folder / "先读我.md").exists():
            print(f"  [X] 缺: {folder}\\先读我.md")
            bad = True

    # 残留引用
    files = [p for p in list(PKG.rglob("*.md")) + list(ROOT.glob("*.md"))
             if not GENERATED.match(p.name) and "cherry-legacy" not in p.parts]
    for p in files:
        for i, line in scannable_lines(p.read_text(encoding="utf-8")):
            if TREE_LINE.match(line):
                continue
            for folder, names in LAYOUT.items():
                for name in names:
                    hits = []
                    if re.search(rf"交付包[\\/]{re.escape(name)}", line):
                        hits.append(f"交付包\\{name}")
                    if name in RENAME and re.search(
                            rf"(?<![\w\\/]){re.escape(name)}", line):
                        hits.append(name)
                    for h in hits:
                        print(f"  [X] 旧引用 {p.relative_to(ROOT)}:{i} "
                              f"({h})  {line.strip()[:80]}")
                        bad = True
    if not bad:
        n = sum(len(v) for v in LAYOUT.values())
        print(f"  [OK] 两个文件夹就位（{n} 个文档），没有残留的旧引用")
    # 03 的必备小节（--eng 预检）—— 放在这里，跑 check_all 的「文档分栏」就会带上 ✓
    if check_eng_sections():
        bad = True
    if mirror_root_docs(write=False):
        bad = True
    else:
        print(f"  [OK] 项目根 {len(MIRROR_DOCS)} 份快照与交付包逐字节一致")
    return 1 if bad else 0


def main() -> int:
    if not PKG.is_dir():
        print(f"[X] 找不到 {PKG}")
        return 1
    if "--check" in sys.argv[1:]:
        print("[校验] 交付包文档分栏")
        return check()

    print("[1/5] 移动文档")
    rc = move()
    print("[2/5] 重写引用")
    rewrite_refs()
    print("[3/5] 生成 先读我.md")
    write_readme()
    print("[4/5] 同步项目根快照")
    mirror_root_docs(write=True)
    print("[5/5] 校验")
    rc2 = check()
    if rc or rc2:
        return 1
    print("\n[OK] 完成。别忘了重跑派生物：")
    print("     python build_single_file.py")
    print("     python build_single_file.py --eng")
    print("     python build_package_zip.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
