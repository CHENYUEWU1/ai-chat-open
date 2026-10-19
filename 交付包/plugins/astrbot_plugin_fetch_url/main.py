# -*- coding: utf-8 -*-
"""给 AstrBot 加一个「读网页」工具：fetch_url

为什么需要它：
    AnySearch 只能给标题 + 摘要，读不到正文。
    别的搜索源（tavily / firecrawl / exa）自带读全文工具，但都要 API Key。

这个插件用 httpx + bs4 自己抓，不需要任何 Key、不需要浏览器。

安装位置（AstrBot 会自动扫描 data/plugins/）：
    E:\\本地ai\\AstrBotData\\data\\plugins\\astrbot_plugin_fetch_url\\
        ├── metadata.yaml
        ├── main.py      ← 本文件
        └── fetch.py     ← 抓取逻辑（不依赖 AstrBot，可单独测）

装卸：删掉这个目录 + 重启 AstrBot 即可。
"""
from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger, star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from .fetch import DEFAULT_CHARS, HARD_CHARS, FetchError, fetch_text

DESCRIPTION = """打开一个网页，把正文读回来（纯文本）。

web_search 只给标题和摘要。当你需要**具体数字、条款、版本号、参数、步骤**，
或者摘要不足以回答问题时，用这个工具读全文。

用法：
- url 填 web_search 结果里的那个 url
- 一次只读一个页面，不要同时读多个
- 读完用**你自己的话**总结给用户，不要把整页原文贴出来
"""


def _safe_url_for_log(raw: str) -> str:
    """保留目标域名用于排错，不把凭据、路径和查询参数写进日志。"""
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "<URL 已隐藏>"
        host = parsed.hostname
        if parsed.port:
            host += f":{parsed.port}"
        return f"{parsed.scheme}://{host}/…"
    except (TypeError, ValueError):
        return "<URL 已隐藏>"


@dataclass
class FetchUrlTool(FunctionTool[AstrAgentContext]):
    name: str = "fetch_url"
    description: str = DESCRIPTION
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要打开的网页地址，http 或 https",
                },
                "max_chars": {
                    "type": "integer",
                    "description": (
                        f"最多返回多少字符，默认 {DEFAULT_CHARS}，"
                        f"上限 {HARD_CHARS}"
                    ),
                },
            },
            "required": ["url"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        url = str(kwargs.get("url") or "").strip()
        raw_max = kwargs.get("max_chars")
        try:
            max_chars = int(raw_max) if raw_max is not None else DEFAULT_CHARS
        except (TypeError, ValueError):
            max_chars = DEFAULT_CHARS

        safe_url = _safe_url_for_log(url)
        logger.info(f"[fetch_url] 抓取 {safe_url}（max_chars={max_chars}）")
        try:
            text = await fetch_text(url, max_chars)
            logger.info(f"[fetch_url] 成功，返回 {len(text)} 字符")
            return text
        except FetchError as exc:
            logger.info(f"[fetch_url] 失败（{type(exc).__name__}）：{safe_url}")
            return f"抓取失败：{exc}"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[fetch_url] 未预期错误 on {safe_url}: {type(exc).__name__}")
            return f"抓取失败：{type(exc).__name__}: {exc}"


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        # 注册到全局工具表。人格的 tools 字段是 NULL（= 全部工具）时会自动挂上。
        self.context.add_llm_tools(FetchUrlTool())
        logger.info("[fetch_url] 插件已加载，fetch_url 工具已注册")
