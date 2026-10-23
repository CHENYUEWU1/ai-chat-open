# 2026-10-22 注意：本脚本面向 Ollama（已弃用，用户只留 llama.cpp）。保留作排错参考；跑之前先起 Ollama。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""关掉 WebUI 的「内联 HTML 卡片」（ChatUI HTML GenUI）。

为什么（用户报的现象）：
    "输出的时候会出现独立的窗口显示 html 码，在 TG 上不会，在 AstrBot 会"。
    因为 WebUI 每次请求都在 `flags` 里**硬编码**带 `enable_inline_genui: true`：

        webui/assets/chatMarkdownComponents-*.js
        function be(t=!0,n=!0){return{enable_inline_genui:!0, ...}}

    `resolve_webchat_request_flags()` 里前端传的布尔值优先级最高，
    于是 `astr_main_agent.py:532` 把一段**英文**系统提示
    `CHATUI_INLINE_GENUI_SYSTEM_PROMPT` 拼进 system prompt：

        When the user asks for an interface / UI ...
        output the runnable HTML inside exactly one `<html-genui>...</html-genui>` block.

    模型于是偶尔不写台词、改吐一整块 `<html-genui title="...">` 的 HTML/CSS/JS，
    WebUI 把它渲染成一张独立窗口的卡片。**Telegram 不走这条链路，所以那边不会出现。**

    和坑 40（future_task 的英文工具说明被当台词念）是同一个病：
    **AstrBot 自带的英文系统提示，混进中文角色扮演的小模型里就出戏。**

改哪里（`.../sources/webchat/request_flags.py`，两处）：
    1. `"enable_inline_genui": True` → `False`（默认值，兜住不传 flags 的调用方）
    2. `resolve_webchat_request_flags()` 的循环里加一行硬判：**只有**把环境变量
       `ASTRBOT_GENUI` 设成 1/true/yes/on 才放行，否则一律 False —— 这一层是为了
       压过前端硬编码的 `true`（只改默认值没用，实测前端永远传 true）。

恢复办法：把 `启动AstrBot.bat` 里的 `set "ASTRBOT_GENUI=0"` 改成 1（改完重启 AstrBot）。

用法：
    python patch_astrbot_genui.py            # 打补丁（幂等）
    python patch_astrbot_genui.py --check    # 只看在不在（退出码：0 在 / 1 不在）
    python patch_astrbot_genui.py --revert   # 还原成 AstrBot 原版
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

from console_utf8 import console_utf8
from safe_write import read_text_raw, write_bytes, write_text

console_utf8()   # GBK 控制台下的兜底，见 console_utf8.py

ROOT = Path(r"C:\LocalAI-Assistant\AstrBot\AstrBot_4.28.1_windows_amd64_portable")
TARGET = ROOT / ("backend/app/astrbot/core/platform/sources/webchat/request_flags.py")
BAT = Path(r"C:\LocalAI-Assistant\启动AstrBot.bat")

MARK = "patch_astrbot_genui.py"

# ---- 第 1 处：默认值 True → False ----
OLD_DEFAULT = '"enable_inline_genui": True,'
NEW_DEFAULT = '"enable_inline_genui": False,  # 补丁：默认关，见 patch_astrbot_genui.py'

# ---- 第 2 处：循环里硬判（压过前端硬编码的 true）----
# ⚠️ 锚点写成 \n；AstrBot 源码是 CRLF，运行时按实际换行符转换（见 patch()）。
#    早先版本忘了这一步，锚点永远匹配不上，补丁静默只做了一半。
ANCHOR = "        resolved[key] = value if isinstance(value, bool) else default"
INSERT = (
    '        if key == "enable_inline_genui" and os.environ.get(\n'
    '            "ASTRBOT_GENUI", "0"\n'
    '        ).strip().lower() not in ("1", "true", "yes", "on"):\n'
    "            # 补丁：WebUI 的内联 HTML 卡片（patch_astrbot_genui.py）\n"
    "            # 前端写死传 true，只改上面的默认值压不住，这里硬判。\n"
    "            resolved[key] = False\n"
    "            continue\n" + ANCHOR
)

IMPORT_ANCHOR = "from typing import Any"
IMPORT_NEW = "import os\n" + IMPORT_ANCHOR


def _has_import_os(text: str) -> bool:
    head = text.split("def ", 1)[0]
    return any(ln.strip() == "import os" for ln in head.splitlines())


def patch(revert: bool = False, check: bool = False) -> int:
    if not TARGET.exists():
        print(f"[X] 找不到 {TARGET}")
        return 1
    text = read_text_raw(TARGET, encoding="utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"      # AstrBot 源码是 CRLF，别重排
    anchor = ANCHOR.replace("\n", nl)
    insert = INSERT.replace("\n", nl)

    ok_default = NEW_DEFAULT in text
    ok_guard = MARK in text          # 硬判那一段的标志注释
    patched = ok_default and ok_guard and _has_import_os(text)

    if check:
        print(f"  文件        : {TARGET}")
        print(f"  默认值关了  : {'[OK] 是' if ok_default else '[X] 否'}")
        print(f"  循环里硬判  : {'[OK] 有' if ok_guard else '[X] 没有'}")
        print(f"  import os   : {'[OK] 在' if _has_import_os(text) else '[X] 不在'}")
        print(f"  结论        : {'[OK] 补丁在位' if patched else '[X] 没打全'}")
        return 0 if patched else 1

    if revert:
        if not (ok_default or ok_guard):
            print("  本来就没打补丁，无需还原")
            return 0
        out = text
        if ok_guard:
            if insert not in out:
                print("[X] 找不到硬判那一段，无法自动还原（可能被手工改过）")
                return 1
            out = out.replace(insert, anchor, 1)
        if NEW_DEFAULT in out:
            out = out.replace(NEW_DEFAULT, OLD_DEFAULT, 1)
        import_new = IMPORT_NEW.replace("\n", nl)
        if import_new in out:
            out = out.replace(import_new, IMPORT_ANCHOR, 1)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(TARGET, TARGET.with_name(f"{TARGET.name}.bak-{stamp}"))
        write_text(TARGET, out, newline="")
        back = read_text_raw(TARGET, encoding="utf-8")
        if MARK in back or NEW_DEFAULT in back or _has_import_os(back):
            print("[X] 还原后仍能看到补丁痕迹，请手工检查")
            return 1
        print("[OK] 已还原成 AstrBot 原版（重启 AstrBot 生效）")
        return 0

    # ---- 打补丁 ----
    if patched:
        print("  补丁已经在位，什么都不用做")
        return 0

    out = text
    if not ok_default:
        if OLD_DEFAULT not in out:
            print(f"[X] 找不到锚点：{OLD_DEFAULT}")
            print("    AstrBot 升级后这行可能变了，先看看这个文件：")
            print(f"    {TARGET}")
            return 1
        out = out.replace(OLD_DEFAULT, NEW_DEFAULT, 1)
        print("  [OK] 默认值 -> False")

    if not ok_guard:
        if anchor not in out:
            print("[X] 找不到 resolve 循环里的赋值锚点，没法插入硬判")
            print(f"    先手工看一眼：{TARGET}")
            return 1
        out = out.replace(anchor, insert, 1)
        print("  [OK] 循环里加了硬判 ASTRBOT_GENUI（默认关）")

    if not _has_import_os(out):
        import_new = IMPORT_NEW.replace("\n", nl)
        if IMPORT_ANCHOR not in out:
            print(f"[X] 找不到 {IMPORT_ANCHOR}，没法补 import os")
            return 1
        out = out.replace(IMPORT_ANCHOR, import_new, 1)
        print("  [OK] 补了 import os")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TARGET, TARGET.with_name(f"{TARGET.name}.bak-{stamp}"))
    print(f"  [OK] 已备份 -> {TARGET.name}.bak-{stamp}")
    write_text(TARGET, out, newline="")          # 保留 AstrBot 源码的 CRLF

    back = read_text_raw(TARGET, encoding="utf-8")
    raw = TARGET.read_bytes()
    crlf = raw.count(b"\r\n")
    lone_lf = raw.count(b"\n") - crlf
    print("\n回读验证:")
    print(f"  默认值已关   : {'[OK]' if NEW_DEFAULT in back else '[X]'}")
    print(f"  硬判已插入   : {'[OK]' if MARK in back else '[X]'}")
    print(f"  import os 在 : {'[OK]' if _has_import_os(back) else '[X]'}")
    print(f"  换行         : CRLF={crlf} 裸LF={lone_lf} {'[OK]' if lone_lf == 0 else '[X] 混了！'}")
    try:
        compile(back, str(TARGET), "exec")
        print("  语法编译     : [OK]")
        ok_compile = True
    except SyntaxError as exc:
        print(f"  语法编译     : [X] {exc}")
        ok_compile = False
    ok = (NEW_DEFAULT in back and MARK in back and _has_import_os(back)
          and lone_lf == 0 and ok_compile)
    return 0 if ok else 1


def patch_bat() -> int:
    """往启动脚本里加 ASTRBOT_GENUI=0（这才是真正的开关）。

    ⚠️ `.bat` 必须是 **GBK + CRLF**（cmd 对 UTF-8 或裸 LF 会吃字符，见坑 5）。
    """
    if not BAT.exists():
        print(f"[!] 找不到 {BAT}，跳过启动脚本（不影响补丁本身）")
        return 0
    raw = BAT.read_bytes()
    if b"ASTRBOT_GENUI" in raw:
        print("  启动脚本里已经有了，跳过")
        return 0
    anchor = 'set "ASTRBOT_CRON_TOOLS=0"'.encode("gbk")
    if anchor not in raw:
        print("[!] 启动脚本里找不到 cron 那行锚点，跳过"
              "（补丁本身仍有效：默认就是关的）")
        return 0
    add = (
        "\r\n"
        "REM 关掉 WebUI 的内联 HTML 卡片：英文 GenUI 提示会让模型吐 HTML 而不写台词。\r\n"
        "REM 由 patch_astrbot_genui.py 写入；改回 1 即可恢复（要重启 AstrBot）。\r\n"
        'set "ASTRBOT_GENUI=0"'
    ).encode("gbk")
    write_bytes(BAT, raw.replace(anchor, anchor + add, 1))
    print("  [OK] 启动脚本加了 ASTRBOT_GENUI=0（GBK + CRLF）")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--check" in args:
        rc = patch(check=True)
        raw = BAT.read_bytes() if BAT.exists() else b""
        print(f"  启动脚本    : {'有 ASTRBOT_GENUI' if b'ASTRBOT_GENUI' in raw else '[X] 没有'}")
        return rc
    if "--revert" in args:
        return patch(revert=True)
    rc = patch()
    if rc == 0:
        patch_bat()
        print("\n[!] 重启 AstrBot 生效")
    return rc


if __name__ == "__main__":
    sys.exit(main())
