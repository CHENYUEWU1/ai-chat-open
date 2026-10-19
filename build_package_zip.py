#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
把 交付包\ 目录重建成 `助手-AI助手-交付包.zip`（纯文档快照）。

为什么要脚本：
    以前这个 zip 是手工压的，压完忘了重压，它就和 交付包\ 目录悄悄不一致了
    （实测过一次：zip 里的文档还是旧的，目录里的已经是新的）。
    这个脚本保证 zip 永远 == 交付包\ 目录。

会排除：
    __pycache__/      运行脚本产生的字节码（不该进包）
    这个 zip 自己

⚠️ 一个**故意的不一致**（别去"修"它）：
    `README.md` 在两处内容不同，是**设计如此** ——
      项目根 `C:\LocalAI-Assistant\README.md`      = 给项目本人的总入口
      交付包 `交付包\README.md`          = 给"拿到 zip 的人"的入口（精简版）
    所以本脚本**不**动 README.md，`organize_package.py` 也**不**镜像它。

⚠️ 文档主副本的方向（2026-09-22 改过，别按旧印象来）：
    **主副本 = `交付包\` 里那份**，项目根的同名文件是**快照**。
    `使用说明.md` / `本地AI部署方案.md` / `人格写作模板.md` / `给AI的完整说明书.md`
    这四份由 `organize_package.py` 从包内同步到项目根，并有 `--check` 逐字节校验。
    （更早的版本说"主副本在根目录"，实测就是这么漂的 ——
     包内的说明书更新到"文档分栏"后，根目录那份还停在分栏之前。
     这正是坑 23 / 坑 24 那个病：**没人校验的副本一定会漂**。）
    → 改这几份文档**改 `交付包\` 里那份**，然后跑 `python organize_package.py`。

用法：
    python build_package_zip.py            # 重建
    python build_package_zip.py --check    # 只对比 zip 和目录，不重建
"""
import os
import sys
import zipfile
import zlib
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # GBK 控制台下打印 ✅/❌ 会崩，见 console_utf8.py

PKG = Path(r"C:\LocalAI-Assistant\交付包")
ZIP = Path(r"C:\LocalAI-Assistant\助手-AI助手-交付包.zip")
TOP = "助手-AI助手-交付包"          # zip 里的顶层目录名

EXCLUDE_DIRS = {"__pycache__"}


def collect() -> list[Path]:
    out = []
    for p in sorted(PKG.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(PKG)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if rel.suffix == ".pyc":
            continue
        out.append(rel)
    return out


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
