#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开启助手「助手」的联网搜索，并确认搜索源可用。"""
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(r"C:\LocalAI-Assistant\CherryStudio\data\Data\cherrystudio.sqlite")


def main() -> int:
    if not DB.exists():
        print(f"❌ 找不到数据库: {DB}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = DB.with_name(f"cherrystudio.sqlite.bak-{stamp}")
    shutil.copy2(DB, bak)
    print(f"✅ 已备份 → {bak.name}\n")

    db = sqlite3.connect(str(DB))
    c = db.cursor()

    # ---- 1. 助手：打开联网 ----
    print("=== 助手设置 ===")
    acols = [r[1] for r in c.execute("PRAGMA table_info(assistant)")]
    for row in c.execute("SELECT * FROM assistant"):
        d = dict(zip(acols, row))
        aid = d["id"]
        try:
            s = json.loads(d.get("settings") or "{}")
        except Exception:
            s = {}
        print(f"  「{d.get('name')}」 enableWebSearch: {s.get('enableWebSearch')} → True")
        s["enableWebSearch"] = True
        c.execute("UPDATE assistant SET settings = ? WHERE id = ?",
                  (json.dumps(s, ensure_ascii=False), aid))
        print(f"     MCP 模式={s.get('mcpMode')}  最大工具调用={s.get('maxToolCalls')}")

    # ---- 2. 检查搜索源配置 ----
    print("\n=== 联网搜索配置 ===")
    keys = {
        "chat.web_search.default_search_keywords_provider": "搜索源",
        "chat.web_search.default_fetch_urls_provider": "抓网页源",
        "chat.web_search.max_results": "结果数",
        "chat.web_search.model_tools_preferred": "模型工具优先",
    }
    for k, label in keys.items():
        r = c.execute("SELECT value FROM preference WHERE key = ?", (k,)).fetchone()
        print(f"  {label:12} = {r[0] if r else '(未设置)'}")

    db.commit()

    # ---- 回读 ----
    print("\n=== 回读校验 ===")
    ok = False
    for row in c.execute("SELECT name, settings FROM assistant"):
        s = json.loads(row[1] or "{}")
        ok = s.get("enableWebSearch") is True
        print(f"  「{row[0]}」 enableWebSearch = {s.get('enableWebSearch')}  "
              f"{'✅' if ok else '❌'}")

    db.close()
    print(f"\n{'✅ 联网已开启' if ok else '❌ 未生效'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
