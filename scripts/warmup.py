# -*- coding: utf-8 -*-
r"""开机预热：启动脚本里先把模型读进来、并保温（2026-10-08 加，用户选的"方案 C"）。

为什么需要它：
  · 35B 冷启动要约 **30 秒**，而手机 App 的请求超时只有 **20~30 秒**（源码写死）
    ⇒ 停一会儿再聊，第一条常被掐掉（表现成「发两句话才回一句」）。
  · Ollama 默认**空闲 5 分钟**就卸载模型。

这里做的事：等 Ollama 起来 ⇒ 发一个最小请求把模型读进来 ⇒ 带 `keep_alive` 保温
（实测 **`/api/generate` 认这个字段 ✓**，而 `/v1/chat/completions` 不认 ✗ —— 所以用原生接口）。

想热身的模型换一个：改 `WARM_MODEL`，或 `python warmup.py --model xiaojiu9b:latest`。
不想用：启动脚本里把那行 `start ... warmup.py` 删掉即可（或 `--quiet` 让输出更少）。
"""
import argparse
import json
import sys
import time
import urllib.request

WARM_MODEL = "qwen36-35b-uncensored:latest"     # 兜底默认；**网页上选过的会优先**（见 _chosen）
WARM_KEEP_ALIVE = "30m"
WARM_MODEL_FILE = r"E:\本地ai\_备份\预热模型.txt"     # 网关网页「🔥 开机预热」写的就是它


def _chosen() -> str:
    r"""网页上选的模型优先（网关那张卡片点一下就写进这个文件）。"""
    try:
        with open(WARM_MODEL_FILE, encoding="utf-8-sig") as f:
            v = f.read().strip()
        if v:
            return v
    except Exception:
        pass
    return WARM_MODEL


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="")      # 空 = 自动（网页选的 > 常量）
    ap.add_argument("--keep-alive", default=WARM_KEEP_ALIVE)
    ap.add_argument("--wait", type=float, default=90.0, help="等 Ollama 起来的秒数上限")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.model:
        args.model = _chosen()

    def say(s):
        if not args.quiet:
            print(s, flush=True)

    t0 = time.time()
    while time.time() - t0 < args.wait:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2):
                break
        except Exception:
            time.sleep(1.0)
    else:
        say("[预热] Ollama 还没起来，跳过（不影响使用）")
        return 0

    say(f"[预热] 正在把 {args.model} 读进显存…（35B 约 30 秒，9B 约 10 秒）")
    body = json.dumps({"model": args.model, "prompt": "hi", "stream": False,
                       "options": {"num_predict": 1},
                       "keep_alive": args.keep_alive}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        t1 = time.time()
        with urllib.request.urlopen(req, timeout=900) as r:
            json.loads(r.read().decode("utf-8", "replace"))
        say(f"[预热] 好了：用时 {time.time() - t1:.0f} 秒，保温 {args.keep_alive}"
            f"（这期间聊天不用等冷启动）")
    except Exception as e:
        say(f"[预热] 没成功（不影响使用）：{type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
