"""中立 Harness 适配接口(能力: harness-adapter)。

`HarnessAdapter` 是框架与任意 harness 之间的唯一边界。编排/轨迹/评估三层只依赖此接口
与中立数据类型,MUST NOT 直接 import 任何具体 harness SDK。接口只收纳核心动词
(`ensure_agent`/`execute`)为必需面,其余以 capability 位 + 方法表达为可选能力。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from .capabilities import Capability
from .types import (
    AgentSpec,
    FileContent,
    HealthStatus,
    TurnResult,
    WorkspaceTruth,
)

T = TypeVar("T", bound=BaseModel)


class HarnessAdapter(ABC):
    """框架与某个具体 harness 之间的中立适配契约。"""

    #: 该 adapter 声明支持的能力集;核心层据此决定是否调用可选能力。基类默认空集。
    capabilities: frozenset[Capability] = frozenset()

    # ------------------------------------------------------------------ #
    # 生命周期(取代 build_*_client)
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def __aenter__(self) -> "HarnessAdapter":
        ...

    @abstractmethod
    async def __aexit__(self, *exc: Any) -> None:
        ...

    # ------------------------------------------------------------------ #
    # 必需面:供给 + 执行
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def ensure_agent(self, spec: AgentSpec) -> None:
        """确保 agent 存在;不存在则按 spec 创建并按 `spec.model` 钉死模型(实现内部细节如重启等待，由派生类负责)。"""
        ...

    @abstractmethod
    async def execute(
        self,
        agent: str,
        session: str,
        query: str,
        *,
        timeout: Optional[int] = None,
    ) -> TurnResult:
        """执行单轮;派生类内部消化可恢复抖动与空响应兜底,不可恢复时抛 HarnessError。"""
        ...

    # ------------------------------------------------------------------ #
    # 以下为 capability-gated 可选能力
    # ------------------------------------------------------------------ #

    async def fetch_history(
        self, agent: str, session: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """拉取会话历史(Capability.HISTORY_FALLBACK)。"""
        raise NotImplementedError

    async def read_workspace(self, agent: str) -> WorkspaceTruth:
        """读取被测 agent 工作区真相:路径 + 文件清单(Capability.FILE_EVIDENCE)。"""
        raise NotImplementedError

    async def get_file(self, agent: str, name: str) -> FileContent:
        """按 agent 寻址读取单个文件(Capability.FILE_EVIDENCE)。"""
        raise NotImplementedError

    async def put_file(self, agent: str, dest: str, content: str) -> None:
        """把内容写入 agent 工作区(Capability.FILE_EVIDENCE)。"""
        raise NotImplementedError

    async def structured(
        self,
        agent: str,
        session: str,
        prompt: str,
        schema: Type[T],
        *,
        max_retries: int = 2,
    ) -> T:
        """原生强制 schema 结构化输出(Capability.STRUCTURED_OUTPUT)。"""
        raise NotImplementedError

    async def reset_session(self, agent: str, session: str) -> None:
        """重置某 agent 会话,清空其历史回放(Capability.SESSION_RESET)。

        持久 evaluator 每轮评估前调用,防止自身上一轮判词被回放造成自我锚定。
        缺该能力时核心层跳过(退回不重置的等价语义)。
        """
        raise NotImplementedError

    async def health(self) -> HealthStatus:
        """HTTP 健康检查(Capability.HEALTHZ)。"""
        raise NotImplementedError
