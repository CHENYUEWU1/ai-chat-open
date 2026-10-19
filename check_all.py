#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
一条命令跑完**全部只读校验** —— 不用再一条一条敲。

为什么需要（这个项目上真实发生过的事）：
    接手的新 AI 窗口想确认状态时，会**自己一条一条试**：
    先猜有哪些脚本、再猜有没有 `--check`、再猜输出算不算"正常"。
    结果是"每次都运行很久，而且看不出它在干什么"，而它自己也未必查全。
    这里把**该查的一次列全、结果压成一行一条**。

设计原则：
    1. **全部只读。** AstrBot / Ollama 开着也能跑，不会改任何文件。
    2. **一条一行。** 通过就一行 ✅，不通过才把细节打出来 —— 让"看结果"这件事变便宜。
    3. **不碰 GPU。** 故意不含 `test_persona_tokens.py`（那个要加载 5.6 GB 模型，
       而且要跟 AstrBot 抢缓存，可能几十秒没反应）。要量体积单独跑它。
    4. **失败必须能被发现。** 任一检查非零退出 → 本脚本也非零退出。

用法：
    python check_all.py            # 摘要
    python check_all.py -v         # 每条都打印完整输出
"""

import hashlib
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from console_utf8 import console_utf8

console_utf8()   # 中文 Windows 控制台是 GBK，见 console_utf8.py

ROOT = Path(__file__).resolve().parent

# 项目根标志文件 —— 在包里误跑时能分辨出来（和 scripts_sync.py 用同一招）
ROOT_MARKER = "启动AstrBot.bat"

# (显示名, 参数, 这一条在查什么, 指定解释器（可选）)
# AstrBot 自带的 python 里才有 bs4 / httpx（抓网页的安全测试要用）
ASTRBOT_PY = ROOT / "AstrBot" / "AstrBot_4.28.1_windows_amd64_portable" / "backend" / "python" / "python.exe"
CHECKS = [
    ("时间补丁",        ["patch_astrbot_time.py", "--check"],
     "时间注入格式补丁还在不在（AstrBot 升级会覆盖）"),
    ("Telegram 代理补丁", ["patch_astrbot_telegram.py", "--check"],
     "Telegram 单独走代理的补丁还在不在"),
    ("关定时任务工具",  ["patch_astrbot_cron.py", "--check"],
     "future_task 那个英文工具说明关没关（它会让中文人设念英文台词，见坑 40）"),
    ("读网页插件",      ["install_fetch_plugin.py", "--check"],
     "fetch_url 插件装没装"),
    ("人格生成物",      ["build_personas.py", "--check"],
     "personas\\ 里的生成物 与 _源文件\\ 是否逐字一致"),
    ("脚本/Modelfile 镜像", ["scripts_sync.py", "--check"],
     "根目录 ↔ scripts\\ ↔ 交付包\\scripts\\ / model-config\\ 三处是否一致"),
    ("文档分栏",        ["organize_package.py", "--check"],
     "给AI看的 / 给我看的 两个文件夹就位、没有悬空引用"),
    ("交付包 zip",      ["build_package_zip.py", "--check"],
     "zip 与 交付包\\ 目录是否逐文件一致"),
    ("AstrBot 配置",    ["astrbot_setup.py", "--check"],
     "模型 / 人格 / 上下文窗口一致性 / 是否逐字导入（只读，可在运行时跑）"),
    ("抓网页安全",      ["plugins\\astrbot_plugin_fetch_url\\test_fetch_safety.py"],
     "内网防护有没有被 DNS 重绑定绕过（不联网、不碰人格，见 2026-10-03 修复）",
     str(ASTRBOT_PY)),
]


def check_page_js() -> tuple[bool, str]:
    r"""**自带网页的脚本不能有"跨行字符串"**（2026-10-05 踩到，代价极大）。

    起因：`gateway_page.py` 里 `PAGE` 是**普通三引号字符串**（不是 raw），
    所以在源码里写 `'\n'` 会被 Python 变成**真换行**；而 `<script>` 里一个单引号字符串
    跨了行 = **语法错误** ⇒ **整段脚本一行都不执行**。现象是：所有按钮点了没反应、
    资源面板停在那儿、任何浏览器都不跑（很容易误判成"浏览器把脚本删了/JS 关了"）。

    这里不依赖 Node，只用最朴素的判据：**`<script>` 里每一行的单引号必须是偶数个**
    （合法写法都是 `'…' + '…'` 拼起来，单行内必然成对；跨行才会出现奇数）。
    """
    src = ROOT / "gateway_page.py"
    if not src.exists():
        return False, "找不到 gateway_page.py"
    txt = src.read_text(encoding="utf-8", errors="replace").splitlines()
    inside, bad = False, []
    for n, line in enumerate(txt, 1):
        if line.startswith("<script>"):
            inside = True
            continue
        if line.startswith("</script>"):
            inside = False
            continue
        if inside and line.count("'") % 2 == 1:
            bad.append(n)
    if bad:
        head = ", ".join(str(x) for x in bad[:8])
        return False, (f"PAGE 里这些行的单引号是奇数个（字符串跨行了，浏览器会整段脚本作废）："
                       f"行 {head}{' …' if len(bad) > 8 else ''}")
    return True, "PAGE 脚本里没有跨行字符串（每行单引号成对）"


def check_page_js_served() -> tuple[bool, str]:
    r"""**在真页面上**再验一次：请求网关首页，把 `<script>` **原样**抽出来交给 Node 查语法。

    ⚠️ 关键是"**原样**"：我先前那个临时抽取脚本会做反转义，把真换行又变回 `\n`，
    于是 `node --check` 一路绿灯、而浏览器一路报错 —— 这个坑就是这么藏了三轮。
    网关没起来 / 没有 Node 时**跳过**（返回 True，不阻塞 check_all）。
    """
    import shutil
    import urllib.request
    if not shutil.which("node"):
        return True, "没有 node，跳过（上面那条静态检查仍然生效）"
    try:
        html = urllib.request.urlopen("http://127.0.0.1:11435/", timeout=5) \
            .read().decode("utf-8", "replace")
    except Exception:
        return True, "网关没在跑，跳过（上面那条静态检查仍然生效）"
    i, j = html.find("<script>"), html.find("</script>")
    if i < 0 or j < 0:
        return False, "页面里找不到 <script> 块"
    js = html[i + 8:j]
    tmp = ROOT / "_备份" / "_page_check.js"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(js, encoding="utf-8", newline="")
    import subprocess
    p = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    if p.returncode == 0:
        return True, f"真页面脚本语法 OK（{len(js)} 字符）"
    first = (p.stderr or "").strip().splitlines()
    return False, "真页面脚本语法错误：" + (first[0] if first else "?")


def check_persona_db() -> tuple[bool, str]:
    r"""库里的人格 与 磁盘生成物 是否一致（**这条是补的漏**）。

    为什么必须单独查这一条：
        前面所有检查都是**磁盘 ↔ 磁盘**。而 AstrBot 的界面（WebUI `#/config`
        的人格页）改的是**数据库** `AstrBotData\data\data_v4.db` 的 `personas` 表，
        **完全不碰磁盘文件**。
        于是会出现"用户以为改好了、文件却一个字没变"，而所有校验全绿 ——
        2026-09-24 真发生过：用户在界面里加了 9 个词，
        磁盘 `_源文件\_核心.txt` 时间戳还是上一次 AI 改的，扫描全找不到。

    ⚠️ 只读。发现漂移时**不自动修** —— 因为两边都可能是"更新的那一份"，
        `astrbot_setup.py` 会用磁盘版**覆盖**界面版，选错了就丢用户的改动。
        细节（含两边的导出命令）见 06 §9.4。
    """
    db = ROOT / "AstrBotData" / "data" / "data_v4.db"
    if not db.exists():
        # ⚠️ 2026-09-29 改：原来这里是 `return True, "（…跳过）"` —— **找不到库就判通过**。
        #    check_all 只允许在项目根跑（没有 ROOT_MARKER 会直接退出），
        #    所以"没有 data_v4.db"说明 AstrBot 从没起过或数据被搬走了 —— 那是**异常**，不是"跳过"。
        return False, f"找不到数据库 {db}（AstrBot 从没启动过，或数据目录被移走）"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = {r[0]: (r[1] or "") for r in
                    con.execute("SELECT persona_id, system_prompt FROM personas")}
        finally:
            con.close()
    except Exception as e:                                   # 库被锁 / 表没了
        # ⚠️ 2026-09-29 改：原来返回 True（"跳过"）。
        #    "AstrBot 开着也能跑"是这条的设计前提，读不到 = **这一项没校验**，
        #    不能算通过 —— 否则它永远是 ✅（这类"异常即通过"是 02 坑 40 那一族）。
        return False, f"读库失败，**这一项没校验成功**（不是通过）：{e}"

    bad: list[str] = []
    # ⚠️ 2026-09-29 改：**两个方向都要查**。
    #    原来只遍历库里的行 —— 于是"磁盘上新加了一份人格、但从来没导入过"
    #    这条完全看不见（反向只在 astrbot_setup 的 diff 里，而它原来也不报错）。
    disk_names = {p.stem for p in (ROOT / "personas").glob("*.txt")}
    for pid in sorted(set(rows) | disk_names):
        f = ROOT / "personas" / f"{pid}.txt"
        txt = rows.get(pid)
        if not f.exists():
            bad.append(f"{pid}：库里在、磁盘上没有（孤儿记录）")
            continue
        if txt is None:
            bad.append(f"{pid}：磁盘上有、**库里没有** —— 新加的人格忘了导入")
            continue
        disk = f.read_text(encoding="utf-8")
        # ⚠️ 必须比较 `rstrip()` 之后的 —— AstrBot 导入时会**吃掉末尾的换行**，
        #    实测：示例角色D 库 3604 / 磁盘 3605，逐字比第一处差异在第 3604 字符
        #    （库里没了结尾的 `\n`）。这是正常的规范化，不是漂移。
        if disk.rstrip() != txt.rstrip():
            # 报**两个方向的字符数差**，方便判断哪边更新
            bad.append(f"{pid}：库 {len(txt)} 字符 / 磁盘 {len(disk)} 字符"
                       f"（差 {len(txt) - len(disk):+d}）")
    if not bad:
        return True, f"（{len(rows)} 份：库与磁盘逐字一致）"
    return False, (
        "库与磁盘不一致（**别急着跑 astrbot_setup.py，它会用磁盘版覆盖界面版**）：\n"
        + "\n".join("           " + b for b in bad)
        + "\n           界面改过 → 先按 06 §9.4 导出，再合回 _源文件\\ 重建；"
          "\n           只想让磁盘版生效 → 跑 astrbot_setup.py（会覆盖界面版）。"
    )


def check_pkg_personas() -> tuple[bool, str]:
    r"""交付包 `personas\` 与当前人格库是否逐字一致（**这条也是补的漏**）。

    为什么必须单独查这一条：
        `build_package_zip.py` 打包的是**整个 `交付包\` 目录**，其中的
        `交付包\personas\` 是一份**手工同步的拷贝**（没有脚本会更新它）。
        于是"当前人格库改了、包里的还是旧版"这种漂移**不会报任何错** ——
        所有校验都会是绿的，因为它们查的是 zip ↔ 目录、库 ↔ 磁盘，
        **没有一条查 目录 ↔ 目录**。
        实测（2026-09-26）：包里躺着 11 份 —— 含 6 份已删除的病娇，
        以及"像人化改动之前"的示例角色B。**从交付包重建出来的机器会装到旧人格。**

    ⚠️ 比对时要**剥掉生成标记行**：
        `病娇-小九-*` 时代由 `build_personas.py` 生成，文件第一行是
        `# 自动生成的文件，别直接改。…`；而包里的拷贝是当初"导入时"存的、
        **没有这一行**。不剥掉的话，一份结构完好的旧拷贝会被误报成"内容不同"，
        而假警会让人干脆不看 `check_all.py`（见 organize_package.py 里同样的教训）。

    ⚠️ 只读。发现漂移时**不自动修** —— 修复动作是"用当前人格库覆盖包里的"，
        那会动交付包内容并让 zip 过期，应该由人确认后再跑。
    """
    root_p = ROOT / "personas"
    pkg_p = ROOT / "交付包" / "personas"
    if not pkg_p.is_dir():
        # ⚠️ 2026-09-29 改：原来返回 True（"跳过"）—— 于是**整个目录被删掉也全绿**：
        #    build_single_file 的附录 A 会变成"人格文件（0 套）"、zip 也少这 7 份，
        #    而 zip↔目录照样"一致"。缺目录是异常，不是"跳过"。
        return False, f"找不到 {pkg_p}（交付包里的人格目录没了，zip 会缺这一整块）"
    if not root_p.is_dir():
        return False, "找不到 personas\\（当前人格库）"

    mark = ("# 自动生成的文件，别直接改。改 personas\\_源文件\\ 里的源文件，"
            "再跑 build_personas.py\n")
    cur = sorted(p.stem for p in root_p.glob("*.txt"))
    bad: list[str] = []
    for p in sorted(pkg_p.glob("*.txt")):
        f = root_p / p.name
        if not f.exists():
            bad.append(f"{p.stem}：包里还在、当前人格库里已删（陈旧人格，会被打进 zip）")
            continue
        a = p.read_text(encoding="utf-8").replace(mark, "", 1).strip()
        b = f.read_text(encoding="utf-8").replace(mark, "", 1).strip()
        if a != b:
            bad.append(f"{p.stem}：包 {len(a)} 字符 / 当前 {len(b)} 字符"
                       f"（差 {len(a) - len(b):+d}）← 包里的旧了")
    have = {p.stem for p in pkg_p.glob("*.txt")}
    for n in cur:
        if n not in have:
            bad.append(f"{n}：当前库里有、包里没有")
    if not bad:
        return True, f"（{len(cur)} 份：与当前人格库逐字一致）"
    return False, (
        "交付包\\personas\\ 与当前人格库不一致（**zip 就是照这个目录打的**）：\n"
        + "\n".join("           " + x for x in bad)
        + "\n           同步：用当前 personas\\*.txt 覆盖 交付包\\personas\\，"
          "再跑 python build_package_zip.py 重打 zip。"
    )


def check_genui_patch() -> tuple[bool, str]:
    r"""WebUI 的「内联 HTML 卡片」是不是真被压住了（**这条查的是行为，不是文本**）。

    为什么必须单独查这一条：
        用户报的现象是"输出的时候出现独立窗口显示 html 码，TG 上不会，AstrBot 会"。
        根因是 WebUI 前端**写死**了 `enable_inline_genui: true`
        （`webui/assets/chatMarkdownComponents-*.js` 里的 `function be(...)`），
        服务端 `resolve_webchat_request_flags()` 里前端传的布尔值优先级最高，
        于是 `astr_main_agent.py` 把一段**英文** GenUI 系统提示拼进 system prompt，
        模型就开始吐 `<html-genui>` 卡片而不是台词。

    ⚠️ 为什么不用 `patch_astrbot_genui.py --check` 文本判断（那是**假绿**）：
        第一版补丁只改了默认值 `True → False`，文本判断全绿 ——
        **但一点用都没有**，因为前端永远显式传 true，默认值根本轮不到。
        所以这里直接 import 那个模块、拿"前端传 true"的 payload 跑一遍，
        看它到底返回什么。文本在、行为不对，照样判失败。

    ⚠️ 只读：import 一个 `request_flags.py` 不会启动 AstrBot，也不会碰配置/模型。
    """
    src = (ROOT / "AstrBot" / "AstrBot_4.28.1_windows_amd64_portable" / "backend"
           / "app" / "astrbot" / "core" / "platform" / "sources" / "webchat"
           / "request_flags.py")
    if not src.exists():
        return False, f"找不到 {src}（AstrBot 目录被挪了/改名了？）"

    raw = src.read_bytes()
    crlf = raw.count(b"\r\n")
    lone_lf = raw.count(b"\n") - crlf
    text = raw.decode("utf-8")
    if "patch_astrbot_genui.py" not in text:
        return False, ("补丁不在了（AstrBot 升级会覆盖源码）——"
                       "跑 python patch_astrbot_genui.py 重打")

    # 换行：AstrBot 源码是 CRLF，被重排成 LF 说明有人用 Path.read_text 覆写过
    # （见坑：read_text 会把 \r\n 归一成 \n，patch 脚本必须用 read_text_raw）
    if lone_lf:
        return False, f"换行符被改坏了：CRLF={crlf} 裸LF={lone_lf}（应当全是 CRLF）"

    # 语法
    try:
        compile(text, str(src), "exec")
    except SyntaxError as exc:
        return False, f"语法错误：{exc}"

    # 行为：前端传 true 时必须返回 False（这就是用户看到卡片的直接原因）
    import importlib.util
    spec = importlib.util.spec_from_file_location("_dsh_rf_check", src)
    if spec is None or spec.loader is None:
        return False, "没法加载 request_flags.py（importlib 拿不到 loader）"
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        payload = {"flags": {"enable_inline_genui": True,
                             "enable_default_system_prompt": True,
                             "enable_streaming": True,
                             "enable_reasoning": True}}
        got = mod.resolve_webchat_request_flags(payload)["enable_inline_genui"]
    except Exception as exc:                       # noqa: BLE001 —— 只读检查，别炸整个 check_all
        return False, f"跑 resolve_webchat_request_flags 时出错：{type(exc).__name__}: {exc}"
    if got is not False:
        return False, ("前端传 true 时服务端仍放行（返回 True）——"
                       "WebUI 还会吐 <html-genui> 卡片，补丁等于没打")
    return True, "前端传 true 也会被压成 False（CRLF 完好、语法通过）"


# ⚠️ 2026-10-18：**开源版模式**。
#   开源仓库不含 AstrBot 运行时 / AstrBotData 数据库 / 交付包 personas 这些**私有素材**，
#   依赖它们的 4 项检查天然跑不了 ⇒ 当"跳过"处理，别让开源用户一上来就看到红色 ✗
#   只有项目根存在 `开源版.txt` 时才生效；私有仓库没有这个文件，行为不变 ✓
PUBLIC_MODE = (ROOT / "开源版.txt").exists()


def _is_missing(out: str) -> bool:
    r"""这条失败是不是"本机压根没有这份素材"（而不是检查不通过）✓"""
    head = (out or "").lstrip()
    return head.startswith(("找不到", "超时"))


def run(args: list[str], python: str | None = None,
        timeout: float = 180) -> tuple[int, str]:
    r"""跑一个子脚本，返回 (退出码, 合并后的输出)。

    `python` 可以指定别的解释器（少数检查需要 AstrBot 自带的那套 python ——
    比如抓网页的安全测试要 `bs4`/`httpx`，系统装的 3.12 里没有）。

    ⚠️ **必须显式把子进程的 stdout 编码钉成 UTF-8**（`PYTHONIOENCODING`）。
    实测踩过：子进程的 stdout 是**管道**不是控制台，于是 Python 用**区域编码
    （本机 cp936）**写出去；父进程按 UTF-8 读 → 中文全变成替换字符，
    而控制台再一编码就成了 `?` —— 报错信息直接变成
    `[!] scripts\ ?????????????`，**等于没有报错信息**。
    这和 `console_utf8.py` 是两件事：那个只改 errors，不改 encoding。
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           # ⚠️ 2026-10-18 加：**子进程输出必须不缓冲**。
           #    原来没设这个 —— 一旦子进程卡住被超时杀掉，它打印过的内容
           #    还压在缓冲区里没吐出来 ⇒ 报「超时（>180s）」但**一个字都没有**，
           #    完全看不出卡在哪一步（用户那边就是这么遇到的）。
           #    加上它以后，超时也能拿到"最后跑到哪一行" ✓
           "PYTHONUNBUFFERED": "1",
           # ⚠️ 2026-10-18 加：过一段时间自动打印**所有线程栈**。
           #    只靠"最后打印到哪一行"分不清卡在事件循环、线程池握手、还是退出阶段；
           #    线程栈能直接看出"主线程在等 future / worker 线程在 queue.get" ✓
           "CHECK_ALL_DUMP_AFTER": f"{max(15.0, timeout * 0.5):g}"}
    exe = python or sys.executable
    started = time.time()
    try:
        p = subprocess.Popen(
            # ⚠️ 2026-10-18：走 `_stackdump_runner.py` 启动，它会在超时前自动打印
            #    **所有线程栈**（卡在 anyio 线程池握手这类问题只能靠栈定位）✓
            ([exe, "-u", str(ROOT / "_stackdump_runner.py"), str(ROOT / args[0])]
             if (ROOT / "_stackdump_runner.py").exists()
             else [exe, "-u", str(ROOT / args[0])]) + args[1:],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,      # 子进程绝不能等键盘输入（无终端时会一直等）
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        return 127, f"找不到脚本或解释器：{args[0]}"

    # ⚠️ 2026-10-18：**不再用 `communicate()`** —— 它会一直等到"管道 EOF"。
    #    如果有**孙进程**继承了 stdout（子进程已经退出了），EOF 永不到来 ⇒
    #    父进程会一直吊着，直到 180 秒超时，而且期间一个字都拿不到。
    #    改成：一个线程边读边攒 + `p.wait(timeout)` 只看**子进程**是否退出。
    #    子进程一退出就取走已读内容，立刻返回 ⇒ 这类"测试其实跑完了却卡住"直接消失 ✓
    sink: list[str] = []

    def _drain(pipe) -> None:
        try:
            for line in iter(pipe.readline, ""):
                sink.append(line)
        except Exception:                 # noqa: BLE001 —— 读失败不影响结论
            pass

    th = threading.Thread(target=_drain, args=(p.stdout,), daemon=True)
    th.start()
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        elapsed = time.time() - started
        alive = p.poll() is None
        _kill_tree(p.pid)
        th.join(timeout=3)
        partial = "".join(sink)
        where = ("① 子进程**还在运行**（没自己退出）⇒ 卡在它内部"
                 if alive else
                 "② 子进程**已经退出**，但输出管道没关 ⇒ 有孙进程继承 stdout")
        return 124, (
            f"超时（>{timeout:g}s，实际 {elapsed:.1f}s）：{args[0]}\n"
            f"  诊断：{where}\n"
            f"  已经打印出来的内容（{len(partial)} 字）：\n"
            f"  - - - - - - - - - - - - - - - - - - - - -\n"
            f"{(partial or '（一个字都没有 —— 卡在导入阶段或第一次 print 之前）').rstrip()}\n"
            f"  - - - - - - - - - - - - - - - - - - - - -"
        )
    th.join(timeout=2)                    # 给读取线程一点收尾时间（**不等管道 EOF**）
    return p.returncode, "".join(sink)


def _kill_tree(pid: int) -> None:
    r"""超时后连**孙进程**一起收掉（Windows 上 `terminate()` 只杀直接子进程）。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=20)
    except Exception:                       # noqa: BLE001 —— 清理失败不影响结论
        pass


def main() -> int:
    verbose = "-v" in sys.argv[1:] or "--verbose" in sys.argv[1:]

    if not (ROOT / ROOT_MARKER).exists():
        print(f"[X] 这里不像项目根（没有 {ROOT_MARKER}）")
        print(f"    本脚本要在 E:\\本地ai\\ 下跑。当前：{ROOT}")
        return 1

    print("=" * 66)
    print(f"  只读校验 · {ROOT}")
    print("=" * 66)

    failed: list[tuple[str, str]] = []
    for entry in CHECKS:
        name, args, what = entry[0], entry[1], entry[2]
        interp = entry[3] if len(entry) > 3 else None
        code, out = run(args, python=interp)
        if code == 0:
            print(f"  [OK] {name:<20} —— {what}")
            if verbose:
                for line in out.rstrip().splitlines():
                    print(f"       | {line}")
        elif PUBLIC_MODE and _is_missing(out):
            print(f"  [--] {name:<20} —— {what}（开源版：本机没有这项素材，跳过）")
        else:
            print(f"  [X ] {name:<20} —— {what}")
            failed.append((name, out))

    # 三条**本地函数**（不是子脚本）—— 见各自 docstring 为什么必须查
    LOCAL_CHECKS = [
        ("网页脚本跨行",     check_page_js,
         "PAGE 是普通字符串，写 \\n 会变成真换行 ⇒ <script> 里字符串跨行 = 整段脚本作废"),
        ("真页面脚本语法",   check_page_js_served,
         "请求网关首页、**原样**抽 <script> 交给 node --check（防「抽取时反转义」骗过检查）"),
        ("人格库 vs 磁盘",   check_persona_db,
         "界面改过的那份有没有和磁盘漂移"),
        ("交付包 personas",  check_pkg_personas,
         "包里的拷贝有没有落后于当前人格库（zip 照这个目录打）"),
        ("关内联HTML卡片",   check_genui_patch,
         "WebUI 前端写死传 true，服务端这一层压不住就会吐 HTML 卡片"),
    ]
    for label, fn, what in LOCAL_CHECKS:
        # ⚠️ 2026-09-29 加 try：本地检查任一抛异常，原来会让整个 check_all
        #    以 traceback 结束 —— 后面几项不跑、连汇总都没有，
        #    和"失败必须能被发现"的初衷相反。现在算这一项失败，继续跑其余的。
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"这一项自己崩了（{type(e).__name__}: {e}）"
        if ok:
            print(f"  [OK] {label:<20} —— {what}")
            if verbose:
                print(f"       | {detail}")
        elif PUBLIC_MODE and _is_missing(detail):
            print(f"  [--] {label:<20} —— {what}（开源版：本机没有这项素材，跳过）")
        else:
            print(f"  [X ] {label:<20} —— {what}")
            failed.append((label, detail))
    all_count = len(CHECKS) + len(LOCAL_CHECKS)

    print("-" * 66)
    if not failed:
        print(f"  [OK] {all_count} 项全部通过")
        print()
        print("  这套校验**不碰 GPU**；要量人格体积另跑：")
        print("      python test_persona_tokens.py --ratio")
        return 0

    print(f"  [X] {len(failed)} / {all_count} 项没过：{', '.join(n for n, _ in failed)}")
    for name, out in failed:
        print()
        print(f"----- {name} 的完整输出 -----")
        print(out.rstrip())
        print("-" * 30)
    print()
    print("  这些检查都是**只读**的。要修，看对应脚本文件头的说明；")
    print("  注意：能自动修的那几个脚本，**不带 --check 跑就是修**。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
