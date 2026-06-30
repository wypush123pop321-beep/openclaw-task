"""中立 Harness 适配层(能力: harness-adapter)。

核心三层(编排/轨迹/评估)只依赖本包导出的接口与中立类型,不直接 import 任何具体
harness SDK。具体实现(OpenClaw / Hermes)分别收拢于 `harness.openclaw` / `harness.hermes`,
经 `registry` 按配置 `harness.type` 选择(惰性导入)。
"""

from __future__ import annotations

from .base import HarnessAdapter
from .capabilities import Capability
from .errors import HarnessError, HarnessExecutionError, HarnessTransportError
from .registry import available_types, create_adapter
from .structured import StructuredParseError, parse_structured_text
from .types import (
    AgentSpec,
    FileContent,
    FileEvidence,
    HealthStatus,
    ToolCallEvidence,
    TurnResult,
    WorkspaceFile,
    WorkspaceTruth,
)

__all__ = [
    "HarnessAdapter",
    "Capability",
    "HarnessError",
    "HarnessTransportError",
    "HarnessExecutionError",
    "create_adapter",
    "available_types",
    "parse_structured_text",
    "StructuredParseError",
    "AgentSpec",
    "FileContent",
    "FileEvidence",
    "HealthStatus",
    "ToolCallEvidence",
    "TurnResult",
    "WorkspaceFile",
    "WorkspaceTruth",
]
