#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Ollama 卡死了怎么办 —— 一条命令复位。**AstrBot 不用关。**

症状（三条里中任意一条就是这个病）：
    - `ollama ps` 挂着不返回（最常见的判据）
    - 明明没在聊天，显存里却**没有**模型（`nvidia-smi` 只看到桌面那 1.8 GB）
    - 测试脚本"一直卡住"，没有任何输出 —— 因为请求在服务端排队，永远轮不到

为什么会这样（诚实版）：
    **根因没有确证。** 观察到的是 ollama 服务进程本身不响应，
    连 `/api/tags` 都可能不答；此时没有 `llama-server.exe` 子进程。
    已知会踩到它的场景：另一个客户端（AstrBot）正占着同一张 8 GB 显卡，
    而测试脚本又发请求 —— 加载/卸载 5.6 GB 模型时容易挤在一起。
    **但这不是定论**，所以本脚本只做"杀掉重开"，不假装知道原因。

用法：
    python fix_ollama.py            # 复位（杀 ollama + llama-server，重启 serve，等就绪）
    python fix_ollama.py --check    # 只体检，不动任何东西（只读）
    python fix_ollama.py --quiet    # 复位，少打印

⚠️ 本脚本**不碰 AstrBot**。要把 AstrBot 也停掉（打游戏前释放显存）用「停止模型.bat」。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

ROOT = Path(r"C:\LocalAI-Assistant")
OLLAMA = ROOT / "ollama" / "ollama.exe"

# ⚠️ 必须和「启动AstrBot.bat」里那几项一致，否则模型库/显存设置会不一样
ENV = {
    "OLLAMA_MODELS": str(ROOT / "models"),
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
    "OLLAMA_HOST": "127.0.0.1:11434",
}

sys.path.insert(0, str(ROOT))
from ollama_guard import PROBE_TIMEOUT, doctor   # noqa: E402


def running() -> list[str]:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/NH"],
        capture_output=True, text=True, errors="replace").stdout
    names = []
    if "ollama.exe" in out.lower():
        names.append("ollama.exe")
    out2 = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"],
        capture_output=True, text=True, errors="replace").stdout
    if "llama-server.exe" in out2.lower():
        names.append("llama-server.exe")
    return names


def kill(names: list[str]) -> None:
    for n in names:
        # ⚠️ 不能只杀 ollama.exe —— llama-server.exe 是它的子进程，会留下来当孤儿
        #    （02 坑 17）。两个都点名杀。
        subprocess.run(["taskkill", "/F", "/IM", n, "/T"],
                       capture_output=True, text=True, errors="replace")


def start() -> None:
    env = {**os.environ, **ENV}
    subprocess.Popen([str(OLLAMA), "serve"], env=env,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_ready(limit: float = 40.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < limit:
        if doctor(timeout=3)["alive"]:
            return True
        time.sleep(1.5)
    return False


def main() -> int:
    args = sys.argv[1:]
    quiet = "--quiet" in args

    if "--check" in args:
        d = doctor()
        if d["alive"]:
            loaded = ", ".join(d["loaded"]) or "（还没加载模型）"
            print(f"[OK] Ollama 正常（{d['ms']} ms）｜已加载：{loaded}")
            return 0
        print(f"[X] Ollama 卡死或没启动（等了 {PROBE_TIMEOUT} 秒：{d['err']}）")
        print(f"    复位：python {ROOT}\\fix_ollama.py")
        return 1

    before = doctor()
    if before["alive"] and not quiet:
        print(f"[i] 复位前 Ollama 是**能应答**的（{before['ms']} ms）"
              f"｜已加载：{', '.join(before['loaded']) or '无'}")
        print("    如果测试还是卡，那问题不在这里 —— 看是不是单条请求太慢"
              "（那属于模型/显存，不是服务卡死）。")

    names = running()
    if not quiet:
        print(f"[1/3] 停掉：{', '.join(names) if names else '（本来就没在跑）'}")
    kill(["ollama.exe", "llama-server.exe"])
    time.sleep(3)

    if not OLLAMA.exists():
        print(f"[X] 找不到 {OLLAMA}")
        return 1
    if not quiet:
        print("[2/3] 重新启动 ollama serve（模型库 / 显存设置与启动脚本一致）")
    start()

    if not quiet:
        print("[3/3] 等它应答 ...")
    if wait_ready():
        d = doctor()
        print(f"[OK] Ollama 已复位（{d['ms']} ms）｜已加载："
              f"{', '.join(d['loaded']) or '（还没加载模型，第一次聊天会慢）'}")
        print("     接着可以重跑刚才那个测试了。")
        return 0

    print("[X] 重启后 40 秒内还是没应答。")
    print("    下一步：双击「停止模型.bat」全部停掉，再双击「启动AstrBot.bat」重来一次。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
