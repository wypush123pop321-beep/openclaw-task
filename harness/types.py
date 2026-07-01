"""中立数据类型(能力: harness-adapter)。

这些类型与任何具体 harness 无关:核心三层(编排/轨迹/评估)只消费它们,具体 adapter
负责把 harness 原生返回(如 OpenClaw 的 `ExecutionResult` / `AgentFileContent` /
`GeneratedFile`,或 Hermes 经 ACP 流式 `session/update`)映射为这些中立类型。

- `ToolCallEvidence` / `FileEvidence`:本就中立,收敛到此处作单一事实源;`trajectory.py`
  重导出以保持现有 import 不破。`ToolCallEvidence.input` 为**原生 JSON**(`Any`),
  `FileEvidence` 含产物 `path` 指针(供"指针投喂")。
- `TurnResult`:取代核心对 `ExecutionResult` 的消费;`with_content(text)` 提供干净构造法,
  取代 pydantic 专属的 `result.model_copy(update=...)`。
- `AgentSpec`:取代直接 `AgentConfig`,作 `ensure_agent` 供给入参(含 `model`/`skills`)。
- `FileContent` / `WorkspaceTruth` / `HealthStatus`:文件证据/健康检查的中立返回。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================================
# 证据类型(本就中立,收敛于此)
# ============================================================================

class ToolCallEvidence(BaseModel):
    """一次工具调用的证据(含入参与返回值)。

    `input` 为**原生 JSON**(工具入参 dict/list 原样保留),而非转义后的 JSON 字符串——
    使落盘轨迹里的 `tool_calls[].input` 与外层同构、可直接解析。非结构化入参(纯文本
    命令等)仍以字符串保留。
    """
    tool: str
    input: Any = ""
    output: Optional[str] = None
    duration_ms: Optional[int] = None


class FileEvidence(BaseModel):
    """一个被声称生成的文件,经磁盘真相校验后的证据。

    exists=True/False 表示文件证据能力在被测工作区是否真的取到该文件;
    checked=False 表示本轮未做磁盘核验(如 evaluator 未启用),仅记录声称的文件名。
    """
    name: str
    checked: bool = False
    exists: bool = False
    size: Optional[int] = None
    content: Optional[str] = None
    path: Optional[str] = None  # 产物在被测工作区的路径,供"指针投喂"(filename + workspace_path)
    error: Optional[str] = None  # 取证失败原因(如路径不可达)→ 降级,不当负面证据
    discovered: bool = False  # True=经工作区清点主动发现(非 agent 自报)


# ============================================================================
# 单轮执行结果 / agent 供给描述
# ============================================================================

class TurnResult(BaseModel):
    """单轮执行的中立结果。

    取代核心层对 harness 原生 `ExecutionResult` 的直接消费。`files` 记录的是 agent
    **声称**生成的文件(磁盘真相由 `trajectory.capture_file_evidence` 在需要时补齐)。
    `evidence_incomplete=True` 表示该结果经 history 兜底恢复(只剩文本、无工具/文件证据)。
    """
    content: str = ""
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    files: list[FileEvidence] = Field(default_factory=list)
    stop_reason: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    evidence_incomplete: bool = False

    def with_content(self, text: str) -> "TurnResult":
        """返回一个内容替换为 `text` 的成功副本(取代 model_copy(update=...))。"""
        return self.model_copy(
            update={
                "content": text,
                "success": True,
                "stop_reason": self.stop_reason or "complete",
                "error": None,
            }
        )


class AgentSpec(BaseModel):
    """agent 供给描述,作 `ensure_agent` 入参(取代直接构造 OC-harness 的 `AgentConfig` 参数)。

    `model` 为可带 provider 前缀的模型串 `"provider/model"`;OpenClaw adapter 经
    `agents.update` 钉死,Hermes adapter 经 `set_session_model` 下发。
    """
    name: str
    workspace: str
    config_files: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    model: Optional[str] = None


# ============================================================================
# 文件证据 / 健康检查的中立返回
# ============================================================================

class FileContent(BaseModel):
    """单个文件的中立内容(adapter 由 harness 原生文件类型映射而来)。"""
    name: str
    path: Optional[str] = None
    missing: bool = False
    size: Optional[int] = None
    content: Optional[str] = None


class WorkspaceFile(BaseModel):
    """工作区清单中的一个文件条目。"""
    name: str
    path: Optional[str] = None
    exists: bool = True
    size: Optional[int] = None


class WorkspaceTruth(BaseModel):
    """被测 agent 工作区的真相:工作区路径 + 文件清单。"""
    workspace_path: Optional[str] = None
    files: list[WorkspaceFile] = Field(default_factory=list)


class HealthStatus(BaseModel):
    """harness 健康检查的中立结果。"""
    liveness: bool = False
    readiness: bool = False
    detail: Optional[Any] = None
