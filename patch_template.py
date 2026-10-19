#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原地修补 GGUF 的 chat template（不重写 2.5 GB 文件）。

两处修改：
 1. 允许多条 system 消息 —— SillyTavern 会发一大串，原模板直接 raise_exception
 2. 默认关闭思考模式 —— 只有显式 enable_thinking=true 时才思考

原理：GGUF 字符串是「uint64 长度 + 字节」。只要新串与原串**字节数完全相同**，
就能定位原偏移原地覆盖，后面的张量数据一个字节都不用动。
不足的长度用 Jinja 注释补齐（注释不产生任何输出）。
"""
import shutil
import sys
from pathlib import Path

from gguf import GGUFReader

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\LocalAI-Assistant\downloads\Qwen3.5-9B-Uncensored-Q4_K_M.gguf"
)
KEY = "tokenizer.chat_template"

OLD_SYSTEM = """    {%- if message.role == "system" %}
        {%- if not loop.first %}
            {{- raise_exception('System message must be at the beginning.') }}
        {%- endif %}"""

NEW_SYSTEM = """    {%- if message.role == "system" %}
        {{- '<|im_start|>system\\n' + content + '<|im_end|>\\n' }}"""

OLD_THINK = """    {%- if enable_thinking is defined and enable_thinking is false %}
        {{- '<think>\\n\\n</think>\\n\\n' }}
    {%- else %}
        {{- '<think>\\n' }}
    {%- endif %}"""

NEW_THINK = """    {%- if enable_thinking is defined and enable_thinking is true %}
        {{- '<think>\\n' }}
    {%- else %}
        {{- '<think>\\n\\n</think>\\n\\n' }}
    {%- endif %}"""


def read_field_bytes() -> bytes:
    """取模板原始字节。parts[-1] 是内容，parts[0] 是 uint64 长度。"""
    r = GGUFReader(str(SRC), "r")
    f = r.fields[KEY]
    return bytes(f.parts[-1].tobytes())


def find_offset(needle: bytes, scan_mb: int = 64) -> int:
    """在文件开头若干 MB 内定位模板字节，并确认唯一。"""
    chunk_size = 1024 * 1024
    limit = scan_mb * chunk_size
    overlap = len(needle) - 1
    hits = []
    with open(SRC, "rb") as fh:
        pos = 0
        prev = b""
        while pos < limit:
            buf = fh.read(chunk_size)
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
    if len(hits) != 1:
        print(f"⚠️ 匹配到 {len(hits)} 处")
        if not hits:
            return -1
    return hits[0]


def main() -> int:
    raw = read_field_bytes()
    original = raw.decode("utf-8")
    print(f"原模板: {len(raw)} 字节")

    offset = find_offset(raw)
    if offset < 0:
        print("❌ 无法在文件头部定位模板")
        return 1
    print(f"✅ 定位到文件偏移: {offset} (0x{offset:x})")

    patched = original
    for name, old, new in (
        ("允许多条 system 消息", OLD_SYSTEM, NEW_SYSTEM),
        ("默认关闭思考模式", OLD_THINK, NEW_THINK),
    ):
        if old not in patched:
            print(f"❌ 未匹配到: {name}")
            return 1
        patched = patched.replace(old, new, 1)
        print(f"✅ 已修补: {name}")

    cur = len(patched.encode("utf-8"))
    print(f"   修补后: {cur} 字节 (原 {len(raw)})")

    if cur > len(raw):
        print(f"❌ 修补后变长 {cur - len(raw)} 字节，无法原地覆盖")
        return 1

    pad_needed = len(raw) - cur
    if pad_needed:
        if pad_needed < 4:
            patched += " " * pad_needed
        else:
            patched += "{#" + ("x" * (pad_needed - 4)) + "#}"
        print(f"   补齐 {pad_needed} 字节")

    new_bytes = patched.encode("utf-8")
    if len(new_bytes) != len(raw):
        print(f"❌ 长度仍不匹配: {len(new_bytes)} != {len(raw)}")
        return 1

    bak = SRC.with_name(SRC.name + ".templatebak")
    if not bak.exists():
        print(f"备份原文件 → {bak.name} (2.5 GB，稍等) ...")
        shutil.copy2(SRC, bak)
        print("   备份完成")

    with open(SRC, "r+b") as fh:
        fh.seek(offset)
        if fh.read(len(raw)) != raw:
            print("❌ 偏移处内容不符，中止以免写坏文件")
            return 1
        print("✅ 偏移校验通过，原地覆盖")
        fh.seek(offset)
        fh.write(new_bytes)

    back = read_field_bytes().decode("utf-8")
    ok1 = "System message must be at the beginning" not in back
    ok2 = "enable_thinking is defined and enable_thinking is true" in back
    ok3 = len(read_field_bytes()) == len(raw)
    print("\n回读验证:")
    print(f"  多 system 消息已放行 : {'✅' if ok1 else '❌'}")
    print(f"  默认关闭思考模式     : {'✅' if ok2 else '❌'}")
    print(f"  长度仍一致           : {'✅' if ok3 else '❌'}")
    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    sys.exit(main())
