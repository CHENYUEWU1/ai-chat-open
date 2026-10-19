#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
查看 / 清理 AstrBot 的对话历史。

为什么需要这个脚本：
    在聊天里发 `/new` 就能"开新话题"，但它**只是让会话指向一条新的空对话**，
    旧对话仍然留在数据库里（占空间、也不好在界面上够到 —— 比如 Telegram 那份）。

    AstrBot 只给了 `/new`，**没有给"删除"命令**。
    删除只能走 WebUI 的会话列表，或者用这个脚本。

用法：
    python clear_history.py                 # 只看，不动（默认）
    python clear_history.py --list          # 同上
    python clear_history.py --delete <id>   # 删一条（id 可以只写前几位）
    python clear_history.py --all           # 删掉**所有**对话历史
    python clear_history.py --webchat       # 连 WebUI 的会话列表一起清

⚠️ 删除前先完全退出 AstrBot：
    会话指针（sel_conv_id）同时存在内存和 preferences 表里，
    运行中改数据库会被它覆盖回去。
    本脚本会拒绝在 AstrBot 运行时执行删除（只看是不受影响的）。
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()

ROOT = Path(r"E:\本地ai\AstrBotData")
DB = ROOT / "data" / "data_v4.db"


def running() -> bool:
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq AstrBot.exe"],
                         capture_output=True, text=True, errors="replace").stdout
    return "AstrBot.exe" in out


def show() -> None:
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    print("=" * 78)
    print("对话历史（conversations）—— 这才是模型每轮读到的东西")
    print("=" * 78)
    rows = db.execute(
        "SELECT conversation_id, platform_id, user_id, token_usage, "
        "updated_at, length(content) FROM conversations "
        "ORDER BY updated_at DESC").fetchall()
    if not rows:
        print("  （空）")
    tot = 0
    for cid, pid, uid, tk, up, ln in rows:
        tot += tk or 0
        print(f"  {cid[:8]}  {pid:<10} {str(uid)[:44]:<44} "
              f"tok={tk or 0:<7} {str(up)[:16]}")
    print(f"  → {len(rows)} 条，合计 {tot:,} token")

    print()
    print("=" * 78)
    print("WebUI 的会话列表（platform_sessions）—— 每个 = 界面左侧一个聊天")
    print("=" * 78)
    rows = db.execute(
        "SELECT session_id, display_name, updated_at FROM platform_sessions "
        "WHERE platform_id = 'webchat' ORDER BY updated_at DESC").fetchall()
    if not rows:
        print("  （空）")
    for sid, dn, up in rows:
        print(f"  {str(sid)[:36]:<36} {(dn or '(无标题)')[:26]:<28} {str(up)[:16]}")
    print(f"  → {len(rows)} 个 WebUI 会话")
    print()
    print("  ⚠️ WebUI 的聊天内容不在 conversations 里，在它自己的存储中；")
    print("     删会话请用界面左侧列表，或加 --webchat 一起清。")
    db.close()


def backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = DB.with_name(f"{DB.name}.bak-clear-{stamp}")
    shutil.copy2(DB, bak)
    print(f"[OK] 已备份 → {bak.name}")
    return bak


def do_delete(ids: list[str] | None, webchat: bool) -> int:
    if running():
        print("[X] AstrBot 正在运行。请先完全退出（含托盘图标），再执行删除。")
        print("    （只看不用退，直接跑 python clear_history.py）")
        return 1
    backup()
    db = sqlite3.connect(str(DB))
    c = db.cursor()

    if ids is None:
        n = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        c.execute("DELETE FROM conversations")
        print(f"[OK] 已删除全部 {n} 条对话历史")
    else:
        for i in ids:
            hit = c.execute(
                "SELECT conversation_id FROM conversations "
                "WHERE conversation_id LIKE ?", (i + "%",)).fetchall()
            if not hit:
                print(f"[!] 没找到匹配 {i!r} 的对话")
                continue
            for (cid,) in hit:
                c.execute("DELETE FROM conversations WHERE conversation_id = ?", (cid,))
                print(f"[OK] 已删除对话 {cid[:8]}")

    # 会话指针也要清 —— 否则它还指着一条已删掉的对话
    c.execute("DELETE FROM preferences WHERE key = 'sel_conv_id'")
    print("[OK] 已清掉会话指针（sel_conv_id）")

    if webchat:
        n = c.execute("SELECT COUNT(*) FROM platform_sessions "
                      "WHERE platform_id='webchat'").fetchone()[0]
        c.execute("DELETE FROM platform_sessions WHERE platform_id = 'webchat'")
        c.execute("DELETE FROM platform_message_history WHERE platform_id = 'webchat'")
        print(f"[OK] 已删除 {n} 个 WebUI 会话及其消息记录")

    db.commit()
    db.close()
    print("\n[!] 重开 AstrBot 生效")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not DB.exists():
        print(f"[X] 找不到 {DB}")
        return 1

    if "--delete" in args:
        i = args.index("--delete") + 1
        if i >= len(args):
            print("[X] --delete 后面要跟对话 id（可以只写前几位）")
            return 1
        return do_delete([args[i]], "--webchat" in args)
    if "--all" in args:
        return do_delete(None, "--webchat" in args)
    show()
    print("删除： python clear_history.py --delete <id>")
    print("全清： python clear_history.py --all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
