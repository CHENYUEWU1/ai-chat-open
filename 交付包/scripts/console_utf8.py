#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让脚本在中文 Windows 的 GBK 控制台下也不会因为打印符号而崩。

为什么需要这个：
    本机代码页是 936（GBK）。脚本里打印 ✅ ❌ ⭐ ★ ⚠️ 这类符号时，
    print() 会抛 UnicodeEncodeError。裸脚本会**直接中断**，
    而且中断位置通常在 else/except 分支里，表现成
    「测试失败」或「日志刷一半就没了」—— 看着像模型/插件坏了，
    其实是打印崩的。实测：
        python test_tools.py
        → 第 1 个用例就 UnicodeEncodeError 崩掉，什么都没测出来。

解法：
    把 stdout/stderr 的错误处理降级成 "?" 而不是让脚本挂掉。
    只改错误策略，**不改编码** —— 控制台能显示什么由系统决定。

用法：在脚本 import 之后调用一次。
    from console_utf8 import console_utf8
    console_utf8()
"""
import sys


def console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


# 允许 `import console_utf8` 之后直接当函数用，省得每个脚本写两行
__all__ = ["console_utf8"]
