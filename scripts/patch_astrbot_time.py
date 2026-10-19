#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给 AstrBot 打「时间提示」补丁。

问题：
    AstrBot 注入给模型的时间长这样：

        <system_reminder>Current datetime: 2026-09-22 12:32 (CST), Weekday: Tuesday</system_reminder>

    两个坑：
      1. `12:32` 是 24 小时制，但小模型会读成"一点半"（实测出现过）
      2. `CST` 这个缩写有歧义 —— 中国标准时间（UTC+8）和美国中部时间（UTC-6）
         都叫 CST

    实测答"现在几点"的准确率：原样 **1/3**，改完 **3/3**。

补丁后：
        Current datetime: 2026-09-22 12:32 (UTC+08:00, 24小时制), Weekday: Tuesday (二)

⚠️ 这是改 AstrBot 的源码。**AstrBot 升级/重装后补丁会丢，要重跑一次。**

用法：
    python patch_astrbot_time.py            # 打补丁
    python patch_astrbot_time.py --check    # 只看现状
    python patch_astrbot_time.py --revert   # 还原

注意：打完要重启 AstrBot 才生效。
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

from console_utf8 import console_utf8
from safe_write import nl_of, read_text_raw, with_nl, write_bytes, write_text

console_utf8()   # GBK 控制台下的兜底，见 console_utf8.py

# AstrBot 主 agent 源码
SRC = Path(
    r"E:\本地ai\AstrBot\AstrBot_4.28.1_windows_amd64_portable"
    r"\backend\app\astrbot\core\astr_main_agent.py"
)

OLD = '''        current_time = now.strftime("%Y-%m-%d %H:%M (%Z)")
        weekday = WEEKDAY_NAMES[now.weekday()]
        system_parts.append(f"Current datetime: {current_time}, Weekday: {weekday}")'''

# ⚠️ 下面两份都是 **LF 版锚点**。AstrBot 源码是 CRLF，
#    用之前必须 `with_nl(...)` 换成文件自己的换行符，否则永远匹配不上
#    （`read_text_raw` 不做归一化 —— 这是 2026-09-29 那次"补丁在、check 说不在"的根因）。
NEW_LF = '''        # ---- 补丁：把时间写成明确时区 + 24 小时制 ----
        # 原来的 %Z 会输出 "CST"（中国标准时间 / 美国中部时间 同缩写，有歧义），
        # 而且 12:32 这种 24 小时制小模型会读成"一点半"。
        # 实测改成下面这样，"现在几点"的答对率从 1/3 升到 3/3。
        _off = now.strftime("%z") or ""
        if _off:
            _off = f"UTC{_off[:3]}:{_off[3:]}"
        else:
            _off = "本地时间"
        current_time = now.strftime(f"%Y-%m-%d %H:%M ({_off}, 24小时制)")
        weekday = WEEKDAY_NAMES[now.weekday()]
        _wd_cn = "一二三四五六日"[now.weekday()]
        system_parts.append(
            f"Current datetime: {current_time}, Weekday: {weekday} ({_wd_cn})"
        )'''

MARK = "补丁：把时间写成明确时区"


def main() -> int:
    args = sys.argv[1:]
    if not SRC.exists():
        print(f"[X] 找不到 {SRC}")
        return 1
    text = read_text_raw(SRC, encoding="utf-8")
    # ⚠️ 按**文件自己的换行符**构造锚点（CRLF 文件用 CRLF 锚点）
    nl = nl_of(text)
    OLD_ = with_nl(OLD, nl)
    NEW = with_nl(NEW_LF, nl)
    # ⚠️ 2026-09-29：判据从"只看 MARK 注释"改成"注释 + 真正的代码块都在"。
    #    原来只找 MARK：万一有人只留了注释、代码被换掉（半坏状态），
    #    这里会报"已打补丁" —— 而 `--check` 是"升级后确认还在不在"的唯一手段。
    patched = (MARK in text) and (NEW in text)

    if "--check" in args:
        print(f"  文件: {SRC}")
        print(f"  状态: {'已打补丁' if patched else '未打补丁（用的是原版格式）'}")
        # ⚠️ 2026-09-29：原来无条件 `return 0` —— 即使打印"未打补丁"也算成功，
        #    而 check_all 只认退出码、通过时还丢弃输出 ⇒ 补丁被 AstrBot 升级冲掉也全绿。
        return 0 if patched else 1

    if "--revert" in args:
        if not patched:
            print("  本来就没打补丁，不用还原")
            return 0
        if NEW not in text:
            print("[X] 找不到补丁后的代码块，无法自动还原")
            return 1
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(SRC, SRC.with_name(f"{SRC.name}.bak-{stamp}"))
        write_text(SRC, text.replace(NEW, OLD_), newline="")
        print("[OK] 已还原成原版（重启 AstrBot 生效）")
        return 0

    if patched:
        print("[OK] 已经打过补丁了，不用重复打")
        return 0

    if OLD_ not in text:
        print("[X] 源码里找不到要替换的那段 —— 可能 AstrBot 版本变了。")
        print("    请手动检查这一段：")
        print(f"    {SRC}:")
        print('        current_time = now.strftime("%Y-%m-%d %H:%M (%Z)")')
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = SRC.with_name(f"{SRC.name}.bak-{stamp}")
    shutil.copy2(SRC, bak)
    print(f"[OK] 已备份 -> {bak.name}")

    write_text(SRC, text.replace(OLD_, NEW, 1), newline="")
    print("[OK] 已打补丁")
    print("     注入格式: Current datetime: YYYY-MM-DD HH:MM (UTC+08:00, 24小时制),"
          " Weekday: Tuesday (二)")
    print("\n[!] 重启 AstrBot 才生效")
    print("[!] AstrBot 升级/重装后补丁会丢，重跑一次这个脚本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
