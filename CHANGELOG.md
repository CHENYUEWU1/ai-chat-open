# 仓库状态快照（CHANGELOG）

> 这份记录**仓库本身**的状态：**当前长什么样、有哪些派生物、为什么有些东西故意不入库**，
> 以及**关键节点做过什么**（不是逐条 commit 日志 —— 那看 `git log`）。
> **这套系统怎么用、怎么换电脑重建，看 [README.md](README.md)；
> 现在这一刻的运行状态与已修问题清单，看 [交付包/给AI看的/08-当前阶段.md](交付包/给AI看的/08-当前阶段.md)。**

---

## 一、当前状态（2026-10-08 核对）

| 项 | 值 |
|---|---|
| 私有仓库 | https://github.com/CHENYUEWU1/ai-chat （**私有**）|
| 最新提交 | 见 `git log -1`（本文件随每次同步一起更新；累计约 **199** 个提交）|
| 跟踪文件 | **241 个 / 约 5.7 MB**（只含脚本、文档、人格、配置）|
| 故意不入库 | 约 **13 GB**（模型、运行时、运行数据 —— 见第三节）|
| 人格 | **4 份**：`示例角色A`（当前默认）/ `示例角色B` / `示例角色C` / `外向-助手`（磁盘与 AstrBot 数据库已双向核对）|
| 模型 | **两个并存可切**：`local-assistant-35b`（35B-A3B MoE，IQ2_M，默认）+ `local-assistant-9b`（Qwen3.5-9B Q4_K_M）|
| 版本 | Ollama **v0.34.2** ｜ AstrBot Desktop **4.28.1** ｜ 自写网关 `ollama_gateway.py` |
| 三条使用入口 | ① AstrBot（本机 `127.0.0.1:6185`）② **局域网网关**（`http://<IP>:11435`，**要 6 位入网码**，手机 App / 浏览器 / 任何 OpenAI 兼容客户端）③ Telegram |
| 移动端 | **手机客户端 App**（源码/工具链/产物/文档在独立目录 `E:\手机客户端App\`，另备份到私有仓库 `CHENYUEWU1/手机客户端-apk` —— 详见其 `操作文档.md` / `构建说明.md`）|
| 自测 | `python check_all.py`（**15 项只读校验**）｜ `python test_access.py`（网关授权，默认 37 项）|

**一句话**：这是「助手」本地离线 AI 助手的**部署档案** —— 代码、人格、文档三样齐全，
换电脑时照文档重建即可；模型与运行时因为体积和密钥原因不进仓库。

---

## 二、仓库里有什么

| 位置 | 内容 |
|---|---|
| 根目录 | `启动AstrBot.bat` / `停止模型.bat` / `切换人格.bat` / `启动对话.bat` / `启动局域网API.bat` / `获取API密钥.bat` / `修复Ollama.bat`，以及全部 Python 脚本 |
| `scripts\` | **根目录脚本的镜像** —— 让文档里 `python scripts\xxx.py` 这种写法也能跑（见坑 23）|
| `交付包\` | **完整文档（00~08）、脚本副本、人格副本、Modelfile、派生物** |
| `personas\` | 4 份人格（生成物）+ `_源文件\`（真身）+ `.active`（记录当前启用哪份）|
| `plugins\` | 自写插件 `astrbot_plugin_fetch_url`（给模型加"读网页正文"工具）|
| `model-config`（在交付包内）| Modelfile、原始 chat 模板备份、角色卡 |

### 派生文档（都是脚本生成的，不要手改）

| 文件 | 生成方式 | 用途 |
|---|---|---|
| `交付包\给AI看的\单文件版-全内容.md` | `python build_single_file.py` | 全部内容合并，含人格正文 |
| `交付包\给AI看的\单文件版-工程版.md` | `python build_single_file.py --eng` | 去掉人格正文，给接手的 AI 看 |
| `助手-AI助手-交付包.zip` | `python build_package_zip.py` | 交付包快照（GBK 条目名 + 正斜杠，与目录逐文件一致）|

---

## 三、故意不入库的（约 13 GB）

GitHub 单文件上限 100 MB，而且这些是**运行时/私有数据**，不该进版本库：

| 未包含 | 体积 | 为什么不传 |
|---|---|---|
| `models\` + `downloads\` | 各 5.2 GB | 模型库与建模源 GGUF（同一份文件的副本）|
| `ollama\` | 1.8 GB | Ollama 便携运行时 |
| `AstrBot\` | 486 MB（3.3 万个小文件）| AstrBot 便携运行时 |
| `AstrBotData\` | 约 5 MB | **运行数据：数据库、自动备份、含 WebUI 口令哈希与 Telegram bot token 的配置**，且每次运行都变 |
| `data\` | 4 个文件 | AstrBot 在项目根误建的游离副本；脚本实际读写的是 `AstrBotData\data\` |
| `__pycache__\` | — | 字节码 |

排除规则在 `.gitignore` 里，已实测生效（`git check-ignore -v` 可验）。

---

## 四、变更时间线

| # | 提交 | 时间 | 做了什么 |
|---|---|---|---|
| 1 | `d8923d0` | 09-22 01:43 | **建仓**：脚本、人格、Modelfile、交付文档首次上传（当时 7 条零散提交压成 1 条干净快照）|
| 2 | `fedb988` | 12:35 | **框架迁移到 AstrBot**：新增 AstrBot 脚本与 `05` 文档、新人格「外向-助手」；Cherry Studio 脚本归档到 `cherry-legacy\`；`AstrBot\`、`AstrBotData\` 加入排除 |
| 3 | `2f47385` | 12:39 | README 按 AstrBot 重写（架构、使用、换机、排障），Cherry 部分压缩为「旧框架（已归档）」|
| 4 | `4937e79` | 13:33 | **Telegram 接入 + `fetch_url` 插件**；游离 `data\` 加入排除 |
| 5 | `c0064af` | 18:20 | **README 瘦身 460 → 152 行**，细节移交交付包文档；补上 Telegram 与插件用法 |
| 6 | `65d6ff4` | 18:50 | **人格精简为 2 套**（删除 `病娇-助手`、`-狂化`、`默认-助手`）；新增 `00-新窗口从这里开始.md` |
| 7 | `f646ed2` | 18:53 | **修复**：补回从项目根消失的 `install_fetch_plugin.py`；新增 `console_utf8.py` 修掉 13 个脚本在 GBK 控制台下打印 ✅ 即崩溃 |
| 8 | `f3aa9c8` | 18:53 | 重打交付包 zip |
| 9 | `6c86e86` | 18:54 | 新增 `build_package_zip.py`（zip 一致性校验/重建）；**人格口径全库统一为 2 套**（`使用说明`、`03`、`04`、`05`、`00`、`交付包/README`）|
| 10 | `11b86df` | 18:54 | 补齐坑 23：`install_fetch_plugin.py` 曾从项目根缺失，文档里的命令全部跑不了 |
| 11 | `f319b96` | 18:55 | 修正 `install_fetch_plugin.py` 的调用路径（脚本已补回根目录，文档不再写 `scripts\` 前缀）|
| 12 | `fbd610a` | 18:55 | 文档同步：坑 18 补记 + 坑 23；zip 改为脚本重建 |
| 13 | `0dd1246` | 18:58 | **`scripts\` 镜像落地**（`scripts_sync.py`），清掉 Cherry 时期的死命令 |
| 14 | 本次 | — | 新增本文件；重跑两个单文件生成器与 zip；补入未跟踪的 `人格写作模板.md`、`给AI的完整说明书.md`、`单文件版-工程版.md` |
| 15 | `81d8aef` | 09-23 | **删掉重复的 `病娇-助手-全部`**；`_核心.txt` 瘦身 10%；新增 `test_persona_tokens.py`；修正 `1.17 token/字符` 这个错系数（真值 1.32，坑 29）；补坑 30 / 31；`scripts_sync.py` 加上 `交付包\model-config\` 校验 |
| 16 | `9e31213` | 09-23 | **新增 `06-人格迭代交接.md`**（给新窗口：怎么改人格、怎么写改动方案，含开场白模板）；接入工程版第 5.5 章；`给AI的完整说明书` 的"人格别碰"改成"结构和规则全包、正文你自己填" |
| 17 | `3c014fe` | 09-23 | **主页修掉自相矛盾**：README 原写"改人格永远不需要 AI"，与新文档口径冲突 → 改成"正文自己写 / 结构规则类可交 AI（传 06）" |
| 18 | `598d366` | 09-23 | **人格瘦身批次**（另一个 AI 窗口做的，原样提交）：`_核心.txt` 5113 → 4785 字符。删掉 ⑥ 整块正面例子（它的开头被 **13/13 条**回复照抄成开场）、两处实测注、与别处重复的条目；「要细节不要概括」的示范句改成**从中间写起**（规则一字未动）。顺带纠正 06 里"进阶内容占核心 25%" → **39%** |
| 19 | `25395a6` | 09-23 | **补救 + 提速**：`【输出格式】` 被**整节删过头**（里面只有 1/3 是死重量）→ 把「不复述问题 / 不输出 markdown 符号」并进 `【语言与长度】`；新增 **`check_all.py`**（8 项只读校验一条命令跑完，不碰 GPU）；06 / 03 / 02 / 先读我 全部补上"**别按整节判断死重量**"的判据和三条省时要求 |
| 20 | `10e27c8` | 09-23 | **实测复核**：① 补回的两条规则**有效**（3 样本：markdown 0 次、复述 0 次）；② 但发现**开场还是在照抄示范句** —— 6 个样本 **6/6** 以「手指/指尖」起手（开场禁词表本身 0/6 命中，没坏）。新增 **`test_persona_opening.py`** 把"开场重复率"变成可复跑的指标；06 新增 **§12 怎么复核另一个窗口改了什么**、§2 记下这条**已知待办 + 三级改法 + 验收标准** |
| 21 | `000f09b` | 09-23 | **治"卡在测试环节"**（用户原话："新窗口一直卡在测试环节，我叫它减少测试了"）：根因是 `test_persona.py` 的 `timeout=300`（一个请求等 5 分钟）+ Ollama 服务会整个卡死。新增 **`ollama_guard.py`**（探活 6 秒 + 硬超时 + 失败直接给复位命令）、**`fix_ollama.py`** / **`修复Ollama.bat`**（一条命令复位，AstrBot 不用关）；三个 persona 测试全部接上护栏；去掉请求里的 `num_ctx`（避免整模型重载）。文档：`02` 新增**坑 32**、`06` 新增 **§10.5 GPU 测试怎么跑才不会卡住**、开场白加"测试分两类" |
| 22 | 本次 | — | **修好 Telegram "完全没反应"**（用户找新窗口修过没修好）。根因：`patch_astrbot_telegram.py` 的 **v1 只加了代理、没加 PTB 超时** —— PTB 默认 5 秒，走代理握手要 2.7–7 秒。`start_polling()` 非阻塞、挂掉后 AstrBot 照样打 "Adapter is running"，**但一个 getUpdates 都没发出去**。补丁升到 **v2**（显式 `HTTPXRequest(connect=20/read=30/write=30/pool=20)`，`request` 与 `get_updates_request` 分开建）。`02` 新增**坑 33**：完整外部证据链（`pending_update_count` / getUpdates 无 409 / TCP 连接表采样）+ 教训"**进程说它 running 不是证据**"；`05` 补上"重启后必须这样验" |

---

## 五、几条容易改错的口径

1. **人格是 4 份**（2026-09-23 起）：3 份玩法人格（`病娇-助手-露骨` / `-异物` / `-玩`）
   + 冻结的 `外向-助手`。`病娇-助手`、`病娇-助手-狂化`、`病娇-助手-全部`、`默认-助手`
   都已删除，全库文档不得再把它们当可用人格推荐。
2. **人格是"生成物"，不能手改**：源文件在 `personas\_源文件\`，
   改完跑 `python build_personas.py`（见 `04-AI迭代交接.md` 第四节）。
   每份 = 完整共有核心 + 一段玩法片段，**所以拆人格不省窗口**（坑 30）。
3. **版本必须对齐**：Ollama `v0.34.2`、AstrBot `4.28.1`。
   `patch_astrbot_time.py` 和 `patch_astrbot_telegram.py` 直接改 AstrBot 源码，升级会被覆盖，**要重跑**。
4. **脚本路径有两种写法，两种都成立**：根目录直接跑，或 `python scripts\xxx.py`。
   保持成立靠 `scripts_sync.py`，改了根目录脚本要跑一次。
   Modelfile 也在它的校验范围内（`交付包\model-config\`）。
5. **派生文件不要手改**，改完源头重跑：

```powershell
python build_personas.py             # 由 personas\_源文件\ 合成人格
python build_single_file.py          # 全内容版（含人格正文）
python build_single_file.py --eng    # 工程版（不含人格正文）
python build_package_zip.py          # 重建 zip
python build_package_zip.py --check  # 只校验 zip 与目录是否一致
python scripts_sync.py               # 同步并核对三处镜像（脚本×2 + Modelfile）
python test_persona_tokens.py        # 量人格真实 token 数（别用字符数乘系数）
```

> ⚠️ 这些脚本要在 **UTF-8 输出**下跑（脚本已内置 `console_utf8.py`）：
> 若手工在 cmd 里跑别的 Python 脚本并看到 `UnicodeEncodeError: 'gbk' codec`，
> 先 `set PYTHONIOENCODING=utf-8`。

---

## 六、安全

- **仓库是私有的**，只有你能看到。
- `AstrBotData\data\cmd_config.json` 里有**真实 Telegram bot token**（46 字符）和 WebUI 口令哈希 ——
  该文件**被排除在仓库外**，并且用 `git grep` 扫过**全部提交历史**，确认 token 从未进入任何一次提交。
- 写这份总结时对已跟踪文件重扫过：无 Telegram token、无 `sk-` 类密钥。
- **如果哪天要改成公开**，先处理这几处：
  1. `旧聊天记录-备份.jsonl`（个人聊天记录）
  2. `personas\病娇-助手-露骨.txt`（18+ 内容）
  3. 文档里的 `@che187n_bot` 与 Telegram 用户 ID、以及人格提示词里的真实姓名

---

## 七、怎么继续同步

```powershell
cd C:\LocalAI-Assistant
python build_single_file.py ; python build_single_file.py --eng   # 改了文档
python build_package_zip.py                                        # 重建交付包快照
python scripts_sync.py                                             # 改了根目录脚本
git add -A
git commit -m "说明这次改了什么"
git push
```

> ⚠️ **同一时间只让一个窗口做 Git 操作。**
> 2026-09-22 18:53 就出现过两个窗口同时改同一批文件：一个窗口的改动被另一个窗口的提交顺带带走，
> 还出现过"文档改了但 zip 没重打"的不一致。多窗口并行没问题，**但 git 提交/推送要串行**。
