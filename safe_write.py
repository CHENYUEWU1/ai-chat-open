#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""原子写文件 + 行尾写死 LF —— 这个项目里所有"写文件"的地方都该用它。

为什么需要（两个都是踩过的坑）：

1. **非原子写**：`Path.write_text()` 直接截断原文件再写。
   写到一半（Ctrl-C、断电、磁盘满、编码异常）就留下**半截文件**。
   受害最重的是 `cmd_config.json` —— 它是 AstrBot 全部 provider / 平台 / 插件的
   唯一配置，半写就等于整个部署废掉；旁边那 100 多个 `.bak-*` 是唯一退路。

2. **行尾没写死**（坑 39）：Windows 上 `write_text(s)` 会把 `\n` 翻译成 `\r\n`，
   而本仓库约定 `.md` / `.py` 一律 **LF**（见 `.gitattributes`）。
   不写死 `newline="\n"` 就会造出"整文件全改"的假 diff，
   把真实改动淹掉 —— 仓库已经专门为这件事修过一次。

用法：
    from safe_write import write_text, write_bytes
    write_text(path, text)              # 原子 + LF
    write_bytes(path, raw)              # 原子 + 原样
    write_text(path, text, newline="")  # 需要保留原行尾时（例如改第三方文件）

⚠️ 临时文件写在**同一个目录**（不是 %TEMP%）—— 跨盘 `os.replace` 不是原子的。
"""
import os
from pathlib import Path


def read_text_raw(path, encoding: str = "utf-8") -> str:
    r"""读文本，**不做 universal-newlines 转换** —— 读出来什么样，写回去就什么样。

    为什么必须有这个（2026-09-29 踩过）：
        `Path.read_text()` 会把 `\r\n` **读成** `\n`。改第三方文件时，
        结果就是"读进来是 LF、写回去也是 LF"，把人家整份文件的 CRLF 重排掉，
        制造"整文件全改"的假 diff —— 正是坑 39 那个病，只不过这次犯在读侧。
        ⚠️ `Path.read_text()` **没有** `newline` 参数（只有 `write_text` 有），
        所以要控制行尾必须用 `open(..., newline="")`。

    配套：写的时候用 `write_text(..., newline="")`（也是不做翻译）。
    """
    with open(path, "r", encoding=encoding, newline="") as fh:
        return fh.read()


def nl_of(text: str) -> str:
    r"""探测这段文本用的是哪种换行符 —— 返回 `"\r\n"` 或 `"\n"`。

    为什么要有这个（2026-09-29 踩过）：
        补丁脚本里的锚点都是**在脚本里写死的多行字符串**（LF），
        而 AstrBot 源码是 **CRLF**。用 `read_text_raw` 读进来之后 CRLF 保留着，
        于是 `"多行锚点" in text` **永远为假** ——
        表现是"补丁明明在文件里，`--check` 却说没打"（假红），
        或者"只改了默认值、后半段静默没插进去"（假绿，见 patch_astrbot_genui.py）。

    ⚠️ `read_text()` 时代看不出这个问题，因为它把 `\r\n` 归一成了 `\n`；
        换成 `read_text_raw` 之后就暴露了。别再用"读侧归一"来迁就锚点 ——
        那样写回去就把人家整份文件的行尾重排了（坑 39）。
    """
    return "\r\n" if "\r\n" in text else "\n"


def with_nl(block: str, nl: str) -> str:
    r"""把锚点块里的 `\n` 换成目标文件的换行符。

    用法（先读原文，再按原文的换行符构造锚点）：
        text = read_text_raw(SRC)
        nl = nl_of(text)
        NEW = with_nl(_NEW_LF, nl)
        if _NEW_LF in ...      # 判断/替换都用转换后的那份
    """
    return block.replace("\n", nl)


def write_bytes(path, data: bytes) -> None:
    """原子写字节。失败时原文件保持不变，临时文件被清掉。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)          # 同目录 → 原子
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def write_text(path, text: str, encoding: str = "utf-8", newline: str = "\n") -> None:
    """原子写文本。

    `newline="\n"`（默认）＝**写出去的就是 LF**，跟仓库约定一致。
    要保留平台默认行尾（改第三方源码时可能需要）就传 `newline=""` ——
    那表示"不做任何翻译"，写什么就是什么。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding=encoding, newline=newline) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
