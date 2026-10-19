# cherry-legacy · 已归档的 Cherry Studio 专用脚本

> **Cherry Studio 已于 2026-09-22 从本机卸载**（前端换成 AstrBot Desktop）。
> 这些脚本**现在跑不了** —— 它们读写的是 Cherry Studio 的 SQLite
> （`C:\LocalAI-Assistant\CherryStudio\data\Data\cherrystudio.sqlite`），那个目录已经删了。
>
> **留在这里纯粹是为了记录踩过的坑。** 如果哪天想装回 Cherry Studio，
> 这些脚本改一下 `DB` 常量还能用。

## 归档了什么

| 脚本 | 原来干什么 | 对应的坑 |
|---|---|---|
| `apply_persona.py` | 把 `personas\*.txt` 写进 Cherry 助手的 `prompt` 字段 | 坑 13（模型/人格要分开管）|
| `switch_persona.ps1` | 上面那个的交互菜单版 | 坑 5（.ps1 要 UTF-8+BOM）|
| `切换人格.bat` | 双击调用 `switch_persona.ps1` | 坑 5（.bat 要 GBK+CRLF）|
| `fix_cherry_assistant.py` | 绑模型 + 设上下文。**曾经会把旧人格写回去覆盖新人格** | 坑 13 |
| `switch_to_9b.py` | 建 9B 模型记录 + 切助手。**同一个覆盖人格的毛病** | 坑 13 |
| `fix_agent_model.py` | 排查 `agent` 表里的模型绑定 | **坑 13（最隐蔽的那个）** |
| `enable_websearch.py` | 打开 `enableWebSearch` | 坑 6 |
| `disable_cloud.py` | 关云端提供者、隐藏云端模型 | 坑 7 |

## 现在用什么代替

| 旧（Cherry） | 新（AstrBot） |
|---|---|
| `apply_persona.py 病娇-助手-露骨` | `python scripts\astrbot_setup.py` |
| `switch_persona.ps1` / `切换人格.bat` | 改 `personas\` 里的文件 + 重跑 `astrbot_setup.py` |
| `fix_agent_model.py` | 不需要了（只有一个前端，一个模型）|
| `enable_websearch.py` / `disable_cloud.py` | `astrbot_setup.py` 一次搞定 |

详见 `05-AstrBot界面.md`。

## 教训仍然适用

**模型配置和人格配置必须由两个独立的脚本管。**
`switch_to_9b.py` 和 `fix_cherry_assistant.py` 都在"改模型"的同时
把一份**硬编码的旧人格**写回数据库 —— 结果 `apply_persona.py`
刚调好的人格被静默还原，而且不报错。

`astrbot_setup.py` 也写人格，但它读的是 `personas\病娇-助手-露骨.txt`
（单一数据源），不会再出现两份人格互相盖的情况。
