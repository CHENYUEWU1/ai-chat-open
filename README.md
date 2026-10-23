<h1 align="center">本地 AI 助手</h1>

<p align="center"><strong>在 Windows 电脑上运行本地模型，并通过浏览器、手机或 OpenAI 兼容客户端使用。</strong></p>

<p align="center">
  <a href="部署指南.md">部署指南</a> ·
  <a href="功能与使用指南.md">功能与使用</a> ·
  <a href="07-局域网API.md">局域网 API</a> ·
  <a href="LICENSE">MIT License</a>
</p>

---

这个项目用 [llama.cpp](https://github.com/ggml-org/llama.cpp) 在本机运行 GGUF 模型，并提供两样东西：一个**网页聊天台**（自带会话、上传文件、人格卡、联网搜索），和一个**轻量网关**（网页授权 + OpenAI 兼容 API，给手机 App / AI 代理用）。首次体验只需要 llama.cpp、Python 和一个 GGUF 模型；AstrBot 与插件是可选扩展。

> 仓库不包含模型权重、llama.cpp 运行时或个人运行数据。项目代码使用 MIT License；模型及第三方软件遵循各自的许可。

## 能做什么

- **网页聊天台（独立进程，11437）：** 多会话（新建 / 改名 / 归档 / 删除 / 搜索）、流式输出与停止、**重新生成**（可指定某一条）、**编辑后重发**、**上传文件让它按要求处理**（txt / md / json / csv / docx）、**人格卡可直接手填**（纯文本或 chara_card_v2 JSON）、**联网搜索**、**上下文档位**（8k/16k/32k/64k）、导出 Markdown、全文检索历史、手机适配。数据默认在项目外的数据目录，不进 Git。
- **本地推理：** 聊天台直连本机 llama.cpp（默认 `11450`），网关在 `11435` 上把它包成 OpenAI 兼容接口。
- **多种入口：** 内置网页聊天、OpenAI 兼容 API，以及可信局域网内的手机访问。
- **网页授权与 API Token：** 浏览器授权码和 API Token 分开管理；可查看本机资源。
- **可选联网搜索：** 聊天台和网关都能搜；搜索会把查询发送给外部搜索服务，不需要时可以关闭。
- **可选扩展：** 仓库包含 AstrBot 插件源码；AstrBot 通过 OpenAI 兼容提供商接入本项目的网关。

## 三种用法怎么选

| 用法 | 入口 | 记忆谁管 | 工具调用 | 排版 | 适合 |
|---|---|---|---|---|---|
| **① 网页聊天台** | `http://127.0.0.1:11437/wc`；或打开网关面板点「网页聊天台」自动拉起 | **聊天台自己**（本地 SQLite，多会话互相隔离，可搜历史） | 不需要 | 自己渲染 markdown | 日常聊天、写东西、传文件让它总结、手填人格卡、联网搜索 |
| **② 手机 App** | App 里填 `http://<电脑IP>:11435/v1` + API Key | **App 自己**（每轮把历史发上来） | 关（网关剥掉） | 网关**边流边洗**（有的 App 不渲染 markdown、会在空行吞字） | 手机上随手聊 |
| **③ AI 代理干活** | 代理里把 Base URL 指到 `http://127.0.0.1:11435/v1` | **代理自己**带历史 | **开**（`/v1` 原样透传 tools） | **逐字原样**（要代码/markdown 原样） | 让 AI 读写文件、跑命令、查资料这类"干活" |

**一句话区别**：① 记忆和数据自己管、体验最好；② 借客户端界面，但受客户端规则约束；③ 给 AI 代理用，必须原样 + 工具。
**互不干扰**：① 直连本机 llama.cpp `11450`，完全不经过网关；只有 ②③ 才走 `11435`。

## 快速开始

### 需要准备

- Windows 10 或更新版本
- Python 3.12 或更新版本
- **llama.cpp 的 Windows 构建**（含 `llama-server.exe`）
- **一个 GGUF 模型文件**（建议先从 4B 级开始）

> 你的显卡比较新（例如 RTX 50 系 / sm_120）时，官方 CUDA 12.4 构建**可能没有对应内核**，会静默退回 CPU（速度掉到个位数 tok/s）。这种情况需要 CUDA 12.8+ 的构建，或直接用 Vulkan 构建。

### 1. 准备 llama.cpp 和模型

从 [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) 下载 Windows 构建并解压，把 `llama-server.exe` 所在目录放在下面二者之一：

```
<项目目录>\llama.cpp\bee\bin\        ← 默认位置（推荐）
```

或用环境变量指向任意位置：

```powershell
setx AI_CHAT_LLAMA_BIN "D:\llama.cpp\build\bin"
```

模型（`.gguf`）默认找 `<项目目录>\downloads\` 里的文件；也可用环境变量指定：

```powershell
setx AI_CHAT_GGUF_35B "D:\models\your-model.gguf"
```

### 2. 克隆仓库并启动

```powershell
git clone https://github.com/CHENYUEWU1/ai-chat-open.git
cd ai-chat-open
```

一键启动（Windows 批处理会依次拉起 llama.cpp → 网关 → 网页聊天台）：

```bat
启动局域网API.bat
```

或手动分步：

```powershell
python .\workbench.py --ensure-llama          # 起 llama.cpp（11450），会打印加载进度
python .\workbench.py                          # 起网页聊天台（11437）
python .\ollama_gateway.py --host 127.0.0.1 --port 11435 --upstream llamacpp --require-key
```

4. 打开 <http://127.0.0.1:11435/>。首次访问时，在 PowerShell 中查看网页授权码：

```powershell
python .\ollama_gateway.py --show-access-code
```

网页授权码用于浏览器访问；连接 API 客户端时，查看并填写 API Token：

```powershell
python .\ollama_gateway.py --show-token
```

API Base URL 为 `http://127.0.0.1:11435/v1`，模型名填 `lc-35b`（网关会把任何模型名改写成当前加载的那个）。

### 让手机或其他设备接入

在电脑和手机连接同一个可信的家庭网络后，停止当前网关，再用下面的命令启动：

```powershell
python .\ollama_gateway.py --host 0.0.0.0 --port 11435 --upstream llamacpp --require-key
```

浏览器访问 `http://<电脑局域网IP>:11435/` 并输入网页授权码。API 客户端使用 `http://<电脑局域网IP>:11435/v1` 和上面查到的 API Token。若 Windows 防火墙弹出提示，只允许专用网络访问。

> **安全提示：** 局域网网关使用未加密 HTTP。只在可信的私人网络中使用，不要把 11435 端口映射到公网。命令中的 `--require-key` 会强制聊天 API 校验 Token；网页授权码与 API Token 是两种不同凭据。

## 电脑配置与模型

模型越大，对内存、显存和磁盘的要求越高。GPU 不是必需品，但会显著影响速度。作为起点，可先试 4B 级的 GGUF；16 GB 内存和 8 GB 显存会更从容。35B 级 MoE 模型在 8 GB 显存上通常需要把一部分专家权重留在内存（`--n-cpu-moe`），要额外预留约 9 GB 内存。

| 规模 | 参考来源 | 说明 |
| --- | --- | --- |
| 4B 级 | 任意 GGUF 发布页（如 Qwen 系列的 GGUF 量化） | 推荐入门 |
| 9B 级 | 同上 | 质量和资源占用更高；全部放显存时速度很快 |
| 35B-A3B（MoE） | 同上，选 IQ2/Q2 级量化 | 进阶选项；8 GB 显存需 `--n-cpu-moe`，内存需求较高 |

模型由你自行下载，不随本仓库分发；使用前请查看其模型页许可。参数选择与实测数据见[部署指南](部署指南.md)。

**llama.cpp 的两个坑**（都实测过，写进 `workbench.py` 的注释里）：

- 必须 `-fa on`（开启 flash attention）。不开时长提示的预填充会掉到约 20 tok/s；
- 8 GB 显存上不要用 `--fit on`，要显式给 `--n-cpu-moe`（本仓库默认按上下文档位成对给）。

## 网络与隐私

模型推理由本机 llama.cpp 执行。联网搜索会把查询发给 AnySearch，网页读取会访问目标网站；使用 Telegram 等第三方平台时，消息也会经过相应平台。不需要搜索时可在启动命令后加 `--no-search`。

网关设置、授权信息和日志保存在本机用户数据目录。日志可能包含来源 IP、客户端类型、访问路径、模型和状态等使用信息；分享前请先检查并脱敏。不要提交 API Token、Bot Token、聊天记录、运行日志或模型文件。

## 仓库内容

| 文件或目录 | 用途 |
| --- | --- |
| `启动局域网API.bat` | 一键启动：llama.cpp（11450）+ 网关（11435）+ 网页聊天台（11437） |
| `停止模型.bat` | 停止上面三个（按端口停 Python 进程，不会误杀别的 Python） |
| `workbench.py` | **网页聊天台**：独立进程（默认 11437），直连 llama.cpp，聊天 / 传文件 / 人格卡 / 联网搜索 / 上下文档位 / 导出 |
| `ollama_gateway.py` | 网关服务：网页、授权、OpenAI 兼容 API，转发到 llama.cpp（`--upstream llamacpp`；文件名是历史遗留） |
| `gateway_page.py` | 网关网页界面（**必须与 `ollama_gateway.py` 同目录**；改页面要一起改 `PAGE_VER`） |
| `check_all.py`、`test_access.py`、`smoke_test.py` | 自检与验收脚本（只读巡检、鉴权、冒烟） |
| `scripts/` | 根目录脚本的同步副本（改脚本改根目录那份） |
| `plugins/` | AstrBot 可选插件源码 |
| `部署指南.md` | 从准备 llama.cpp 到手机接入的完整步骤 |
| `功能与使用指南.md` | 功能说明和使用限制 |
| `07-局域网API.md` | 网关接口、授权与安全设置 |

**运行数据不进仓库**：网关状态、授权设备、日志在网关自己的数据目录；网页聊天台的会话、上传文件、人格卡、备份在其数据目录（默认 `%LOCALAPPDATA%\AIWebChat`，可用 `AI_CHAT_DIR` 改）。两者都不参与 Git 与打包。

仓库中的 `.bat` 启动入口用 `%~dp0` 按脚本所在目录定位项目文件，整个目录搬到别处也能双击运行；llama.cpp 与模型位置用上面提到的环境变量指定。AstrBot 相关高级脚本面向特定安装结构，不是通用安装器。
