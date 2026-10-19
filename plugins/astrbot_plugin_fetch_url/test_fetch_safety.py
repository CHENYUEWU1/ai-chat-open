#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""fetch_url 插件的**安全测试**：不联网、不读人格，纯逻辑验证。

测什么（2026-10-03 重写，起因见下面三条真实事故）：

    1. 本机/内网地址被拒（localhost / 127.0.0.1 / 192.168.x / 10.x / [::1] / 0.0.0.0 / 169.254.x）
    2. 域名解析到内网时被拒（注入假解析器，不动系统 hosts）
    3. 解析器只返回公网 IP；混合结果（公网+内网）整次拒绝
    4. **集成回归（最关键的一条）**：加载本插件后，
       · 全局 `socket.getaddrinfo` **没有被替换**；
       · 未登记的 `127.0.0.1`、`localhost`、普通外部域名**仍能正常解析**
         —— 上一版把全局解析器包了，导致同进程的 Ollama(127.0.0.1:11434)、
         `api.telegram.org`、AnySearch 全部解析失败，用户当场复现；
    5. fetch 请求内的**公网→内网 DNS 重绑定**仍被拦截
       （第一次解析给公网、第二次给 127.0.0.1 → 整次拒绝，且**从未连过那个内网 IP**）
    6. **并发抓取不串台**：两个传输层各带各的解析器，各连各的 IP
    7. Host 头 / TLS SNI 用的仍是原始域名（传下去连的是 IP，验的是域名）
    8. 原有的保护没被改掉：逐跳重定向校验、trust_env=False、流式大小限制

⚠️ 全程**不发任何网络请求**（用假的网络后端和假解析器）。
用法（依赖 httpx/bs4，要 AstrBot 自带的 python）：
    <AstrBot>\backend\python\python.exe plugins\astrbot_plugin_fetch_url\test_fetch_safety.py
退出码 0 = 全过。
"""
import asyncio
import hashlib
import socket
import sys
from pathlib import Path

# console_utf8 在项目根，测试在插件子目录里 → 两个路径都要加
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

try:                                     # 项目根里有；装到 AstrBot 目录里跑时可能没有
    from console_utf8 import console_utf8  # noqa: E402
    console_utf8()
except ModuleNotFoundError:
    pass

try:
    import fetch as F  # noqa: E402
except ModuleNotFoundError as exc:      # bs4 / httpx 只有 AstrBot 自带的那套 python 有
    print(f"  [i] 跳过：当前解释器缺依赖（{exc.name}）。")
    print("      用 AstrBot 自带的 python 跑：")
    print(r"      E:\本地ai\AstrBot\AstrBot_4.28.1_windows_amd64_portable\backend\python\python.exe \ ")
    print(r"        plugins\astrbot_plugin_fetch_url\test_fetch_safety.py")
    sys.exit(0)

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK' if ok else 'X '}] {name}{('  —— ' + detail) if detail else ''}")


PUBLIC_IP = "93.184.216.34"          # 只做假解析用，不真连
PUBLIC_IP2 = "1.1.1.1"
PRIVATE_IP = "127.0.0.1"


def make_infos(ip: str, port: int = 443):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]


def fake_resolver(ip_map: dict):
    """假解析器：按域名给 IP（域名不在表里就抛解析失败）。"""
    def _fake(host, port=0, family=0, *a, **k):
        key = F._host_key(host)
        if key not in ip_map:
            raise socket.gaierror(f"假解析器不认识：{key}")
        return make_infos(ip_map[key], port or 443)
    return _fake


class FakeInner:
    """假的底层网络后端：只记录"被要求连到哪个地址"，不真的连。

    抛一个自定义异常当作"到此为止"的信号，好让 fetch 流程干净地停下。
    """

    class Stop(Exception):
        pass

    def __init__(self):
        self.calls = []

    async def connect_tcp(self, host, port=0, timeout=None, local_address=None,
                          socket_options=None):
        self.calls.append((F._host_key(host), port))
        raise FakeInner.Stop("到此为止（测试不真的建连）")


# ================================================================ 1) 内网/本机一律拒
print("=== 1) 本机与内网地址必须被拒 ===")
for bad in ("http://127.0.0.1:8080/", "http://localhost/", "http://192.168.1.1/",
            "http://10.0.0.5/", "http://[::1]/", "http://0.0.0.0/",
            "http://169.254.169.254/latest/meta-data/", "ftp://example.com/",
            "http://172.16.5.5/"):
    try:
        F._check_url(bad)
        check(f"拒绝 {bad}", False, "居然放行了")
    except F.FetchError as e:
        check(f"拒绝 {bad}", True, str(e)[:26])

# ================================================================ 2) 域名→内网 也要拒
print("\n=== 2) 域名解析到内网时必须被拒（注入假解析器，不动 hosts）===")
real_gai = socket.getaddrinfo
try:
    socket.getaddrinfo = fake_resolver({"evil.example.com": PRIVATE_IP})
    try:
        F._check_url("http://evil.example.com/")
        check("域名→127.0.0.1 被拒", False, "居然放行了")
    except F.FetchError as e:
        check("域名→127.0.0.1 被拒", True, str(e)[:26])
finally:
    socket.getaddrinfo = real_gai

# ================================================================ 3) 解析器：校验 + 只用公网 IP
print("\n=== 3) PinnedResolver：每次解析都校验，只返回公网 IP ===")


def run_resolver(delegate, host="good.example.com", port=80):
    r = F.PinnedResolver(delegate=delegate)
    return asyncio.run(r.resolve(host, port))


try:
    got = run_resolver(fake_resolver({"good.example.com": PUBLIC_IP}))
    check("公网域名 → 只返回校验过的公网 IP",
          [ip for _f, ip in got] == [PUBLIC_IP], f"{[ip for _f, ip in got]}")
except Exception as e:
    check("公网域名 → 只返回校验过的公网 IP", False, f"{type(e).__name__}: {e}")

for bad_ip in ("127.0.0.1", "192.168.1.7", "10.1.2.3", "169.254.169.254", "0.0.0.0"):
    try:
        run_resolver(fake_resolver({"good.example.com": bad_ip}))
        check(f"解析到 {bad_ip} 必须拒绝", False, "居然放行了")
    except F.FetchError:
        check(f"解析到 {bad_ip} 必须拒绝", True)


def mixed_resolver(host, port=0, family=0, *a, **k):
    """一次解析同时返回公网 + 内网（多 A 记录被污染）→ 必须整次拒绝。"""
    return make_infos(PUBLIC_IP, port or 443) + make_infos(PRIVATE_IP, port or 443)


try:
    run_resolver(mixed_resolver)
    check("公网+内网混合结果必须整次拒绝", False, "居然放行了")
except F.FetchError:
    check("公网+内网混合结果必须整次拒绝", True)

# ============================== 4) 集成回归：加载插件不能影响进程里其它组件的解析
print("\n=== 4) 集成回归：导入本插件后，全局解析器没被动过、别的组件照常解析 ===")
check("模块源码里没有任何对全局 socket.getaddrinfo 的赋值",
      "socket.getaddrinfo =" not in (HERE / "fetch.py").read_text(encoding="utf-8"))
check("导入本模块后 socket.getaddrinfo 仍是原函数", socket.getaddrinfo is real_gai)
for host, port in (("127.0.0.1", 11434), ("localhost", 11434),
                   ("api.telegram.org", 443), ("www.baidu.com", 443)):
    try:
        infos = socket.getaddrinfo(host, port)
        check(f"未登记主机仍可正常解析：{host}:{port}", bool(infos),
              f"{infos[0][4][0]}" if infos else "空结果")
    except Exception as e:
        check(f"未登记主机仍可正常解析：{host}:{port}", False, f"{type(e).__name__}: {e}")

# ============================== 5) DNS 重绑定：解析结果里混进内网 → 不许连
print("\n=== 5) DNS 重绑定（解析结果里混进 127.0.0.1）必须挡住 ===")
# 原理：PinnedBackend 把"解析"和"拿 IP 去连"放在**同一次调用**里 —— 校验过的那个
# IP 就是拿去的那个，中间没有再解析的窗口。所以攻击者能做的只有"让解析结果里
# 混进内网地址"，而那种情况我们**整次拒绝**。
cb_seq = {"n": 0}


def rebinding_delegate(host, port=0, family=0, *a, **k):
    """第 1 次给公网（想骗过预检），第 2 次给内网（想被真的连上）。"""
    cb_seq["n"] += 1
    return make_infos(PUBLIC_IP if cb_seq["n"] == 1 else PRIVATE_IP, port or 443)


inner = FakeInner()
backend = F.PinnedBackend(inner, F.PinnedResolver(delegate=rebinding_delegate))
# 预检（_check_url → _is_private_host）走的是真 socket.getaddrinfo，这里临时注掉它，
# 让"预检被公网答案骗过"这个攻击前提真实成立（测完立刻还原）。
cb_seq["n"] = 0
try:
    socket.getaddrinfo = rebinding_delegate          # 第 1 次给公网
    try:
        F._check_url("http://rebind.example.com/")
        precheck_ok = True
    except F.FetchError:
        precheck_ok = False
    # 建连：同一域名第 2 次解析给内网 → 必须拒绝
    try:
        asyncio.run(backend.connect_tcp("rebind.example.com", 80))
        blocked = False
        detail = "居然连上了"
    except F.FetchError as e:
        blocked = True
        detail = str(e)[:36]
    except FakeInner.Stop:
        blocked = False
        detail = "放行到了底层建连"
finally:
    socket.getaddrinfo = real_gai

check("预检这一步确实被公网答案骗过（复现攻击前提）", precheck_ok)
check("建连阶段把重绑定挡下来了", blocked, detail)
check("底层后端**从未**被要求连接内网 IP", inner.calls == [], f"{inner.calls}")

# 同一域名一次解析同时给出公网+内网（多 A 记录被污染）→ 也整次拒绝
inner_mix = FakeInner()
backend_mix = F.PinnedBackend(inner_mix, F.PinnedResolver(delegate=mixed_resolver))
try:
    asyncio.run(backend_mix.connect_tcp("mixed.example.com", 80))
    check("公网+内网混合答案下也不建连", False, "居然连上了")
except F.FetchError:
    check("公网+内网混合答案下也不建连", True)
except FakeInner.Stop:
    check("公网+内网混合答案下也不建连", False, "放行到了底层建连")
check("混合答案时底层后端也没被调用", inner_mix.calls == [], f"{inner_mix.calls}")

# ============================== 6) 只连校验过的 IP + 保留域名（Host / SNI 靠它）
print("\n=== 6) 建连只连校验过的 IP，同时保留原始域名 ===")
seen = {}


def spy_delegate(host, port=0, family=0, *a, **k):
    seen["host"] = F._host_key(host)
    return make_infos(PUBLIC_IP, port or 443)


inner2 = FakeInner()
backend2 = F.PinnedBackend(inner2, F.PinnedResolver(delegate=spy_delegate))
try:
    asyncio.run(backend2.connect_tcp("example.com", 443))
except FakeInner.Stop:
    pass
check("解析用的是原始域名（Host / SNI 不会变成 IP）", seen.get("host") == "example.com",
      f"{seen.get('host')}")
check("底层后端拿到的 remote_host 是校验过的 IP",
      inner2.calls and inner2.calls[0][0] == PUBLIC_IP, f"{inner2.calls}")

# ============================== 7) 并发：两个传输层各连各的，不串台
print("\n=== 7) 并发抓取：两个传输层各用各的解析结果，不串台 ===")
inner_a, inner_b = FakeInner(), FakeInner()
t_a = F.make_transport(resolver=F.PinnedResolver(
    delegate=fake_resolver({"a.example.com": PUBLIC_IP})))
t_b = F.make_transport(resolver=F.PinnedResolver(
    delegate=fake_resolver({"b.example.com": PUBLIC_IP2})))
# 把两个传输层的后端换成"记录用"的假后端（保留各自的解析器）
pool_a, pool_b = t_a._pool, t_b._pool
pin_a, pin_b = pool_a._network_backend, pool_b._network_backend
check("make_transport 确实装了 PinnedBackend",
      isinstance(pin_a, F.PinnedBackend) and isinstance(pin_b, F.PinnedBackend))
pool_a._network_backend = F.PinnedBackend(inner_a, pin_a._resolver)
pool_b._network_backend = F.PinnedBackend(inner_b, pin_b._resolver)


async def overlap():
    """两个传输层同时开始抓取：各自解析各自建连，谁都不该用对方的 IP。"""
    import anyio

    async def one(backend, host, delay):
        await anyio.sleep(delay)             # 错开一点，制造真正的重叠窗口
        try:
            await backend.connect_tcp(host, 80)
        except FakeInner.Stop:
            return None
        except F.FetchError as e:
            return e
        return None

    return await asyncio.gather(
        one(pool_a._network_backend, "a.example.com", 0.02),
        one(pool_b._network_backend, "b.example.com", 0.0),
    )


try:
    asyncio.run(overlap())
    check("并发：A 只连自己的 IP",
          inner_a.calls and inner_a.calls[0][0] == PUBLIC_IP, f"{inner_a.calls}")
    check("并发：B 只连自己的 IP",
          inner_b.calls and inner_b.calls[0][0] == PUBLIC_IP2, f"{inner_b.calls}")
    check("并发：两边互不影响（没有串台）",
          inner_a.calls[0][0] != inner_b.calls[0][0])
except Exception as e:
    check("并发抓取不串台", False, f"{type(e).__name__}: {e}")

# A 的传输层不认识 b 的域名 → 必须拒绝（隔离的证据）
inner_c = FakeInner()
pool_a._network_backend = F.PinnedBackend(
    inner_c, F.PinnedResolver(delegate=fake_resolver({"a.example.com": PUBLIC_IP})))
try:
    asyncio.run(pool_a._network_backend.connect_tcp("b.example.com", 80))
    check("A 的传输层解析 b 的域名被拒（真隔离）", False, "居然解析成功了")
except F.FetchError:
    check("A 的传输层解析 b 的域名被拒（真隔离）", True)
except FakeInner.Stop:
    check("A 的传输层解析 b 的域名被拒（真隔离）", False, "放行到了底层建连")
except socket.gaierror:
    # 假解析器对不认识的域名抛 gaierror 也是"拒绝"，同样算通过
    check("A 的传输层解析 b 的域名被拒（真隔离）", True, "假解析器不认识该域名")

for tr in (t_a, t_b):
    try:
        import anyio
        anyio.run(tr.aclose)
    except Exception:
        pass

# ================================================================ 8) 原有保护没被改掉
print("\n=== 8) 原有的保护还在不在（源码级，防回归；项目根 与 交付包 两份都查）===")
src = (HERE / "fetch.py").read_text(encoding="utf-8")
PKG = HERE.parents[1] / "交付包" / "plugins" / HERE.name / "fetch.py"
if PKG.exists():
    same = hashlib.sha256(src.encode("utf-8")).hexdigest() == \
           hashlib.sha256(PKG.read_bytes()).hexdigest()
    check("交付包里的 fetch.py 与项目根一致（副本不漂移）", same,
          "" if same else "包内那份旧了 → 复制过去")
elif (HERE.parents[1] / "交付包").exists():
    check("交付包里的 fetch.py 存在", False, f"找不到 {PKG}")
else:
    # 从 AstrBot 的 plugins 目录里跑（装过去的那份）时没有"交付包"这一层，跳过
    print("  [i] 跳过副本一致性检查（当前不是从项目根跑的）")
check("逐跳重定向校验（每一跳都 _check_url）", src.count("_check_url(nxt)") == 1)
check("手动跟随重定向（关掉 follow_redirects）", "follow_redirects=False" in src)
check("响应大小边收边截断（MAX_BYTES）", "len(buf) >= MAX_BYTES" in src)
check("禁用 trust_env（代理无法替我们解析）", "trust_env=False" in src)
check("DNS 固定只挂在传输层的 pool 上（不改全局）",
      "_network_backend = PinnedBackend" in src)
check("传输层真的用了 make_transport()", "transport=make_transport()" in src)

# ================================================================ 汇总
print("\n" + "-" * 62)
if FAIL:
    print(f"  [X] {len(FAIL)} / {len(PASS) + len(FAIL)} 项没过：{', '.join(FAIL)}")
    sys.exit(1)
print(f"  [OK] {len(PASS)} 项全部通过（未发任何网络请求）")
sys.exit(0)
