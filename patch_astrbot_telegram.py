#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
给 AstrBot 的 Telegram 适配器打补丁：**单独走代理 + 放宽 PTB 超时**。

问题史（两段，第二段是 2026-09-23 查出来的）：
    【第一段】Telegram 适配器一直 `telegram.error.TimedOut`，`getMe` 就连不上，
    机器人永远收不到消息。但同一个 token 用 httpx 直连只要 0.9 秒。
    按 AstrBot 的方式处理环境变量（清掉 http_proxy、设 no_proxy）之后，
    python-telegram-bot 的 HTTPXRequest 直连就会超时；给它一个代理立刻正常。
    → v1 补丁：读 `telegram_proxy`，只让 Telegram 走它。

    【第二段】2026-09-23：**v1 仍然会"完全没反应"**。实测证据链：
      - Telegram 服务器上堆着 3 条没被取走的更新，`getWebhookInfo.pending_update_count = 3`
      - 日志里 `Telegram polling crashed with exception: TimedOut`，重试后只打了
        「Telegram Platform Adapter is running.」—— 而**这行不代表真的在收**：
        PTB 的 `start_polling()` 是**非阻塞**的，起完立刻返回
      - 采样 12 秒，**AstrBot 的 python 进程一条到代理的连接都没有**（只有浏览器有）
      - 但日志里**没有任何** "Telegram polling request failed" 错误
      → 结论：轮询根本没跑起来，而它对外的表现是"一切正常"。

    根因：**PTB 默认 connect/read/write 全是 5 秒**，而走这个代理握手本身要 2.7–7 秒
    （实测 `getMe` 花了 7 秒）。5 秒的窗口装不下，于是随机 TimedOut；
    v1 只补了代理，**没补超时**。
    → v2 补丁：显式构造 `HTTPXRequest`，把超时放宽到 20/30 秒，并设到
      `request` 和 `get_updates_request` 两处。

⚠️ 改的是 AstrBot 源码，**升级/重装后会丢，要重跑。**

用法：
    python patch_astrbot_telegram.py            # 打补丁 / 从 v1 升级到 v2
    python patch_astrbot_telegram.py --check    # 看状态（含版本）
    python patch_astrbot_telegram.py --revert   # 还原成 AstrBot 原版
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

from console_utf8 import console_utf8
from safe_write import nl_of, read_text_raw, with_nl, write_bytes, write_text

console_utf8()   # GBK 控制台下的兜底，见 console_utf8.py

SRC = Path(
    r"C:\LocalAI-Assistant\AstrBot\AstrBot_4.28.1_windows_amd64_portable"
    r"\backend\app\astrbot\core\platform\sources\telegram\tg_adapter.py"
)

# AstrBot 原版
OLD = '''    def _build_application(self) -> None:
        self.application = (
            ApplicationBuilder()
            .token(self.config["telegram_token"])
            .base_url(self.base_url)
            .base_file_url(self.file_base_url)
            .build()
        )'''

# v1（只加代理，没加超时）—— 保留它才能把已经打过 v1 的机器升级上来
NEW_V1 = '''    def _build_application(self) -> None:
        # ---- 补丁：Telegram 可以单独走代理 ----
        # PTB 默认连接超时只有 5 秒，直连 api.telegram.org 被限速时会一直
        # telegram.error.TimedOut，机器人收不到任何消息。
        # 读平台配置的 telegram_proxy，有值就只让 Telegram 走它，
        # 不动全局 http_proxy（联网搜索仍直连）。
        _builder = (
            ApplicationBuilder()
            .token(self.config["telegram_token"])
            .base_url(self.base_url)
            .base_file_url(self.file_base_url)
        )
        _proxy = str(self.config.get("telegram_proxy") or "").strip()
        if _proxy:
            _builder = _builder.proxy(_proxy).get_updates_proxy(_proxy)
            logger.info(f"Telegram 走代理: {_proxy}")
        else:
            logger.info("Telegram 未配置代理，直连 api.telegram.org")
        self.application = _builder.build()'''

# v2（代理 + 放宽超时）
NEW_V2 = '''    def _build_application(self) -> None:
        # ---- 补丁 v2：Telegram 单独走代理 + 放宽超时 ----
        # ⚠️ v1 只补了代理，**没补超时**，所以仍然会"完全没反应"：
        #    PTB 默认 connect/read/write 全是 5 秒，而走代理握手要 2.7–7 秒
        #    （实测 getMe 花了 7 秒）。5 秒装不下 → 随机 TimedOut →
        #    start_polling() 立刻返回、日志照样打 "Adapter is running"，
        #    但**一个 getUpdates 都没发出去**，消息全堆在 Telegram 服务器上。
        #    实证判据：连代理端口的进程里**只有浏览器**、没有 AstrBot 的 python。
        from telegram.request import HTTPXRequest

        _timeouts = dict(
            connect_timeout=20.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=20.0,
        )
        _proxy = str(self.config.get("telegram_proxy") or "").strip()
        # 两个 request 必须**分开建**（PTB 不建议共用：连接池和长轮询的
        # read_timeout 要求不一样）。
        if _proxy:
            _req = HTTPXRequest(proxy=_proxy, **_timeouts)
            _upd_req = HTTPXRequest(proxy=_proxy, **_timeouts)
            logger.info(
                f"Telegram 走代理: {_proxy}"
                f"（超时 connect={_timeouts['connect_timeout']:.0f}s"
                f" read={_timeouts['read_timeout']:.0f}s）"
            )
        else:
            _req = HTTPXRequest(**_timeouts)
            _upd_req = HTTPXRequest(**_timeouts)
            logger.info("Telegram 未配置代理，直连 api.telegram.org")
        _builder = (
            ApplicationBuilder()
            .token(self.config["telegram_token"])
            .base_url(self.base_url)
            .base_file_url(self.file_base_url)
            .request(_req)
            .get_updates_request(_upd_req)
        )
        self.application = _builder.build()'''

MARK_V1 = "补丁：Telegram 可以单独走代理"
MARK_V2 = "补丁 v2：Telegram 单独走代理 + 放宽超时"


def main() -> int:
    args = sys.argv[1:]
    if not SRC.exists():
        print(f"[X] 找不到 {SRC}")
        return 1
    text = read_text_raw(SRC, encoding="utf-8")
    # ⚠️ 按文件自己的换行符构造锚点：AstrBot 源码是 CRLF，
    #    read_text_raw 不做归一化，LF 锚点会永远匹配不上（2026-09-29 踩过）。
    nl = nl_of(text)
    OLD_ = with_nl(OLD, nl)
    NEW_V1_ = with_nl(NEW_V1, nl)
    NEW_V2_ = with_nl(NEW_V2, nl)
    # ⚠️ 2026-09-29：判据同时看**注释**和**真正的代码块**（见 patch_astrbot_time 的同类说明）。
    #    另外补上脚本自己反复强调的三样实质特征 —— 光有注释不代表真的在走代理。
    has_v2 = (MARK_V2 in text) and (NEW_V2_ in text)
    has_v1 = (MARK_V1 in text or NEW_V1_ in text) and not has_v2
    # v2 的实质特征（脚本 docstring 里点名过：这里靠"注释"判是自相矛盾的）
    real_v2 = ("telegram_proxy" in text) and ("HTTPXRequest" in text) \
        and (".get_updates_request(" in text)

    if "--check" in args:
        print(f"  文件: {SRC}")
        if has_v2 and real_v2:
            print("  状态: 已打补丁 **v2**（代理 + 超时 20/30 秒）")
        elif has_v2 and not real_v2:
            print("  状态: [X] 有 v2 的注释，但**代理/超时的代码不在** —— 半坏状态，重打一次")
        elif has_v1:
            print("  状态: 已打补丁 v1（**只加了代理，没加超时** —— 会'没反应'）")
            print("        修法：python patch_astrbot_telegram.py（会就地升级到 v2）")
        else:
            print("  状态: 未打补丁（AstrBot 原版）")
        # ⚠️ 2026-09-29：原来无条件 `return 0` —— v1/未打/半坏都算成功，
        #    而 check_all 只认退出码 ⇒ 代理补丁被冲掉也全绿。现在只有"完整 v2"才算通过。
        return 0 if (has_v2 and real_v2) else 1

    if "--revert" in args:
        if not (has_v1 or has_v2):
            print("  本来就没打，无需还原")
            return 0
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(SRC, SRC.with_name(f"{SRC.name}.bak-{stamp}"))
        out = text
        if has_v2:
            out = out.replace(NEW_V2_, OLD_, 1)
        if MARK_V1 in out or NEW_V1_ in out:
            out = out.replace(NEW_V1_, OLD_, 1)
        write_text(SRC, out, newline="")
        print("[OK] 已还原成 AstrBot 原版（重启 AstrBot 生效）")
        return 0

    if has_v2:
        print("[OK] 已经是 v2 了，不用再打")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = SRC.with_name(f"{SRC.name}.bak-{stamp}")
    shutil.copy2(SRC, bak)
    print(f"[OK] 已备份 -> {bak.name}")

    if has_v1:
        write_text(SRC, text.replace(NEW_V1_, NEW_V2_, 1), newline="")
        print("[OK] 已从 v1 升级到 v2（补上了 20/30 秒超时）")
    else:
        if OLD_ not in text:
            print("[X] 源码里找不到要替换的那段 —— AstrBot 版本可能变了。")
            print("    请手动找 `_build_application` 并加上代理 + HTTPXRequest 超时。")
            return 1
        write_text(SRC, text.replace(OLD_, NEW_V2_, 1), newline="")
        print("[OK] 已打补丁 v2")

    print("\n[!] 必须重启 AstrBot 才生效；AstrBot 升级后补丁会丢，重跑本脚本")
    print("[!] 重启后**必须验证真的在收消息**（光看日志不算）：")
    print("      curl -x http://127.0.0.1:7897 "
          "'https://api.telegram.org/bot<token>/getWebhookInfo'")
    print("      pending_update_count 应该变成 0；还是 >0 就是没在收。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
