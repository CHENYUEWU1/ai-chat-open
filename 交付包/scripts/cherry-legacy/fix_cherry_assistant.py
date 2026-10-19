#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Cherry Studio 的助手从云端模型改绑到本地模型（9B）。

⚠️ 默认**不动提示词** —— 人格由 apply_persona.py 单独管理，别互相覆盖。
   只有加 --with-prompt 才会写入 personas/默认-小九.txt（用于全新重建）。

用法：
    python fix_cherry_assistant.py                 # 只绑模型 + 设上下文
    python fix_cherry_assistant.py --with-prompt   # 顺带写入默认人格
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(r"E:\本地ai\CherryStudio\data\Data\cherrystudio.sqlite")
LOCAL_MODEL = "ollama::xiaojiu9b:latest"
CLOUD_MODEL = "cherryai::qwen"
CTX = 32768
PERSONA = Path(r"E:\本地ai\personas\默认-小九.txt")

def load_default_persona() -> str:
    """从 personas/ 读默认人格，避免这里再维护第二份副本。"""
    if not PERSONA.exists():
        print(f"⚠️ 找不到 {PERSONA}，跳过提示词写入")
        return ""
    return PERSONA.read_text(encoding="utf-8").rstrip() + "\n"


def main() -> int:
    with_prompt = "--with-prompt" in sys.argv[1:]

    if not DB.exists():
        print(f"❌ 找不到数据库: {DB}")
        return 1

    # 备份
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = DB.with_name(f"cherrystudio.sqlite.bak-{stamp}")
    shutil.copy2(DB, bak)
    print(f"✅ 已备份 → {bak.name}  ({bak.stat().st_size/1024:.0f} KB)\n")

    db = sqlite3.connect(str(DB))
    c = db.cursor()

    # ---- 1. 助手 ----
    print("=== 修改前：assistant 表 ===")
    cols = [r[1] for r in c.execute("PRAGMA table_info(assistant)")]
    for row in c.execute("SELECT * FROM assistant"):
        d = dict(zip(cols, row))
        for k in ("id", "name", "model_id", "prompt"):
            v = d.get(k)
            print(f"  {k:10} = {repr(v)[:90]}")

    # 只改模型；提示词要显式加 --with-prompt 才动（人格归 apply_persona.py 管）
    if with_prompt:
        p = load_default_persona()
        if p:
            c.execute("UPDATE assistant SET name = ?, model_id = ?, prompt = ?",
                      ("小九", LOCAL_MODEL, p))
            print(f"\n✅ 已更新 {c.rowcount} 行助手（含提示词 {len(p)} 字符）")
        else:
            c.execute("UPDATE assistant SET name = ?, model_id = ?", ("小九", LOCAL_MODEL))
            print(f"\n✅ 已更新 {c.rowcount} 行助手（提示词未动）")
    else:
        c.execute("UPDATE assistant SET name = ?, model_id = ?", ("小九", LOCAL_MODEL))
        print(f"\n✅ 已更新 {c.rowcount} 行助手，提示词**保持不变**")
        print("   （要写默认人格请加 --with-prompt；要换人格用 apply_persona.py）")

    # ---- 2. 默认模型偏好 ----
    print("\n=== 默认模型偏好 ===")
    for key in ("chat.default_model_id", "feature.quick_assistant.model_id",
                "feature.translate.model_id"):
        row = c.execute("SELECT value FROM preference WHERE key = ?", (key,)).fetchone()
        if row is None:
            print(f"  {key:44} (不存在)")
            continue
        old = str(row[0]).strip('"')
        print(f"  {key:44} = {old}")
        if old == CLOUD_MODEL:
            c.execute("UPDATE preference SET value = ? WHERE key = ?",
                      (f'"{LOCAL_MODEL}"', key))
            print(f"      → 已改为 {LOCAL_MODEL}")

    # ---- 3. 模型上下文长度 ----
    print("\n=== 模型上下文长度 ===")
    row = c.execute(
        "SELECT context_window FROM user_model WHERE id = ?", (LOCAL_MODEL,)
    ).fetchone()
    if row:
        print(f"  修改前 context_window = {row[0]}")
        c.execute(
            "UPDATE user_model SET context_window = ?, max_input_tokens = ? WHERE id = ?",
            (CTX, CTX, LOCAL_MODEL),
        )
        print(f"  修改后 context_window = {CTX}")
    else:
        print(f"  ⚠️ user_model 里没找到 {LOCAL_MODEL}")

    db.commit()

    # ---- 回读校验 ----
    print("\n=== 回读校验 ===")
    cols = [r[1] for r in c.execute("PRAGMA table_info(assistant)")]
    ok = True
    for row in c.execute("SELECT * FROM assistant"):
        d = dict(zip(cols, row))
        print(f"  名称     = {d.get('name')}")
        print(f"  模型     = {d.get('model_id')}")
        p = d.get("prompt") or ""
        print(f"  提示词   = {len(p)} 字符  开头: {p[:34]}...")
        if d.get("model_id") != LOCAL_MODEL:
            ok = False
        if not p:
            ok = False
    m = c.execute("SELECT context_window FROM user_model WHERE id = ?", (LOCAL_MODEL,)).fetchone()
    print(f"  上下文   = {m[0] if m else '?'}")

    db.close()
    print(f"\n{'✅ 全部修改成功' if ok else '❌ 部分修改未生效'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
