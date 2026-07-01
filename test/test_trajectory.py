"""轨迹捕获单测(能力: trajectory-capture)。

用法:  python test/test_trajectory.py
不依赖网关/网络/具体 harness SDK,只验证纯逻辑:构造中立 `TurnResult` /
fake `HarnessAdapter`(声明 FILE_EVIDENCE),驱动 build_turn_record / capture_file_evidence /
extract_tool_calls。
"""

import asyncio
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import Capability
from harness.types import FileContent, TurnResult, WorkspaceFile, WorkspaceTruth
from trajectory import (
    FileEvidence,
    ToolCallEvidence,
    build_turn_record,
    capture_file_evidence,
    extract_tool_calls,
)


def test_normal_turn_captures_tool_calls():
    """正常返回的 turn 捕获到 tool_calls(及其返回值)。"""
    result = TurnResult(
        success=True,
        content="已完成",
        tool_calls=[ToolCallEvidence(tool="write_file", input="report.md", output="ok", duration_ms=12)],
        files=[FileEvidence(name="report.md")],
        stop_reason="complete",
    )
    rec = build_turn_record(1, "帮我写报告", result, evidence_incomplete=False)
    assert len(rec.tool_calls) == 1
    assert rec.tool_calls[0].tool == "write_file"
    assert rec.tool_calls[0].output == "ok"
    assert [f.name for f in rec.files] == ["report.md"]
    assert rec.files[0].checked is False  # 尚未做磁盘核验,仅记录声称
    assert rec.evidence_incomplete is False
    print("✓ 正常 turn 捕获 tool_calls")


def test_fallback_turn_marked_incomplete():
    """经 history 兜底恢复的 turn 被标 evidence_incomplete。"""
    result = TurnResult(success=True, content="兜底文本", stop_reason="complete")
    rec = build_turn_record(2, "继续", result, evidence_incomplete=True)
    assert rec.evidence_incomplete is True
    assert rec.tool_calls == []
    print("✓ 兜底 turn 标记 evidence_incomplete")


class _FakeAdapter:
    """假 adapter:声明 FILE_EVIDENCE;disk[name]=内容(存在)或 None(不存在)。

    read_workspace 返回空清单(workspace_path=None → 跳过本地目录扫描);
    get_file 据 disk 返回中立 FileContent。
    """

    capabilities = frozenset({Capability.FILE_EVIDENCE})

    def __init__(self, disk):
        self.disk = disk

    async def read_workspace(self, agent_id):
        return WorkspaceTruth(workspace_path=None, files=[])

    async def get_file(self, agent_id, name):
        if self.disk.get(name) is not None:
            return FileContent(name=name, content=self.disk[name], missing=False)
        return FileContent(name=name, content=None, missing=True)


def test_disk_truth_overrides_claim():
    """声称生成的文件以磁盘核对为准(拆穿声称但磁盘无)。"""
    result = TurnResult(
        success=True,
        content="我生成了 a.md 和 b.md",
        files=[FileEvidence(name="a.md"), FileEvidence(name="b.md")],
    )
    rec = build_turn_record(1, "q", result, evidence_incomplete=False)
    adapter = _FakeAdapter({"a.md": "hello", "b.md": None})
    asyncio.run(capture_file_evidence(adapter, "paper_reader", rec))
    by = {f.name: f for f in rec.files}
    assert by["a.md"].checked and by["a.md"].exists and by["a.md"].content == "hello"
    assert by["b.md"].checked and not by["b.md"].exists  # 声称生成但磁盘无 → 拆穿
    print("✓ 磁盘真相校正自报文件证据")


def test_file_fetch_error_degrades_not_negative():
    """取证受阻降级为 error(证据缺失),而非判负。"""

    class _BrokenAdapter:
        capabilities = frozenset({Capability.FILE_EVIDENCE})

        async def read_workspace(self, agent_id):
            return WorkspaceTruth(workspace_path=None, files=[])

        async def get_file(self, agent_id, name):
            raise RuntimeError("路径不可达")

    result = TurnResult(
        success=True, content="生成了 c.md",
        files=[FileEvidence(name="c.md")],
    )
    rec = build_turn_record(1, "q", result, evidence_incomplete=False)
    asyncio.run(capture_file_evidence(_BrokenAdapter(), "a", rec))
    fe = rec.files[0]
    assert fe.checked and fe.error is not None and fe.exists is False
    print("✓ 取证受阻降级为证据缺失(不判负)")


def test_no_file_evidence_capability_skips():
    """缺 FILE_EVIDENCE 能力时跳过磁盘核验(证据不完整降级),不报错、不判负。"""

    class _NoFileAdapter:
        capabilities = frozenset()  # 不声明 FILE_EVIDENCE

    result = TurnResult(success=True, content="生成了 d.md", files=[FileEvidence(name="d.md")])
    rec = build_turn_record(1, "q", result, evidence_incomplete=False)
    asyncio.run(capture_file_evidence(_NoFileAdapter(), "a", rec))
    fe = rec.files[0]
    assert fe.checked is False  # 未核验,仅声称(降级)
    print("✓ 缺文件证据能力时跳过核验(降级不报错)")


def test_discovers_workspace_file_when_self_report_empty():
    """自报为空 + adapter get_file 白名单读不到用户文件时,经 read_workspace 拿到
    workspace 路径后**直接扫描本地工作区目录**发现新产物并读盘。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as ws:
        Path(ws, "AGENTS.md").write_text("scaffold", encoding="utf-8")
        Path(ws, "openclaw_report.md").write_text("- 要点1\n- 要点2\n- 要点3\n", encoding="utf-8")

        class _WhitelistAdapter:
            capabilities = frozenset({Capability.FILE_EVIDENCE})

            async def read_workspace(self, agent_id):
                # 真实网关只暴露脚手架白名单,不含用户新建文件
                return WorkspaceTruth(
                    workspace_path=ws,
                    files=[WorkspaceFile(name="AGENTS.md", path=str(Path(ws, "AGENTS.md")), exists=True, size=8)],
                )

            async def get_file(self, agent_id, name):
                raise RuntimeError(f'unsupported file "{name}"')

        result = TurnResult(success=True, content="文件已创建", files=[])  # 自报为空
        rec = build_turn_record(1, "创建 openclaw_report.md", result, evidence_incomplete=False)
        assert rec.files == []
        asyncio.run(capture_file_evidence(_WhitelistAdapter(), "main", rec))
        by = {f.name: f for f in rec.files}
        assert "openclaw_report.md" in by, "应扫描本地工作区发现用户新建文件"
        fe = by["openclaw_report.md"]
        assert fe.checked and fe.exists and fe.discovered
        assert fe.content and "要点1" in fe.content, "应读到真实磁盘内容"
        assert "AGENTS.md" not in by, "脚手架文件不应被当作新产物 surface"
    print("✓ 自报为空时扫描本地工作区发现新文件并读到磁盘内容")


def test_extract_tool_calls_from_history():
    """从 OC chat_history 解析 toolCall/toolResult 并按 id 配对(黄金样本同构)。"""
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "建文件并读"}]},
        {"role": "assistant", "content": [
            {"type": "toolCall", "id": "c1", "name": "write",
             "arguments": {"file_path": "probe.txt", "content": "hello-probe"}},
            {"type": "text", "text": "\n"},
            {"type": "toolCall", "id": "c2", "name": "read",
             "arguments": {"file_path": "probe.txt"}},
        ]},
        {"role": "toolResult", "toolCallId": "c1", "toolName": "write",
         "content": [{"type": "text", "text": "Successfully wrote 11 bytes to probe.txt"}], "isError": False},
        {"role": "toolResult", "toolCallId": "c2", "toolName": "read",
         "content": [{"type": "text", "text": "hello-probe"}], "isError": False},
        {"role": "assistant", "content": [{"type": "text", "text": "内容是 hello-probe"}]},
    ]
    calls = extract_tool_calls(messages)
    assert len(calls) == 2, f"应解析出 2 次工具调用,实得 {len(calls)}"
    assert calls[0].tool == "write"
    # input 为原生 JSON 对象(非转义字符串):入参 dict 原样保留
    assert calls[0].input == {"file_path": "probe.txt", "content": "hello-probe"}
    assert calls[0].output == "Successfully wrote 11 bytes to probe.txt"
    assert calls[1].tool == "read" and calls[1].output == "hello-probe"
    print("✓ 从 chat_history 解析 toolCall/toolResult 并按 id 配对")


def test_extract_tool_calls_edge_cases():
    """无工具步骤→空;缺 result→output None;isError→[error] 标注。"""
    # 纯对话无工具调用
    assert extract_tool_calls([
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]) == []
    # toolCall 缺对应 toolResult → output 为 None
    only_call = extract_tool_calls([
        {"role": "assistant", "content": [
            {"type": "toolCall", "id": "x", "name": "read", "arguments": {"p": 1}}]},
    ])
    assert len(only_call) == 1 and only_call[0].output is None
    # isError → output 带 [error] 前缀
    err = extract_tool_calls([
        {"role": "assistant", "content": [
            {"type": "toolCall", "id": "e", "name": "read", "arguments": {}}]},
        {"role": "toolResult", "toolCallId": "e", "toolName": "read",
         "content": [{"type": "text", "text": "No such file"}], "isError": True},
    ])
    assert err[0].output.startswith("[error]") and "No such file" in err[0].output
    print("✓ 边界:无工具→空 / 缺 result→None / isError→标注")


if __name__ == "__main__":
    test_normal_turn_captures_tool_calls()
    test_fallback_turn_marked_incomplete()
    test_disk_truth_overrides_claim()
    test_file_fetch_error_degrades_not_negative()
    test_no_file_evidence_capability_skips()
    test_discovers_workspace_file_when_self_report_empty()
    test_extract_tool_calls_from_history()
    test_extract_tool_calls_edge_cases()
    print("\n全部通过 ✅ (test_trajectory)")
