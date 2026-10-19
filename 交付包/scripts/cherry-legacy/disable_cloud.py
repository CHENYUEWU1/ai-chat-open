#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关闭 Cherry Studio 的云端模型入口，避免对话误发到 Cherry 服务器。"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(r"E:\本地ai\CherryStudio\data\Data\cherrystudio.sqlite")

# 要关闭的云端提供者
CLOUD_PROVIDERS = ("cherryai", "cherryai-subscription")
# 要隐藏的云端模型
CLOUD_MODEL_PREFIX = "cherryai::"


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

    print("=== 1. 关闭云端提供者 ===")
    for pid in CLOUD_PROVIDERS:
        row = c.execute(
            "SELECT name, is_enabled FROM user_provider WHERE provider_id = ?", (pid,)
        ).fetchone()
        if not row:
            print(f"  {pid:24} (不存在，跳过)")
            continue
        c.execute("UPDATE user_provider SET is_enabled = 0 WHERE provider_id = ?", (pid,))
        print(f"  {pid:24} {row[0]:10}  is_enabled {row[1]} → 0")

    print("\n=== 2. 隐藏云端模型 ===")
    for row in c.execute("SELECT id, name, is_enabled, is_hidden FROM user_model"):
        mid, name, en, hid = row
        if str(mid).startswith(CLOUD_MODEL_PREFIX):
            c.execute(
                "UPDATE user_model SET is_enabled = 0, is_hidden = 1 WHERE id = ?", (mid,)
            )
            print(f"  {mid:24} is_enabled {en}→0, is_hidden {hid}→1")
        elif str(mid).startswith("ollama::"):
            # 本地模型一律启用可见（4B 已删除，所以不能写死具体名字）
            c.execute("UPDATE user_model SET is_enabled = 1, is_hidden = 0 WHERE id = ?", (mid,))
            print(f"  {mid:24} ✅ 确保启用且可见")

    db.commit()

    print("\n=== 回读校验 ===")
    ok = True
    for pid in CLOUD_PROVIDERS:
        r = c.execute("SELECT is_enabled FROM user_provider WHERE provider_id = ?", (pid,)).fetchone()
        state = "已关闭 ✅" if r and r[0] == 0 else "❌ 仍启用"
        print(f"  提供者 {pid:24} {state}")
        if not (r and r[0] == 0):
            ok = False
    for row in c.execute("SELECT id, is_enabled, is_hidden FROM user_model"):
        if str(row[0]).startswith(CLOUD_MODEL_PREFIX):
            good = row[1] == 0 and row[2] == 1
            print(f"  模型   {row[0]:24} {'已隐藏 ✅' if good else '❌ 仍可见'}")
            if not good:
                ok = False
    for r in c.execute("SELECT id, is_enabled, is_hidden FROM user_model WHERE id LIKE 'ollama::%'"):
        print(f"  本地模型 {r[0]:24} {'已启用 ✅' if r[1] == 1 else '❌ 未启用'}")
        if r[1] != 1:
            ok = False

    db.close()
    print(f"\n{'✅ 完成' if ok else '❌ 部分未生效'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
