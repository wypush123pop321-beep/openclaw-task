"""Adapter 注册表与工厂(能力: harness-adapter)。

按配置项 `harness.type` 选择并构造对应的 `HarnessAdapter` 实现;未知 type 显式报错,
MUST NOT 静默回退到错误的 adapter。具体 adapter 类**惰性导入**,避免 `import
harness.registry` 即拉起某个 harness SDK。
"""

from __future__ import annotations

from typing import Any, Callable

from .base import HarnessAdapter

# type -> 惰性构造函数(connection dict -> HarnessAdapter)
_REGISTRY: dict[str, Callable[[dict[str, Any]], HarnessAdapter]] = {}


def _make_openclaw(connection: dict[str, Any]) -> HarnessAdapter:
    from .openclaw import OpenClawAdapter  # 惰性:仅在选用 openclaw 时才 import SDK
    return OpenClawAdapter(connection)


def _make_hermes(connection: dict[str, Any]) -> HarnessAdapter:
    from .hermes import HermesAdapter  # 惰性:仅在选用 hermes 时才 import ACP SDK
    return HermesAdapter(connection)


_REGISTRY["openclaw"] = _make_openclaw
_REGISTRY["hermes"] = _make_hermes


def available_types() -> list[str]:
    return sorted(_REGISTRY)


def create_adapter(harness_config: Any) -> HarnessAdapter:
    """按 `harness_config.type` 构造 adapter。

    `harness_config` 须暴露 `.type`(str)与 `.connection`(dict);未知 type 抛错。
    """
    htype = getattr(harness_config, "type", None)
    connection = dict(getattr(harness_config, "connection", {}) or {})
    factory = _REGISTRY.get(htype)
    if factory is None:
        raise ValueError(
            f"未知 harness 类型: {htype!r};可用类型: {available_types()}"
        )
    return factory(connection)
