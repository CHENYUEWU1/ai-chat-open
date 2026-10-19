#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
让脚本的「副本」不再悄悄漂移 —— 同时管两处镜像：

    1) 项目根 `scripts\`        ← 让文档里 `python scripts\xxx.py` 这种写法能跑（坑 23）
    2) 交付包 `交付包\scripts\`  ← zip 里那份，给"拿到包的人 / 另一个 AI"

为什么需要这个（坑 23 的根因之一）：
    全库文档里有两种路径写法，互相矛盾：

        python astrbot_setup.py             ← 项目根直接跑
        python scripts\astrbot_setup.py     ← 带 scripts\ 前缀（05 有 15 处、03 有 13 处）

    而**项目根原本没有 `scripts\` 目录** —— 脚本都在根，`交付包\scripts\` 才是副本。
    所以照 `05` / `03` 敲命令会全部失败：
        python: can't open file 'E:\本地ai\scripts\astrbot_setup.py': [Errno 2] ...

    这和坑 23（`install_fetch_plugin.py` 从项目根消失）是同一类问题：
    **文档描述的目录结构不是真实存在的目录结构。**

解法（为什么不直接把文档里的 `scripts\` 全删掉）：
    1. 项目根是用户实际使用的地方（`启动AstrBot.bat` 等都在这），
       文档里的裸文件名写法和它一致，是对的；
    2. 但 `交付包\` 里脚本**确实**在 `scripts\` 子目录下 —— 根目录要放那一堆 .md，
       脚本堆在 `scripts\` 里更整齐。所以"带 `scripts\`"在交付包语境下是合理的；
    3. 与其把 35 处引用改一遍（改完两种语境还是各说各话），
       **不如让两种写法都成立** —— 项目根也放一份 `scripts\` 镜像。

镜像 vs 真身：
    真身 = 项目根的脚本。**改脚本一定改根目录那份**，然后跑这个脚本同步。
    本脚本会校验两边逐字节一致，不一致就报出来（`--check`）。
    和坑 23 的教训对齐：**不允许存在"没有任何东西会校验"的副本。**

    交付包那份**同样要校验** —— 之前它就是这么漂移的：
    改了根目录的 `build_single_file.py`，`交付包\scripts\` 里还是旧的，
    而 zip 是从 `交付包\` 压的，于是"发出去的脚本"和"能跑的脚本"不是同一个。

用法：
    python scripts_sync.py            # 从项目根同步到两处镜像
    python scripts_sync.py --check    # 只校验一致性，不写
"""
import filecmp
import shutil
import sys
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

ROOT = Path(__file__).resolve().parent

# 本脚本会被镜像进 `交付包\scripts\`（包要自包含）。如果有人在包里单独跑它，
# ROOT 就变成 `交付包\scripts\`，镜像目标会算歪、凭空造出嵌套的 scripts\scripts\。
# 用「项目根标志文件」把这种情况挡掉 —— 这个文件只在项目根有。
ROOT_MARKER = "启动AstrBot.bat"

# 要镜像的文件：项目根的 .py 脚本。
# 用显式后缀而不是 `*` —— 免得把未来出现的临时文件也镜像进去。
#
# 为什么不镜像 .bat 到项目根 `scripts\`：
#   .bat 里全是硬编码绝对路径（`set "ASTRBOT_ROOT=E:\本地ai\AstrBotData"`、
#   `"E:\本地ai\astrbot_setup.py"`），从哪个目录双击都一样能跑，
#   所以 `scripts\启动AstrBot.bat` 是**纯粹的重复文件**，没有存在价值。
#   文档里说到 .bat 一律写「双击 `启动AstrBot.bat`」（不带路径前缀）。
#
# 但交付包里要带上 .bat —— 那是给"另一台电脑"的，根目录只有 .md 和 README。
MIRRORS = (
    {
        "dir": ROOT / "scripts",
        "patterns": ("*.py",),
        "skip": {"setup_paths.py", "scripts_sync.py"},
        "label": "scripts\\",
        "note": "改脚本请改根目录那份",
    },
    {
        "dir": ROOT / "交付包" / "scripts",
        "patterns": ("*.py", "*.bat"),
        "skip": {"setup_paths.py"},
        "label": "交付包\\scripts\\",
        "note": "这份是 zip 的内容，必须与根目录一致",
    },
    # Modelfile 也是"真身在项目根、交付包里一份副本"，同样会漂。
    # 2026-09-23 补上 —— 当时刚把 `repeat_last_n 256 → 1024` 和
    # `num_predict 512 → 768` 改进根目录那份，而**当时没有任何东西会校验
    # `交付包\model-config\` 里那份**。这正是坑 24 / 坑 26 的同一个模式：
    # 「不允许存在没有任何东西会校验的副本」。
    #
    # `allow_extra: True` —— 交付包的 model-config\ 里还有两个**只在包里存在**
    # 的文件（`template_original.jinja`、`角色卡-小九.json`），
    # 它们不是根目录文件的副本，所以既不能报"多余"，更不能被删掉。
    {
        "dir": ROOT / "交付包" / "model-config",
        "patterns": ("Modelfile*",),
        "skip": set(),
        "label": "交付包\\model-config\\",
        "note": "Modelfile 的副本，改请改根目录那份",
        "allow_extra": True,
    },)


def sources(spec: dict) -> list[Path]:
    out = []
    for pat in spec["patterns"]:
        for p in sorted(ROOT.glob(pat)):
            if p.name in spec["skip"]:
                continue
            # 跳过下划线开头的：那是临时/探针脚本（`_probe_*.py` / `_msg.txt`），
            # 不是项目的一部分。实测踩过：一个临时探针 `_probe_A2.py` 被镜像进了
            # 两处 scripts\，然后被打进交付包 zip —— 多出 16 KB 垃圾，
            # 而 `--check` 一路绿灯（因为它只比对"根目录有的文件"，
            # **根目录多出来的东西它照样当正常**）。
            if p.name.startswith("_"):
                continue
            out.append(p)
    return out


def compare(spec: dict) -> tuple[list[str], list[str], list[str]]:
    """返回 (缺失, 内容不同, 多余)。"""
    d = spec["dir"]
    missing, differs, extra = [], [], []
    want = {p.name for p in sources(spec)}
    for p in sources(spec):
        t = d / p.name
        if not t.exists():
            missing.append(p.name)
        elif not filecmp.cmp(p, t, shallow=False):
            differs.append(p.name)
    if d.is_dir() and not spec.get("allow_extra"):
        for t in sorted(d.iterdir()):
            if t.is_file() and t.name not in want and t.name not in spec["skip"]:
                extra.append(t.name)
    return missing, differs, extra


def report(spec: dict, missing, differs, extra) -> None:
    if not (missing or differs or extra):
        print(f"[OK] {spec['label']} 与项目根一致（{len(sources(spec))} 个文件）")
        return
    print(f"[!] {spec['label']} 和项目根不一致：")
    for n in missing:
        print(f"      {spec['label']} 缺            : {n}")
    for n in differs:
        print(f"      两边内容不同           : {n}")
    for n in extra:
        print(f"      {spec['label']} 里有、根没有 : {n}")


def check() -> int:
    if not (ROOT / ROOT_MARKER).exists():
        print(f"[i] 这里不是项目根（没有 {ROOT_MARKER}），跳过一次性的镜像校验。")
        print(f"    本脚本只在项目根 E:\\本地ai\\ 下运行；包里的这份是副本，不用跑。")
        return 0
    bad = False
    for spec in MIRRORS:
        missing, differs, extra = compare(spec)
        report(spec, missing, differs, extra)
        bad = bad or bool(missing or differs or extra)
    if bad:
        print("\n跑 `python scripts_sync.py` 同步（改脚本请改根目录那份）")
        return 1
    return 0


def sync_one(spec: dict) -> None:
    d = spec["dir"]
    d.mkdir(parents=True, exist_ok=True)
    copied, same, extra = [], [], []
    want = {p.name for p in sources(spec)}
    for p in sources(spec):
        t = d / p.name
        if t.exists() and filecmp.cmp(p, t, shallow=False):
            same.append(p.name)
            continue
        existed = t.exists()
        shutil.copy2(p, t)
        copied.append((p.name, existed))
    if d.is_dir() and not spec.get("allow_extra"):
        for t in sorted(d.iterdir()):
            if t.is_file() and t.name not in want and t.name not in spec["skip"]:
                extra.append(t.name)
    for n in extra:
        (d / n).unlink()

    print(f"[OK] 已同步 {ROOT.name}\\ → {spec['label']}")
    for n, existed in copied:
        print(f"      {'更新' if existed else '新增'}: {n}")
    if same:
        print(f"      未变: {len(same)} 个")
    for n in extra:
        print(f"      已删除（根目录没有）: {n}")


def sync() -> int:
    if not (ROOT / ROOT_MARKER).exists():
        print(f"[i] 这里不是项目根（没有 {ROOT_MARKER}），不动任何文件。")
        print(f"    本脚本只在项目根 E:\\本地ai\\ 下运行；包里的这份是副本，不用跑。")
        return 0
    for spec in MIRRORS:
        sync_one(spec)
    print()
    return check()


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv[1:] else sync())
