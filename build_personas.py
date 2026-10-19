#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
由「共有核心 + 玩法片段」生成 `personas\*.txt`。

为什么要生成，而不是直接写 4 份完整人格：
    4 份人格里有 ~5.5KB 是**完全相同的共有内容**（代词、回复形态、一回一步、
    人物设定、说话方式、进阶内容 ①～⑨、要直接答的、语言长度、硬约束、
    时间、输出格式）。手工复制 4 份 = 改一处要改四处，
    而这正是本项目反复踩的坑（见 02-技术踩坑档案 坑 23 / 24 / 26 / 27）：
    **没有任何东西会校验的副本，一定会漂。**

所以：
    `personas\_源文件\_核心.txt`        共有内容，里面有一个 `{{进阶玩法}}` 占位符
    `personas\_源文件\玩法-*.txt`       各玩法片段
    本脚本把它们拼起来 → `personas\病娇-助手-<名字>.txt`

⚠️ **`personas\` 下的那 4 份是生成物，别直接改** —— 会被本脚本覆盖。
   要改内容改 `personas\_源文件\` 里的源文件，然后重跑本脚本。

用法：
    python build_personas.py            # 生成/更新
    python build_personas.py --check    # 只校验，不写
    python build_personas.py --force    # 生成物被手改过也照样覆盖
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

from console_utf8 import console_utf8
from safe_write import write_bytes, write_text

console_utf8()

ROOT = Path(r"C:\LocalAI-Assistant")
PERSONAS = ROOT / "personas"
SRC = PERSONAS / "_源文件"
CORE = SRC / "_核心.txt"
STATE = SRC / ".built.json"          # 记录上次生成的内容哈希，用来发现手改
PLACEHOLDER = "{{进阶玩法}}"

# ⚠️ 第二套源文件：**男版**（2026-09-24 用户要求"男版也留一份，方便切换"）。
#    为什么单开一套源，而不是拿备份：
#      那些备份是**改人称之前**的（用「他」指雅雾 56 处）——
#      拿它们做男版会把"你我分不清"那件事一起带回来。
#    所以男版是**从当前女版生成的**，只翻两处：性别 + 关系那节。
#    改法见 make_male 那一步（或直接手改 `_源文件-男\_核心.txt`）。
SRC_MALE = PERSONAS / "_源文件-男"
STATE_MALE = SRC_MALE / ".built.json"

# 玩法段的小标题和共同要求 —— 由脚本加，片段文件里只写各自的内容
HEADER = ("【进阶玩法——只做这一类】\n"
          "**共同要求：按【进阶内容】来 —— 备选池里挑、强度有起伏、句子短、一回一步。**\n")
ONLY_ONE = "\n**只做这一类。** 你提到别的玩法时也要往这一类靠。\n"

# 生成哪几份： 文件名 → (用哪个源目录, [用哪几个玩法片段])
#
# ⚠️ 曾经还有一份「病娇-助手-全部」（三段拼起来），2026-09-23 用户让删了：
#    它 8500 字符 / 30% 窗口，和另外三份重复，而且是切换人格就能替代的东西。
#    **每份都带一份相同的共有核心，所以多一份就是多 6KB 全量重复。**
#
# ⚠️ 2026-09-24 加了**男版三份**（用户："男版的有备份吗？可以先放在切换人格那里"）。
#    男版 = 同一套结构，源目录换成 `_源文件-男\`，三个玩法片段内容相同（性别中立）。
MAP = {
    # ---- 2026-09-26：病娇 6 份已删（用户要求），这里**故意留空** ----
    # 框架保留：`_源文件\` / `_源文件-男\` 里的 _核心.txt + 玩法-*.txt 都还在，
    # 别的 AI 照这套骨架写自己的源文件，然后在下面加回一行即可重新生成：
    #     "人格名": (SRC,      ["玩法-xxx.txt"]),     # 女版源
    #     "人格名": (SRC_MALE, ["玩法-xxx.txt"]),     # 男版源
}

# 第一行标记：提醒"这是生成的"。只有一行，代价约 25 token。
# （人格里已经规定"不要输出 markdown 符号"，所以模型不会把它念出来。）
MARK = "# 自动生成的文件，别直接改。改 personas\\_源文件\\ 里的源文件，再跑 build_personas.py\n"


def build_text(core: str, frags: list[str]) -> str:
    if PLACEHOLDER not in core:
        raise ValueError(f"{CORE.name} 里找不到占位符 {PLACEHOLDER}")
    parts = [HEADER] + [f.rstrip() + "\n" for f in frags]
    if len(frags) == 1:
        parts.append(ONLY_ONE)
    body = "\n".join(parts)
    return MARK + core.replace(PLACEHOLDER, body.strip()).strip() + "\n"


def expected() -> dict[str, str]:
    """生成"应该长什么样"的全表。每份按 MAP 里指定的**源目录**取核心和玩法片段。"""
    out = {}
    cache: dict[Path, str] = {}
    for name, (src_dir, frag_names) in MAP.items():
        if src_dir not in cache:
            cache[src_dir] = (src_dir / "_核心.txt").read_text(encoding="utf-8")
        core = cache[src_dir]
        frags = [(src_dir / fn).read_text(encoding="utf-8").rstrip() for fn in frag_names]
        out[name] = build_text(core, frags)
    return out


# 两套源目录各自一份状态文件（记录上次生成的哈希，用来发现手改）
def state_paths() -> dict[Path, Path]:
    return {SRC: STATE, SRC_MALE: STATE_MALE}


def name_src(name: str) -> Path:
    return MAP[name][0]


def load_state() -> dict:
    """把两套源的哈希合并成一个 dict（key 是人格名，不会撞）。

    ⚠️ 2026-09-29 改：坏状态文件**不再静默当空**。
        原来这里是 `except Exception: pass` —— 状态文件损坏/半写/被 git clean 掉时，
        状态变空 ⇒ `手改检测` 静默失效 ⇒ `build()` 直接覆盖被手工编辑过的人格文件
        并把新哈希写回状态：**用户的手改永久丢失，而且一个字提示都没有**。
        现在：坏状态打一行警告并**要求显式 --force**（见 main 里的用法），
        不把"读不出来"当成"没有状态"。
    """
    merged: dict = {}
    broken: list[Path] = []
    for p in state_paths().values():
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"不是 dict，而是 {type(data).__name__}")
            merged.update(data)
        except Exception as e:
            broken.append(p)
            print(f"[!] 状态文件读不出来：{p}")
            print(f"    原因：{type(e).__name__}: {e}")
    if broken:
        print(f"[!] 有 {len(broken)} 个状态文件坏了 —— **手改检测这次不可信**。")
        print(f"    如果生成物是手工改过的，现在重建会把你的改动覆盖掉。")
        print(f"    确认要覆盖就加 --force；否则先修/删掉上面那些状态文件。")
    return merged, bool(broken)


def save_state(want: dict[str, str]) -> None:
    """按源目录把哈希分开写回各自的 .built.json。"""
    by_src: dict[Path, dict] = {}
    for k, v in want.items():
        by_src.setdefault(name_src(k), {})[k] = hashlib.md5(v.encode()).hexdigest()
    for src_dir, p in state_paths().items():
        if src_dir in by_src:
            write_text(p, json.dumps(by_src[src_dir], ensure_ascii=False, indent=2))


def check() -> int:
    missing = [d for d in (SRC, SRC_MALE) if not (d / "_核心.txt").exists()]
    if missing:
        for d in missing:
            print(f"[X] 找不到 {d / '_核心.txt'}")
        return 1
    want = expected()
    bad = 0
    for name, text in want.items():
        p = PERSONAS / f"{name}.txt"
        if not p.exists():
            print(f"  [X] 缺: {name}.txt")
            bad += 1
        elif p.read_text(encoding="utf-8") != text:
            print(f"  [X] 过期/不一致: {name}.txt（源文件改过，或者生成物被手改）")
            bad += 1
    # personas\ 下有没有不在 MAP 里的 .txt
    for p in sorted(PERSONAS.glob("*.txt")):
        if p.stem not in want:
            print(f"  [!] personas\\{p.name} 不是本脚本生成的（会一起被 AstrBot 导入）")
    if not bad:
        # ⚠️ 2026-09-29：MAP 为空时不能报"0 份一致"就通过 —— 那是**假绿**：
        #    现在 7 份人格全都不受本脚本管（改了源不重生成、手工改也没人发现），
        #    而 check_all 里那一项会显示 [OK]。
        if not want:
            print("  [!] MAP 是空的 —— **本脚本现在不管任何人格**，这一项没有可校验的内容。")
            print("      这不是错误（6 份病娇删掉后故意留空），但别把它当成'人格都没问题'。")
            print("      人格现在由这些地方管：personas\\*.txt 直接改 + check_all.py 的")
            print("      「人格库 vs 磁盘」和「交付包 personas」两项。")
            return 0
        print(f"  [OK] {len(want)} 份人格与源文件一致")
    else:
        print("\n跑 `python build_personas.py` 重新生成")
    return 1 if bad else 0


def build(force: bool) -> int:
    missing = [d for d in (SRC, SRC_MALE) if not (d / "_核心.txt").exists()]
    if missing:
        for d in missing:
            print(f"[X] 找不到 {d / '_核心.txt'}")
        return 1
    want = expected()
    state, state_broken = load_state()
    if state_broken and not force:
        # ⚠️ 2026-09-29：状态坏了就不能信"手改检测"，也就不该往下覆盖。
        #    （原来状态坏了会被当成空状态，于是检测静默失效、直接覆盖用户手改。）
        print("[X] 状态文件坏了 —— 这次没法判断生成物有没有被手改，先不重建。")
        print("    确认生成物不要了 → 加 --force；或者把坏掉的 .built.json 修好/删掉再跑。")
        return 1
    # 手改检测：生成物当前内容 != 上次生成的内容 → 有人直接改过它
    hand = []
    for name in want:
        p = PERSONAS / f"{name}.txt"
        if not p.exists():
            continue
        old = state.get(name)
        if old and hashlib.md5(p.read_text(encoding="utf-8").encode()).hexdigest() != old:
            hand.append(name)
    if hand and not force:
        print("[X] 这几份生成物被手改过，直接跑会丢掉那些改动：")
        for n in hand:
            print(f"      - {n}.txt")
        print("    先把改动搬到 personas\\_源文件\\ 里，")
        print("    或者确认不要了就加 --force 覆盖。")
        return 1

    for name, text in want.items():
        p = PERSONAS / f"{name}.txt"
        existed = p.exists()
        if existed and p.read_text(encoding="utf-8") == text:
            continue
        write_text(p, text)
        print(f"  [{'更新' if existed else '生成'}] personas\\{name}.txt  "
              f"({len(text.rstrip())} 字符)")
    save_state(want)
    print()
    return check()


def sync_package(prune: bool = False) -> None:
    """把人格同步一份到交付包（那边以前是手工拷的，已经过期很久了）。

    ⚠️ 2026-09-29 改：**默认不再删交付包里多出来的文件**。
        原来的清理判据是"当前 `personas\\` 里有什么"（`keep = PERSONAS.glob("*.txt")`），
        而**不是**"本次生成了什么"。于是当 `personas\\` 被移走/清空时（正是 `MAP` 被清空那种背景），
        `keep` 变成空集 ⇒ `dst` 里每一个 `.txt` 都不在 keep 里
        ⇒ **无条件把 `交付包\\personas\\` 全部删掉**。而 `main()` 在 rc==0 时就会调它。
        现在：清理要显式 `--prune`，且先打印将删的清单（不静默删）。
    """
    dst = ROOT / "交付包" / "personas"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in MAP:
        src = PERSONAS / f"{name}.txt"
        if src.exists():
            shutil.copy2(src, dst / src.name)
            n += 1
    for p in sorted(PERSONAS.glob("*.txt")):
        if p.stem not in MAP:
            shutil.copy2(p, dst / p.name)
            n += 1
    # 交付包里多出来的（已删人格）：默认只报告，不删
    keep = {p.name for p in PERSONAS.glob("*.txt")}
    extra = [p for p in sorted(dst.glob("*.txt")) if p.name not in keep]
    if extra and not prune:
        print(f"  [!] 交付包\\personas\\ 里有 {len(extra)} 份在 personas\\ 里已经没有的：")
        for p in extra:
            print(f"        - {p.name}")
        print(f"      要删的话加 --prune（默认不删，避免误伤）")
    elif extra and prune:
        for p in extra:
            p.unlink()
            print(f"  [删] 交付包\\personas\\{p.name}（源里已经没有了）")
    print(f"  [OK] 已同步 {n} 份到 交付包\\personas\\")


def main() -> int:
    args = sys.argv[1:]
    if "--check" in args:
        print("[校验] 生成人格 vs 源文件")
        return check()
    print("[生成] personas\\_源文件\\ → personas\\")
    rc = build("--force" in args)
    if rc == 0:
        print("[同步] → 交付包\\personas\\")
        sync_package(prune="--prune" in args)
    return rc


if __name__ == "__main__":
    sys.exit(main())
