#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给 AstrBot 打「关掉定时任务工具」补丁。

问题（2026-09-29 实测）：
    AstrBot 默认给每个请求挂一个内置工具 `future_task`（定时任务），
    它的说明是**英文**的：

        "Manage your future tasks. Use action='create' to schedule a recurring
         cron task or one-time run_at task. ..."

    对一个**中文角色扮演**的本地小模型来说，这段英文是纯粹的干扰：
    它偶尔会把工具说明**当成自己的台词念出来**。实测那次（35B、温度 1.0）：

        用户：来亲亲
        模型：I will check if there's any need to update future tasks or perform
              other background operations. I don't have specific instructions for
              this timestamp yet. I'll proceed with checking existing tasks first.
              → 然后真去调 future_task(action="list") → "No cron jobs found."

    用户不用定时任务，这个工具**一点用都没有**，只有副作用。

为什么不能只改配置：
    `provider_settings.proactive_capability.add_cron_tools` 改成 false 是有效的，
    但 **AstrBot 会自己把 `cmd_config.json` 整个写回去**，顺手把这个值盖回 true
    （实测：13:59 改成 false，14:02 AstrBot 自己重写时变回 true）。
    所以配置层改不住 —— 必须从源码层关掉。

补丁做的事：
    在 `astr_main_agent.py` 里给那一行加一条环境变量兜底：

        if config.add_cron_tools and os.environ.get("ASTRBOT_CRON_TOOLS", "1").lower() not in (...):

    配套在 `启动AstrBot.bat` 里设 `set "ASTRBOT_CRON_TOOLS=0"`。

    好处：以后要恢复只要把 .bat 里那行改成 1（或删掉），**不用再碰源码**；
    而且升级 AstrBot 后重跑本脚本，`--check` 会告诉你补丁丢没丢。

⚠️ 这是改 AstrBot 的源码。**AstrBot 升级/重装后补丁会丢，要重跑一次。**

用法：
    python patch_astrbot_cron.py            # 打补丁（源码 + 启动脚本）
    python patch_astrbot_cron.py --check    # 只看现状
    python patch_astrbot_cron.py --revert   # 还原

注意：打完要**完全退出 AstrBot 再重启**才生效。
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

from console_utf8 import console_utf8
from safe_write import nl_of, read_text_raw, with_nl, write_bytes, write_text

console_utf8()   # GBK 控制台下的兜底，见 console_utf8.py

ROOT = Path(r"C:\LocalAI-Assistant\AstrBot\AstrBot_4.28.1_windows_amd64_portable")
TARGET = ROOT / "backend/app/astrbot/core/astr_main_agent.py"
BAT = Path(r"C:\LocalAI-Assistant\启动AstrBot.bat")

OLD = """    if config.add_cron_tools:
        _proactive_cron_job_tools(req, plugin_context)"""

NEW = """    # ---- 补丁：关掉定时任务工具 future_task（patch_astrbot_cron.py）----
    # 那个工具的说明是英文的，中文角色扮演的本地小模型会把说明当台词念出来
    # （实测："I will check if there's any need to update future tasks..."）。
    # 配置项 add_cron_tools 会被 AstrBot 自己重写覆盖，所以这里再加一层环境变量兜底。
    # 恢复办法：把 启动AstrBot.bat 里的 ASTRBOT_CRON_TOOLS 改成 1（或删掉那行）。
    if config.add_cron_tools and os.environ.get(
        "ASTRBOT_CRON_TOOLS", "1"
    ).strip().lower() not in ("0", "false", "no", "off"):
        _proactive_cron_job_tools(req, plugin_context)"""

MARK = "关掉定时任务工具 future_task（patch_astrbot_cron.py）"

BAT_ANCHOR = 'set "OLLAMA_MAX_LOADED_MODELS=1"'
BAT_ADD = (
    'set "OLLAMA_MAX_LOADED_MODELS=1"\r\n'
    "\r\n"
    "REM 关掉 future_task（定时任务）工具：它的英文说明会让中文人设的模型念英文台词。\r\n"
    "REM 由 patch_astrbot_cron.py 配套写入；改回 1 即可恢复（要重启）。\r\n"
    'set "ASTRBOT_CRON_TOOLS=0"'
)


def patch_source(revert: bool) -> int:
    if not TARGET.exists():
        print(f"[X] 找不到 {TARGET}")
        return 1
    text = read_text_raw(TARGET, encoding="utf-8")
    # ⚠️ 按文件自己的换行符构造锚点：AstrBot 源码是 CRLF，
    #    read_text_raw 不做归一化，LF 锚点永远匹配不上（2026-09-29 踩过）。
    nl = nl_of(text)
    OLD_ = with_nl(OLD, nl)
    NEW_ = with_nl(NEW, nl)
    patched = MARK in text

    if revert:
        if not patched:
            print("  源码本来就没打补丁，跳过")
            return 0
        if NEW_ not in text:
            print("[X] 源码里找不到补丁后的代码块，无法自动还原")
            return 1
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(TARGET, TARGET.with_name(f"{TARGET.name}.bak-{stamp}"))
        write_text(TARGET, text.replace(NEW_, OLD_, 1), newline="")
        print("[OK] 源码已还原")
        return 0

    if patched:
        print("[OK] 源码已打过补丁")
        return 0
    if OLD_ not in text:
        print("[X] 源码里找不到要替换的那段 —— 可能 AstrBot 版本变了。")
        print(f"    请看 {TARGET} 里这一段：")
        print('        if config.add_cron_tools:')
        print("            _proactive_cron_job_tools(req, plugin_context)")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = TARGET.with_name(f"{TARGET.name}.bak-{stamp}")
    shutil.copy2(TARGET, bak)
    print(f"[OK] 已备份源码 -> {bak.name}")
    write_text(TARGET, text.replace(OLD_, NEW_, 1), newline="")
    print("[OK] 源码已打补丁（加环境变量兜底 ASTRBOT_CRON_TOOLS）")
    return 0


def patch_bat(revert: bool) -> int:
    if not BAT.exists():
        print(f"[X] 找不到 {BAT}")
        return 1
    raw = BAT.read_bytes()
    patched = b"ASTRBOT_CRON_TOOLS" in raw

    if revert:
        if not patched:
            print("  启动脚本本来就没打补丁，跳过")
            return 0
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(BAT, BAT.with_name(f"{BAT.name}.bak-cron-{stamp}"))
        # 逐行删掉补丁加的那两行 REM + 一行 set（.bat 是 GBK，注释也要按 GBK 比）
        # ⚠️ bytes 字面量只能是 ASCII，中文必须 .encode("gbk")，见本脚本这次踩的坑
        m1 = "future_task（定时任务）工具".encode("gbk")
        m2 = "patch_astrbot_cron.py 配套写入".encode("gbk")
        keep = [ln for ln in raw.split(b"\r\n")
                if b"ASTRBOT_CRON_TOOLS" not in ln
                and m1 not in ln and m2 not in ln]
        write_bytes(BAT, b"\r\n".join(keep))
        print("[OK] 启动脚本已还原")
        return 0

    if patched:
        print("[OK] 启动脚本已打过补丁")
        return 0
    if BAT_ANCHOR.encode("gbk") not in raw:
        print("[X] 启动脚本里找不到锚点行（OLLAMA_MAX_LOADED_MODELS），无法安全插入")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(BAT, BAT.with_name(f"{BAT.name}.bak-cron-{stamp}"))
    write_bytes(BAT, raw.replace(BAT_ANCHOR.encode("gbk"), BAT_ADD.encode("gbk"), 1))
    print("[OK] 启动脚本已打补丁（ASTRBOT_CRON_TOOLS=0，GBK + CRLF）")
    return 0


def main() -> int:
    args = sys.argv[1:]
    revert = "--revert" in args

    if "--check" in args:
        if not TARGET.exists() or not BAT.exists():
            print("[X] 找不到源码或启动脚本")
            return 1
        st_src = "已打" if MARK in read_text_raw(TARGET, encoding="utf-8") else "未打"
        st_bat = "已打" if b"ASTRBOT_CRON_TOOLS" in BAT.read_bytes() else "未打"
        print(f"  源码补丁   : {st_src}   ({TARGET.name})")
        print(f"  启动脚本   : {st_bat}   ({BAT.name})")
        ok = st_src == "已打" and st_bat == "已打"
        print(f"  结论       : {'✅ 补丁在位' if ok else '❌ 补丁不完整（跑一次 python patch_astrbot_cron.py）'}")
        return 0 if ok else 1

    print(f"源码: {TARGET}")
    rc1 = patch_source(revert)
    print(f"启动脚本: {BAT}")
    rc2 = patch_bat(revert)
    if rc1 or rc2:
        return 1
    if not revert:
        print("\n[!] 重启 AstrBot 才生效：完全退出（含托盘）→ 双击 启动AstrBot.bat")
        print("[!] AstrBot 升级/重装后补丁会丢，重跑一次这个脚本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
