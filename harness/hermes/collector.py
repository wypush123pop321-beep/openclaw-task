"""ACP 客户端侧:回合收集器 + Client sink(能力: harness-adapter)。

Hermes 经 ACP 的 `prompt()` 只返回 `stop_reason`,正文/工具调用/文件证据是在这一轮里
经 `session/update` 通知**流式**回来的。本模块把这些更新按 `session_id` 累加成中立
`TurnResult` 的素材;`HermesClientSink` 是我们实现的 ACP `Client`,只覆盖两个回调:

- `session_update`:把更新落到该 session 当前活跃的 `TurnCollector`;
- `request_permission`:无人值守自动放行(选一个 allow_* 选项),否则被测 agent 会挂起等人。

串行回合制下任意时刻每个 session 至多一个活跃收集器(`begin`/`end` 成对)。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from acp import schema as S
from acp.interfaces import Client

from ..types import FileEvidence, ToolCallEvidence, TurnResult

logger = logging.getLogger("openclaw_automation")

# 被视为"产生/改动文件"的工具类别 → 据其 locations 提取文件证据。
_FILE_KINDS = {"edit", "delete", "move"}


def _block_text(content: Any) -> str:
    """从 AgentMessageChunk.content(ContentBlock 或其列表)抽取纯文本。"""
    if content is None:
        return ""
    if isinstance(content, (list, tuple)):
        return "".join(_block_text(c) for c in content)
    text = getattr(content, "text", None)
    return text if isinstance(text, str) else ""


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(value)


class TurnCollector:
    """单轮的累加器:文本 + 工具调用(按 tool_call_id)+ 文件证据。"""

    def __init__(self) -> None:
        self._text_parts: list[str] = []
        self._tools: dict[str, ToolCallEvidence] = {}
        self._tool_order: list[str] = []
        self._files: dict[str, FileEvidence] = {}

    # ---- 摄入 session/update ---------------------------------------------
    def ingest(self, update: Any) -> None:
        if isinstance(update, S.AgentMessageChunk):
            self._text_parts.append(_block_text(update.content))
        elif isinstance(update, S.ToolCallStart):
            self._on_tool(update, started=True)
        elif isinstance(update, S.ToolCallProgress):
            self._on_tool(update, started=False)
        # AgentThoughtChunk / plan / 其余更新:不进中立结果(思考与计划非证据)。

    def _on_tool(self, u: Any, *, started: bool) -> None:
        tc_id = getattr(u, "tool_call_id", None) or ""
        if not tc_id:
            return
        ev = self._tools.get(tc_id)
        if ev is None:
            ev = ToolCallEvidence(tool=str(getattr(u, "title", "") or getattr(u, "kind", "") or "tool"))
            self._tools[tc_id] = ev
            self._tool_order.append(tc_id)
        # 标题/入参/出参增量补全(progress 往往带更全的 raw_output)。
        title = getattr(u, "title", None)
        if title:
            ev.tool = str(title)
        raw_input = getattr(u, "raw_input", None)
        if raw_input is not None and not ev.input:
            ev.input = _stringify(raw_input)
        raw_output = getattr(u, "raw_output", None)
        if raw_output is not None:
            ev.output = _stringify(raw_output)
        # 编辑类工具:据 locations 收集文件证据(磁盘真相由轨迹层在需要时核验)。
        if (getattr(u, "kind", None) in _FILE_KINDS):
            for loc in (getattr(u, "locations", None) or []):
                path = getattr(loc, "path", None)
                if path:
                    self._files.setdefault(str(path), FileEvidence(name=str(path)))

    # ---- 产出 -------------------------------------------------------------
    def assemble(self, stop_reason: Optional[str]) -> TurnResult:
        success = stop_reason not in ("refusal",)
        return TurnResult(
            content="".join(self._text_parts).strip(),
            tool_calls=[self._tools[i] for i in self._tool_order],
            files=list(self._files.values()),
            stop_reason=stop_reason,
            success=success,
        )


class HermesClientSink(Client):
    """我们实现的 ACP Client:把 session/update 路由到活跃收集器 + 自动放行权限。"""

    def __init__(self, auto_approve: bool = True) -> None:
        self._auto_approve = auto_approve
        self._active: dict[str, TurnCollector] = {}

    def begin(self, session_id: str) -> TurnCollector:
        collector = TurnCollector()
        self._active[session_id] = collector
        return collector

    def end(self, session_id: str) -> Optional[TurnCollector]:
        return self._active.pop(session_id, None)

    # ---- ACP Client 回调 --------------------------------------------------
    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        collector = self._active.get(session_id)
        if collector is None:
            # 非活跃回合的杂散更新(如建会话时的命令清单)忽略。
            return
        try:
            collector.ingest(update)
        except Exception:  # noqa: BLE001
            logger.debug("ingest session_update 失败", exc_info=True)

    async def request_permission(
        self, options: list, session_id: str, tool_call: Any, **kwargs: Any
    ) -> "S.RequestPermissionResponse":
        if self._auto_approve and options:
            chosen = next(
                (o for o in options if getattr(o, "kind", "") in ("allow_once", "allow_always")),
                options[0],
            )
            return S.RequestPermissionResponse(
                outcome=S.AllowedOutcome(outcome="selected", option_id=chosen.option_id)
            )
        return S.RequestPermissionResponse(outcome=S.DeniedOutcome(outcome="cancelled"))
