#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Cherry Studio 里所有残留的 4B 引用改成 9B，并（默认）隐藏 4B。

为什么需要这个脚本：
    Cherry Studio 有两个内置「智能体」(agent 表) —— Cherry 小助手 / 产品反馈，
    它们默认绑定了 ollama::xiaojiu:latest（4B）。Cherry Studio 启动时会预热
    智能体的模型，于是每次开软件都会把 4B 拉进显存，占掉 2.7 GB，
    并且 ollama ps 里看到的是 4B 而不是你真正在聊的 9B。

    助手的 model_id 和 preference 早就指向 9B 了，所以只查这些地方永远找不到原因。

用法：
    python fix_agent_model.py            # 改成 9B 并隐藏 4B
    python fix_agent_model.py --show-4b  # 改成 9B 但让 4B 重新显示在列表里
    python fix_agent_model.py --check    # 只看现状，不改

注意：需要先完全关闭 Cherry Studio，否则改动会被覆盖。
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(r"E:\本地ai\CherryStudio\data\Data\cherrystudio.sqlite")
OLD = "ollama::xiaojiu:latest"      # 4B
NEW = "ollama::xiaojiu9b:latest"    # 9B


def show(db):
    print("=== agent 表（智能体，启动时会预热模型）===")
    for r in db.execute('SELECT rowid, name, type, model, plan_model, small_model FROM agent'):
        mark = "  ← 4B，要改" if OLD in (r[3], r[4], r[5]) else ""
        print(f"  rowid={r[0]}  {r[1]:12} type={r[2]:12} model={r[3]}{mark}")

    print("\n=== user_model 表（模型选择器里能看到的）===")
    for r in db.execute('SELECT rowid, id, name, is_enabled, is_hidden FROM user_model'):
        state = "隐藏" if r[4] else "显示"
        print(f"  rowid={r[0]}  {r[1]:34} {state}  enabled={r[3]}")

    print("\n=== 助手 / 偏好 ===")
    for r in db.execute("SELECT name, model_id, length(prompt) FROM assistant"):
        print(f"  助手 {r[0]}  模型={r[1]}  提示词={r[2]} 字符")
    for r in db.execute("SELECT key, value FROM preference WHERE key LIKE '%model%'"):
        print(f"  {r[0]:42} {r[1]}")


def main() -> int:
    args = sys.argv[1:]
    if not DB.exists():
        print(f"❌ 找不到数据库: {DB}")
        return 1
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    if "--check" in args:
        show(db)
        db.close()
        return 0
    db.close()

    hide_4b = 1 if "--show-4b" not in args else 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = DB.with_name(f"cherrystudio.sqlite.bak-{stamp}")
    shutil.copy2(DB, bak)
    print(f"✅ 已备份 → {bak.name}\n")

    db = sqlite3.connect(str(DB))
    c = db.cursor()

    # ---- 1. 智能体里的 4B → 9B ----
    print("=== 1. 修正智能体绑定的模型 ===")
    n = 0
    for col in ("model", "plan_model", "small_model"):
        cur = c.execute(
            f'UPDATE agent SET "{col}" = ?, updated_at = ? WHERE "{col}" = ?',
            (NEW, int(datetime.now().timestamp() * 1000), OLD),
        )
        if cur.rowcount:
            print(f"  agent.{col}: {cur.rowcount} 行  {OLD} → {NEW}")
            n += cur.rowcount
    if not n:
        print("  没有需要改的行（已经都是 9B）")

    # ---- 2. 4B 的显示开关 ----
    print("\n=== 2. 模型列表显示状态 ===")
    c.execute("UPDATE user_model SET is_enabled = 1 WHERE id = ?", (NEW,))
    print(f"  9B  {NEW}  已启用、显示")
    c.execute("UPDATE user_model SET is_enabled = 1, is_hidden = ? WHERE id = ?", (hide_4b, OLD))
    print(f"  4B  {OLD}  {'已隐藏（防止手滑选错）' if hide_4b else '保持显示'}")

    # ---- 3. 助手 + 默认偏好（只改模型，不动提示词）----
    print("\n=== 3. 助手与默认偏好 ===")
    c.execute("UPDATE assistant SET model_id = ? WHERE model_id <> ?", (NEW, NEW))
    print(f"  助手模型 → {NEW}（提示词未改动）")
    for key in ("chat.default_model_id", "feature.quick_assistant.model_id",
                "feature.translate.model_id"):
        r = c.execute("SELECT value FROM preference WHERE key = ?", (key,)).fetchone()
        if r is None:
            continue
        print(f"  {key:42} {r[0]} → \"{NEW}\"")
        c.execute("UPDATE preference SET value = ? WHERE key = ?", (f'"{NEW}"', key))
    # 模型选择器里可能残留的"当前模型"指针
    c.execute("UPDATE preference SET value = ? WHERE key LIKE '%current%model%'", (f'"{NEW}"',))

    db.commit()
    print("\n=== 回读校验 ===")
    leftover = c.execute(
        'SELECT COUNT(*) FROM agent WHERE model = ? OR plan_model = ? OR small_model = ?',
        (OLD, OLD, OLD)).fetchone()[0]
    show(db)
    db.close()

    ok = leftover == 0
    print(f"\n{'✅ 完成：已无 4B 残留引用' if ok else f'❌ 还有 {leftover} 处 4B 引用'}")
    print("⚠️ 重启 Cherry Studio 才生效")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
