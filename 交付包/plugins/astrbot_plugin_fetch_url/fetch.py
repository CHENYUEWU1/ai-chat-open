# -*- coding: utf-8 -*-
"""网页正文抓取 —— 纯逻辑，不依赖 AstrBot，方便单独测试。

设计要点：
    1. 伪装成浏览器 UA（很多站直接拦 python-httpx）
    2. 编码靠 charset_normalizer 猜（中文站大量还是 GBK）
    3. 用 bs4 + lxml 解析，先清掉 script/style/nav/footer 这些噪声
    4. 优先取 <article> / <main>，取不到再退回 <body>
    5. 输出截断，免得把模型上下文塞爆（9B 只有 32K）
    6. 内网防护 + DNS 固定**只在本插件自己的传输层里做**，绝不碰全局解析器
       （见下面「DNS 固定」那段 —— 这里栽过最严重的一次跟头）
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse, urlsplit

import httpx
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------- DNS 固定（只在传输层里）
#
# 要解决的问题：**"校验时解析到的 IP"和"真正连的 IP"必须是同一批**。否则攻击者
# 控制的域名可以让第一次解析返回公网 IP（骗过检查）、第二次解析返回 127.0.0.1，
# 于是能读到本机服务 —— 经典 DNS 重绑定（TOCTOU）。
#
# ⚠️ 走过的四条路，**前三条都别再试**（全是实测踩出来的）：
#   ① 逐请求把全局 `socket.getaddrinfo` 换成"只返回已校验 IP"、退出再换回来
#      → 并发互相顶掉；异常路径还会把被替换的函数留在进程里。
#   ② `httpx.AsyncHTTPTransport(resolver=...)`（"给 client 配自己的解析器"最干净）
#      → **这套 httpx 是 0.28.1 / httpcore 1.0.9，没有 `resolver` 参数**（实测 TypeError）。
#   ③ 模块导入时把全局 `socket.getaddrinfo` 包装一次（当时想的是"永不还原就没风险"）
#      → 🔴 **最严重的一次错误**：本插件是被 AstrBot **主进程** import 的，
#        于是**整个进程**的 DNS 都被换成"只放行 fetch_url 登记过的域名"，
#        结果本机 Ollama（127.0.0.1:11434）、`api.telegram.org`、AnySearch
#        全部解析失败（用户当场复现）。
#        **结论：任何对全局解析器的替换/包装都不可接受，哪怕只有一次。**
#
# 现在这条（第四条）**只在 fetch_url 自己的传输层里固定**：
#   httpx 的传输层内部是 `httpcore.AsyncConnectionPool`，它把"把域名变成 socket"
#   交给 `pool._network_backend.connect_tcp(host, port, ...)`（实测属性名就是
#   `_network_backend`，实现是 `httpcore._backends.auto.AutoBackend`）。
#   → 给这个 pool 换上一个**只覆写 `connect_tcp` 的包装后端**（`PinnedBackend`）：
#       · 先解析 + 逐个校验 IP（内网/回环/链路本地/保留/组播/未指定 → 整次拒绝）；
#       · 只把**校验过的那个 IP** 交给底层后端去连；
#       · hostname 原样交给上层 httpcore —— 于是 HTTP `Host:` 头、TLS SNI、
#         证书校验用的都还是原始域名（**连 IP、验域名**）。
#   · 全局 `socket.getaddrinfo` **全程不动**：同一进程里其它组件
#     （Ollama / AnySearch / Telegram）的解析完全不受影响。
#   · 固定信息只活在**这一个传输层实例**里（实例属性，无锁、无 TTL、
#     无进程级注册表）→ 并发抓取各用各的，天然不会串台。


def _host_key(host) -> str:
    """把 host 统一成小写字符串键（兼容 bytes 和带方括号的 IPv6）。"""
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("utf-8", "ignore")
    return str(host).strip("[]").lower()


def _is_blocked_ip(ip) -> bool:
    """这个 IP 是不是"不该连"的（本机 / 内网 / 保留等）。"""
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_BYTES = 3 * 1024 * 1024          # 单页最多下 3 MB
DEFAULT_CHARS = 6000                 # 默认返回多少字符
HARD_CHARS = 20000                   # 上限

# 整块丢掉、肯定不是正文的标签
DROP_TAGS = ("script", "style", "noscript", "iframe", "svg", "canvas",
             "nav", "header", "footer", "aside", "form", "button",
             "template", "figure", "video", "audio", "map")


class FetchError(Exception):
    """抓取失败，消息直接给模型看。"""


class PinnedResolver:
    r"""解析 + 校验：**只返回通过公网检查的 IP**，不缓存到任何全局地方。

    每一次解析都重新校验（不是只信调用方传来的字符串）。解析结果里只要出现
    内网/本机/保留地址，就**整次拒绝** —— 这正是 DNS 重绑定的典型形态
    （一次解析给公网、另一次给 127.0.0.1）。解析放在线程池里跑，不在事件循环里阻塞。
    """

    def __init__(self, delegate=None):
        # `delegate` 只给测试注入假解析器；默认是真正的 socket.getaddrinfo
        # （⚠️ 本文件从不替换它，所以这里取到的永远是真的那个）
        self._delegate = delegate or socket.getaddrinfo

    async def resolve(self, host: str, port: int = 0, family: int = 0):
        import anyio

        fam = family or socket.AF_UNSPEC
        key = _host_key(host)
        if not key:
            raise FetchError("没有主机名")

        def _lookup():
            return self._delegate(host, port, fam, socket.SOCK_STREAM)

        infos = await anyio.to_thread.run_sync(_lookup)
        out = []
        for info in infos:
            fam_i, addr = info[0], info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _is_blocked_ip(ip):
                raise FetchError(f"域名解析到内网/本机地址，拒绝：{host} → {addr}")
            out.append((fam_i, addr))
        if not out:
            raise FetchError(f"解析不到地址：{host}")
        return out

    __call__ = resolve


class PinnedBackend:
    r"""包住 httpcore 的网络后端，**只覆写 `connect_tcp`**：先解析校验、再连校验过的 IP。

    这是 DNS 固定的落点，也是它**只影响 fetch_url 自己**的原因：包装对象只挂在
    **这一个传输层实例**的 pool 上（`pool._network_backend`）；进程里别的组件
    （Ollama / AnySearch / Telegram）用它们自己的后端，全局解析器全程不动。

    关键点：传给底层后端的 remote_host 是**校验过的 IP**，hostname 仍交给上层
    httpcore —— 于是 TLS SNI、证书校验、HTTP `Host:` 头用的都还是原始域名。
    """

    def __init__(self, inner, resolver: PinnedResolver):
        self._inner = inner
        self._resolver = resolver
        self.connected = []          # 记录"实际拿去连的 (host, port, ip)"，供测试检查

    async def connect_tcp(self, host, port=0, timeout=None, local_address=None,
                          socket_options=None):
        key = _host_key(host)
        ips = await self._resolver.resolve(key, port or 0)
        chosen = ips[0][1]           # 只连这个校验过的地址，绝不退回未校验的
        self.connected.append((key, port, chosen))
        return await self._inner.connect_tcp(
            chosen, port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )

    def __getattr__(self, name):
        # 其余方法（connect_unix_socket / sleep 等）原样转发
        return getattr(self._inner, name)


# 默认解析器（无状态、可复用；每次抓取各建各的传输层）
_RESOLVER = PinnedResolver()


def make_transport(resolver: PinnedResolver | None = None):
    r"""造一个**只在这个传输层内部固定 DNS** 的 httpx 传输层。

    做法：先按 httpx 的方式把 `AsyncHTTPTransport` 建好，再把它内部
    `httpcore.AsyncConnectionPool` 的网络后端换成 `PinnedBackend`。
    **全程不碰任何全局对象**（这套 httpx 0.28.1 没有 `resolver=` 参数可用，
    见上面「DNS 固定」那段）。顺带关掉环境代理：走代理时解析与建连都由代理做，
    "只连校验过的 IP"就失效了。

    `resolver` 参数只给测试注入假解析器，平时不用传。
    """
    tr = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
    pool = tr._pool
    inner = getattr(pool, "_network_backend", None)
    if inner is None:
        # 换不到后端就**宁可不让它抓** —— 不能悄悄退回"不固定 DNS"的版本
        raise FetchError(
            "这套 httpcore 的连接池结构变了（没有 _network_backend）；"
            "为了不放弃 DNS 固定，本次拒绝抓取"
        )
    pool._network_backend = PinnedBackend(inner, resolver or _RESOLVER)
    return tr


def _is_private_host(host: str) -> bool:
    """挡掉本机/内网地址 —— 免得模型被网页里的内容诱导去读本机服务。

    这是**预检**（给模型一句清楚的错误信息用）。真正"连的时候不许连内网"的保证
    在 `PinnedBackend` + `PinnedResolver`：每次新建连接都会重新解析并校验。
    """
    if not host:
        return True
    h = host.strip("[]").lower()
    if h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return _is_blocked_ip(ip)
    except ValueError:
        pass
    # 域名：解析一下看指向哪（用真正的解析函数 —— 我们从没换过它）
    try:
        infos = socket.getaddrinfo(h, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if _is_blocked_ip(ip):
                return True
    except Exception:
        # ⚠️ 2026-09-29：解析失败原来 `return False` = **放行**。
        #    解析不了通常意味着网络有问题，不该当成"安全"。
        #    改成拦下来（宁可少抓一个页面，也不留下"解析失败即放行"这个口子）。
        return True
    return False


def _check_url(u: str) -> None:
    """校验一个 URL 能不能抓：协议 + 内网。**不做全局状态修改。**

    ⚠️ 抽成函数是为了**每一跳都调用**（2026-09-29）：原来只在开头校验初始 URL，
    而 `follow_redirects=True` 会自动跟到任意地方 —— 公网页面 302 到
    `http://127.0.0.1:8080/` 就能读到本机服务。现在重定向改成手动、
    每一跳都过这个函数。

    ⚠️ 这里只是**快速失败**（给模型清楚的报错）。真正"建连时只连公网 IP"的保证
    在 `PinnedBackend`：它在每次 `connect_tcp` 时重新解析 + 校验 + 只连校验过的 IP，
    所以不存在"检查一次、连接时 DNS 变了"的窗口。
    """
    p = urlsplit(u)
    if p.scheme not in ("http", "https"):
        raise FetchError(f"只支持 http/https，不支持 {p.scheme or '（空）'}")
    host = (p.hostname or "").strip("[]").lower()
    if not host:
        raise FetchError("URL 里没有主机名")
    if _is_private_host(host):
        raise FetchError("不抓本机和内网地址（安全限制）")


def _clean(soup: BeautifulSoup) -> None:
    for tag in soup(list(DROP_TAGS)):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()


def _text_of(node) -> str:
    raw = node.get_text(separator="\n")
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        # 去掉只有符号/装饰的短行
        if len(s) <= 2 and not s.isalnum() and not "\u4e00" <= s[0] <= "\u9fff":
            continue
        lines.append(s)
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


async def fetch_text(url: str, max_chars: int = DEFAULT_CHARS) -> str:
    """抓一个网页，返回「标题 + 正文纯文本」。失败抛 FetchError。"""
    url = (url or "").strip()
    if not url:
        raise FetchError("没给 url")
    if "://" not in url:
        url = "https://" + url
    _check_url(url)          # 每一跳都会调（见函数说明）

    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = DEFAULT_CHARS
    max_chars = max(500, min(max_chars, HARD_CHARS))

    # ⚠️ 2026-09-29 重写这一段，修两个问题：
    #   ① **内网防护可被 302 绕过**：原来 `follow_redirects=True` 只在开头校验初始 host，
    #      一个公网页面只要 302 到 http://127.0.0.1:8080/ 就能读到本机服务。
    #      → 改成**手动跟随**，每一跳都重新校验 host（最多 MAX_REDIRECTS 跳）。
    #   ② **MAX_BYTES 挡不住大响应**：原来 `resp.content` 已经把整块下完了才切片，
    #      几十 MB 的页面会整块进内存。→ 改成 `client.stream` 边收边截断。
    # ⚠️ 2026-10-03 第三次改 DNS 固定：改成"只在这个传输层里固定"（`make_transport()`），
    #    **不再碰全局 socket.getaddrinfo**（上一版包了全局，把同进程的 Ollama /
    #    Telegram / AnySearch 的解析全废了，用户当场复现）。详见文件头那段。
    MAX_REDIRECTS = 5
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            # trust_env=False（2026-09-30 改）：原来 True 会读 HTTP(S)_PROXY 环境变量。
            # 走代理时**解析和建连都由代理去做**，"只连校验过的 IP"就白做了 ——
            # 代理可以让请求落到任意地址（包括内网）。这个插件只抓公网页面，
            # 不需要代理；要代理的场景请走别的工具。
            follow_redirects=False, timeout=TIMEOUT, trust_env=False, headers=headers,
            transport=make_transport(),
        ) as client:
            cur = url
            for hop in range(MAX_REDIRECTS + 1):
                async with client.stream("GET", cur) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FetchError(f"HTTP {resp.status_code} 但没有 Location")
                        nxt = str(httpx.URL(cur).join(loc))
                        # 逐跳校验：跳转目标也不许是内网
                        # （下一跳建连时 PinnedBackend 还会再解析 + 校验一次，双保险）
                        _check_url(nxt)
                        cur = nxt
                        continue
                    if resp.status_code >= 400:
                        raise FetchError(f"服务器返回 HTTP {resp.status_code}")
                    ctype = resp.headers.get("content-type", "").lower()
                    if "pdf" in ctype:
                        raise FetchError("这是 PDF，抓不了正文（只支持 HTML 页面）")
                    if not any(k in ctype for k in ("html", "xml", "text", "json")) and ctype:
                        raise FetchError(f"不是网页内容（content-type: {ctype[:60]}）")
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf += chunk
                        if len(buf) >= MAX_BYTES:      # 真正在下载过程中截断
                            break
                    content = bytes(buf[:MAX_BYTES])
                    break
            else:
                raise FetchError(f"跳转次数超过 {MAX_REDIRECTS} 次，放弃")
    except FetchError:
        raise
    except httpx.TimeoutException:
        raise FetchError(f"请求超时（{TIMEOUT} 秒），换个页面或稍后再试")
    except httpx.HTTPError as exc:
        raise FetchError(f"请求失败：{type(exc).__name__}: {exc}")

    # 编码：httpx 猜错的话用 charset_normalizer 再试一次
    if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        try:
            from charset_normalizer import from_bytes
            best = from_bytes(content).best()
            encoding = best.encoding if best else "utf-8"
        except Exception:
            encoding = "utf-8"
    else:
        encoding = resp.encoding

    try:
        html = content.decode(encoding, errors="replace")
    except LookupError:
        html = content.decode("utf-8", errors="replace")

    if "json" in ctype:
        return f"URL: {url}\n\n{html[:max_chars]}"

    soup = BeautifulSoup(html, "lxml")
    _clean(soup)

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    node = None
    for sel in ("article", "main", "[role=main]", "#content", ".content", "#main"):
        found = soup.select_one(sel)
        if found and len(_text_of(found)) > 200:
            node = found
            break
    if node is None:
        node = soup.body or soup

    body = _text_of(node)
    if not body:
        raise FetchError("页面里没抽到正文（可能是纯 JS 渲染的站点）")

    head = f"URL: {url}"
    if title:
        head += f"\n标题: {title}"
    text = f"{head}\n\n{body}"

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n…（已截断，全文约 {len(body)} 字）"
    return text
