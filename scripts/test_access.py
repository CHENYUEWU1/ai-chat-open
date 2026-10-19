# -*- coding: utf-8 -*-
r"""访问授权 + 授权管理的验收测试（2026-10-06）。

覆盖：
  ① 未授权：只能看到"输授权码"，看不到模型/人格/资源/授权码/设备表
  ② 不受影响：APK 下载、API（/v1 /api）、本机
  ③ 输对码 ⇒ 302 + 一年期 cookie（会话 token）
  ④ 退出授权 / 伪造 cookie / 改一位
  ⑤ 防爆破：连错 5 次锁定（锁定期内正确码也拒）
  ⑥ 管理界面：已授权设备能看到入网码 +「📱 生成手机授权码」+ 设备表；未授权什么都看不到
  ⑦ 逐个解除：解除别的设备后它立刻失效、自己还能用；解除自己会清 cookie
  ⑧ 换入网码：**已授权设备不受影响**（会话与入网码解耦）
  ⑨ 解除全部：所有会话立即失效

用法：
    python test_access.py                  # 打本机 11435（平时那个）；局域网地址**自动认本机 IP**
    python test_access.py --port 11436     # 打测试实例
    python test_access.py --destructive    # 额外跑⑤（锁 5 分钟）和⑨（踢掉所有已授权设备）
    python test_access.py --allow-code-change   # 额外跑⑧（真的换掉入网码）

⚠️ **默认是安全的**：不锁 IP、不踢设备、不换码，而且跑完会**清理自己新建的会话**
   （只删测试建的，用户手机上的一律不碰）。
⚠️ 别再用 `--host 192.168.x.x` 写死地址：这台机器走 DHCP，**换网后旧 IP 会连不上**，
   表现成"每个请求等 40 秒、十几分钟没结果"（2026-10-08 踩过）。
"""
import argparse
import http.cookiejar
import io
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ACCESS_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关访问码.txt")
SESSION_FILE = Path(r"C:\LocalAI-Assistant\_备份\网关授权设备.json")
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name} {extra}")
    else:
        fail += 1
        print(f"  ❌ {name} {extra}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


NO_REDIRECT = urllib.request.build_opener(NoRedirect)
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def detect_lan_ip() -> str:
    r"""本机当前的局域网 IP。

    为什么要这个（2026-10-08 踩到）：这台机器走 DHCP，**换网/换路由器后 IP 会变**
    （`<你的电脑IP>` → `<你的电脑IP>`）。测试默认写死旧 IP 时，每个请求都要等
    40 秒连接超时（25 项 ≈ 十几分钟）—— **看起来像"卡死"，其实是地址过期了**。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # 不发包，只为让系统选出口 ⇒ 拿到本机 IP
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    finally:
        s.close()
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if ip.startswith(("192.168.", "10.", "172.")):
            return ip
    return "127.0.0.1"


def main() -> int:

    # ---- 2026-10-09 加：先确认网关在跑，否则别产出 27 个假失败 ✗ ----
    import socket as _sock
    def _up(p=11435):
        try:
            with _sock.create_connection(("127.0.0.1", p), timeout=1.5):
                return True
        except Exception:
            return False
    if not _up():
        print("  ❌ 网关（11435）没在跑 ⇒ 先双击 启动局域网API.bat（或 python ollama_gateway.py）再跑本测试。")
        print("     （这里直接退出，避免产出几十条假失败 ✗）")
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="auto",
                    help="局域网地址；默认 auto = 自动认本机当前 IP"
                         "（DHCP 换网后旧 IP 会连不上，表现成『卡住』）")
    ap.add_argument("--port", type=int, default=11435)
    ap.add_argument("--destructive", action="store_true",
                    help="额外跑那两段**会改动别人状态**的测试："
                         "⑤ 连错 5 次锁定（把本机 IP 锁 5 分钟，期间手机也输不进码）、"
                         "⑨ 解除全部设备（把你手机上已授权的设备全踢掉，得重新输一次入网码）。"
                         "**默认不跑** —— 所以默认跑完什么都不影响 ✓")
    ap.add_argument("--allow-code-change", action="store_true",
                    help="允许换掉入网码（⑧ 那段）。**默认不动码** —— 换完文件与实例内存会不一致，"
                         "还会把你手机上记着的码一起换掉")
    args = ap.parse_args()
    host = detect_lan_ip() if args.host in ("auto", "", None) else args.host
    lan = f"http://{host}:{args.port}"
    loc = f"http://127.0.0.1:{args.port}"

    if not ACCESS_FILE.exists():
        print("  ❌ 没有访问码文件（网关还没跑过？）：", ACCESS_FILE)
        return 1
    code = ACCESS_FILE.read_text(encoding="utf-8").strip()

    def get(base, path, opener=NO_REDIRECT, cookie=None, data=None, timeout=40, ua="test_access.py"):
        req = urllib.request.Request(base + path, data=data)
        if cookie:
            req.add_header("Cookie", cookie)
        req.add_header("User-Agent", ua)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
        except Exception as e:
            return -1, str(e), {}

    def auth(base=lan, ua="test_access.py"):
        st, _, hdrs = get(base, "/__auth?code=" + code, ua=ua)
        m = re.search(r"gw_auth=([0-9a-f]{8,});", hdrs.get("Set-Cookie", ""))
        return st, (m.group(1) if m else "")

    def session_tokens(base=loc):
        r"""当前会话表里的 token。

        本机访问**免授权** ⇒ 直接读控制台页面里的设备表就行（表格每行带 `name='tok' value='…'`）。
        用它做两件事：① 记下测试开跑前就有哪些会话；② 结尾**只清理本次新建的**。
        """
        _, h, _ = get(base, "/")
        return set(re.findall(r"""name=['"]tok['"] value=['"]([0-9a-f]{8,})['"]""", h))

    before = session_tokens()      # ⭐ 快照：这些是用户自己的会话，之后一个都不许动
    print(f"  访问码 = {code}   目标 {lan}")
    print(f"  测试前已有会话 {len(before)} 个（全程不碰它们）\n")

    print("① 未授权：只能看到「输授权码」，看不到任何数据")
    st, h, _ = get(lan, "/")
    check("GET / 有输入框", "需要授权" in h and 'name="code"' in h)
    check("没泄露模型名", "local-assistant-35b" not in h and "local-assistant-9b" not in h)
    check("没泄露人格名", "示例角色A" not in h and "外向-助手" not in h)
    check("没泄露入网码", code not in h)
    check("没泄露设备表", "已授权设备" not in h and "生成手机授权码" not in h)
    for p in ("/__stats", "/__personas", "/__ticket", "/__clientlog"):
        st, _, _ = get(lan, p)
        check(f"GET {p} 被挡（403）", st == 403, f"HTTP {st}")
    st, h, _ = get(lan, "/plain")
    check("GET /plain 只给授权页", "需要授权" in h and "资源" not in h)
    st, _, _ = get(lan, "/__revoke", data=b"all=1")
    check("未授权不能解除设备（403）", st == 403, f"HTTP {st}")

    print("\n② 不受影响：APK 下载、API、本机")
    for p in ("/api/version", "/api/tags", "/手机客户端-1.9.1-release.apk"):
        st, _, _ = get(lan, p)
        check(f"GET {p} 放行", st == 200, f"HTTP {st}")
    st, h, _ = get(loc, "/")
    check("本机 GET / 直接进控制台", "需要授权" not in h and "访问授权" in h)

    print("\n③ 输对授权码 ⇒ 302 + 一年期 cookie（会话 token）")
    st, tok = auth(ua="test_access.py/deviceA")
    check("返回 302", st == 302, f"HTTP {st}")
    check("拿到会话 token", len(tok) >= 16, f"token={tok[:10]}…")
    st, _, hdrs = get(lan, "/__auth?code=" + code, ua="deviceB")
    sc = hdrs.get("Set-Cookie", "")
    check("cookie 是 HttpOnly + 一年", "HttpOnly" in sc and "Max-Age=31536000" in sc, sc[:70])
    ckA = f"gw_auth={tok}"
    st, h, _ = get(lan, "/", cookie=ckA)
    check("带 cookie 进控制台", "需要授权" not in h and "访问授权" in h)
    check("带 cookie 看得到模型名", "local-assistant-35b" in h or "local-assistant-9b" in h)

    print("\n④ 退出授权 / 伪造 cookie")
    st, _, hdrs = get(lan, "/__auth?out=1", cookie=ckA)
    check("退出返回 302", st == 302, f"HTTP {st}")
    check("清 cookie（Max-Age=0）", "Max-Age=0" in hdrs.get("Set-Cookie", ""))
    for bad in ("gw_auth=deadbeef", f"gw_auth={tok[:-1]}x"):
        st, h, _ = get(lan, "/", cookie=bad)
        check(f"无效 cookie 被拒（{bad[:18]}…）", "需要授权" in h)
    _, tokA = auth(ua="deviceA2")          # ④ 把 A 退掉了，重新拿一个

    print("\n⑥ 管理界面（已授权设备才看得到）")
    # ⭐ ⑦ 要用"另一台设备"来试解除 —— 这里**自己造一台** deviceB。
    #    绝不从表里随便挑一个 ✗：表里那些多半就是用户自己的手机，踢掉他要重新授权。
    _, tokB = auth(ua="deviceB")
    ckA = f"gw_auth={tokA}"
    st, h, _ = get(lan, "/", cookie=ckA)
    check("显示入网码", code in h)
    check("显示「📱 生成手机授权码」按钮", "生成手机授权码" in h)
    check("显示设备表", "已授权设备" in h and "解除全部设备" in h)
    toks = re.findall(r"name='tok' value='([0-9a-f]+)'", h) or \
           re.findall(r'name="tok" value="([0-9a-f]+)"', h)
    check("表里能列出会话 token", len(toks) >= 2, f"共 {len(toks)} 行")
    check("本机访问码也在（本机免授权）", code in get(loc, "/")[1])

    print("\n⑦ 逐个解除")
    other = tokB        # ⚠️ 只解"自己刚造的 deviceB"，不碰用户手机上的会话
    if other:
        st, _, _ = get(lan, "/__revoke", cookie=ckA, data=f"tok={other}".encode())
        check("解除别的设备返回 302", st == 302, f"HTTP {st}")
        st, h, _ = get(lan, "/", cookie=f"gw_auth={other}")
        check("被解除的设备立刻要重新授权", "需要授权" in h)
        st, h, _ = get(lan, "/", cookie=ckA)
        check("自己不受影响", "需要授权" not in h)
    else:
        check("有第二台设备可解", False, "（没抓到其它 token）")
    st, _, _ = get(lan, "/__revoke", cookie=ckA, data=f"tok={tokA}".encode())
    st, h, _ = get(lan, "/", cookie=ckA)
    check("解除自己 ⇒ 自己也要重新授权", "需要授权" in h)
    _, tokA = auth(ua="deviceA3")
    ckA = f"gw_auth={tokA}"

    if args.allow_code_change:
        print("\n⑧ 换入网码：已授权设备不受影响")
        old = code
        st, _, _ = get(lan, "/__newcode", cookie=ckA, data=b"")
        check("换码返回 302", st == 302, f"HTTP {st}")
        time.sleep(0.3)
        new = ACCESS_FILE.read_text(encoding="utf-8").strip()
        check("入网码真的换了", new != old, f"{old} → {new}")
        st, h, _ = get(lan, "/", cookie=ckA)
        check("已授权设备照旧能进", "需要授权" not in h)
        st, _, hdrs = get(lan, "/__auth?code=" + old)
        check("旧入网码失效（新设备进不来）", "需要授权" in hdrs.get("Set-Cookie", "") or
              "gw_auth" not in hdrs.get("Set-Cookie", ""))
        # ⚠️ 不能把文件改回去：**实例内存里已经是新码**，改文件只会让两边不一致
        #    （这坑在 ⑨ 上踩过一次：改回旧码后，后面用旧码授权当然失败）。
        code = new
    else:
        print("\n⑧ 换入网码：**跳过**（默认不动码；要测就加 --allow-code-change）")
        print("     ⚠️ 换码后文件与实例内存会不一致，还会把你手机上记的码一起换掉 —— 所以默认跳过")
    print(f"     （入网码现在是 {code}，测试后半段都用它）")

    if args.destructive:
        print("\n⑨ 解除全部设备（--destructive）")
        st, _, _ = get(lan, "/__revoke", cookie=ckA, data=b"all=1")
        check("解除全部返回 302", st == 302, f"HTTP {st}")
        st, h, _ = get(lan, "/", cookie=ckA)
        check("全部解除后自己也失效", "需要授权" in h)
        st, h, _ = get(lan, "/", cookie=ckA)
        check("设备表已清空（重授权后看）", True)
        _, tokA = auth(ua="deviceA4")
        st, h, _ = get(lan, "/", cookie=f"gw_auth={tokA}")
        check("重新授权又是新会话", "需要授权" not in h and "已授权设备（1）" in h)
    else:
        print("\n⑨ 解除全部设备：**跳过**（默认不跑；要测就加 --destructive）")
        print("     ⚠️ 它会把**你手机上已授权的设备一起踢掉**，之后要重新输一次入网码")

    if args.destructive:
        print("\n⑤ 防爆破：连错 5 次锁定（--destructive；锁定期内正确码也拒）")
        for i in range(1, 7):
            st, h, _ = get(lan, f"/__auth?code=00000{i}")
            if i <= 4:
                check(f"第 {i} 次输错提示不对", "授权码不对" in h)
            else:
                check(f"第 {i} 次输错进入锁定", "输错太多次" in h)
        st, h, _ = get(lan, "/__auth?code=" + ACCESS_FILE.read_text(encoding="utf-8").strip())
        check("锁定期内正确码也被拒", "输错太多次" in h)
        st, h, _ = get(lan, "/", cookie=f"gw_auth={tokA}")
        check("锁定期不影响已授权设备", "需要授权" not in h)
    else:
        print("⑤ 防爆破锁定：**跳过**（默认不跑；要测就加 --destructive）")
        print("     ⚠️ 它会把本机 IP 锁 5 分钟，期间手机也输不进授权码")

    # ⭐ 自己清理：把本次测试**新建**的会话全部解除（用户原有的一个都不动）
    left = session_tokens() - before
    for t in left:
        get(loc, "/__revoke", data=f"tok={t}".encode())
    rest = session_tokens() - before
    print(f"\n  🧹 清理测试会话：本次新建 {len(left)} 个 → 残留 {len(rest)} 个"
          f"{'  ✅' if not rest else '  ⚠️ 还有残留，可手动在网页上解除'}")

    print(f"\n  当前入网码 = {ACCESS_FILE.read_text(encoding='utf-8').strip()}"
          f"（换过码就是这个新值）")
    print(f"  === 通过 {ok} / 失败 {fail} ===")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
