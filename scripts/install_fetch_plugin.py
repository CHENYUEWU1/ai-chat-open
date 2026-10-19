#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「读网页」插件装进 AstrBot。

插件干什么：
    给模型加一个 `fetch_url` 工具 —— 打开网页读正文。
    补上 AnySearch 只能看摘要的短板，**不需要 API Key、不需要浏览器**。

为什么不用现成的：
    AstrBot 内置的搜索源里，只有 tavily / firecrawl / exa 自带"读全文"工具，
    但那三个都要 API Key。AnySearch 免密钥，可惜只有搜索没有读全文。

用法：
    python install_fetch_plugin.py            # 安装 / 更新
    python install_fetch_plugin.py --check    # 看装没装
    python install_fetch_plugin.py --remove   # 卸载

⚠️ 安装/卸载前先完全退出 AstrBot，否则要重启才生效。
"""
import shutil
import sys
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

PLUGIN_NAME = "astrbot_plugin_fetch_url"
HERE = Path(__file__).resolve().parent

# 插件源码在哪。这个脚本有两个位置：
#   ① 项目根  E:\本地ai\install_fetch_plugin.py        → 源码在同级 plugins\
#   ② 交付包  E:\本地ai\交付包\scripts\install_fetch_plugin.py → 源码在同级 ..\plugins\
# 两个位置都试，别写死一个 —— 写死会让另一个位置直接报"找不到源码"。
SRC_CANDIDATES = (
    HERE / "plugins" / PLUGIN_NAME,
    HERE.parent / "plugins" / PLUGIN_NAME,
)

DST = Path(r"E:\本地ai\AstrBotData\data\plugins") / PLUGIN_NAME

# 装哪些文件。`test_fetch_safety.py` 不是运行时必需的，但一起装过去有个好处：
# 现场就能用它验证"装进去的那份"没被改坏（2026-10-03 加 —— 之前漏装，
# 结果装的副本和项目根是否一致只能靠人记得比）。
FILES = ("main.py", "fetch.py", "metadata.yaml", "test_fetch_safety.py")


def find_src() -> Path | None:
    for c in SRC_CANDIDATES:
        if c.is_dir():
            return c
    return None


def running() -> bool:
    import subprocess
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq AstrBot.exe"],
        capture_output=True, text=True, errors="replace").stdout
    return "AstrBot.exe" in out


def main() -> int:
    args = sys.argv[1:]
    src = find_src()

    if "--check" in args:
        print(f"  插件源码 : {src or SRC_CANDIDATES[0]}  {'存在' if src else '[X] 不存在'}")
        print(f"  安装位置 : {DST}  {'已安装' if DST.is_dir() else '[X] 未安装'}")
        missing = []
        if DST.is_dir():
            for f in FILES:
                p = DST / f
                ok = p.exists()
                print(f"    - {f:16} {'OK' if ok else '[X] 缺失'}")
                if not ok:
                    missing.append(f)
        # ⚠️ 2026-09-29 改：原来只 `return 0 if src else 1` —— **只看源码在不在**，
        #    于是"没装""装了一半（少文件）"全都返回 0，而 check_all 只认退出码
        #    ⇒ 体检里那一项写的是"fetch_url 插件装没装"，实际永远 ✅。
        #    现在：源码缺 / 没装 / 少文件 —— 任一都算失败。
        if src is None or not DST.is_dir() or missing:
            return 1
        return 0

    if "--remove" in args:
        if not DST.is_dir():
            print("  本来就没装")
            return 0
        if running():
            print("[!] AstrBot 正在运行 —— 删掉后要重启才生效")
        shutil.rmtree(DST)
        print(f"[OK] 已卸载 {DST}")
        print("[!] 重启 AstrBot 生效")
        return 0

    if src is None:
        print("[X] 找不到插件源码，试过这些位置：")
        for c in SRC_CANDIDATES:
            print(f"      {c}")
        return 1
    missing = [f for f in FILES if not (src / f).exists()]
    if missing:
        print(f"[X] 插件源码不完整（{src}），缺：{missing}")
        return 1

    if running():
        print("[!] AstrBot 正在运行 —— 装完要重启才生效")

    DST.mkdir(parents=True, exist_ok=True)
    changed = []
    for f in FILES:
        s, d = src / f, DST / f
        same = d.exists() and s.read_bytes() == d.read_bytes()
        shutil.copy2(s, d)
        print(f"  [{'=' if same else 'OK'}] {f}" + ("（内容没变）" if same else ""))
        if not same:
            changed.append(f)
    # 清掉可能残留的 __pycache__，避免加载到旧字节码
    cache = DST / "__pycache__"
    if cache.is_dir():
        shutil.rmtree(cache)

    print(f"\n[OK] 已装到 {DST}")
    if changed:
        print(f"     本次更新：{', '.join(changed)}")
    print("[!] 重启 AstrBot 生效")
    print("    装好后模型多一个 `fetch_url` 工具：")
    print("    搜完摘要不够时，它会自己去把那一页读下来。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
