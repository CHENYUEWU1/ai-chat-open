#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a reviewable ZIP from tracked, public package files.

Private persona text, generated full-content bundles, backups, chat files and
untracked local material are excluded even when present in the working tree.
"""
import os
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

def find_project_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "启动AstrBot.bat").is_file():
            return parent
    raise RuntimeError("找不到项目根目录标记：启动AstrBot.bat")


ROOT = find_project_root(Path(__file__).resolve().parent)
PKG = ROOT / "交付包"
ZIP = ROOT / "小九-AI助手-交付包.zip"
TOP = "小九-AI助手-交付包"          # zip 里的顶层目录名

EXCLUDE_DIRS = {"__pycache__", "personas", "_源文件", "_备份", "聊天文件", "不要看"}


def is_public_package_file(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if rel.name.startswith("单文件版-"):
        return False
    if rel.suffix.lower() in {".pyc", ".log", ".db", ".jsonl"}:
        return False
    return True


def collect() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "交付包"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("无法读取 Git 跟踪文件；为避免打入本机私有文件，已停止打包")

    out = []
    for raw in result.stdout.decode("utf-8").split("\0"):
        if not raw:
            continue
        tracked = Path(raw.replace("/", os.sep))
        try:
            rel = tracked.relative_to(Path("交付包"))
        except ValueError:
            continue
        source = PKG / rel
        if source.is_file() and not source.is_symlink() and is_public_package_file(rel):
            out.append(rel)
    return sorted(out)


def zip_entries(path: Path) -> dict[str, tuple[int, int]]:
    """返回 zip 里的 {相对路径: (大小, CRC32)}，相对 TOP 目录。

    ⚠️ 2026-09-29：原来只返回大小。**同字节数的改动会被判"一致"** ——
        比如把一个汉字换成另一个、把版本号 30 改成 40，zip 里还是旧内容，
        而校验显示 [OK]。`ZipInfo` 本来就带 CRC32，用它才真的比内容。
    """
    out = {}
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            if i.is_dir():
                continue
            n = i.filename.replace("\\", "/")
            if n.startswith(TOP + "/"):
                n = n[len(TOP) + 1:]
            out[n] = (i.file_size, i.CRC)
    return out


def check() -> int:
    if not ZIP.exists():
        print(f"[X] 还没有 {ZIP.name}，跑一次不带 --check 的")
        return 1
    files = collect()
    disk = {}
    for r in files:
        p = PKG / r
        raw = p.read_bytes()
        disk[str(r).replace("\\", "/")] = (p.stat().st_size, zlib.crc32(raw) & 0xFFFFFFFF)
    z = zip_entries(ZIP)
    only_disk = sorted(set(disk) - set(z))
    only_zip = sorted(set(z) - set(disk))
    differs = sorted(k for k in set(disk) & set(z) if disk[k] != z[k])

    if not (only_disk or only_zip or differs):
        print(f"[OK] zip 与 交付包\\ 一致（{len(disk)} 个文件，逐 CRC 比对）")
        return 0

    print(f"[!] zip 与 交付包\\ 不一致：")
    for k in only_disk:
        print(f"      目录里有、zip 没有 : {k}")
    for k in only_zip:
        print(f"      zip 里有、目录没有 : {k}")
    for k in differs:
        same_size = disk[k][0] == z[k][0]
        why = "大小相同但**内容不同**" if same_size else f"zip={z[k][0]}  磁盘={disk[k][0]}"
        print(f"      内容不同           : {k}  ({why})")
    print("\n跑 `python build_package_zip.py` 重建")
    return 1


def build() -> int:
    if not PKG.is_dir():
        print(f"[X] 找不到 {PKG}")
        return 1
    files = collect()
    # ⚠️ 2026-09-29 改：写临时文件再原子替换。
    #    原来是 `ZIP.unlink()` 然后原地重建 —— 写到一半失败（磁盘满/被杀）
    #    会**连上一版 zip 一起丢掉**，而那是唯一的快照。
    tmp = ZIP.with_name(ZIP.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in files:
                z.write(PKG / rel, f"{TOP}/{rel}".replace("\\", "/"))
        os.replace(tmp, ZIP)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    size = ZIP.stat().st_size
    print(f"[OK] 已重建 {ZIP.name}")
    print(f"     {len(files)} 个文件 / {size/1024:.1f} KB")
    hidden = [str(r) for r in PKG.rglob("*")
              if r.is_file() and any(p in EXCLUDE_DIRS for p in r.parts)]
    if hidden:
        print(f"     已排除 {len(hidden)} 个 __pycache__ 文件")
    return 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv[1:] else build())
