#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 personas/ 目录下的人格文件应用到 Cherry Studio 的助手「助手」。

用法：
    python apply_persona.py 病娇-助手-露骨   # 不加 .txt
    python apply_persona.py --list           # 列出可用人格
    python apply_persona.py --current        # 显示当前人格

注意：需要先完全关闭 Cherry Studio，否则改动会被覆盖。
"""
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(r"C:\LocalAI-Assistant\CherryStudio\data\Data\cherrystudio.sqlite")
PDIR = Path(r"C:\LocalAI-Assistant\personas")


def list_personas():
    files = sorted(PDIR.glob("*.txt"))
    print("可用人格：")
    for f in files:
        n = len(f.read_text(encoding="utf-8"))
        print(f"  - {f.stem:20} ({n} 字符)")
    return files


def show_current():
    if not DB.exists():
        print("❌ 数据库不存在")
        return 1
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for r in db.execute("SELECT name, model_id, settings, prompt FROM assistant"):
        s = json.loads(r[2] or "{}")
        print(f"助手   : {r[0]}")
        print(f"模型   : {r[1]}")
        print(f"联网   : {s.get('enableWebSearch')}")
        print(f"提示词 : {len(r[3] or '')} 字符")
        print(f"--- 提示词内容 ---\n{r[3]}")
    db.close()
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        list_personas()
        return 0
    if args[0] == "--list":
        list_personas()
        return 0
    if args[0] == "--current":
        return show_current()

    name = args[0]
    if name.endswith(".txt"):
        name = name[:-4]
    pf = PDIR / f"{name}.txt"
    if not pf.exists():
        print(f"❌ 找不到人格文件: {pf}")
        list_personas()
        return 1

    prompt = pf.read_text(encoding="utf-8").rstrip() + "\n"
    print(f"人格文件: {pf.name}  ({len(prompt)} 字符)")
    print("--- 前 3 行 ---")
    for line in prompt.splitlines()[:3]:
        print(f"  {line}")

    if not DB.exists():
        print(f"❌ 数据库不存在: {DB}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = DB.with_name(f"cherrystudio.sqlite.bak-{stamp}")
    shutil.copy2(DB, bak)
    print(f"\n已备份 → {bak.name}")

    db = sqlite3.connect(str(DB))
    c = db.cursor()
    c.execute("UPDATE assistant SET prompt = ?", (prompt,))
    n = c.rowcount
    db.commit()

    print(f"\n=== 回读 ===")
    for r in c.execute("SELECT name, model_id, length(prompt), substr(prompt,1,40) FROM assistant"):
        print(f"  「{r[0]}」 模型={r[1]}  提示词={r[2]} 字符")
        print(f"    开头: {r[3]}...")
    db.close()
    print(f"\n✅ 已应用「{name}」到 {n} 个助手")
    print("⚠️ 重启 Cherry Studio 才生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
