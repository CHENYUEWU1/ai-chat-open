# -*- coding: utf-8 -*-
r"""可选的 Ollama 模型预热工具。

它向本机 Ollama 发送一个最小请求，让模型提前载入并按 keep-alive 保持一段时间。
基础聊天和网关启动不需要这个脚本。使用示例：python warmup.py --model qwen3.5:4b
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

WARM_MODEL = os.environ.get("LOCAL_AI_WARM_MODEL", "qwen3.5:4b")
WARM_KEEP_ALIVE = "30m"
if os.environ.get("LOCALAPPDATA"):
    _default_data_dir = Path(os.environ["LOCALAPPDATA"]) / "LocalAI-Assistant"
else:
    _default_data_dir = Path.home() / ".local" / "share" / "local-ai-assistant"
DATA_DIR = Path(os.environ.get("LOCAL_AI_DATA_DIR", str(_default_data_dir))).expanduser()
WARM_MODEL_FILE = DATA_DIR / "state" / "warm_model.txt"


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

    say(f"[预热] 正在载入 {args.model}…")
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
