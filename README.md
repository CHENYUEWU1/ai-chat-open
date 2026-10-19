<h1 align="center">消费级电脑本地部署的局域网 AI 助手</h1>

<p align="center"><strong>用自己的电脑运行 AI，让手机和可信局域网设备也能使用。</strong></p>

<p align="center">Windows · Ollama · 本地模型 · 局域网网页与 API</p>

<p align="center">
  <a href="部署指南.md">部署指南</a> ·
  <a href="功能与使用指南.md">功能与使用</a> ·
  <a href="07-局域网API.md">局域网 API</a> ·
  <a href="LICENSE">MIT License</a>
</p>

---

这是一个供个人电脑运行的本地 AI 项目。Ollama 负责下载和运行模型，项目网关提供浏览器聊天页面及 OpenAI 兼容 API。AstrBot 和项目插件属于可选扩展；首次体验不需要安装它们。

## 快速开始

1. 安装 [Ollama for Windows](https://ollama.com/download/windows)（Windows 10 或更新版本）。
2. 在 PowerShell 下载一个模型并先验证能聊天：

   ```powershell
   ollama pull qwen3.5:4b
   ollama run qwen3.5:4b
   ```

3. 安装 Python 3.12 或更新版本，下载本仓库 ZIP 并解压。
4. 双击 `启动局域网API.bat`，按窗口提示打开本机网页。首次访问要用网页授权码；`获取API密钥.bat` 会显示授权码和 API Token。API Token 用于配置兼容客户端。
5. 只在需要手机或其他设备时开放局域网访问。手机和电脑连同一个可信 Wi-Fi，在浏览器访问 `http://<电脑局域网IP>:11435/`。

完整步骤、配置建议和排错见[部署指南](部署指南.md)。

## 电脑配置与模型选择

以下是实际使用的粗略建议，不是硬性最低要求。模型文件大小来自 [Ollama Qwen 3.5 模型库](https://ollama.com/library/qwen3.5)；运行时还要给 Windows、上下文缓存和其他软件留内存。

| 模型 | 下载命令 | 模型文件大小 | 建议用途与配置 |
| --- | --- | ---: | --- |
| Qwen 3.5 4B | `ollama pull qwen3.5:4b` | 约 3.3–4.0 GB | 推荐起步；16 GB 内存，6–8 GB 显存更从容；也可纯 CPU 运行但会慢 |
| Qwen 3.5 9B | `ollama pull qwen3.5:9b` | 约 6.6–7.6 GB | 质量更好；建议 24 GB 内存或 12 GB 以上显存；8 GB 显存通常比较紧 |
| Qwen 3.5 35B-A3B | `ollama pull qwen3.5:35b-a3b` | 约 22 GB | 进阶尝试；建议 32 GB 以上内存或 24 GB 以上显存，模型可能需要 CPU/GPU 混合运行 |

磁盘至少预留所选模型大小的两倍，给下载缓存、其他模型和升级留空间。GPU 不是必需品；没有独显也能运行，只是生成速度会降低。**模型文件大小不等于显存需求**：上下文越长、显卡桌面占用越多，可用显存越少。先从 4B 开始，再根据 `ollama ps` 的实际占用尝试更大模型。

常见瓶颈：显存不足会让部分模型层转到系统内存或 CPU，速度明显下降；内存不足会卡顿或导致模型退出；上下文太长会增加缓存占用；多个手机/客户端同时请求会共享一份算力。SSD 能缩短模型载入时间，但不能弥补显存或内存不足。

## 模型下载链接

- [Ollama Qwen 3.5 模型库与各尺寸标签](https://ollama.com/library/qwen3.5)：推荐新用户从这里选 4B 或 9B，并用上表命令下载。
- [Ollama Windows 安装页](https://ollama.com/download/windows)
- [AstrBot Desktop 官方发布页](https://github.com/AstrBotDevs/AstrBot-desktop/releases)：只在需要 AstrBot 聊天界面、人格或插件时安装。

模型权重不包含在本仓库中，由 Ollama 从模型库下载。上游模型有自己的许可条款；使用或再分发模型前请查看对应模型页的许可。

## 项目文件怎么用

| 文件或目录 | 用途 | 新用户是否需要 |
| --- | --- | --- |
| `启动局域网API.bat` | 检查 Python、Ollama 是否可用，然后启动本地网关 | 需要使用项目网页或局域网 API 时使用 |
| `ollama_gateway.py` | 网关服务：浏览器页面、授权、OpenAI 兼容 API、请求转发 | 由启动脚本调用；一般不用手动改 |
| `gateway_page.py` | 网关网页的界面模板 | 只在修改页面时使用 |
| `获取API密钥.bat` | 在本机显示网页授权码和 API Token | 浏览器首次授权、配置 API 客户端时使用 |
| `Modelfile.assistant*` | 官方 Qwen 4B、9B、35B 的参数与系统提示词示例 | 可选；见[部署指南](部署指南.md) |
| `plugins/` | AstrBot 的可选插件 | 只有安装 AstrBot 并按其说明配置时使用 |
| `交付包/`、`scripts/` | 辅助、同步和维护脚本 | 首次部署不需要运行 |

`astrbot_setup.py`、若干人格切换和维护脚本针对原作者的自定义 AstrBot 安装结构；它们不是通用安装器。新电脑请按部署指南手动连接 Ollama，先不要运行这些高级脚本。

## 网络与隐私

模型推理默认由本机 Ollama 完成。Ollama 的[隐私说明](https://ollama.com/privacy)表示，本地处理的提示和回复不会被 Ollama 收集或传输。网关联网搜索默认按问题自动触发：自动搜索会把命中的问题文本（最多 200 字符）发送到 AnySearch；显式搜索会发送触发词后面的查询内容。不需要注册密钥不等于匿名或私密，搜索服务仍会收到查询和网络请求。网页读取会访问目标网站；Telegram 等第三方平台也会收到相应消息。想关闭搜索，可用 `启动局域网API.bat --no-search` 启动。

授权信息、上传文件、设置和日志保存在本机数据目录。日志会包含设备和使用元数据；启用本地思考时，推理过程也可能写入本机。分享日志前先检查并脱敏，不要提交日志、聊天记录或授权凭据。

局域网网关使用未加密 HTTP；聊天 API 默认要求 Token。用 `获取API密钥.bat` 查看 Token，并只配置到可信客户端中。只在可信的专用网络中开放，不要将 11435 端口映射到互联网。可用 `--no-require-key` 关闭 API 验证，但不建议这样做。

欢迎提交问题和改进。不要提交 API Token、Bot Token、个人角色卡、聊天记录、运行日志或模型文件。
