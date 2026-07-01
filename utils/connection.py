"""OpenClaw 连接管理工具(向后兼容 shim)。

真实实现已迁入 `harness/openclaw/connection.py`(收拢 `openclaw_sdk` 依赖到 OpenClaw
adapter 子包内)。本模块仅为不破坏既有 import(测试/归档脚本)而重导出,核心三层
(`openclaw_automation`/`trajectory`/`evaluator`)不再直接依赖本模块。
"""

from __future__ import annotations

from harness.openclaw.connection import (  # noqa: F401
    DEFAULT_GATEWAY_TIMEOUT_SECONDS,
    GATEWAY_CONNECT_GRACE_SECONDS,
    ResilientGateway,
    build_openclaw_client,
    check_http_health,
    gateway_http_base,
    rebuild_gateway,
)

__all__ = [
    "DEFAULT_GATEWAY_TIMEOUT_SECONDS",
    "GATEWAY_CONNECT_GRACE_SECONDS",
    "ResilientGateway",
    "build_openclaw_client",
    "check_http_health",
    "gateway_http_base",
    "rebuild_gateway",
]
