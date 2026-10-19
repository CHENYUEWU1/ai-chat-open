#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取 GGUF 的 chat template，另存出来供修改。"""
import sys
from pathlib import Path
from gguf import GGUFReader

from console_utf8 import console_utf8
from safe_write import write_bytes, write_text

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\LocalAI-Assistant\downloads\Qwen3.5-9B-Uncensored-Q4_K_M.gguf"
)
OUT = Path(r"C:\LocalAI-Assistant\template_original.jinja")

KEY = "tokenizer.chat_template"


def main() -> int:
    print(f"读取: {SRC}  ({SRC.stat().st_size/1024**3:.2f} GB)")
    r = GGUFReader(str(SRC), "r")

    field = r.fields.get(KEY)
    if field is None:
        print(f"❌ 未找到 '{KEY}'")
        print("可用的 tokenizer.* 字段:")
        for k in r.fields:
            if k.startswith("tokenizer."):
                print("   ", k)
        return 1

    # 字符串字段：parts 是字节，最后一个是长度
    raw = field.parts[-1]
    if isinstance(raw, (bytes, bytearray)):
        text = bytes(raw).decode("utf-8", errors="replace")
    else:
        # numpy 数组
        text = bytes(raw.tobytes()).decode("utf-8", errors="replace")

    # 去掉末尾的长度字节残留（gguf 把长度放在最后一个 part）
    text = text.rstrip("\x00")

    write_text(OUT, text)
    print(f"✅ 已导出模板: {OUT}  ({len(text)} 字符)")
    print(f"   字段类型: {field.types}")
    print(f"   换行数: {text.count(chr(10))}")

    # 打印关键片段
    for marker in [
        "System message must be at the beginning",
        "enable_thinking",
    ]:
        idx = text.find(marker)
        print(f"\n--- 定位 '{marker}' @ {idx} ---")
        if idx >= 0:
            print(text[max(0, idx - 260): idx + 200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
