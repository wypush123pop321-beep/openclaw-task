"""中立 Harness 异常层(能力: harness-adapter)。

规则(见 design.md):
- adapter **内部**消化可恢复的传输抖动(断线重连/心跳/退避/空响应兜底)。
- 重试耗尽、确实不可恢复时 → 抛中立 `HarnessError`(传输类用 `HarnessTransportError`,
  执行类用 `HarnessExecutionError`)。
- 核心层只捕获 `HarnessError`,MUST NOT 捕获 harness 专属异常(如 `GatewayError`),
  也 MUST NOT 直接调用 harness 专属重连方法(如 `ensure_connected`)。
"""

from __future__ import annotations


class HarnessError(Exception):
    """所有 harness 故障的中立基类。"""


class HarnessTransportError(HarnessError):
    """不可恢复的传输故障(重连/超时重试耗尽)。"""


class HarnessExecutionError(HarnessError):
    """执行层不可恢复故障(如连续空响应且 history 无兜底)。"""
