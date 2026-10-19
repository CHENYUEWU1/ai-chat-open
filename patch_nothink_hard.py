#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 GGUF 模板里的思考开关**彻底删掉**。

上一版补丁是「默认关闭」：
    {%- if enable_thinking is defined and enable_thinking is true %}
        {{- '<think>\n' }}
    {%- else %}
        {{- '<think>\n\n</think>\n\n' }}
    {%- endif %}

问题是客户端只要传 enable_thinking=true（Cherry Studio 的推理开关就会），
思考还是会被打开，然后被 num_predict 截断 → 表现为"只有思考过程，没有回答"。

这一版直接硬编码空思考块，**结构上不可能开启思考**：
    {{- '<think>\n\n</think>\n\n' }}

等长原地覆盖，不需要重写整个文件。
"""
import shutil
import sys
from pathlib import Path

from gguf import GGUFReader

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

KEY = "tokenizer.chat_template"

OLD = """    {%- if enable_thinking is defined and enable_thinking is true %}
        {{- '<think>\\n' }}
    {%- else %}
        {{- '<think>\\n\\n</think>\\n\\n' }}
    {%- endif %}"""

NEW = """    {{- '<think>\\n\\n</think>\\n\\n' }}"""


def read_field(src: Path) -> bytes:
    r = GGUFReader(str(src), "r")
    return bytes(r.fields[KEY].parts[-1].tobytes())


def find_offset(src: Path, needle: bytes, scan_mb: int = 64) -> int:
    chunk = 1024 * 1024
    limit = scan_mb * chunk
    overlap = len(needle) - 1
    hits = []
    with open(src, "rb") as fh:
        pos = 0
        prev = b""
        while pos < limit:
            buf = fh.read(chunk)
            if not buf:
                break
            data = prev + buf
            start = 0
            while True:
                i = data.find(needle, start)
                if i < 0:
                    break
                hits.append(pos - len(prev) + i)
                start = i + 1
            prev = data[-overlap:] if overlap > 0 else b""
            pos += len(buf)
    if not hits:
        return -1
    return hits[0]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法: python patch_nothink_hard.py <模型.gguf>")
        return 1

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"❌ 找不到: {src}")
        return 1

    raw = read_field(src)
    original = raw.decode("utf-8")
    print(f"文件: {src.name}")
    print(f"模板: {len(raw)} 字节")

    if OLD not in original:
        if NEW.strip() in original:
            print("✅ 已经是硬编码版，无需修改")
            return 0
        print("❌ 未找到目标片段，模板可能不是预期版本")
        print("   含 'enable_thinking':", "enable_thinking" in original)
        return 1

    patched = original.replace(OLD, NEW, 1)
    cur = len(patched.encode("utf-8"))
    pad_needed = len(raw) - cur
    if pad_needed < 0:
        print(f"❌ 修补后变长 {(-pad_needed)} 字节，无法原地覆盖")
        return 1
    if pad_needed:
        patched += "{#" + ("x" * (pad_needed - 4)) + "#}" if pad_needed >= 4 else " " * pad_needed
    while len((patched).encode("utf-8")) > len(raw):
        patched = patched[:-1]
    while len((patched).encode("utf-8")) < len(raw):
        patched += " "
    new_bytes = patched.encode("utf-8")
    if len(new_bytes) != len(raw):
        print(f"❌ 长度不匹配 {len(new_bytes)} != {len(raw)}")
        return 1
    print(f"补齐 {pad_needed} 字节")

    offset = find_offset(src, raw)
    if offset < 0:
        print("❌ 无法定位模板偏移")
        return 1
    print(f"偏移: {offset}")

    bak = src.with_name(src.name + ".nothinkbak")
    if not bak.exists():
        print(f"备份 → {bak.name}")
        shutil.copy2(src, bak)

    with open(src, "r+b") as fh:
        fh.seek(offset)
        if fh.read(len(raw)) != raw:
            print("❌ 偏移处内容不符，中止")
            return 1
        fh.seek(offset)
        fh.write(new_bytes)
    print("✅ 原地覆盖完成")

    back = read_field(src).decode("utf-8")
    ok1 = "enable_thinking is defined" not in back
    ok2 = "<think>\\n\\n</think>\\n\\n" in back
    ok3 = len(read_field(src)) == len(raw)
    print("\n回读验证:")
    print(f"  思考开关已彻底移除 : {'✅' if ok1 else '❌'}")
    print(f"  硬编码空思考块     : {'✅' if ok2 else '❌'}")
    print(f"  长度一致           : {'✅' if ok3 else '❌'}")
    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    sys.exit(main())
