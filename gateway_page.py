"""网关主页模板。页面内容与后端请求处理分开维护。"""

import datetime

# 网关主页不包含密钥；API Key 只由服务端的 /__key 路由按访问来源决定是否下发。
PAGE_VER = "2026-10-19-ui4"      # 改页面就改它（服务端与页面共用这一个来源）

PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>消费级电脑本地部署的局域网 AI 助手</title>
<meta name="description" content="在消费级 Windows 电脑上运行本地 AI 模型，通过可信局域网连接浏览器、手机和兼容客户端。">
<meta name="theme-color" content="#090d18">
<!-- 不需要 JS 的探针①：JS 关掉的浏览器才会取它（用来区分"JS 关了"还是"脚本被拦了"） -->
<noscript><link rel="stylesheet" href="/__nojs">
<!-- 而且 JS 关掉时，让页面**自己每 5 秒重载**：下面的数字是服务端渲染进去的，
     这样"没有 JS 也能看到会动的资源数字"（重载也会在网关日志里留痕 = 又一重证据）。 -->
<meta http-equiv="refresh" content="5"></noscript>
<!-- 主页面主题样式集中在此；/plain 是单独的无 JS 兜底页，不依赖本页 CSS。 -->
<style>
 /* 页面主题和基础组件集中在这里；服务端组件只输出结构与状态。 */
 :root{color-scheme:dark;--bg:#090d18;--panel:#111827;--panel2:#0c1220;
       --line:rgba(150,170,210,.16);--text:#f3f5ff;--muted:#98a3bb;
       --blue:#94b8ff;--blue2:#687bff;--green:#78e2b2;--amber:#ffd078;--red:#ff9292}
 *{box-sizing:border-box}
 html{scroll-behavior:smooth;scroll-padding-top:82px}
 body{font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
      margin:0;padding:0 22px 56px;background:var(--bg);color:var(--text);
      background-image:url('/__cssprobe'),radial-gradient(ellipse at 50% -22%,rgba(77,94,171,.25),transparent 58%),
                       radial-gradient(ellipse at 100% 55%,rgba(37,132,147,.08),transparent 34%);
      background-attachment:fixed}
 .w{max-width:1120px;margin:0 auto}
 .topbar{height:76px;display:flex;align-items:center;justify-content:space-between;gap:16px}
 .brand{display:flex;align-items:center;gap:11px;color:var(--text);text-decoration:none}
 .brand-mark{width:38px;height:38px;display:grid;place-items:center;border-radius:13px;
      color:white;font-size:19px;font-weight:800;background:linear-gradient(145deg,#8196ff,#5965d9);
      box-shadow:0 7px 22px rgba(94,111,230,.28)}
 .brand-copy{display:grid;line-height:1.1;gap:4px}
 .brand-copy strong{font-size:16px;letter-spacing:.04em}
 .brand-copy small{font-size:9px;letter-spacing:.2em;color:#8290ac}
 .top-actions{display:flex;align-items:center;gap:15px}
 .top-caption{color:#8591aa;font-size:12px;letter-spacing:.08em}
 .status-pill{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border-radius:99px;
      background:rgba(16,28,37,.8);border:1px solid rgba(120,226,178,.2);color:#a8e8cc;font-size:12px}
 .status-pill i{width:7px;height:7px;border-radius:50%;background:#727d92;box-shadow:0 0 0 4px rgba(114,125,146,.12)}
 .status-pill[data-state="online"] i{background:var(--green);box-shadow:0 0 0 4px rgba(120,226,178,.12)}
 .status-pill[data-state="offline"]{border-color:rgba(255,146,146,.25);color:#ffc3c3}
 .status-pill[data-state="offline"] i{background:var(--red);box-shadow:0 0 0 4px rgba(255,146,146,.12)}
 .hero{position:relative;display:grid;grid-template-columns:minmax(0,1.08fr) minmax(320px,.92fr);
      min-height:390px;overflow:hidden;align-items:center;padding:42px 48px;margin:5px 0 26px;
      border:1px solid rgba(165,179,232,.18);border-radius:28px;
      background:linear-gradient(112deg,rgba(24,31,58,.96),rgba(18,26,45,.96) 56%,rgba(14,42,53,.94));
      box-shadow:0 26px 80px rgba(0,0,0,.28)}
 .hero:before{content:"";position:absolute;inset:0;pointer-events:none;
      background:radial-gradient(ellipse at 20% 0%,rgba(116,127,255,.18),transparent 47%),
                 linear-gradient(120deg,transparent 48%,rgba(63,184,174,.045))}
 .hero-copy{position:relative;z-index:1;max-width:590px}
 .eyebrow{display:flex;align-items:center;gap:10px;color:#b7c4e7;font-size:10px;
      font-weight:700;letter-spacing:.2em;margin:0 0 18px}
 .eyebrow:before{content:"";width:24px;height:1px;background:#a1a8ff}
 .hero h1{font-size:clamp(44px,5.5vw,68px);line-height:1.12;letter-spacing:-.055em;margin:0}
 .hero h1 span{background:linear-gradient(100deg,#c8d1ff 5%,#8eb6ff 54%,#73ddce 100%);
      color:transparent;background-clip:text;-webkit-background-clip:text}
 .hero-lead{max-width:480px;margin:18px 0 23px;color:#b1bad0;font-size:15px;line-height:1.9}
 .hero-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
 .hero-cta,.hero-link{min-height:46px;display:inline-flex;align-items:center;justify-content:center;
      gap:12px;padding:0 18px;border-radius:12px;text-decoration:none;font-size:13px;font-weight:700}
 .hero-cta{color:#101528;background:linear-gradient(105deg,#b4c1ff,#8ddbd4);
      box-shadow:0 9px 24px rgba(112,155,234,.2);transition:transform .18s,filter .18s}
 .hero-cta:hover{color:#101528;filter:brightness(1.07);transform:translateY(-2px)}
 .hero-link{color:#d8def1;border:1px solid rgba(196,207,238,.2);background:rgba(255,255,255,.035)}
 .hero-link:hover{background:rgba(255,255,255,.08)}
 .hero-trust{display:flex;gap:17px;flex-wrap:wrap;margin-top:24px;color:#a3aec4;font-size:11px}
 .hero-trust span{display:inline-flex;align-items:center;gap:6px}
 .hero-trust b{color:#83e0bd;font-size:13px}
 .hero-endpoint{display:flex;align-items:center;gap:9px;margin-top:22px;color:#7e8aa5;font-size:11px}
 .hero-endpoint code{padding:5px 8px;border:1px solid rgba(169,185,224,.15);border-radius:7px;
      color:#cbd5ee;background:rgba(6,11,23,.26)}
 .hero-visual{position:relative;min-height:300px;display:grid;place-items:center;isolation:isolate}
 .hero-visual:before,.hero-visual:after{content:"";position:absolute;border-radius:50%;pointer-events:none}
 .hero-visual:before{width:255px;height:255px;border:1px solid rgba(154,176,255,.13);
      box-shadow:0 0 0 24px rgba(144,162,255,.025),0 0 0 54px rgba(144,162,255,.02)}
 .hero-visual:after{width:205px;height:205px;background:radial-gradient(circle,rgba(103,126,238,.28),rgba(65,171,169,.12) 48%,transparent 72%);
      filter:blur(8px);z-index:-1}
 .orbit{position:absolute;border:1px solid rgba(158,183,240,.17);border-radius:50%;transform:rotate(-26deg)}
 .orbit-a{width:330px;height:126px}.orbit-b{width:365px;height:160px;transform:rotate(34deg)}
 .orbit-dot{position:absolute;width:8px;height:8px;border-radius:50%;background:#a9d7ff;
      box-shadow:0 0 13px rgba(153,205,255,.95)}
 .dot-a{top:76px;right:78px}.dot-b{bottom:76px;left:72px;background:#7de0cf}
 .engine-card{position:relative;width:min(290px,90%);padding:17px 18px 14px;border-radius:19px;
      border:1px solid rgba(201,211,255,.22);
      background:linear-gradient(145deg,rgba(29,39,70,.94),rgba(13,24,42,.96));
      box-shadow:0 24px 60px rgba(0,0,0,.4),inset 0 1px rgba(255,255,255,.07);
      transform:rotate(-3deg)}
 .engine-cap,.engine-foot{display:flex;align-items:center;justify-content:space-between;color:#9ba9c7;font-size:9px;letter-spacing:.16em}
 .engine-cap i{width:6px;height:6px;margin-right:6px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}
 .engine-cap span{margin-left:auto;color:#b3ecd5;letter-spacing:.04em}
 .engine-mark{width:52px;height:52px;display:grid;place-items:center;margin:17px 0 13px;border-radius:17px;
      color:#e8eaff;font-size:25px;font-weight:800;background:linear-gradient(145deg,rgba(133,151,255,.35),rgba(67,186,177,.2));
      border:1px solid rgba(194,211,255,.22)}
 .engine-title{display:grid;gap:3px}
 .engine-title small{color:#8795b1;font-size:9px;letter-spacing:.16em}
 .engine-title strong{color:#f1f4ff;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .engine-wave{height:30px;display:flex;align-items:center;gap:4px;margin:13px 0}
 .engine-wave i{flex:1;height:var(--h);border-radius:4px;background:linear-gradient(180deg,#8ea8ff,#62d8c4);opacity:.78}
 .engine-foot{padding-top:10px;border-top:1px solid rgba(181,196,235,.12);font-size:8px}
 .orbit-note{position:absolute;padding:6px 9px;border:1px solid rgba(175,194,232,.15);
      border-radius:8px;background:rgba(13,22,39,.85);color:#b9c6df;font-size:9px;letter-spacing:.08em}
 .note-a{top:22px;left:15px}.note-b{right:3px;bottom:31px;color:#9fe3d4}
 .quick-nav{position:sticky;top:0;z-index:10;display:flex;gap:8px;overflow-x:auto;
      padding:10px 0;margin:0 0 18px;scrollbar-width:thin;
      background:rgba(9,13,24,.9);backdrop-filter:blur(14px);
      border-bottom:1px solid rgba(125,145,190,.12)}
 .quick-nav a{flex:none;text-decoration:none;color:#aeb9cf;background:rgba(255,255,255,.035);
      border:1px solid rgba(150,170,210,.1);border-radius:9px;padding:7px 12px;font-size:12px}
 .quick-nav a:hover,.quick-nav a:focus-visible{border-color:rgba(148,184,255,.48);color:#fff;background:rgba(120,142,255,.1)}
 .card{background:linear-gradient(145deg,rgba(20,28,45,.97),rgba(14,20,33,.98));
      border:1px solid var(--line);border-radius:18px;padding:20px;margin:14px 0;
      box-shadow:0 12px 36px rgba(0,0,0,.16);scroll-margin-top:82px}
 .card:hover{border-color:rgba(148,184,255,.23)}
 .lbl{color:#d2daf0;font-size:14px;font-weight:700;letter-spacing:.01em;margin-bottom:12px}
 .row{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
 input,textarea,select,button{font:inherit;border-radius:10px;border:1px solid rgba(160,178,218,.2);
      background:var(--panel2);color:var(--text);padding:9px 11px}
 input,select{flex:1;min-width:180px}
 #api-key input#keyin{min-width:0;flex:1 1 280px}
 textarea{width:100%;min-height:48px;resize:vertical}
 input:focus-visible,textarea:focus-visible,select:focus-visible,button:focus-visible,a:focus-visible,summary:focus-visible{
      outline:2px solid var(--blue);outline-offset:2px}
 button{min-height:42px;background:#1a2439;cursor:pointer;white-space:nowrap;transition:background .15s,border-color .15s,transform .15s}
 button:hover{background:#263451;border-color:#718bbd;transform:translateY(-1px)}
 button.p{background:linear-gradient(105deg,#7186ff,#5772e7);border-color:#8293ff;color:white}
 button.p:hover{background:linear-gradient(105deg,#8798ff,#6782f4)}
 a{color:#a9c5ff}
 code,pre{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
 pre{background:rgba(8,13,24,.78);border:1px solid var(--line);border-radius:11px;padding:13px;
     overflow:auto;white-space:pre-wrap;word-break:break-all}
 .k{background:rgba(8,13,24,.75);border:1px dashed rgba(149,171,217,.29);border-radius:11px;padding:12px;
    word-break:break-all;font-family:ui-monospace,Consolas,monospace}
 .out{min-height:100px;white-space:pre-wrap;border-left:3px solid #8b9bff;padding:11px 13px;
      background:rgba(7,13,24,.48);border-radius:0 11px 11px 0}
 .hint{color:var(--muted);font-size:12.5px}
 .warn{color:var(--amber)}.ok{color:var(--green)}.bad{color:var(--red)}
 table{border-collapse:collapse;width:100%;font-size:13.5px}
 td{border-top:1px solid var(--line);padding:10px 8px;vertical-align:top}
 td:first-child{color:var(--muted);width:150px}
 .meter{display:flex;align-items:center;gap:10px;margin:9px 0}
 .meter>span{width:58px;color:#bdcbe0;font-size:13px}
 .meter>.bar{flex:1;height:10px;background:rgba(6,11,22,.85);border:1px solid rgba(155,175,217,.1);border-radius:99px;overflow:hidden}
 .meter>.bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#6a80ff,#7cb9ff);transition:width .35s,background .35s}
 .meter>em{width:158px;text-align:right;color:#dbe6f7;font-style:normal;font-size:13px;font-variant-numeric:tabular-nums}
 .lg{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-top:8px}
 .lg b{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:4px}
 details.help{margin-top:9px;border-top:1px solid rgba(75,96,127,.42);padding-top:8px}
 details.help>summary{color:#b8c9e2;cursor:pointer;font-size:12.5px;min-height:30px;display:flex;align-items:center}
 details.help[open]>summary{margin-bottom:7px}
 /* 授权设备组件的规则集中维护；组件函数只负责输出 HTML。 */
 .dev{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0}
 .dev th,.dev td{border-bottom:1px solid var(--line);padding:7px 6px;text-align:left}
 .dev .ua{color:var(--muted);max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 button.mini{padding:5px 10px;font-size:12px;border-radius:7px;border:1px solid #3a4a63;
             background:#1c293c;color:var(--text);cursor:pointer}
 .code{font-size:19px;letter-spacing:4px;font-weight:700;color:#d5e4ff}
 @media(max-width:640px){
   body{padding:0 13px 36px;background-attachment:scroll}
   .topbar{height:66px}.top-caption{display:none}
   .hero{grid-template-columns:1fr;min-height:0;padding:29px 23px 20px;border-radius:22px;margin-bottom:18px}
   .hero h1{font-size:clamp(43px,12vw,58px)}
   .hero-lead{font-size:14px;margin:14px 0 18px}
   .hero-trust{gap:9px 14px;margin-top:18px}
   .hero-endpoint{flex-wrap:wrap;margin-top:17px}.hero-endpoint code{max-width:100%;overflow-wrap:anywhere}
   .hero-visual{min-height:245px;margin:8px -8px -8px}
   .hero-visual:before{width:205px;height:205px}
   .hero-visual:after{width:165px;height:165px}
   .orbit-a{width:270px;height:104px}.orbit-b{width:290px;height:126px}
   .engine-card{width:260px}.dot-a{top:63px;right:43px}.dot-b{bottom:56px;left:39px}
   .note-a{top:8px;left:0}.note-b{right:0;bottom:14px}
   .card{padding:15px;border-radius:15px;margin:11px 0}
   .meter{display:grid;grid-template-columns:46px minmax(0,1fr);gap:5px 9px}
   .meter>span{width:auto;grid-row:span 2;align-self:center}
   .meter>.bar{min-width:0;width:100%}.meter>em{width:auto;text-align:left;font-size:12px}
   input,select{min-width:min(180px,100%)}input[type=file]{width:100%;min-width:0}
   .row>button{max-width:100%}.quick-nav{margin-right:-2px}
   td:first-child{width:105px}.dev{display:block;overflow-x:auto;white-space:nowrap}
 }
 @media(max-width:380px){.hero{padding:25px 18px 18px}.hero-trust{font-size:10px}.hero-visual{min-height:220px}}
 @media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important}}
</style></head><body><div class="w">
<header class="topbar">
  <a class="brand" href="/" aria-label="小九网关主页">
    <span class="brand-mark" aria-hidden="true">九</span>
    <span class="brand-copy"><strong>小九</strong><small>LOCAL AI WORKSPACE</small></span>
  </a>
  <div class="top-actions">
    <span class="top-caption">你的模型 · 你的设备 · 你的节奏</span>
    <span class="status-pill" id="heroStatus" data-state="checking" role="status">
      <i></i><span id="heroStatusText">正在连接</span>
    </span>
  </div>
</header>
<section class="hero" aria-labelledby="heroTitle">
  <div class="hero-copy">
    <p class="eyebrow">YOUR OWN AI SPACE</p>
    <h1 id="heroTitle">你的 AI，<br><span>就在本地。</span></h1>
    <p class="hero-lead">在自己的设备上运行模型。直接开始对话，查看实时算力，或把接口接入手机与常用客户端。</p>
    <div class="hero-actions">
      <a class="hero-cta" href="#try-chat">开始体验 <span aria-hidden="true">↘</span></a>
      <a class="hero-link" href="#connect">连接设备 <span aria-hidden="true">→</span></a>
    </div>
    <div class="hero-trust">
      <span><b>✦</b> 本机推理</span><span><b>⌁</b> 搜索按需联网</span><span><b>◈</b> 设备访问可管理</span>
    </div>
    <div class="hero-endpoint"><span>当前服务</span><code id="base"></code></div>
  </div>
  <div class="hero-visual" aria-hidden="true">
    <div class="orbit orbit-a"></div><div class="orbit orbit-b"></div>
    <i class="orbit-dot dot-a"></i><i class="orbit-dot dot-b"></i>
    <span class="orbit-note note-a">RUNNING ON YOUR DEVICE</span>
    <span class="orbit-note note-b">NO CLOUD INFERENCE</span>
    <div class="engine-card">
      <div class="engine-cap"><i></i> LOCAL ENGINE <span>READY</span></div>
      <div class="engine-mark">九</div>
      <div class="engine-title"><small>ACTIVE MODEL</small><strong id="heroModel">正在读取模型…</strong></div>
      <div class="engine-wave" aria-hidden="true">
        <i style="--h:9px"></i><i style="--h:16px"></i><i style="--h:12px"></i><i style="--h:24px"></i>
        <i style="--h:15px"></i><i style="--h:27px"></i><i style="--h:11px"></i><i style="--h:19px"></i>
        <i style="--h:13px"></i><i style="--h:23px"></i><i style="--h:10px"></i><i style="--h:17px"></i>
      </div>
      <div class="engine-foot"><span>OLLAMA</span><span>ON DEVICE</span></div>
    </div>
  </div>
</section>
<!-- 不需要 JS 的探针②：普通图片，任何会渲染 HTML 的浏览器都会取它 -->
<img src="/__imgprobe" width="1" height="1" alt="" style="position:absolute;left:-9px;top:-9px">
<noscript><div class="card" style="border-color:#7a2b2b;background:#2a1414;color:#ffd0d0">
  ⚠️ <b>这个浏览器没有执行 JavaScript</b> —— 所以页面上的按钮、资源面板、上报都不会动，
  看起来就是"按了没反应 / 一直读取中"。<br>
  请在浏览器设置里打开 <b>JavaScript</b>（有些国产浏览器的"省流/极速/无脚本"模式会关掉它），
  或者换 <b>Chrome / Edge / 系统浏览器</b> 打开这个地址。
</div></noscript>
<div id="banner" class="card"
     style="display:none;border-color:#7a2b2b;background:#2a1414;color:#ffd0d0"></div>
<!-- 用原生锚点和 details，不依赖 JS；不要移除目标 id，或把长说明改成 JS 才能展开。 -->
<nav class="quick-nav" aria-label="页面快捷导航">
  <a href="#resources">资源状态</a><a href="#api-key">API Key</a><a href="#try-chat">快速对话</a>
  <a href="#connect">客户端接入</a><a href="#access">授权与设置</a><a href="#actions">电源控制</a>
</nav>

<div class="card" id="resources">
  <div class="lbl">系统资源（每 3 秒刷新；页面切到后台自动暂停）</div>
  <div class="meter"><span>CPU</span><div class="bar"><i id="b_cpu" style="<!--SRV:cpu_w-->"></i></div><em id="v_cpu"><!--SRV:cpu--></em></div>
  <div class="meter"><span>内存</span><div class="bar"><i id="b_mem" style="<!--SRV:mem_w-->"></i></div><em id="v_mem"><!--SRV:mem--></em></div>
  <div class="meter"><span>显存</span><div class="bar"><i id="b_vram" style="<!--SRV:vram_w-->"></i></div><em id="v_vram"><!--SRV:vram--></em></div>
  <div class="meter"><span>GPU</span><div class="bar"><i id="b_gpu" style="<!--SRV:gpu_w-->"></i></div><em id="v_gpu"><!--SRV:gpu--></em></div>
  <canvas id="spark" width="840" height="92" style="width:100%;height:92px;margin-top:10px"></canvas>
  <div class="hint" style="margin-top:8px">模型：<span id="v_model"><!--SRV:model--></span></div>
  <div class="hint">最近一次对话：<span id="v_lastchat"><!--SRV:lastchat--></span></div>
  <div class="hint">上下文占用：<span id="v_ctx"><!--SRV:ctx--></span></div>
  <div class="lg">
    <span><b style="background:#2f6df6"></b>CPU</span>
    <span><b style="background:#6ee7a8"></b>内存</span>
    <span><b style="background:#ffcf6b"></b>显存</span>
    <span><b style="background:#ff8f8f"></b>GPU</span>
    <span id="v_gpu_name" class="hint"></span>
  </div>
  <details class="help"><summary>资源面板说明</summary><div class="hint">
    CPU / 内存来自 Windows 本身（纯标准库，不用装 psutil）；显存 / GPU / 温度来自 <code>nvidia-smi</code>。
    曲线 = 最近 60 次采样（约 3 分钟）。<b>推理时这条曲线会顶上去</b>，能直观看出显存还剩多少。<br>
    开销实测：一次 <code>/__stats</code> 约 <b>85 ms</b>、<b>0.25 KB</b>（大头是起一次 nvidia-smi 42 ms，
    已做 3.5 秒缓存 ⇒ 大约两次刷新才起一次进程）。<b>页面切到后台／锁屏就不再请求</b>。
  </div></details>
  <div class="hint" id="pstat" style="margin-top:6px">面板状态：初始化…</div>
  <div class="hint">页面版本 <code id="pver"><!--SRV:ver--></code> —— 手机上看不到新功能时，先对一下这个号；
    对不上就是拿到了旧页面（下拉刷新 / 清一下缓存）。</div>
</div>

<!-- ⚠️ 2026-10-18 加：**手机把文件传给电脑**（纯 HTML 表单 ⇒ 不跑 JS 的浏览器也能用）。
     存到 `E:\本地ai\聊天文件\`；`/__upload` 和别的 __ 端点走同一道授权门 ✓ -->
<div class="card" id="upload">
  <div class="lbl">📎 传文件给电脑（存到 <code>E:\本地ai\聊天文件\</code>）</div>
  <div class="hint" style="margin:6px 0">选好文件点「上传」；单个文件 ≤ 25 MB。成功后显示保存后的文件名。</div>
  <form method="post" action="/__upload" enctype="multipart/form-data">
    <input type="file" name="f"
           style="max-width:100%;padding:6px;background:#0f1115;color:#e6e6e6;border:1px solid #333a47;border-radius:7px">
    <button type="submit" style="margin-left:6px">上传</button>
  </form>
  <div class="hint" id="uphint" style="margin-top:6px"><!--SRV:upload--></div>
</div>

<div class="card" id="actions">
  <div class="lbl">控制</div>
  <div class="row">
    <button class="p" id="btn_stop" onclick="shutdownXiaojiu()">⏹ 停止小九（需先填 Key）</button>
    <button onclick="dryRun()">先看看会停哪些</button>
    <button onclick="makeTicket()">📱 生成手机授权码</button>
    <span id="ctlmsg" class="hint"></span>
  </div>
  <details class="help"><summary>停止服务会关闭哪些进程？</summary><div class="hint">
    等于双击 <code>停止小九.bat</code>：停 <b>Ollama</b>（释放显存）+ 清 <b>llama-server 残留</b>
    （不杀它会留下占几 GB 内存的孤儿）+ 关 <b>AstrBot</b>。<br>
    ⚠️ <b>连网关自己也一起停</b>：响应发出去后 <b>5 秒</b>结束网关（含别的 ollama_gateway 实例）
    —— 也就是"小九的所有进程都关掉"。这 5 秒是留给你看结果的，之后这个页面会连不上。<br>
    要重新启动：在电脑上双击 <code>启动局域网API.bat</code>（只起网关）或
    <code>启动AstrBot.bat</code>（起对话整套）。<br>
    🔒 这个按钮<b>要 Key</b>（先在上面「用这个 Key」填好）；电脑本机上打开则不用。
  </div></details>
  <form method="post" action="/__shutdown" style="margin-top:10px;border-top:1px solid #262b36;padding-top:10px">
    <div class="hint" style="margin-bottom:5px">
      🔧 <b>如果这个浏览器不执行 JavaScript</b>（按钮点了没反应、面板一直"读取中"、页面上没有
      「页面版本」那行），用下面这个 <b>表单版</b>：提交表单不需要 JS。
    </div>
    <input name="key" type="password" placeholder="把 Key 粘在这里"
           style="width:min(300px,55%)">
    <button type="submit">⏹ 停止小九（表单版）</button>
    <button type="submit" name="dry" value="1">先看看会停哪些</button>
  </form>
</div>

<div class="card" id="access" style="<!--SRV:access-card-->">
  <div class="lbl">🔒 访问授权</div>
  <div class="hint"><!--SRV:access--></div>
</div>

<div class="card" style="<!--SRV:apk-card-->">
  <div class="lbl">📦 手机 App 安装包（自己从源码编译的最新版）</div>
  <div class="row">
    <a href="<!--SRV:apk-url-->" style="display:inline-block;padding:8px 12px;border-radius:8px;
       background:#2f6df6;color:#fff;text-decoration:none">⬇ 下载 APK</a>
    <a href="<!--SRV:apk-zip-url-->" style="display:inline-block;padding:8px 12px;border-radius:8px;
       background:#2a3140;color:#e6e6e6;text-decoration:none">⬇ 下载 zip（点不动 apk 时用）</a>
    <span class="hint"><!--SRV:apk--></span>
  </div>
  <div class="hint" style="margin-top:6px">
    ✅ <b>可以直接覆盖安装</b>：<b>1.9.2</b> 与上一版是<b>同一个签名</b>（<code>…6cd3b40d</code>）⇒
    Android 会当成升级装，<b>不用卸载、App 数据都在</b>。<br>
    ⚠️ <b>只有换了打包密钥（签名变了）才需要先卸载</b>：那时要先用 App 自己的「备份」功能导出
    —— 卸载会清掉 App 数据。<br>
    ⚠️ 手机上如果提示"<b>不支持应用类型</b>"：说明浏览器把文件存成**没有后缀**的名字了 ——
    用手机「文件管理」找到它、改名成 <code>xxx.apk</code> 再点安装，
    或者**换成上面那个 zip**（解压后点里面的 apk）。
  </div>
</div>

<div class="card" id="api-key">
  <div class="lbl">API Key（口令）</div>
  <div id="keybox" class="k">读取中…</div>
  <div class="row" style="margin-top:8px">
    <input id="keyin" type="text" placeholder="📱 手机上：把 Key 粘到这里，点右边那个按钮">
    <button class="p" onclick="useKey()">用这个 Key</button>
    <button onclick="loadKey()">从本机读</button>
  </div>
  <div class="row" style="margin-top:6px">
    <button onclick="copyKey()">📋 一键复制 Key</button>
    <span id="keymsg" class="hint"></span>
  </div>
  <details class="help"><summary>Key 如何使用？</summary><div class="hint">
    ⚠️ 出于安全，<b>只有在这台电脑上</b>打开本页才读得到 Key。<br>
    📱 <b>手机上打开本页时</b>：在这台电脑上复制好 Key → 粘进上面那个输入框 → 点
    <b>「用这个 Key」</b>。它会存在<b>你手机浏览器里</b>，下次打开自动带上，不用再填。
  </div></details>
</div>

<div class="card">
  <div class="lbl">人格（可选 —— 选一份填进下面的系统提示词）</div>
  <div class="row">
    <select id="persona"><option value="">（读取中…）</option></select>
    <button class="p" onclick="fillPersona()">填入系统提示词</button>
    <button onclick="clearSys()">清空（= 裸模型）</button>
    <span id="pmsg" class="hint"></span>
  </div>
  <div class="hint" style="margin-top:6px">
    人格正文在 <code>personas\\</code> 里，<b>这里只读不写</b>（要改请改文件或在 AstrBot 界面改）。<br>
    ⚠️ 手机上要<b>先填 Key</b> 才读得到人格正文（列表不用）。<b>越长的越吃上下文</b>：
    一份 2.8 万字节的人格每轮都要重新读一遍，35B 上一半在 CPU —— 手机上想轻快就选短的。
  </div>
</div>

<div class="card" id="try-chat">
  <div class="lbl">当场测一次（流式）</div>
  <div class="row">
    <select id="model"></select>
    <button onclick="loadModels()">刷新模型</button>
  </div>
  <div class="row" style="margin-top:8px">
    <span class="hint">这条 API 给的是<b>裸模型</b> —— 没有内置人格。要人设就在下面自己写系统提示词，不写就是不写。</span>
  </div>
  <div style="margin-top:8px"><textarea id="sys" rows="3"
     placeholder="系统提示词（可留空 = 纯模型）"></textarea></div>
  <div style="margin-top:8px"><textarea id="ask" rows="2"
     placeholder="问一句试试，例如：你叫什么？ / 搜 今天有什么新闻"></textarea></div>
  <div class="row" style="margin-top:8px">
    <input id="img" type="file" accept="image/*" style="flex:0 0 auto;min-width:0;max-width:100%">
    <span class="hint">选张图 = 连图一起发（**要选支持图像的模型**，如 qwen2.5vl / minicpm-v / gemma3 / llava）</span>
  </div>
  <details class="help"><summary>联网搜索怎么触发？</summary><div class="hint">
    🔎 <b>联网搜索</b>（默认 <code>auto</code>）：网关<b>自己判断</b> —— 消息里出现
    事实/时效词（今天、最新、天气、价格、几点、版本…）就先去搜，再把结果和"必须引用来源"塞给模型；
    <b>「搜 / 搜索 / 查一下」开头的照旧强制搜</b>。纯闲聊/角色扮演不搜（省时间、免得把新闻编进剧情）。<br>
    想"每句都搜"：启动加 <code>--search-mode always</code>；想回到"只有关键字才搜"：
    <code>--search-mode keywords</code>。
  </div></details>
  <div class="row" style="margin-top:8px">
    <button class="p" onclick="send()">发送</button>
    <span id="smsg" class="hint"></span>
  </div>
  <div id="out" class="out" style="margin-top:10px"></div>
</div>

<div class="card" id="connect">
  <div class="lbl">别的设备（手机 App）怎么填</div>
  <table>
    <tr><td>API 地址</td><td><code id="v1"></code>（OpenAI 兼容）</td></tr>
    <tr><td>API Key</td><td>上面那个口令</td></tr>
    <tr><td>模型名</td><td><code>qiaojiu 见上面列表</code></td></tr>
    <tr><td>系统提示词</td><td>想给人设就自己写进这栏；不写就是纯模型</td></tr>
  </table>
  <pre id="curl"></pre>
</div>

<div class="card" id="page-notes">
  <div class="lbl">说明</div>
  <details class="help"><summary>网关能力和使用限制</summary><div class="hint">
    · 这条 API 给的是<b>裸模型</b>：没有人格（要人设就自己在客户端的「系统提示词」里写）；<br>
    · <b>联网搜索</b>：默认 <code>auto</code> —— 消息里出现事实/时效词（今天、最新、天气、价格、几点、版本…）网关就先去搜，
    结果里带来源；<b>「搜 / 搜索 / 查一下」开头是强制搜</b>。要"每句都搜"用 <code>--search-mode always</code>。<br>
    · 拉模型 <code>/api/pull</code>、删模型 <code>/api/delete</code> 被网关<b>默认拒绝（403）</b>。<br>
    · 多人同时用会互相抢显存和内存；手机上想轻快，模型选 <code>xiaojiu9b</code>。
  </div></details>
</div>
</div>
<script>
const $ = id => document.getElementById(id);
// 页面版本号：改页面就把它一起改掉（2026-10-05 加）。
// 用途：手机上"看不到新按钮/新逻辑"时，日志里的 `ver=` 和页面右下角能立刻告诉我们是**新版还是缓存**。
const PAGE_VER = '<!--SRV:ver-->';
try{ document.title = '消费级电脑本地部署的局域网 AI 助手 · ' + PAGE_VER; }catch(e){}
// 把手机上的情况回报给网关日志（我这边看不到你的控制台，只能靠这个）。
// ⚠️ 两条路一起走：`fetch` + **图片信标**（`new Image()`）—— 有些老浏览器/WebView 没有 fetch，
//    但图片信标一定能发出去；两条都不来，就说明这台设备的 JS 根本没在跑。
function beacon(msg){
  try{
    (new Image()).src = '/__clientlog?m=' + encodeURIComponent(String(msg).slice(0, 200))
                    + '&ver=' + PAGE_VER + '&t=' + Date.now();
  }catch(e){}
}
function clientlog(msg){
  beacon(msg);
  try{
    fetch('/__clientlog', {method:'POST', cache:'no-store',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({msg: String(msg).slice(0, 300), ver: PAGE_VER}),
      keepalive: true});
  }catch(e){}
}
window.onerror = function(m, s, l, c){ clientlog('JS错误: ' + m + ' @' + l + ':' + c); };
window.addEventListener('unhandledrejection', function(e){
  clientlog('Promise未处理: ' + ((e.reason && e.reason.message) || e.reason));
});
function pstat(t){ const e = $('pstat'); if(e) e.textContent = '面板状态：' + t; }
const base = location.origin;
$('base').textContent = base;
$('v1').textContent = base + '/v1';

// ---- Key：本机能自动读；手机读不到，就粘进输入框（存在本机浏览器里）----
let TOKEN = '';
function setKey(k, msg){
  TOKEN = (k || '').trim();
  $('keyin').value = TOKEN;
  $('keybox').textContent = TOKEN ? TOKEN : '（本页还没有 Key）';
  $('keymsg').innerHTML = msg || '';
  try{ if(TOKEN) localStorage.setItem('gw_key', TOKEN); else localStorage.removeItem('gw_key'); }catch(e){}
}
function useKey(){
  if(!$('keyin').value.trim()){
    $('keymsg').innerHTML = '<span class="warn">先把 Key 粘进输入框</span>'; return;
  }
  setKey($('keyin').value, '<span class="ok">已记住 ✓（存在这台设备上）</span>');
  loadPersonas();
}
async function loadKey(){
  $('keybox').textContent = '读取中…';
  try{
    const r = await fetch('/__key');
    const d = await r.json();
    if(r.ok){ setKey(d.token, '<span class="ok">从本机读到 ✓</span>'); }
    else {
      let saved = '';
      try{ saved = localStorage.getItem('gw_key') || ''; }catch(e){}
      if(saved){ setKey(saved, '<span class="ok">用本设备记住的 Key</span>'); }
      else {
        $('keybox').textContent = '（本页读不到 Key）';
        $('keymsg').innerHTML = '<span class="warn">' +
          (d.error || '被拒绝') + ' —— 请在电脑上复制 Key，粘进上面的输入框</span>';
      }
    }
  }catch(e){ $('keybox').textContent = '读取失败'; $('keymsg').textContent = e; }
  loadPersonas();
}
async function copyKey(){
  if(!TOKEN){ try{ const r = await fetch('/__key'); const d = await r.json(); TOKEN = d.token||''; }catch(e){} }
  if(!TOKEN){ $('keymsg').textContent = '本机没读到 Key（手机上就是读不到，得从电脑上复制）'; return; }
  try{ await navigator.clipboard.writeText(TOKEN); $('keymsg').textContent = '已复制 ✓'; }
  catch(e){ $('keymsg').textContent = '浏览器不让复制，请手动选中复制'; }
}
// ---- 人格：列表谁都能看（只有名字）；正文要本机、或带上正确 Key ----
async function loadPersonas(){
  try{
    const r = await fetch('/__personas'); const d = await r.json();
    const sel = $('persona'); const cur = sel.value; sel.innerHTML = '';
    (d.personas||[]).forEach(p => { const o = document.createElement('option');
      o.value = p.name;
      o.textContent = p.name + '（' + p.chars + ' 字' + (p.active ? ' · 默认' : '') + '）';
      sel.appendChild(o); });
    if(cur){ sel.value = cur; }
    // 记住上次选的那份：**只记名字、不自动填正文** —— 一填就是几千 token 的 prefill，
    // 不该在用户没点之前偷偷发生。
    let last = ''; try{ last = localStorage.getItem('gw_persona') || ''; }catch(e){}
    if(last && Array.from(sel.options).some(o => o.value === last)){
      sel.value = last;
      $('pmsg').innerHTML = '<span class="hint">上次选的是 ' + last + ' —— 点「填入系统提示词」就带上</span>';
    } else {
      $('pmsg').textContent = '共 ' + (d.personas||[]).length + ' 份';
    }
  }catch(e){ $('pmsg').innerHTML = '<span class="bad">读不到人格列表：' + e + '</span>'; }
}
async function fillPersona(){
  const name = $('persona').value;
  if(!name){ $('pmsg').textContent = '先选一份人格'; return; }
  const h = {}; if(TOKEN) h['Authorization'] = 'Bearer ' + TOKEN;
  try{
    const r = await fetch('/__persona?name=' + encodeURIComponent(name), {headers:h});
    const d = await r.json();
    if(!r.ok){ $('pmsg').innerHTML = '<span class="bad">' + (d.error || '被拒绝') + '</span>'; return; }
    $('sys').value = d.content || '';
    try{ localStorage.setItem('gw_persona', name); }catch(e){}
    $('pmsg').innerHTML = '<span class="ok">已填入 ' + name + '（' + (d.chars||0) + ' 字）</span>';
  }catch(e){ $('pmsg').innerHTML = '<span class="bad">' + e + '</span>'; }
}
let STOPPED = false;               // 小九是否已停（Ollama 不在跑）
function clearSys(){ $('sys').value = ''; $('pmsg').textContent = '已清空 —— 现在是裸模型'; }
function setHeroStatus(up){
  const pill = $('heroStatus'), label = $('heroStatusText');
  if(!pill || !label) return;
  pill.dataset.state = up ? 'online' : 'offline';
  label.textContent = up ? '模型服务在线' : '模型服务离线';
}
function showBanner(html, danger){
  const b = $('banner');
  if(!html){ b.style.display = 'none'; return; }
  b.style.display = 'block';
  b.style.borderColor = danger ? '#7a2b2b' : '#2b5a3a';
  b.style.background = danger ? '#2a1414' : '#12251a';
  b.style.color = danger ? '#ffd0d0' : '#cdeed8';
  b.innerHTML = html;
}
// 健康检查：Ollama 一停（不管是点上面那个按钮，还是双击 停止小九.bat），
// 这个页面就**停止刷新**并明确显示"已停止" —— 用户报过"网页脚本还在跑、不同步"。
async function healthTick(){
  let up = false;
  try{ const r = await fetch('/api/version?t=' + Date.now() + '&v=' + PAGE_VER, {cache: 'no-store'}); up = r.ok;
       pstat('正常（Ollama ' + (up ? '在跑' : '已停止') + '）'); }
  catch(e){ up = false; pstat('连不上网关：' + e); clientlog('健康检查失败: ' + e); }
  setHeroStatus(up);
  const was = STOPPED; STOPPED = !up;
  if(STOPPED){
    showBanner('⏹ <b>小九已停止</b>（Ollama 没在跑）。在电脑上双击 <code>启动AstrBot.bat</code> 就能起来，'
               + '这个页面会在几秒内自动恢复；期间<b>资源面板已暂停刷新</b>。', true);
  } else {
    if(was) showBanner('✅ 小九又起来了（Ollama 已就绪），面板继续刷新。', false);
    else showBanner('', false);
    if(was) loadStats();
  }
}
function ctlSay(html){ $('ctlmsg').innerHTML = html; }
function noKeyHint(){
  // 没填 Key 时**必须让人一眼看见**：以前只往小字里塞一句话，用户以为"按了没反应"
  showBanner('🔒 停止小九需要先填 <b>API Key</b>：把上面的 Key 粘进「API Key（口令）」那个输入框，'
             + '点 <b>「用这个 Key」</b>，再按下面的「⏹ 停止小九」。（电脑本机上打开则不用填）', true);
  const k = $('keyin');
  if(k){ k.style.borderColor = '#c0392b'; k.focus();
         try{ k.scrollIntoView({behavior:'smooth', block:'center'}); }catch(e){ k.scrollIntoView(); } }
}
async function dryRun(){
  if(!TOKEN){ noKeyHint(); return; }
  try{
    const h = {}; if(TOKEN) h['Authorization'] = 'Bearer ' + TOKEN;
    const r = await fetch('/__shutdown?dry=1&t=' + Date.now(), {method:'POST', headers:h, cache:'no-store'});
    const d = await r.json();
    if(!r.ok){ ctlSay('<span class="bad">' + (d.error || '被拒绝') + '</span>'); return; }
    ctlSay('会停这些：' + (d.detail || []).map(x => x.what + '（' + x.result + '）').join('；'));
  }catch(e){ ctlSay('<span class="bad">' + e + '</span>'); }
}
async function makeTicket(){
  // 在电脑上生成一个 4 位授权码 → 手机上在 /plain 填一次 → 之后手机免 Key（种 cookie）
  try{
    const h = {}; if(TOKEN) h['Authorization'] = 'Bearer ' + TOKEN;
    const r = await fetch('/__ticket?t=' + Date.now(), {method:'POST', headers:h, cache:'no-store'});
    const d = await r.json();
    if(!r.ok){ ctlSay('<span class="bad">' + (d.error || '被拒绝') + '</span>'); return; }
    showBanner('📱 手机授权码：<b style="font-size:26px;letter-spacing:3px">' + d.code + '</b>'
               + '　（' + Math.round(d.ttl / 60) + ' 分钟内有效，用一次就作废）<br>'
               + '在手机上打开 <b>' + location.origin + '/plain</b> → 把它填进「✅ 授权这台手机」→ '
               + '以后手机点「⏹ 停止小九」就不用再填 Key 了。', false);
    const k = $('ticketmsg'); if(k) k.innerHTML = '授权码 <b>' + d.code + '</b>（填到手机 /plain 页）';
  }catch(e){ ctlSay('<span class="bad">' + e + '</span>'); }
}
async function shutdownXiaojiu(){
  clientlog('点击了 停止小九（Key=' + (TOKEN ? '有' : '没有') + '）');
  if(!TOKEN){ noKeyHint(); return; }
  if(!confirm('确定要停掉小九吗？\\n\\n停 Ollama（释放显存）+ 清 llama-server 残留 + 关 AstrBot。\\n' +
              '网关和这个页面会留着，并提示"已停止"。')) return;
  ctlSay('正在停…');
  try{
    const r = await fetch('/__shutdown?t=' + Date.now(), {method:'POST', cache:'no-store',
      headers:{'Authorization': 'Bearer ' + TOKEN}});
    const d = await r.json();
    if(!r.ok){ ctlSay('<span class="bad">' + (d.error || '被拒绝') + '</span>'); return; }
    ctlSay('<span class="ok">已执行：' +
           (d.detail || []).map(x => x.what + ' → ' + x.result).join('；') + '</span>');
    if(d.gateway_stops_in){
      STOPPED = true;                 // 停止面板轮询（网关马上要没了）
      showBanner('⏹ <b>小九已全部停止</b> —— 网关（这个页面）将在 <b>'
                 + d.gateway_stops_in + ' 秒</b>后关闭，之后本页会连不上。<br>'
                 + '要重新启动：在电脑上双击 <code>启动局域网API.bat</code>（只起网关）'
                 + '或 <code>启动AstrBot.bat</code>（起整套）。', true);
    }
    healthTick();
  }catch(e){ ctlSay('<span class="bad">' + e + '</span>'); }
}

// ---- 系统资源面板（2026-10-05 加）：4 条进度条 + 一条 60 点的 sparkline ----
const HIST = {cpu: [], mem: [], vram: [], gpu: []};
const HMAX = 60;
function setMeter(barId, valId, pct, text, color){
  const b = $(barId); if(b){ b.style.width = Math.max(0, Math.min(100, pct)) + '%'; b.style.background = color; }
  if(text !== null) $(valId).textContent = text;
}
function drawSpark(){
  const cv = $('spark'); if(!cv) return;
  const g = cv.getContext('2d'), W = cv.width, H = cv.height;
  g.clearRect(0, 0, W, H);
  g.strokeStyle = '#262b36'; g.lineWidth = 1;
  [0.25, 0.5, 0.75].forEach(f => {               // 25/50/75% 参考线
    g.beginPath(); g.moveTo(0, H * f); g.lineTo(W, H * f); g.stroke();
  });
  [['cpu', '#2f6df6'], ['mem', '#6ee7a8'], ['vram', '#ffcf6b'], ['gpu', '#ff8f8f']].forEach(([k, col]) => {
    const a = HIST[k]; if(a.length < 2) return;
    g.strokeStyle = col; g.lineWidth = 1.8; g.beginPath();
    a.forEach((v, i) => {
      const x = i / (HMAX - 1) * W, y = H - (Math.max(0, Math.min(100, v)) / 100) * (H - 4) - 2;
      i ? g.lineTo(x, y) : g.moveTo(x, y);
    });
    g.stroke();
  });
}
async function loadStats(){
  try{
    // 带时间戳 + no-store：手机浏览器缓存过 `/__stats` 的旧响应（那个 null 让面板一直"读取中"）
    const r = await fetch('/__stats?t=' + Date.now() + '&v=' + PAGE_VER, {cache: 'no-store'});
    const d = await r.json();
    pstat('正常（最近一次 ' + new Date().toLocaleTimeString() + '）');
    $('pver').textContent = PAGE_VER;
    // 「模型」+「最近一次对话」（2026-10-06 加）：让"到底有没有调用模型"一眼可见
    if($('v_model') && d.model_line) $('v_model').innerHTML = d.model_line;
    if($('heroModel') && d.model_line) $('heroModel').innerHTML = d.model_line;
    if($('v_lastchat') && d.last_chat_line) $('v_lastchat').innerHTML = d.last_chat_line;
// 上下文占用（2026-10-18 加）：回答"快超载了吗"——分母是模型真窗口，不是写死的 64K
if($('v_ctx') && d.ctx_line) $('v_ctx').innerHTML = d.ctx_line;
    if(d.cpu_pct === null || d.cpu_pct === undefined){
      $('v_cpu').textContent = '读取中…';       // 第一次调用没有基准，2 秒后就有了
    } else {
      setMeter('b_cpu', 'v_cpu', d.cpu_pct, d.cpu_pct.toFixed(1) + '%', '#2f6df6');
      HIST.cpu.push(d.cpu_pct);
    }
    if(d.mem){
      setMeter('b_mem', 'v_mem', d.mem.pct,
               d.mem.used_gb + ' / ' + d.mem.total_gb + ' GB（' + d.mem.pct + '%）', '#6ee7a8');
      HIST.mem.push(d.mem.pct);
    }
    if(d.gpu && d.gpu.length){
      const g0 = d.gpu[0], vram = g0.mem_used_mb / g0.mem_total_mb * 100;
      setMeter('b_vram', 'v_vram', vram,
               (g0.mem_used_mb / 1024).toFixed(2) + ' / ' + (g0.mem_total_mb / 1024).toFixed(2) + ' GB', '#ffcf6b');
      setMeter('b_gpu', 'v_gpu', g0.util, g0.util + '%　' + g0.temp_c + '°C', '#ff8f8f');
      $('v_gpu_name').textContent = g0.name || '';
      HIST.vram.push(vram); HIST.gpu.push(g0.util);
    } else {
      $('v_gpu').textContent = '没有 nvidia-smi';
    }
    Object.keys(HIST).forEach(k => { if(HIST[k].length > HMAX) HIST[k].shift(); });
    drawSpark();
  }catch(e){ $('v_cpu').textContent = '读不到：' + e; pstat('取数失败：' + e); clientlog('面板取数失败: ' + e); }
}
async function loadModels(){
  try{
    const r = await fetch('/api/tags'); const d = await r.json();
    const sel = $('model'); sel.innerHTML = '';
    (d.models||[]).forEach(m => { const o = document.createElement('option');
      o.value = m.name; o.textContent = m.name + '  (' + (m.size/1e9).toFixed(1) + ' GB)'; sel.appendChild(o); });
    $('curl').textContent =
      'curl.exe ' + base + '/v1/chat/completions -H "Authorization: Bearer <KEY>" ^\\n' +
      '  -H "Content-Type: application/json" -d "{\\"model\\":\\"' + (sel.value||'xiaojiu9b:latest') +
      '\\",\\"messages\\":[{\\"role\\":\\"user\\",\\"content\\":\\"你好\\"}]}"';
  }catch(e){ $('smsg').innerHTML = '<span class="bad">拉模型列表失败：' + e + '</span>'; }
}
function readAsDataURL(f){
  return new Promise(function(res, rej){
    const r = new FileReader(); r.onload = function(){ res(r.result); }; r.onerror = rej;
    r.readAsDataURL(f);
  });
}
async function send(){
  const ask = $('ask').value.trim();
  const f = $('img') && $('img').files && $('img').files[0];
  if(!ask && !f){ $('smsg').textContent = '先写一句（或选一张图）'; return; }
  if(!TOKEN){ try{ const r = await fetch('/__key'); const d = await r.json(); TOKEN = d.token||''; }catch(e){} }
  if(TOKEN){ $('keyin').value = TOKEN; }
  const msgs = [];
  const sys = $('sys').value.trim(); if(sys) msgs.push({role:'system', content:sys});
  // 视觉：选了图就发 OpenAI 那种多模态数组。网关会按接口自动转换
  //（/api/chat 会被它转成 Ollama 原生的 images 字段），所以这里只写一种形状即可。
  if(f){
    const dataUrl = await readAsDataURL(f);
    msgs.push({role:'user', content:[
      {type:'text', text: ask || '这张图里有什么？'},
      {type:'image_url', image_url:{url: dataUrl}}]});
    $('smsg').textContent = '已带图（' + Math.round(f.size/1024) + ' KB），用的是 ' + $('model').value;
  } else {
    msgs.push({role:'user', content:ask});
  }
  $('out').textContent = ''; $('smsg').textContent = ($('smsg').textContent || '') + ' 生成中…';
  const t0 = Date.now();
  try{
    const h = {'Content-Type':'application/json'};
    if(TOKEN) h['Authorization'] = 'Bearer ' + TOKEN;   // 没 Key 也发：服务端默认不强制口令
    const r = await fetch('/api/chat', {method:'POST', headers:h,
      body: JSON.stringify({model:$('model').value, messages:msgs, stream:true})});
    if(!r.ok){ $('out').textContent = 'HTTP ' + r.status + '\\n' + (await r.text()).slice(0,400);
               $('smsg').innerHTML = '<span class="bad">失败</span>'; return; }
    const rd = r.body.getReader(); const dec = new TextDecoder(); let buf = '', n = 0;
    while(true){
      const {done, value} = await rd.read(); if(done) break;
      buf += dec.decode(value, {stream:true});
      const lines = buf.split('\\n'); buf = lines.pop();
      for(const ln of lines){
        if(!ln.trim()) continue;
        try{ const j = JSON.parse(ln);
          if(j.message && j.message.content){ $('out').textContent += j.message.content; n += j.message.content.length; }
        }catch(e){}
      }
    }
    $('smsg').innerHTML = '<span class="ok">完成：' + n + ' 字符 / ' +
      ((Date.now()-t0)/1000).toFixed(1) + ' 秒</span>';
  }catch(e){ $('out').textContent += '\\n[出错] ' + e; $('smsg').innerHTML = '<span class="bad">出错</span>'; }
}
loadKey(); loadModels();
// 资源面板：每 3 秒刷一次，但**页面切到后台就不请求**（手机锁屏/切 App 时完全不耗）
function statsTick(){ if(!document.hidden && !STOPPED) loadStats(); }   // 停了/切后台就不拉
statsTick(); setInterval(statsTick, 3000);
healthTick(); setInterval(healthTick, 5000);   // 小九一停，5 秒内页面就会显示"已停止"并停手
// 回到前台/重新获得焦点都立刻拉一次（手机上切走再回来，定时器可能被系统冻结过）
['visibilitychange', 'focus', 'pageshow'].forEach(function(ev){
  window.addEventListener(ev, function(){
    if(ev === 'visibilitychange' && document.hidden) return;
    statsTick(); healthTick();
  });
});
// 页面一打开就把话说回去：手机上"看不到新版/面板不动"时，日志里就能看到这条
setTimeout(function(){
  const has = !!TOKEN;
  clientlog('页面已加载 ' + (has ? '（有 Key）' : '（没有 Key）')
            + ' hidden=' + document.hidden + ' 屏宽=' + window.innerWidth);
  $('pver').textContent = PAGE_VER;
  if(!has){
    showBanner('🔒 这一页<b>还没有填 Key</b>：停止小九用不了。在电脑上打开 '
               + '<code>http://127.0.0.1:11435/</code> 复制 Key → 粘进上面「API Key（口令）」框 '
               + '→ 点「用这个 Key」。填一次就记住了（存在手机本地）。', true);
  }
}, 600);
</script></body></html>"""



def render_plain_page(st: dict, ok_msg: str = "", page_ver: str = PAGE_VER) -> str:
    r"""**完全不用 JavaScript 的极简控制页**（`GET /plain`）。

    为什么单独做这一页（2026-10-05）：用户的手机自带浏览器（vivo）**会把内联脚本删掉**
    （HTML/CSS 照渲染），于是主页面永远"资源读取中"、按钮点了没反应。
    这一页只用 HTML：
      · 数字由**服务端渲染**；
      · `<meta http-equiv="refresh" content="3">` **每 3 秒自己重载** ⇒ 数字会动；
      · 停止小九 = **表单 POST**（表单不需要 JS）。
    """
    cpu = st.get("cpu_pct")
    mem = st.get("mem") or {}
    g = (st.get("gpu") or [{}])[0]
    vram = (g.get("mem_used_mb", 0) / g["mem_total_mb"] * 100) if g.get("mem_total_mb") else None

    def row(name, pct, text):
        w = 0 if pct is None else max(0.0, min(100.0, pct))
        return (f"<div class='m'><span>{name}</span>"
                f"<div class='bar'><i style='width:{w:.1f}%'></i></div>"
                f"<em>{text}</em></div>")

    rows = (row("CPU", cpu, "读取中…" if cpu is None else f"{cpu:.1f}%")
            + row("内存", mem.get("pct"),
                  "" if not mem else f"{mem['used_gb']} / {mem['total_gb']} GB（{mem['pct']}%）")
            + row("显存", vram,
                  "" if not g.get("mem_total_mb")
                  else f"{g['mem_used_mb'] / 1024:.2f} / {g['mem_total_mb'] / 1024:.2f} GB")
            + row("GPU", g.get("util"),
                  "" if not g else f"{g.get('util')}%　{g.get('temp_c')}°C"))
    when = datetime.datetime.now().strftime("%H:%M:%S")
    ok_html = ("" if not ok_msg else
               f"<div style='margin:8px 0;padding:8px;border-radius:8px;"
               f"background:{'#12251a' if ok_msg.startswith('✅') else '#2a1414'};"
               f"color:{'#cdeed8' if ok_msg.startswith('✅') else '#ffd0d0'}'>{ok_msg}</div>")
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- 这一页**故意没有一行 JavaScript**：给"会删掉脚本"的浏览器用。
     数字靠服务端渲染 + 这行 meta 每 3 秒自动重载来更新。 -->
<meta http-equiv="refresh" content="3">
<title>局域网 AI 助手控制台（无脚本版）</title>
<style>
 body{{font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif;margin:0;padding:16px;
      background:#0f1115;color:#e6e6e6}}
 .w{{max-width:620px;margin:0 auto}}
 h1{{font-size:19px;margin:6px 0 2px}}
 .sub{{color:#8b93a1;font-size:13px;margin-bottom:14px}}
 .card{{background:#151922;border:1px solid #262b36;border-radius:10px;padding:14px;margin:12px 0}}
 .m{{display:flex;align-items:center;gap:9px;margin:7px 0}}
 .m>span{{width:44px;color:#8b93a1;font-size:13px}}
 .bar{{flex:1;height:13px;background:#0f1115;border:1px solid #262b36;border-radius:7px;overflow:hidden}}
 .bar>i{{display:block;height:100%;background:#2f6df6}}
 .m>em{{width:150px;text-align:right;font-style:normal;font-size:13px}}
 input{{font:15px;padding:7px;border-radius:7px;border:1px solid #333a47;background:#0f1115;
        color:#e6e6e6;width:min(260px,70%)}}
 button{{font:15px;padding:8px 12px;border-radius:7px;border:0;background:#2f6df6;color:#fff;
         margin:6px 6px 0 0}}
 .hint{{color:#8b93a1;font-size:12.5px}}
 a{{color:#7aa2f7}}
</style></head><body><div class="w">
<h1>⏹ 局域网 AI 助手控制台（无脚本版）</h1>
<div class="sub">这一页<b>一行 JavaScript 都没有</b>，所以"会删脚本的浏览器"也能用。
  数字由服务端渲染，靠 <code>&lt;meta refresh&gt;</code> 每 3 秒重载更新（这一页刷新时间 {when}）。</div>

<div class="card"><div class="hint" style="margin-bottom:6px">系统资源</div>{rows}</div>

<!-- ⚠️ 2026-10-18 加：不用脚本的这页也要能看到"这一轮等了多久 / 上下文占了多少" ✓ -->
<div class="card"><div class="hint" style="margin-bottom:6px">最近一次对话 / 上下文占用</div>
  <div>{st.get('last_chat_line') or '（还没有对话）'}</div>
  <div style="margin-top:6px">{st.get('ctx_line') or ''}</div></div>

<div class="card">
  <div class="hint" style="margin-bottom:6px">
    停止小九 ＝ 双击 <code>停止小九.bat</code> 的三步：停 Ollama（释放显存）+
    清 llama-server 残留 + 关 AstrBot，**并且 5 秒后连网关自己也关掉**
    （＝ 用户要的"所有小九进程都关闭"）。这 5 秒是留给你看结果的。<br>
    要重新启动：电脑上双击 <code>启动局域网API.bat</code>（只起网关）或
    <code>启动AstrBot.bat</code>（起对话整套）。<br>
    {ok_html}
  </div>
  <form method="post" action="/__shutdown">
    <input name="key" type="password" placeholder="把 Key 粘在这里（或先做下面的授权）">
    <div>
      <button type="submit">⏹ 停止小九</button>
      <button type="submit" name="dry" value="1">先看看会停哪些</button>
    </div>
  </form>
</div>

<div class="card">
  <div class="hint" style="margin-bottom:6px">
    📱 <b>一次性授权（30 天免填 Key）</b>：在电脑上打开
    <a href="/">http://127.0.0.1:11435/</a>，点 <b>「📱 生成手机授权码」</b>，
    会显示一个 <b>4 位数字</b>（10 分钟内有效）。把它填到下面：
  </div>
  <form method="get" action="/plain">
    <input name="code" inputmode="numeric" pattern="[0-9]*" maxlength="4"
           placeholder="电脑上显示的 4 位数字">
    <div><button type="submit">✅ 授权这台手机</button></div>
  </form>
</div>

<div class="hint">完整的网页（带对话测试、人格、Key 管理，需要浏览器执行脚本）：
  <a href="/">/</a> · 本页版本 {page_ver}</div>
</div></body></html>"""
