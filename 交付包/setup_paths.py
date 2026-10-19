#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交付包路径批量替换工具。

把包里所有写死的 `E:\\本地ai` 改成新的安装路径。

关键点：包里三种编码混用，必须按扩展名用对应编码读写，否则会把文件写坏：
    .bat        → GBK (cp936)          中文 Windows 的 cmd 只认这个
    .ps1        → UTF-8 with BOM       PowerShell 5.1 靠 BOM 识别 UTF-8
    其它文本    → UTF-8 without BOM

用法：
    python setup_paths.py                 # 交互式，会提示输入新路径
    python setup_paths.py D:\\ai           # 直接指定
    python setup_paths.py D:\\ai --dry-run # 只预览，不修改
"""
import codecs
import os
import sys
from pathlib import Path

# 包里写死的原始路径（要替换的目标）
OLD_BASES = [
    r"E:\本地ai",
    "E:/本地ai",
    "E:\\\\本地ai",
]

# 要处理的文本文件扩展名
EXTS = {".py", ".md", ".txt", ".bat", ".ps1", ".jinja", ".json", ".yaml", ".yml"}

# 单个文件最大处理大小（跳过二进制/模型）
MAX_SIZE = 8 * 1024 * 1024

PKG = Path(__file__).resolve().parent


def detect_encoding(path: Path):
    """返回 (编码名, 是否带BOM)。按扩展名判定，这是本包的实际约定。"""
    ext = path.suffix.lower()
    if ext == ".bat":
        return "gbk", False
    if ext == ".ps1":
        raw = path.read_bytes()[:3]
        if raw == codecs.BOM_UTF8:
            return "utf-8", True
        return "gbk", False          # 无 BOM 的 ps1 按系统 ANSI 读
    return "utf-8", False


def read_text(path: Path):
    enc, bom = detect_encoding(path)
    raw = path.read_bytes()
    body = raw[len(codecs.BOM_UTF8):] if bom else raw
    return body.decode(enc), enc, bom


def write_text(path: Path, text: str, enc: str, bom: bool):
    body = text.encode(enc)
    path.write_bytes((codecs.BOM_UTF8 + body) if bom else body)


def collect_files(root: Path):
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in EXTS:
            continue
        try:
            if p.stat().st_size > MAX_SIZE:
                continue
        except OSError:
            continue
        # 跳过自己
        if p.resolve() == Path(__file__).resolve():
            continue
        out.append(p)
    return sorted(out)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv

    print("=" * 62)
    print("  交付包 · 路径批量替换")
    print("=" * 62)
    print(f"\n包目录: {PKG}")

    if args:
        new_base = args[0].rstrip("\\/")
    else:
        print(f"\n当前写死的路径是: E:\\本地ai")
        print("如果你的安装目录不同，请输入新路径（直接回车 = 保持不变）：")
        new_base = input("> ").strip().rstrip("\\/")

    if not new_base:
        print("\n未修改（路径保持不变）。")
        return 0

    if new_base.lower() == r"e:\本地ai".lower():
        print("\n新路径与原来相同，无需修改。")
        return 0

    print(f"\n将把  E:\\本地ai  替换为  {new_base}")
    if dry:
        print("【预览模式】不会真的修改文件\n")
    else:
        print("", flush=True)
        if input("确认？(y/N) ").strip().lower() not in ("y", "yes"):
            print("已取消。")
            return 0
        print()

    files = collect_files(PKG)
    print(f"扫描到 {len(files)} 个文本文件\n")

    changed = 0
    skipped = 0
    for f in files:
        try:
            text, enc, bom = read_text(f)
        except Exception as e:
            print(f"  ⚠️ 跳过 {f.relative_to(PKG)}: 读取失败 {e}")
            skipped += 1
            continue

        orig = text
        for old in OLD_BASES:
            text = text.replace(old, new_base)

        if text == orig:
            continue

        n = sum(orig.count(o) for o in OLD_BASES)
        rel = f.relative_to(PKG)
        if dry:
            print(f"  [预览] {rel}  ({n} 处)")
        else:
            write_text(f, text, enc, bom)
            print(f"  ✅ {rel}  ({n} 处)")
        changed += 1

    print(f"\n{'预览' if dry else '修改'}完成：{changed} 个文件有改动"
          + (f"，{skipped} 个跳过" if skipped else ""))

    # 校验：还有没有残留
    if not dry:
        print("\n=== 校验：是否还有残留的旧路径 ===")
        left = []
        for f in files:
            try:
                text, _, _ = read_text(f)
            except Exception:
                continue
            for old in OLD_BASES:
                if old in text:
                    left.append((f.relative_to(PKG), old))
                    break
        if left:
            print("  ❌ 仍有残留：")
            for rel, old in left[:20]:
                print(f"     {rel}  含 {old}")
        else:
            print("  ✅ 无残留，全部替换干净")

    print("\n提示：脚本里的路径都已更新。")
    print("      接下来按 03-文件与脚本说明.md 的重建顺序执行即可。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(1)
