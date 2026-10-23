# -*- coding: utf-8 -*-
r"""预热脚本（2026-10-22 重写：Ollama 已弃用，改成给 llama.cpp 热身）。

现在默认上游是 **llama.cpp**（llama-server 一启动就把模型读进来了，不存在"空闲卸载"），
所以这个脚本的作用只剩两件：
  1. 等 llama-server 就绪（它可能还在加载 10.86 GB 的 gguf）；
  2. 发一条最小请求，把**首次请求要编译的图/CUDA 上下文**提前走一遍
     （实测首次请求比后续慢 2~10 秒，跑一下能让用户第一次点发送就快）。

沿用旧接口：`python warmup.py --quiet`，失败也只打印一行，**不阻塞启动脚本** ✓
"""
import argparse
import json
import time
import urllib.request

LLAMA_BASE = "http://127.0.0.1:11450"
OLLAMA_BASE = "http://127.0.0.1:11434"
WARM_MODEL = "lc-35b"


def _get(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _up(base: str) -> bool:
    try:
        return bool(_get(base + "/v1/models", 2.0))
    except Exception:
        return False


def warm_llamacpp(quiet: bool) -> int:
    t0 = time.time()
    while time.time() - t0 < 180:
        if _up(LLAMA_BASE):
            break
        if not quiet:
            print("   …等 llama.cpp 就绪", flush=True)
        time.sleep(3)
    else:
        print("[预热] llama.cpp 180 秒还没就绪，跳过")
        return 1
    body = json.dumps({"model": WARM_MODEL, "max_tokens": 8, "stream": False,
                       "messages": [{"role": "user", "content": "在吗"}],
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    t1 = time.time()
    try:
        req = urllib.request.Request(LLAMA_BASE + "/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()
        print(f"[预热] llama.cpp 已热身（{time.time()-t1:.1f} 秒）")
        return 0
    except Exception as e:
        print(f"[预热] 请求失败：{type(e).__name__}（不影响使用）")
        return 1


def warm_ollama(quiet: bool) -> int:
    r"""老路径：某天又把 Ollama 起回来时才用得到 ✓"""
    body = json.dumps({"model": "local-assistant-35b:latest", "prompt": "在吗",
                       "stream": False, "keep_alive": "30m",
                       "options": {"num_predict": 8}}).encode()
    try:
        req = urllib.request.Request(OLLAMA_BASE + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()
        print("[预热] Ollama 已热身（keep_alive 30m）")
        return 0
    except Exception as e:
        print(f"[预热] Ollama 失败：{type(e).__name__}（不影响使用）")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--model", default="", help="兼容旧参数，已忽略（llama.cpp 一进程一模型）")
    a = ap.parse_args()
    if _up(LLAMA_BASE):
        return warm_llamacpp(a.quiet)
    if _up(OLLAMA_BASE):
        return warm_ollama(a.quiet)
    print("[预热] 11450 / 11434 都没在跑，跳过（先双击 启动局域网API.bat）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())