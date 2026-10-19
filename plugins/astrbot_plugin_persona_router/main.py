# -*- coding: utf-8 -*-
"""按平台固定人格（persona router）。

为什么需要（2026-09-24 用户要求）：
    "微信聊天就固定外向小九，然后其他平台还是和之前一样想改什么就改什么"

    AstrBot **没有**"按平台指定人格"的配置项 —— 人格只有全局一份
    （`agent_runner.config.persona`），改它会把所有平台一起改掉。
    但它的**人格优先级链**里有一条正好能用（`core/persona_mgr.py`）：

        force_applied_persona_id = session_service_config.get("persona_id")   ← 最高
        if not persona_id:
            persona_id = conversation_persona_id                              ← 次之
            if persona_id is None:
                persona_id = cfg["agent_runner"]["config"]["persona"]...       ← 兜底（全局）

    所以：**把某个会话的 `session_service_config.persona_id` 写死**，
    就等于给那个会话固定了人格，而**全局那份一个字不用改** → 其他平台照旧。

    `session_service_config` 由 AstrBot 自己的会话存储管
    （`sp.session_get/session_put`，落在 `preferences` 表 scope='umo'），
    所以它是**持久化**的：重启后仍然生效。

⚠️ 时序要求：必须在 agent 跑之前写。所以用**最高优先级**的事件处理器
   （本项目的落点：`session_service_config` 是 agent 运行时**现读**的，
   不是启动时缓存，所以处理器里写、同一条消息就生效）。

⚠️ 这条只解决"用哪个人格"；**记忆隔离不用做** —— AstrBot 本来就把
   `conversations.user_id = umo`（`platform_name:message_type:session_id`），
   每个平台各自一条会话，历史不互通。长期记忆（provider_ltm_settings）也全关着。

装卸：删掉这个目录 + 重启 AstrBot。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from astrbot.api import logger, sp, star
from astrbot.api.event import AstrMessageEvent, filter

# ---------------------------------------------------------------- 配置
#
# 放在 AstrBotData\data\persona_router.json（插件目录外，方便改且不会被升级覆盖）。
# 不配也行 —— 用下面的内置默认值。
#
# 格式：{"平台 id 前缀": "人格名"}
#   平台 id 就是 umo 的第一段，例如
#     weixin_personal_example:FriendMessage:xxx@im.wechat  →  平台 id = weixin_personal_example
#   前缀匹配（startswith），所以写 "weixin" 能一次覆盖所有微信系适配器
#   （不同适配器生成的平台 id 可能不同）。
DEFAULT_MAP = {
    "weixin": "示例角色D",      # 微信 → 固定外向小九（用户要求）
}
# 没列在这里的平台一律**不碰**：Telegram / WebUI 照旧，想换人格随时换。

CONFIG_NAME = "persona_router.json"
ROOT_MARKER = "启动AstrBot.bat"          # 用来找项目根
PRIORITY = 10 ** 6                        # 越大越先跑

# 只在"该会话当前值不是目标值"时才写库，省掉每条消息一次 IO。
# ⚠️ 2026-09-29：从"永久缓存"改成"带失效时间的缓存" ——
#    原来一旦设过就再也不看，WebUI 把人格改掉后插件永远不写回，
#    固定人格静默失效直到重启。现在超过 CACHE_TTL 秒就重新确认一次。
_LAST: dict[str, tuple[str, float]] = {}
CACHE_TTL = 30.0                          # 秒


def find_data_dir() -> Path | None:
    """找 AstrBotData\\data —— 从插件文件位置往上找项目根，再往下进 AstrBotData。"""
    here = Path(__file__).resolve()
    for up in here.parents:
        if (up / ROOT_MARKER).exists():
            d = up / "AstrBotData" / "data"
            return d if d.exists() else None
        if (up / "cmd_config.json").exists() and (up / "data_v4.db").exists():
            return up
    return None


def load_map(data_dir: Path | None) -> dict[str, str]:
    """读 persona_router.json；没有就用默认；坏 JSON 也退回默认（不让插件起不来）。"""
    if data_dir is None:
        return dict(DEFAULT_MAP)
    p = data_dir / CONFIG_NAME
    if not p.exists():
        try:
            p.write_text(json.dumps(DEFAULT_MAP, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            logger.info(f"[persona_router] 已生成默认配置 {p}")
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"[persona_router] 写默认配置失败：{e!r}")
        return dict(DEFAULT_MAP)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out = {str(k): str(v) for k, v in raw.items() if str(k).strip()}
        logger.info(f"[persona_router] 配置：{out}")
        return out or dict(DEFAULT_MAP)
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"[persona_router] {p.name} 读不了（{e!r}），用默认值")
        return dict(DEFAULT_MAP)


def known_personas(data_dir: Path | None) -> set[str]:
    """从库里读一遍现有的人格名，用来在启动时校验配置有没有写错。"""
    if data_dir is None:
        return set()
    db = data_dir / "data_v4.db"
    if not db.exists():
        return set()
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        names = {r[0] for r in con.execute("SELECT persona_id FROM personas")}
        con.close()
        return names
    except Exception:                                             # noqa: BLE001
        return set()


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        self.data_dir = find_data_dir()
        self.persona_map = load_map(self.data_dir)
        # 启动时校验一次：名字写错比"静默不生效"好发现得多
        known = known_personas(self.data_dir)
        if known:
            for prefix, name in self.persona_map.items():
                if name not in known:
                    logger.warning(
                        f"[persona_router] ⚠️ 配置里 {prefix} → {name!r}，"
                        f"但库里没有这个人格。现有：{sorted(known)}"
                    )
        logger.info(
            "[persona_router] 已加载：%s（只影响这些平台，其他平台不动）"
            % ", ".join(f"{k}*→{v}" for k, v in self.persona_map.items())
        )

    def _target_for(self, platform_id: str) -> str | None:
        for prefix, name in self.persona_map.items():
            if platform_id.startswith(prefix):
                return name
        return None

    # ⚠️ 装饰器在 `astrbot.api.event.filter` 里，**不在 `star` 上** ——
    #    实测：`hasattr(star, "event_message_type")` = False，
    #    而 `astrbot.api.event.filter.event_message_type` = True。
    #    （写之前核过，见那次 API 核对脚本。）
    @filter.event_message_type(filter.EventMessageType.ALL, priority=PRIORITY)
    async def force_persona(self, event: AstrMessageEvent) -> None:
        umo = event.unified_msg_origin
        platform_id = umo.split(":", 1)[0]
        target = self._target_for(platform_id)
        if not target:
            return                                     # 其他平台：一个字都不碰

        # ⚠️ 2026-09-29：缓存加**失效时间**。
        #    原来 `_LAST` 是永久缓存：一旦设过就不再看 —— 于是 WebUI 会话设置
        #    （或 AstrBot 自己）把这个 umo 的 persona_id 改掉/清掉之后，
        #    插件因为缓存命中**永远不再写回**，"固定人格"就**静默失效**，
        #    直到重启 AstrBot。症状和原因完全脱节。
        #    现在：缓存只在 CACHE_TTL 秒内可信，过期就重新确认一次
        #    （正常情况下只是多读一次 session，代价很低）。
        hit = _LAST.get(umo)
        if hit and hit[0] == target and (time.monotonic() - hit[1]) < CACHE_TTL:
            return

        try:
            cfg = await sp.session_get(umo, "session_service_config", {}) or {}
            if cfg.get("persona_id") == target:
                _LAST[umo] = (target, time.monotonic())
                return
            cfg["persona_id"] = target                 # ← 只动这一个键，其他字段保留
            await sp.session_put(umo, "session_service_config", cfg)
            _LAST[umo] = (target, time.monotonic())
            logger.info(f"[persona_router] {umo} → 固定人格 {target!r}")
        except Exception as e:                         # noqa: BLE001
            # 不往外抛：路由失败不该让这条消息整个挂掉（退化成全局人格）
            logger.warning(f"[persona_router] 设置 {umo} 的人格失败：{e!r}")
