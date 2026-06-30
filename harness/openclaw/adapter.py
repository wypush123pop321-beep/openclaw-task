"""OpenClawAdapter:`HarnessAdapter` 的首个实现。

把现有全部 OpenClaw 调用(客户端构造、`ResilientGateway` 韧性、agent 供给、`_pin_model`
钉模型、单轮执行、history 兜底、文件证据读写、`sessions_reset` 会话重置、结构化输出、
HTTP 健康检查)收拢于此,逻辑保持不变。原生↔中立映射(`ExecutionResult → TurnResult`、
`AgentFileContent → FileContent`、`GeneratedFile → FileEvidence`)与异常翻译
(`GatewayError`/超时 → `HarnessTransportError`)都在本类边界完成,对核心层透明。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from openclaw_sdk import AgentConfig, ExecutionOptions
from openclaw_sdk.core.exceptions import GatewayError
from openclaw_sdk.core.types import AgentFileContent
from openclaw_sdk.output.structured import StructuredOutput

from ..base import HarnessAdapter
from ..capabilities import Capability
from ..errors import HarnessExecutionError, HarnessTransportError
from ..types import (
    AgentSpec,
    FileContent,
    FileEvidence,
    HealthStatus,
    ToolCallEvidence,
    TurnResult,
    WorkspaceFile,
    WorkspaceTruth,
)
from .connection import build_openclaw_client, check_http_health, gateway_http_base

logger = logging.getLogger("openclaw_automation")

T = TypeVar("T", bound=BaseModel)

# 执行重试 / history 兜底参数(原 openclaw_automation 模块常量,迁入 adapter 内部)
DEFAULT_GATEWAY_TIMEOUT_SECONDS = 3600
EXECUTION_MAX_ATTEMPTS = 5
EXECUTION_RETRY_WAIT_SECONDS = 60
EXECUTION_HISTORY_FALLBACK_LIMIT = 50
EXECUTION_HISTORY_FALLBACK_MAX_POLLS = 40
EXECUTION_HISTORY_FALLBACK_POLL_INTERVAL_SECONDS = 30.0
AGENT_CREATE_GATEWAY_WAIT_SECONDS = 90.0


# ============================================================================
# 纯函数:history 消息解析(原 execute_with_retry 内闭包,提为模块级)
# ============================================================================

def _extract_message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text") or block.get("content")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts).strip()
    text = message.get("text")
    return text.strip() if isinstance(text, str) else ""


def _is_assistant_message(message: Any) -> bool:
    return (
        isinstance(message, dict)
        and str(message.get("role", "")).lower() == "assistant"
    )


def _find_new_assistant_text(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> str:
    before_signatures = {
        (
            str(message.get("role", "")),
            _extract_message_text(message),
            str(message.get("timestamp", "")),
            str(message.get("id", "")),
        )
        for message in before
        if isinstance(message, dict)
    }
    new_messages = []
    for message in after:
        if not isinstance(message, dict):
            continue
        signature = (
            str(message.get("role", "")),
            _extract_message_text(message),
            str(message.get("timestamp", "")),
            str(message.get("id", "")),
        )
        if signature not in before_signatures:
            new_messages.append(message)
    for message in reversed(new_messages):
        if _is_assistant_message(message):
            text = _extract_message_text(message)
            if text:
                return text
    return ""


# ============================================================================
# OpenClawAdapter
# ============================================================================

class OpenClawAdapter(HarnessAdapter):
    """OpenClaw harness 的中立适配实现(声明全量能力集)。"""

    capabilities = frozenset(
        {
            Capability.MULTI_AGENT,
            Capability.FILE_EVIDENCE,
            Capability.STRUCTURED_OUTPUT,
            Capability.HEALTHZ,
            Capability.HISTORY_FALLBACK,
            Capability.SESSION_RESET,
        }
    )

    def __init__(self, connection: Optional[dict[str, Any]] = None) -> None:
        self._connection: dict[str, Any] = dict(connection or {})
        self._client: Any = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "OpenClawAdapter":
        conn = self._connection
        self._client = await build_openclaw_client(
            gateway_ws_url=conn.get("gateway_ws_url"),
            api_key=conn.get("api_key"),
            gateway_timeout=conn.get("gateway_timeout"),
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None

    @property
    def client(self) -> Any:
        """暴露底层 client(仅供同包/调试;核心层 MUST NOT 依赖)。"""
        return self._client

    # ------------------------------------------------------------------ #
    # 供给:create_agent + 按 spec.model 钉模型
    # ------------------------------------------------------------------ #

    async def ensure_agent(self, spec: AgentSpec) -> None:
        """不存在则创建 agent;创建后固定等待 gateway 重启就绪;再按 `spec.model` 钉模型。"""
        logger.info("设置 Agent: %s", spec.name)
        existing_ids = {a.agent_id for a in await self._client.list_agents()}
        if spec.name not in existing_ids:
            # SDK 的 create_agent 不从 AgentConfig 读 workspace,必须显式传 kwarg,
            # 否则 gateway 收到 "." → 解析为其自身 cwd(可能是 system32)→ EPERM。
            await self._client.create_agent(
                AgentConfig(
                    agent_id=spec.name,
                    workspace=spec.workspace,
                ),
                workspace=spec.workspace,
            )
            logger.info("创建新 Agent: %s,等待 gateway 重启就绪...", spec.name)
            await self._wait_gateway_ready()

        # 钉死模型:agents.create 不下发模型,改用 agents.update 下发(网关侧认 model,
        # model 可带 'provider/' 前缀选已在网关侧定义的 provider)。evaluator 即靠此钉死
        # 独立的 flash 级裁判模型。模型串的 provider 拼装由核心层在构造 AgentSpec 时完成。
        if spec.model:
            await self._pin_model(spec.name, spec.model)

    async def _pin_model(self, agent_name: str, model: str) -> None:
        """经 agents.update 钉死 agent 模型(本网关唯一可靠的 per-agent 通道)。

        本网关事实:`agents.update` 只认 `model`,但 model 可带 provider 前缀
        `"provider/model"` 选**已在网关侧定义**的 provider(provider 携带 baseUrl/apiKey)。
        provider 的 baseUrl/apiKey 须在网关侧 `config.models.providers.<provider>` 配置,
        harness 不下发(本网关整份回写被拒)。
        """
        try:
            resp = await self._client.gateway.agents_update(agent_name, model=model)
            logger.info(
                "已为 agent '%s' 钉死模型=%s(agents.update 返回: %s)",
                agent_name, model, resp,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "为 agent '%s' 下发模型=%s 失败(MUST NOT 静默退回默认): %s",
                agent_name, model, e,
            )

    async def _wait_gateway_ready(self, wait: float = AGENT_CREATE_GATEWAY_WAIT_SECONDS) -> None:
        """创建 agent 后 gateway 会重启,固定等待一段时间让其就绪(纯 OpenClaw 细节)。"""
        logger.info("等待 gateway 重启就绪,固定等待 %ds ...", int(wait))
        await asyncio.sleep(wait)
        logger.info("gateway 等待完成")

    # ------------------------------------------------------------------ #
    # 执行(含空响应 / history 兜底 / 重连,内部消化可恢复抖动)
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        agent: str,
        session: str,
        query: str,
        *,
        timeout: Optional[int] = None,
    ) -> TurnResult:
        agent_handle = self._client.get_agent(agent, session)
        options = ExecutionOptions(timeout_seconds=timeout) if timeout else None
        max_attempts = EXECUTION_MAX_ATTEMPTS

        async def history_fallback(
            before_history: list[dict[str, Any]],
            max_polls: int = EXECUTION_HISTORY_FALLBACK_MAX_POLLS,
            poll_interval: float = EXECUTION_HISTORY_FALLBACK_POLL_INTERVAL_SECONDS,
        ) -> Optional[str]:
            """轮询 chat.history 等待旧 run 完成。

            agent 长任务可能还在后台执行(WS 断开但 run 没停),
            不能只查一次就放弃——需要多轮轮询直到出现新的 assistant 回复。
            """
            for poll in range(1, max_polls + 1):
                await asyncio.sleep(poll_interval)
                try:
                    after_history = await self._fetch_history(agent_handle.session_key)
                except Exception as e:  # noqa: BLE001
                    logger.debug("history_fallback 第 %d/%d 次查询失败: %s", poll, max_polls, e)
                    continue
                text = _find_new_assistant_text(before_history, after_history)
                if text:
                    logger.info(
                        "execute 返回空内容,但第 %d 次 history 轮询获取到回复 (等待 %.0fs)",
                        poll, poll * poll_interval,
                    )
                    return text
                logger.debug(
                    "history_fallback 第 %d/%d 次轮询,暂无新回复",
                    poll, max_polls,
                )
            return None

        for attempt in range(1, max_attempts + 1):
            before_history = await self._fetch_history(agent_handle.session_key)
            try:
                result = await agent_handle.execute(query, options=options)
                if result is None:
                    raise RuntimeError("Agent returned None")

                if getattr(result, "content", None):
                    return self._map_result(result, evidence_incomplete=False)

                fallback_text = await history_fallback(before_history)
                if fallback_text:
                    return self._map_result(
                        result, evidence_incomplete=True
                    ).with_content(fallback_text)

                error_message = getattr(result, "error_message", None)
                if error_message and not str(error_message).startswith(
                    "Agent completed with no response"
                ):
                    raise RuntimeError(error_message)

                raise RuntimeError(
                    "Agent returned empty content and chat.history had no new assistant reply"
                )
            except (GatewayError, asyncio.TimeoutError) as e:
                logger.warning(
                    "gateway 连接异常 (第 %d/%d 次): %s，先查 history 看旧 run 是否已完成",
                    attempt, max_attempts, e,
                )
                gw = self._client.gateway
                if hasattr(gw, "ensure_connected"):
                    try:
                        await gw.ensure_connected(timeout=DEFAULT_GATEWAY_TIMEOUT_SECONDS)
                        logger.info("gateway 重连恢复")
                    except GatewayError:
                        logger.warning("gateway 重连未恢复")

                fallback_text = await history_fallback(before_history)
                if fallback_text:
                    logger.info("WS 断开但 agent 已完成,从 history 获取到回复")
                    return TurnResult(
                        success=True,
                        content=fallback_text,
                        stop_reason="complete",
                        evidence_incomplete=True,
                    )

                if attempt >= max_attempts:
                    raise HarnessTransportError(
                        f"gateway 连接异常重试耗尽 ({max_attempts} 次): {e}"
                    ) from e
                logger.warning(
                    "history 也无结果,第 %d/%d 次重试前等待 %d 秒",
                    attempt, max_attempts, EXECUTION_RETRY_WAIT_SECONDS,
                )
                await asyncio.sleep(EXECUTION_RETRY_WAIT_SECONDS)
                continue
            except RuntimeError as e:
                if attempt >= max_attempts:
                    logger.error("agent 连续返回空内容 %d 次: %s", attempt, e)
                    raise HarnessExecutionError(str(e)) from e
                logger.warning(
                    "agent 返回空内容且 history 无兜底,第 %d/%d 次重试前等待 %d 秒: %s",
                    attempt, max_attempts, EXECUTION_RETRY_WAIT_SECONDS, e,
                )
                await asyncio.sleep(EXECUTION_RETRY_WAIT_SECONDS)

        # 理论不可达(循环内必 return 或 raise);兜底防御。
        raise HarnessExecutionError("execute 未取得任何结果")

    @staticmethod
    def _map_result(result: Any, evidence_incomplete: bool = False) -> TurnResult:
        """ExecutionResult → TurnResult(含 ToolCall→ToolCallEvidence、GeneratedFile→FileEvidence)。"""
        return TurnResult(
            content=result.content or "",
            tool_calls=[
                ToolCallEvidence(
                    tool=tc.tool,
                    input=tc.input,
                    output=tc.output,
                    duration_ms=tc.duration_ms,
                )
                for tc in (result.tool_calls or [])
            ],
            files=[
                FileEvidence(name=(gf.name or gf.path or ""))
                for gf in (result.files or [])
            ],
            stop_reason=result.stop_reason,
            success=bool(getattr(result, "success", True)),
            error=getattr(result, "error_message", None),
            evidence_incomplete=evidence_incomplete,
        )

    # ------------------------------------------------------------------ #
    # history 兜底
    # ------------------------------------------------------------------ #

    async def fetch_history(
        self, agent: str, session: str, *, limit: int = EXECUTION_HISTORY_FALLBACK_LIMIT
    ) -> list[dict[str, Any]]:
        agent_handle = self._client.get_agent(agent, session)
        return await self._fetch_history(agent_handle.session_key, limit)

    async def _fetch_history(
        self, session_key: str, limit: int = EXECUTION_HISTORY_FALLBACK_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            return await self._client.gateway.chat_history(session_key, limit=limit)
        except Exception as e:  # noqa: BLE001
            logger.debug("chat.history 兜底查询失败: %s", e)
            return []

    # ------------------------------------------------------------------ #
    # 文件证据
    # ------------------------------------------------------------------ #

    async def read_workspace(self, agent: str) -> WorkspaceTruth:
        listing = await self._client.gateway.agents_files_list(agent)
        files = []
        for e in (listing.get("files") or []):
            files.append(
                WorkspaceFile(
                    name=e.get("name") or e.get("path") or "",
                    path=e.get("path"),
                    exists=not e.get("missing", False),
                    size=e.get("size"),
                )
            )
        return WorkspaceTruth(workspace_path=listing.get("workspace"), files=files)

    async def get_file(self, agent: str, name: str) -> FileContent:
        resp = await self._client.gateway.agents_files_get(agent, name)
        parsed = AgentFileContent.model_validate(resp)
        return FileContent(
            name=parsed.name,
            path=parsed.path,
            missing=parsed.missing,
            size=parsed.size,
            content=parsed.content,
        )

    async def put_file(self, agent: str, dest: str, content: str) -> None:
        await self._client.gateway.agents_files_set(agent, dest, content)

    # ------------------------------------------------------------------ #
    # 结构化输出
    # ------------------------------------------------------------------ #

    async def structured(
        self,
        agent: str,
        session: str,
        prompt: str,
        schema: Type[T],
        *,
        max_retries: int = 2,
    ) -> T:
        eval_agent = self._client.get_agent(agent, session)
        return await StructuredOutput.execute(
            eval_agent, prompt, schema, max_retries=max_retries
        )

    # ------------------------------------------------------------------ #
    # 会话重置(持久 evaluator 每轮 reset 防判词锚定)
    # ------------------------------------------------------------------ #

    async def reset_session(self, agent: str, session: str) -> None:
        eval_agent = self._client.get_agent(agent, session)
        await self._client.gateway.sessions_reset(eval_agent.session_key)

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #

    async def health(self) -> HealthStatus:
        http_base = gateway_http_base(self._client.gateway)
        if not http_base:
            return HealthStatus()
        live, ready, body = await check_http_health(http_base)
        return HealthStatus(liveness=live, readiness=ready, detail=body)
