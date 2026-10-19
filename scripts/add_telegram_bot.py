#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给 AstrBot 加一个 Telegram（纸飞机）机器人。

为什么推荐 Telegram 而不是微信：
    Telegram 不审消息内容。微信会静默丢掉含敏感词的回复，
    看起来就像"本地模型不肯说话"（见 02-技术踩坑档案.md 坑 21）。

做四件事：
    1. 校验 token（真的打一次 Telegram 的 getMe）
    2. 往 cmd_config.json 的 platform 列表里加一条 telegram 机器人
    3. 可选：设 ID 白名单（★强烈建议，不然任何人在 Telegram 上都能跟你的小九聊天）
    4. 可选：设 HTTP 代理（如果直连不通）

用法：
    python add_telegram_bot.py --token 123456:ABC-DEF...
    python add_telegram_bot.py --token 123456:ABC... --allow 123456789
    python add_telegram_bot.py --check
    python add_telegram_bot.py --remove

⚠️ 改动前先完全退出 AstrBot，改完要重启。
"""
import json
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from console_utf8 import console_utf8
from safe_write import write_bytes, write_text

console_utf8()   # GBK 控制台下的兜底，见 console_utf8.py

ROOT = Path(r"E:\本地ai\AstrBotData")
CFG = ROOT / "data" / "cmd_config.json"
BOT_ID = "telegram_main"


def read_cfg():
    raw = CFG.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), raw.startswith(b"\xef\xbb\xbf")


def write_cfg(cfg, bom: bool):
    data = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    write_bytes(CFG, ("\ufeff" + data).encode("utf-8") if bom else data.encode("utf-8"))


def running() -> bool:
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq AstrBot.exe"],
                         capture_output=True, text=True, errors="replace").stdout
    return "AstrBot.exe" in out


def get_me(token: str, proxy: str = "") -> dict | None:
    """打一次 getMe —— 真的验证 token 有效，而不是等重启后去日志里找错。"""
    url = f"https://api.telegram.org/bot{token}/getMe"
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"  [X] Telegram 返回 HTTP {e.code}: {body[:200]}")
        print("      token 不对，或者被 BotFather 撤销了。")
        return None
    except Exception as e:
        print(f"  [X] 连不上 Telegram: {type(e).__name__}: {str(e)[:120]}")
        print("      直连不通的话，加 --proxy http://127.0.0.1:7897")
        return None


def show(cfg):
    print("=== 当前消息平台 ===")
    plats = cfg.get("platform", [])
    if not plats:
        print("  （空）")
    for p in plats:
        tok = p.get("telegram_token") or p.get("weixin_oc_token") or ""
        tok = (tok[:14] + "…") if len(tok) > 14 else tok
        print(f"  id={p.get('id'):24} type={p.get('type'):16} enable={p.get('enable')}"
              + (f"  token={tok}" if tok else ""))
    ps = cfg.get("platform_settings", {})
    wl = ps.get("id_whitelist") or []
    print(f"\n  ID 白名单: enable={ps.get('enable_id_white_list')}  "
          f"白名单={wl if wl else '（空 = 谁都能聊！）'}")
    print(f"  HTTP 代理: {cfg.get('http_proxy') or '（空）'}")


def main() -> int:
    args = sys.argv[1:]
    if not CFG.exists():
        print(f"[X] 找不到 {CFG}")
        return 1
    cfg, bom = read_cfg()

    if "--check" in args or not args:
        show(cfg)
        if not args:
            print("\n用法： python add_telegram_bot.py --token <BotFather给的token>")
        return 0

    if running():
        print("[!] AstrBot 正在运行 —— 改完要重启才生效\n")

    # ---------- 移除 ----------
    if "--remove" in args:
        before = len(cfg.get("platform", []))
        cfg["platform"] = [p for p in cfg.get("platform", [])
                           if p.get("type") != "telegram"]
        if len(cfg["platform"]) == before:
            print("  没有 telegram 平台，无需移除")
            return 0
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(CFG, CFG.with_name(f"{CFG.name}.bak-{stamp}"))
        write_cfg(cfg, bom)
        print("[OK] 已移除 telegram 平台（重启 AstrBot 生效）")
        return 0

    # ---------- 取参数 ----------
    def arg(name):
        """取一个开关后面的值。

        ⚠️ 2026-09-29 加校验：下一个参数不能是另一个开关。
        原来 `--token --allow 123` 会把 `--allow` 当成 token 的值，
        要到很后面才以一个看不懂的错误失败。
        """
        if name in args:
            i = args.index(name) + 1
            if i < len(args):
                v = args[i]
                if v.startswith("--"):
                    print(f"[X] {name} 后面缺值（读到的是另一个开关 {v}）")
                    sys.exit(1)
                return v
        return ""

    token = arg("--token").strip()
    allow = arg("--allow").strip()
    proxy = arg("--proxy").strip()

    if not token:
        print("[X] 要传 --token。先去找 @BotFather 建一个机器人（见下面的步骤）")
        return 1
    if ":" not in token:
        print(f"[X] token 格式不对（应该像 123456789:AAE...，中间有冒号）：{token[:20]}")
        return 1

    # ---------- 校验 token ----------
    print(f"=== 校验 token（打 Telegram getMe）===")
    me = get_me(token, proxy)
    if not me or not me.get("ok"):
        return 1
    u = me["result"]
    print(f"  [OK] token 有效")
    print(f"       机器人: @{u.get('username')}  ({u.get('first_name')})")
    print(f"       id: {u.get('id')}")

    # ---------- 写配置 ----------
    plats = cfg.setdefault("platform", [])
    # 找已有的 telegram 平台（不管 id 是什么，用户可能已经手建过一条）
    idx = next((i for i, p in enumerate(plats) if p.get("type") == "telegram"), None)
    # ⚠️ 必须在构造 new_bot **之前**取旧代理：下面 merged.update 会整键覆盖
    _OLD_PROXY = (plats[idx].get("telegram_proxy") or "") if idx is not None else ""

    new_bot = {
        "id": BOT_ID,
        "type": "telegram",
        "enable": True,
        "telegram_token": token,
        "telegram_api_base_url": "https://api.telegram.org/bot",
        "telegram_file_base_url": "https://api.telegram.org/file/bot",
        "telegram_command_register": True,
        "telegram_command_auto_refresh": True,
        # 只让 Telegram 走代理，不动全局 http_proxy（联网搜索仍直连）。
        # 需要 patch_astrbot_telegram.py 打过补丁才认这个字段。
        #
        # ⚠️ 2026-09-29 改：**不传 --proxy 时不能写成空串**。
        #    下面 `merged.update(new_bot)` 会整键覆盖 —— 原来这里写 `proxy or ""`，
        #    于是"重跑一次脚本"（比如只想加个白名单、或换个 token）会把**已经配好的代理清掉**，
        #    而症状（TimedOut、模型不理人）和原因（代理被清）完全脱节，最难查。
        #    现在：没传就保留旧值（新增时才给空串）。
        "telegram_proxy": proxy or _OLD_PROXY,
    }

    if idx is not None:
        old = plats[idx]
        # 保留用户自己加的字段，只覆盖我们管的
        merged = dict(old)
        merged.update(new_bot)
        merged["id"] = old.get("id") or BOT_ID
        plats[idx] = merged
        print(f"\n[OK] 已更新已有的 telegram 平台（id={merged['id']}）")
    else:
        plats.append(new_bot)
        print(f"\n[OK] 已添加 telegram 平台（id={BOT_ID}）")

    if proxy:
        print(f"[OK] Telegram 单独走代理 → {proxy}")
        print("     （需要先跑 patch_astrbot_telegram.py，否则适配器不认这个字段）")

    # ---------- 白名单 ----------
    ps = cfg.setdefault("platform_settings", {})
    if allow:
        ids = [x.strip() for x in allow.replace(",", " ").split() if x.strip()]
        cur = [x for x in (ps.get("id_whitelist") or []) if x]
        for i in ids:
            if i not in cur:
                cur.append(i)
        ps["id_whitelist"] = cur
        ps["enable_id_white_list"] = True
        print(f"[OK] ID 白名单 → {cur}")
    else:
        wl = ps.get("id_whitelist") or []
        if not wl:
            print("\n[!] 警告：ID 白名单是空的 —— 任何人在 Telegram 上找到这个机器人，")
            print("    都能跟你的小九聊天（而且它是不审查的）。")
            print("    强烈建议加白名单：")
            print("      1. 在 Telegram 里找 @userinfobot，发任意消息，它会回你的数字 ID")
            print("      2. python add_telegram_bot.py --token <token> --allow <你的ID>")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(CFG, CFG.with_name(f"{CFG.name}.bak-{stamp}"))
    print(f"[OK] 已备份 → {CFG.name}.bak-{stamp}")
    write_cfg(cfg, bom)
    print(f"[OK] 配置已写入")

    print("\n=== 回读 ===")
    show(read_cfg()[0])
    print("\n[!] 重启 AstrBot 生效。然后在 Telegram 里给 @" + str(u.get("username")) + " 发消息。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
