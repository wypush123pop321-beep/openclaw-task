"""Hermes harness adapter 子包(`HarnessAdapter` 的第二个实现)。

`agent-client-protocol`(ACP SDK,安装版 0.10.1)的依赖收拢在本子包内部:连接/收集器
(`collector`)、配置翻译(`config`)与适配实现(`adapter`)。经 `harness.registry` 按
`harness.type="hermes"` 惰性选用。
"""

from __future__ import annotations

from .adapter import HermesAdapter

__all__ = ["HermesAdapter"]
