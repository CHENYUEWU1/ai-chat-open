# -*- coding: utf-8 -*-
r"""冒烟测试（重构/模块化之后的**准入闸门**）。

它在**备用端口**起一个网关实例，把"必须还能用"的东西逐条验一遍，最后给 通过/失败 汇总。
任何一条挂了 ⇒ 退出码非 0 ⇒ 这个改动**不许合**。

用法：
    python smoke_test.py                 # 默认用 11436 端口，不碰正在跑的 11435
    python smoke_test.py --port 11437    # 换端口
    python smoke_test.py --no-chat       # 跳过"真发一条聊天"（不想占显存时）

⚠️ 它和正式实例**共享 `_备份\\` 状态**（访问码/授权设备/思考模式/预算/温度/过程日志）——
   所以本脚本**只读不改**：所有 POST 都用"设成它原本的值"的方式，绝不改变你的设置 ✓
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ⚠️ 2026-10-19 加：stdout **不是控制台**（管道 / 重定向 / `| Tee-Object` / 日志采集）时，
#    Python 按**区域编码**（本机 cp936）写出去 ⇒ 打印第一个 ✅ 就
#    `UnicodeEncodeError: 'gbk' codec can't encode '\u2705'`，脚本**在第一条结果处直接崩**，
#    看着像"冒烟挂了"，实际什么都还没测。实测踩过：`python smoke_test.py > 日志.txt` 立刻崩。
#    与 `test_access.py` 顶部同一行处理**保持逐字一致**（那里早就有了，这里漏了）✓
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 —— 老解释器 / 被替换过的流不支持就算了，别因此崩
    pass

ROOT = Path(__file__).resolve().parent
RESULTS: list = []


SKIPPED: list = []

# 那条「真发一条聊天」的硬超时（秒）—— 2026-10-11 从写死的 600 收成 180。
#
# ⚠️ 为什么收：正常时这条请求 **0.3~1.2 秒**就返回，600 秒只在"卡死"时才用得上；
#    而它意味着"这套验收最长可能挂 **10 分钟**"，比验收预算（5 分钟）还长 ✗
#    180 秒的依据是实测：35B 冷启动 **28~36 秒**（换模型/重启后第一条，见 03 的冷启动表），
#    180 ≈ 5 倍余量 —— 够冷启动、也够一次慢回复；真卡死则 3 分钟就放弃 ✓
#    这条上界是给已知的「Ollama 偶尔整个卡死」准备的（根因未确证，见 02 坑 32 / 00 第五节）✓
CHAT_TIMEOUT = 180.0


def rec(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""), flush=True)


def skip(name: str, why: str) -> None:
    r"""依赖 Ollama 的检查在 Ollama 没跑时**明确跳过**（不算失败，但要说清）✓"""
    SKIPPED.append(name)
    print(f"  ⏭ {name}  —— 跳过：{why}", flush=True)


class _NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OP = urllib.request.build_opener(_NR)


def port_open(p: int, t: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", p), timeout=t):
            return True
    except Exception:
        return False


def fetch(base: str, path: str, timeout: float = 20.0):
    r = urllib.request.urlopen(base + path, timeout=timeout)
    return r.status, r.read().decode("utf-8", "replace")


def post(base: str, path: str, data: bytes):
    r"""返回状态码；302 也算成功（这些按钮就是跳转回面板）。"""
    try:
        return OP.open(urllib.request.Request(base + path, data=data), timeout=15).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def api_ps(timeout: float = 6.0) -> str:
    r"""GET Ollama 的 `/api/ps` ⇒ **当前已经加载**的那个模型名（一个都没加载时返回 ""）。

    为什么要这一条：启动脚本设了 `OLLAMA_MAX_LOADED_MODELS=1`，
    所以"加载谁"就是**独占**的 —— 冒烟测试想知道"现在我能不能不动用户的现场"，
    就必须先问清楚**现在加载的是谁** ✓（见下面第 4 节的 ⚠️⚠️ 注释）
    """
    try:
        r = urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=timeout)
        d = json.loads(r.read().decode("utf-8", "replace"))
        ms = d.get("models") or []
        return str(ms[0].get("name") or "").strip() if ms else ""
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--no-chat", action="store_true", help="跳过真发一条聊天")
    # 2026-10-22（GPT 复核）：**默认只验收 llama.cpp**。要测 Ollama 必须显式指定，
    # 否则会出现"打印退回 Ollama、但网关其实还按 llamacpp 起"的错测。
    ap.add_argument("--upstream", choices=["llamacpp", "ollama"], default="llamacpp",
                    help="验收哪个上游（默认 llamacpp）")
    ap.add_argument("--timeout", type=float, default=60.0, help="等实例起来的秒数")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    print("=" * 62)
    print("  冒烟测试：重构之后必须还能用的东西")
    print("=" * 62)
    # 当前默认验收 llama.cpp；只有显式 --upstream ollama 才访问旧后端。
    ollama_up = port_open(11434)
    llama_up = port_open(11450)
    # 只认**选定的**上游，不再"哪个通就用哪个"
    upstream_ok = llama_up if args.upstream == "llamacpp" else ollama_up
    ps_start = api_ps() if args.upstream == "ollama" and ollama_up else ""
    if not upstream_ok:
        selected = "llama.cpp 11450" if args.upstream == "llamacpp" else "Ollama 11434"
        print(f"  ⚠️ 所选上游（{selected}）没在运行 ⇒ 依赖它的检查会跳过。")
        print("     想跑完整测试：先双击 启动局域网API.bat 再跑本脚本 ✓")

    # ── 0 静态检查（不需要起服务）─────────────────────────────
    for f in ("ollama_gateway.py", "gateway_page.py"):
        p = ROOT / f
        rec(f"文件存在：{f}", p.exists(), f"{p.stat().st_size // 1024} KB" if p.exists() else "缺失")
    for f in ("ollama_gateway.py", "gateway_page.py"):
        try:
            import ast
            ast.parse((ROOT / f).read_text(encoding="utf-8"))
            rec(f"语法正确：{f}", True)
        except Exception as e:
            rec(f"语法正确：{f}", False, f"{type(e).__name__}")
    gp = ROOT / "gateway_page.py"
    if gp.exists():
        t = gp.read_text(encoding="utf-8")
        keys = ["#resources", "#api-key", "#try-chat", "#connect", "#access", "#actions"]
        rec("页面锚点 id 都在 gateway_page.py", all(k in t for k in keys),
            "缺失：" + ",".join(k for k in keys if k not in t) if not all(k in t for k in keys) else "")
        rec("有 PAGE_VER（手机缓存识别）", "PAGE_VER" in t)
        rec("折叠用原生 <details>（不依赖 JS）", "<details" in t and "<summary" in t)

    # ── 1 起测试实例 ────────────────────────────────────────
    if port_open(args.port):
        print(f"  ⚠️ 端口 {args.port} 已在被占用，先关掉它再跑（避免误测别的实例）")
        return 2
    # 网关测试实例必须显式使用所选上游，不能依据端口状态自动切换。
    extra = []
    # 2026-10-22（GPT 复核）：上游由 `--upstream` 决定，**不再自动退回**。
    if args.upstream == "llamacpp":
        extra = ["--upstream", "llamacpp", "--llamacpp-port", "11450"]
        if llama_up:
            print("  上游：llama.cpp（11450 通）")
        else:
            print("  ⚠️ llama.cpp（11450）没在跑：聊天相关项会**明确跳过**（不算通过）。")
            print("     想跑完整测试：先双击 启动局域网API.bat（或 python workbench.py --ensure-llama）")
    else:
        extra = ["--upstream", "ollama"]
        if not ollama_up:
            print("  ⚠️ 指定了 --upstream ollama，但 11434 没在跑：聊天相关项会跳过。")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "ollama_gateway.py"), "--port", str(args.port)] + extra,
        stdout=(ROOT / "_备份" / "smoke_out.txt").open("wb"),
        stderr=(ROOT / "_备份" / "smoke_err.txt").open("wb"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    up = False
    t0 = time.time()
    while time.time() - t0 < args.timeout:
        if port_open(args.port):
            up = True
            break
        if proc.poll() is not None:
            break
        time.sleep(1)
    if not up:
        tail = ""
        try:
            tail = (ROOT / "_备份" / "smoke_err.txt").read_text(encoding="utf-8", errors="replace")[-400:]
        except Exception:
            pass
        rec("网关能在备用端口起来", False, f"stderr 尾部：{tail.strip()[:200]}")
        proc.terminate()
        return 1
    rec("网关能在备用端口起来", True, f"{time.time()-t0:.1f} 秒")

    try:
        # ── 2 页面 ─────────────────────────────────────────
        st, html = fetch(base, "/")
        rec("主页 / 返回 200", st == 200)
        anchors = sum(1 for a in ("resources", "api-key", "try-chat", "connect", "access", "actions")
                      if f'id="{a}"' in html)
        rec("主页 6 个锚点齐全", anchors == 6, f"{anchors}/6")
        rec("主页带版本占位（手机缓存用）", "2026-10-09-ui" in html or "PAGE_VER" in html
            or bool(__import__("re").search(r"\d{4}-\d\d-\d\d-ui\d", html)))
        st2, plain = fetch(base, "/plain")
        rec("/plain 无脚本兜底页 返回 200", st2 == 200)
        rec("/plain 不含内联脚本（手机浏览器会拦）", "<script" not in plain)
        for label, marker in (("思考模式 4 档", 'action="/__think"'),
                              ("思考过程 3 个按钮", 'action="/__thinklog"'),
                              ("温度旋钮", 'action="/__temp"'),
                              ("开机预热", 'action="/__warm"'),
                              ("第一轮预算", 'action="/__budget"'),
                              ("看最近一条思考", "/__peek")):
            rec(f"/plain 有：{label}", marker in plain)

        # ── 3 接口 & 按钮（只读 + 幂等 POST）───────────────
        for path in ("/api/version", "/api/tags", "/__stats", "/__peek?n=1"):
            depends = path in ("/api/version", "/api/tags")     # 这两条是转发给 Ollama 的
            if depends and not upstream_ok:
                skip(f"{path} 可访问", "Ollama 没在跑")
                continue
            try:
                st3, body = fetch(base, path)
                rec(f"{path} 可访问", st3 == 200 and len(body) > 0, f"{len(body)} 字符")
            except Exception as e:
                rec(f"{path} 可访问", False, type(e).__name__)

        # 幂等：把设置写回它**原本的值**（不改动用户状态）
        def cur(name: str, default: str) -> str:
            f = ROOT / "_备份" / name
            try:
                return f.read_text(encoding="utf-8-sig").strip() or default
            except Exception:
                return default

        mode = cur("网关思考模式.txt", "auto")
        bud = cur("本地思考预算.txt", "400")
        temp = cur("网关温度.txt", "auto")
        # ⚠️ 这一条原来**写死 `act=rec_on`**（不是"写回原值"）—— 与文件头"只读不改 ✓"自相矛盾：
        #    用户一旦把「记录过程」关掉，跑一次验收就会**静默把它打开**。
        #    2026-10-11 修：按 `_备份\思考过程记录.txt` 的现值回写
        #    （网关侧认的两个动作见 ollama_gateway.py 的 `act in ("rec_on", "rec_off")`）✓
        rec_now = cur("思考过程记录.txt", "on").strip().lower()
        log_act = "rec_off" if rec_now in ("off", "false", "0", "no", "关") else "rec_on"
        rec("POST /__think（写回原值）", post(base, "/__think", f"mode={mode}".encode()) == 302)
        rec("POST /__budget（写回原值）", post(base, "/__budget", f"n={bud}".encode()) == 302)
        rec("POST /__temp（写回原值）", post(base, "/__temp", f"v={temp}".encode()) == 302)
        rec(f"POST /__thinklog（写回原值：{log_act}）",
            post(base, "/__thinklog", f"act={log_act}".encode()) == 302)

        # ── 4 真发一条聊天 ─────────────────────────────────
        #
        # 当前默认走 llama.cpp；Ollama 仅保留给显式指定旧上游的兼容验收。
        # Ollama 兼容模式要尽量复用已加载模型，避免验收时改变用户现场。
        preheat = cur("预热模型.txt", "") if args.upstream == "ollama" else ""
        if args.no_chat:
            print("  ℹ️ --no-chat：跳过「真发一条聊天」（不会动你加载的模型）", flush=True)
        elif not upstream_ok:
            skip("真发一条聊天能拿到正文", "上游没在跑")
        else:
            # 现在只有 lc-35b（llama.cpp 一进程一模型）；Ollama 模式下才用 ps/预热名
            chat_model = ("lc-35b" if args.upstream == "llamacpp"
                          else (ps_start or preheat or "lc-35b"))
            if not preheat or chat_model == preheat:
                print(f"  ℹ️ 本次聊天用的模型 = {chat_model}（预热的是 {preheat or '未设置'}）",
                      flush=True)
            else:
                print(f"  ⚠️ 本次聊天用的模型 = {chat_model}（预热的是 {preheat}）"
                      f"　—— 和预热的不一样，跑完你的预热可能被顶掉！", flush=True)
            body = json.dumps({"model": chat_model, "max_tokens": 64,
                               "messages": [{"role": "user", "content": "只回两个字：在的"}]}).encode()
            try:
                t1 = time.time()
                r = urllib.request.urlopen(
                    urllib.request.Request(base + "/v1/chat/completions", data=body,
                                           headers={"Content-Type": "application/json"}),
                    timeout=CHAT_TIMEOUT)
                raw = r.read().decode("utf-8", "replace")
                text = ""
                if raw.lstrip().startswith("data:"):
                    for line in raw.split("\n"):
                        if line.startswith("data: ") and "[DONE]" not in line:
                            try:
                                d = json.loads(line[6:])
                                text += ((d.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                            except Exception:
                                pass
                else:
                    try:
                        text = ((json.loads(raw).get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                    except Exception:
                        pass
                rec("真发一条聊天能拿到正文", bool(text.strip()) and r.status == 200,
                    f"{len(text)} 字 ｜ {time.time()-t1:.1f} 秒 ｜ {chat_model}")
            except Exception as e:
                rec("真发一条聊天能拿到正文", False, f"{type(e).__name__}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    # ── 4.5 温和回归提醒：本测试有没有把你的模型顶掉（**不判失败**）──────
    #     只在"跑之前已经加载着模型"时才真的有话可说 —— 那是用户的预热成果。
    #     不判失败的理由：本脚本验的是**页面/接口**，显存里是谁不该让它变红 ✓
    if args.upstream == "ollama" and ollama_up:
        ps_end = api_ps()
        if not ps_start:
            print(f"  ℹ️ 跑之前没有模型加载；跑完加载的是 {ps_end or '(无)'}（正常，不算失败）",
                  flush=True)
        elif ps_end == ps_start:
            print(f"  ✅ 跑完加载的仍是 {ps_end} —— 你的预热没被顶掉", flush=True)
        else:
            print(f"  ⚠️ 已加载的模型被换过：{ps_start} → {ps_end or '(无)'}"
                  f"　⇒ 下一条消息要重读模型（35B 冷启动 16~38 秒）。"
                  f"**这不是测试失败**，但你的预热被顶掉了。", flush=True)

    # ── 汇总 ───────────────────────────────────────────────
    bad = [r for r in RESULTS if not r[1]]
    print("=" * 62)
    print(f"  共 {len(RESULTS)} 项 ｜ 通过 {len(RESULTS)-len(bad)} ｜ 失败 {len(bad)}"
          + (f" ｜ 跳过 {len(SKIPPED)}" if SKIPPED else ""))
    if bad:
        print("  失败项：")
        for n, _, d in bad:
            print(f"    ✗ {n}" + (f"（{d}）" if d else ""))
    print("=" * 62)
    print("  ⇒ " + ("✅ 全过：这个改动可以合" if not bad else "❌ 不许合：先把上面的失败项修掉"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
