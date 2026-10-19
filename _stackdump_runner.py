r"""超时自动打印**所有线程栈**（check_all 的 run() 用它启动子脚本）。

为什么要它：用户那边「抓网页安全」卡在 `anyio.to_thread.run_sync` —— 假解析器是纯函数、
不发网络，所以卡的是**线程池握手**（worker 线程有没有起来 / future 有没有被回填）。
只看"最后打印到哪一行"分不清这几种情况，必须看线程栈 ✓

用法：
    python _stackdump_runner.py <脚本> [参数...]
环境变量：
    CHECK_ALL_DUMP_AFTER  多少秒后开始周期性 dump（0/空 = 不 dump）
"""
import faulthandler
import os
import runpy
import sys

_delay = 0.0
try:
    _delay = float(os.environ.get("CHECK_ALL_DUMP_AFTER", "0") or 0)
except ValueError:
    _delay = 0.0

if _delay > 0:
    # repeat=True：卡很久时会连续打几次，便于看出"一直卡在同一处"
    faulthandler.dump_traceback_later(_delay, repeat=True, exit=False)
    print(f"[stackdump] {_delay:g} 秒后开始打印所有线程栈（超时诊断用）", flush=True)

if len(sys.argv) < 2:
    print("[stackdump] 用法：python _stackdump_runner.py <脚本> [参数...]", file=sys.stderr)
    raise SystemExit(2)

_script = sys.argv[1]
sys.argv = sys.argv[1:]
try:
    runpy.run_path(_script, run_name="__main__")
finally:
    if _delay > 0:
        faulthandler.cancel_dump_traceback_later()
