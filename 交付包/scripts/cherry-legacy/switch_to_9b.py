#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 9B 模型加入 Cherry Studio，并把助手「小九」切到 9B。
4B 仍保留在列表里，随时可切回。
"""
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

DB = Path(r"E:\本地ai\CherryStudio\data\Data\cherrystudio.sqlite")

SRC_ID = "ollama::xiaojiu:latest"        # 已有的 4B
DST_ID = "ollama::xiaojiu9b:latest"      # 要新增的 9B
DST_MODEL = "xiaojiu9b:latest"
DST_CTX = 32768
PROMPT_FILE = Path(r"E:\本地ai\fix_cherry_assistant.py")


def load_prompt() -> str:
    """从 fix 脚本里取人格提示词，避免两处维护。"""
    text = PROMPT_FILE.read_text(encoding="utf-8")
    start = text.index('PROMPT = """') + len('PROMPT = """')
    end = text.index('"""', start)
    return text[start:end]


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

    # ---- 1. 参考模板行（优先 4B，没有就用 9B 自己，都没有就用内置默认）----
    cols = [r[1] for r in c.execute("PRAGMA table_info(user_model)")]
    row = c.execute("SELECT * FROM user_model WHERE id = ?", (SRC_ID,)).fetchone()
    src = "4B"
    if not row:
        row = c.execute("SELECT * FROM user_model WHERE id = ?", (DST_ID,)).fetchone()
        src = "9B（4B 已删除，改用 9B 现有行作模板）"
    if row:
        tpl = dict(zip(cols, row))
    else:
        src = "内置默认（user_model 里一个都没有）"
        tpl = {"provider_id": "ollama", "parameters": "{}", "capabilities": "[]",
               "input_modalities": '["text"]', "output_modalities": '["text"]',
               "endpoint_types": '["openai"]', "supports_streaming": 1, "reasoning": 0}
        for k in cols:
            tpl.setdefault(k, None)
    print(f"=== 参考行（{src}）===")
    for k in ("id", "provider_id", "model_id", "name", "group", "context_window", "is_enabled"):
        print(f"  {k:16} = {tpl.get(k)}")

    # ---- 2. 插入/更新 9B ----
    print("\n=== 处理 9B 模型记录 ===")
    now = int(time.time() * 1000)
    new = dict(tpl)
    new.update({
        "id": DST_ID,
        "model_id": DST_MODEL,
        "name": DST_MODEL,
        "group": "xiaojiu9b",
        "context_window": DST_CTX,
        "max_input_tokens": DST_CTX,
        "is_enabled": 1,
        "is_hidden": 0,
        "order_key": "a1",
        "created_at": now,
        "updated_at": now,
    })

    exists = c.execute("SELECT 1 FROM user_model WHERE id = ?", (DST_ID,)).fetchone()
    if exists:
        # 列名一律加双引号，避免 group 这类保留字报错
        sets = ", ".join(f'"{k}" = ?' for k in new if k != "id")
        vals = [new[k] for k in new if k != "id"] + [DST_ID]
        c.execute(f"UPDATE user_model SET {sets} WHERE id = ?", vals)
        print(f"  已更新现有记录 {DST_ID}")
    else:
        keys = list(new.keys())
        collist = ", ".join(f'"{k}"' for k in keys)
        marks = ", ".join("?" * len(keys))
        c.execute(
            f"INSERT INTO user_model ({collist}) VALUES ({marks})",
            [new[k] for k in keys],
        )
        print(f"  已新增记录 {DST_ID}  (context_window={DST_CTX})")

    # 4B 若还在列表里，保持启用可见；已删除就跳过
    n4 = c.execute("UPDATE user_model SET is_enabled = 1, is_hidden = 0 WHERE id = ?", (SRC_ID,)).rowcount
    print(f"  4B {'保持启用可见' if n4 else '不存在（已删除），跳过'}")

    # ---- 3. 助手切到 9B ----
    print("\n=== 助手切换到 9B ===")
    acols = [r[1] for r in c.execute("PRAGMA table_info(assistant)")]
    for r in c.execute("SELECT * FROM assistant"):
        d = dict(zip(acols, r))
        print(f"  改前: name={d.get('name')}  model={d.get('model_id')}")
    # 只改模型，不碰 prompt —— 人格由 apply_persona.py 单独管理，别覆盖掉
    c.execute("UPDATE assistant SET model_id = ?", (DST_ID,))
    print(f"  改后: 模型 → {DST_ID}（提示词保持不变）")

    # ---- 4. 默认模型偏好 ----
    print("\n=== 默认模型偏好 ===")
    for key in ("chat.default_model_id", "feature.quick_assistant.model_id",
                "feature.translate.model_id"):
        r = c.execute("SELECT value FROM preference WHERE key = ?", (key,)).fetchone()
        if r is None:
            print(f"  {key:42} (不存在)")
            continue
        print(f"  {key:42} {r[0]}  →  \"{DST_ID}\"")
        c.execute("UPDATE preference SET value = ? WHERE key = ?", (f'"{DST_ID}"', key))

    db.commit()

    # ---- 回读校验 ----
    print("\n=== 回读校验 ===")
    ok = True
    for m, required in ((DST_ID, True), (SRC_ID, False)):
        r = c.execute("SELECT name, context_window, is_enabled, is_hidden FROM user_model WHERE id = ?",
                      (m,)).fetchone()
        if r:
            print(f"  {m:30} ctx={r[1]:6} enabled={r[2]} hidden={r[3]}")
        elif required:
            print(f"  {m:30} ❌ 缺失")
            ok = False
        else:
            print(f"  {m:30} — 不存在（已删除，正常）")
    for r in c.execute("SELECT name, model_id, length(prompt) FROM assistant"):
        print(f"  助手: {r[0]}  模型={r[1]}  提示词={r[2]}字符")
        if r[1] != DST_ID or not r[2]:
            ok = False

    db.close()
    print(f"\n{'✅ 完成' if ok else '❌ 有问题'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
