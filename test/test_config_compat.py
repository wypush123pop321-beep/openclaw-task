"""配置后向兼容单测(能力: harness-adapter / D6)。

用法:  python test/test_config_compat.py
验证:顶层连接字段折叠为默认 openclaw、显式 harness 段保留、显式 openclaw 顶层补齐、
未知 harness.type 显式报错。不连网(create_adapter 仅构造对象)。
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from openclaw_automation import AutomationConfig
from harness import create_adapter


def test_old_config_folds_into_openclaw():
    """旧 config 无 harness 段:顶层连接字段折叠成默认 openclaw 的 connection。"""
    cfg = AutomationConfig(gateway_ws_url="ws://h:1/gateway", api_key="k", gateway_timeout=10)
    assert cfg.harness is not None
    assert cfg.harness.type == "openclaw"
    conn = cfg.harness.connection
    assert conn["gateway_ws_url"] == "ws://h:1/gateway"
    assert conn["api_key"] == "k"
    assert conn["gateway_timeout"] == 10
    a = create_adapter(cfg.harness)  # 仅构造,不连网
    assert type(a).__name__ == "OpenClawAdapter"
    print("✓ 旧 config 折叠为默认 openclaw")


def test_explicit_harness_preserved():
    """显式 harness 段(非 openclaw)原样保留,不被顶层覆盖。"""
    cfg = AutomationConfig(harness={"type": "hermes", "connection": {"model": "m"}})
    assert cfg.harness.type == "hermes"
    assert cfg.harness.connection["model"] == "m"
    print("✓ 显式 harness 段保留")


def test_explicit_openclaw_merges_top_level():
    """显式 openclaw 段:顶层连接字段补齐 connection 未显式给出的键(显式优先)。"""
    cfg = AutomationConfig(
        gateway_ws_url="ws://h:1/gateway",
        harness={"type": "openclaw", "connection": {"api_key": "explicit"}},
    )
    conn = cfg.harness.connection
    assert conn["api_key"] == "explicit"               # 显式优先
    assert conn["gateway_ws_url"] == "ws://h:1/gateway"  # 顶层补齐
    print("✓ 显式 openclaw 顶层补齐")


def test_unknown_harness_type_raises():
    """未知 harness.type → create_adapter 显式报错(不静默回退)。"""
    cfg = AutomationConfig(harness={"type": "nope", "connection": {}})
    try:
        create_adapter(cfg.harness)
        assert False, "应抛 ValueError"
    except ValueError as e:
        assert "nope" in str(e)
    print("✓ 未知 harness 类型显式报错")


if __name__ == "__main__":
    test_old_config_folds_into_openclaw()
    test_explicit_harness_preserved()
    test_explicit_openclaw_merges_top_level()
    test_unknown_harness_type_raises()
    print("\n全部通过 ✅ (test_config_compat)")
