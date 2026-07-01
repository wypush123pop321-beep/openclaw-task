"""OpenClawAdapter 原生→中立映射单测(能力: harness-adapter)。

用法:  python test/test_adapter_mapping.py
验证 `ExecutionResult → TurnResult` 映射与 `TurnResult.with_content` 干净构造法。
本测试位于 adapter 子包边界内,故允许 import openclaw_sdk(核心三层才禁)。
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from openclaw_sdk.core.types import ExecutionResult, GeneratedFile, ToolCall

from harness.openclaw.adapter import OpenClawAdapter
from harness.types import TurnResult


def test_map_execution_result_to_turn_result():
    """ExecutionResult → TurnResult:content/tool_calls/files/stop_reason/success 等价映射。"""
    er = ExecutionResult(
        success=True,
        content="hi",
        tool_calls=[ToolCall(tool="write", input="a.md", output="ok", duration_ms=5)],
        files=[GeneratedFile(name="a.md", path="/ws/a.md", size_bytes=3, mime_type="text/markdown")],
        stop_reason="complete",
    )
    tr = OpenClawAdapter._map_result(er, evidence_incomplete=False)
    assert isinstance(tr, TurnResult)
    assert tr.content == "hi"
    assert len(tr.tool_calls) == 1
    assert tr.tool_calls[0].tool == "write"
    assert tr.tool_calls[0].output == "ok"
    assert tr.tool_calls[0].duration_ms == 5
    assert [f.name for f in tr.files] == ["a.md"]
    assert tr.stop_reason == "complete"
    assert tr.success is True
    assert tr.evidence_incomplete is False
    print("✓ ExecutionResult → TurnResult 映射")


def test_map_empty_result():
    """空内容/无工具/无文件的 ExecutionResult 映射为干净空 TurnResult。"""
    er = ExecutionResult(success=True, content="", stop_reason="complete")
    tr = OpenClawAdapter._map_result(er, evidence_incomplete=True)
    assert tr.content == ""
    assert tr.tool_calls == []
    assert tr.files == []
    assert tr.evidence_incomplete is True
    print("✓ 空 ExecutionResult 映射")


def test_with_content_builds_clean_copy():
    """TurnResult.with_content:替换文本为成功副本(取代 model_copy(update=...))。"""
    tr = TurnResult(content="", stop_reason=None, evidence_incomplete=True)
    tr2 = tr.with_content("recovered")
    assert tr2.content == "recovered"
    assert tr2.success is True
    assert tr2.stop_reason == "complete"
    assert tr2.error is None
    # 原对象不被修改(model_copy 语义)
    assert tr.content == ""
    print("✓ with_content 干净构造副本")


if __name__ == "__main__":
    test_map_execution_result_to_turn_result()
    test_map_empty_result()
    test_with_content_builds_clean_copy()
    print("\n全部通过 ✅ (test_adapter_mapping)")
