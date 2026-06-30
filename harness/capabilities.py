"""Harness 能力枚举(能力: harness-adapter)。

把今天散落的"运行时 try/except 降级"提升为"声明式查询":核心在调用某可选能力前
`if Capability.X in adapter.capabilities`,缺失即落入既有降级分支。OpenClaw adapter
声明全集;未来弱 harness 声明子集即自动降级。
"""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """harness adapter 声明的可选能力位。"""

    MULTI_AGENT = "multi_agent"          # 多 agent 供给(ensure_agent)
    FILE_EVIDENCE = "file_evidence"      # 文件证据读写(read_workspace/get_file/put_file)
    STRUCTURED_OUTPUT = "structured_output"  # 原生强制 schema 结构化输出
    HEALTHZ = "healthz"                  # HTTP 健康检查
    HISTORY_FALLBACK = "history_fallback"  # 空响应时经 history 兜底恢复
    SESSION_RESET = "session_reset"      # 会话重置(持久 evaluator 每轮 reset 防判词锚定)
