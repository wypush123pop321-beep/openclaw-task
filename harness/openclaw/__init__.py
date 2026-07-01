"""OpenClaw harness adapter 子包(`HarnessAdapter` 的首个实现)。

`openclaw_sdk` 的依赖收拢在本子包内部:连接/韧性(`connection`)与适配实现(`adapter`)。
经 `harness.registry` 按 `harness.type="openclaw"`(默认)惰性选用。
"""

from __future__ import annotations

from .adapter import OpenClawAdapter

__all__ = ["OpenClawAdapter"]
