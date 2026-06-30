"""HermesAdapter 单测(能力: harness-adapter)。

用法:  python test/test_hermes_adapter.py
不起真实子进程:用 Fake ACP conn 注入 `adapter._conn`,直接驱动收集器与会话映射;
用真实 `acp.schema` 对象喂收集器,验证 session/update → 中立 TurnResult 的映射。
覆盖:会话映射(首见建会话/复用/隔离)、收集器组装(文本+工具+文件)、权限自动放行、
能力降级声明、本地文件证据、execute 流、结构化兜底重试(对齐主线 Evaluator API)。
"""

import asyncio
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from acp import schema as S
from acp import start_tool_call, update_agent_message_text, update_tool_call

from harness import Capability, create_adapter
from harness.hermes import HermesAdapter
from harness.hermes.collector import HermesClientSink, TurnCollector
from harness.types import AgentSpec


# ---------------------------------------------------------------------------
# Fake ACP conn:记录调用,prompt() 模拟 Hermes 流式推 session/update 后返回 stop_reason
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, session_id=None, stop_reason=None):
        self.session_id = session_id
        self.stop_reason = stop_reason


class _FakeConn:
    def __init__(self, sink: HermesClientSink, updates_per_prompt=None):
        self._sink = sink
        self._n = 0
        self.new_session_calls = []
        self.set_model_calls = []
        self.prompts = []
        self.cancels = []
        self._updates = updates_per_prompt or []

    async def initialize(self, protocol_version=None, **kw):
        return _Resp()

    async def new_session(self, cwd=None, **kw):
        self._n += 1
        sid = f"uuid-{self._n}"
        self.new_session_calls.append((sid, cwd))
        return _Resp(session_id=sid)

    async def set_session_model(self, model_id=None, session_id=None, **kw):
        self.set_model_calls.append((session_id, model_id))
        return None

    async def prompt(self, prompt=None, session_id=None, message_id=None, **kw):
        self.prompts.append((session_id, prompt[0].text if prompt else "", message_id))
        for u in self._updates:
            await self._sink.session_update(session_id, u)
        return _Resp(stop_reason="end_turn")

    async def cancel(self, session_id=None, **kw):
        self.cancels.append(session_id)


def _adapter_with(conn_factory=None, **conn_kw):
    a = HermesAdapter(connection={"model": "default-model"})
    conn = (conn_factory or _FakeConn)(a._sink, **conn_kw)
    a._conn = conn  # 绕过 __aenter__,不起子进程
    return a, conn


# ---------------------------------------------------------------------------
# 1. 会话映射:首见建会话、复用、不同 session 隔离
# ---------------------------------------------------------------------------

async def test_session_mapping():
    a, conn = _adapter_with()
    await a.ensure_agent(AgentSpec(name="main3", workspace=tempfile.mkdtemp(), model="m1"))

    await a.execute("main3", "test", "q1")
    await a.execute("main3", "test", "q3")   # 同元组复用
    await a.execute("main3", "eval", "q2")   # 不同 session → 新会话

    assert len(conn.new_session_calls) == 2, conn.new_session_calls  # test 一次、eval 一次
    assert a._sessions[("main3", "test")] == "uuid-1"
    assert a._sessions[("main3", "eval")] == "uuid-2"
    # 复用:test 的两次 prompt 落到同一 sid
    test_sids = [p[0] for p in conn.prompts if p[2] is not None and p[0] == "uuid-1"]
    assert len(test_sids) == 2, conn.prompts
    # 模型按 spec.model 优先(覆盖 connection 默认)
    assert conn.set_model_calls[0] == ("uuid-1", "m1"), conn.set_model_calls
    print("✓ test_session_mapping")


# ---------------------------------------------------------------------------
# 2. 收集器组装:文本块 + 工具调用 + 编辑类文件证据
# ---------------------------------------------------------------------------

async def test_collector_assembly():
    c = TurnCollector()
    c.ingest(update_agent_message_text("上海"))
    c.ingest(update_agent_message_text("是经济中心"))
    c.ingest(start_tool_call(
        tool_call_id="t1", title="write_file", kind="edit",
        raw_input={"path": "ans.md"},
        locations=[S.ToolCallLocation(path="ans.md")],
        status="in_progress",
    ))
    c.ingest(update_tool_call(tool_call_id="t1", status="completed", raw_output="written"))

    tr = c.assemble(stop_reason="end_turn")
    assert tr.content == "上海是经济中心", repr(tr.content)
    assert tr.success is True and tr.stop_reason == "end_turn"
    assert len(tr.tool_calls) == 1
    assert tr.tool_calls[0].tool == "write_file"
    assert "ans.md" in tr.tool_calls[0].input
    assert tr.tool_calls[0].output == "written"
    assert [f.name for f in tr.files] == ["ans.md"], tr.files
    print("✓ test_collector_assembly")


# ---------------------------------------------------------------------------
# 3. 权限自动放行 / 拒绝
# ---------------------------------------------------------------------------

async def test_permission():
    opts = [
        S.PermissionOption(option_id="no", name="Reject", kind="reject_once"),
        S.PermissionOption(option_id="yes", name="Allow", kind="allow_once"),
    ]
    sink = HermesClientSink(auto_approve=True)
    resp = await sink.request_permission(opts, "sid", tool_call=None)
    assert isinstance(resp.outcome, S.AllowedOutcome) and resp.outcome.option_id == "yes", resp

    sink_off = HermesClientSink(auto_approve=False)
    resp2 = await sink_off.request_permission(opts, "sid", tool_call=None)
    assert isinstance(resp2.outcome, S.DeniedOutcome), resp2
    print("✓ test_permission")


# ---------------------------------------------------------------------------
# 4. 能力声明 + registry 选择
# ---------------------------------------------------------------------------

async def test_capabilities_registry():
    assert HermesAdapter.capabilities == frozenset({Capability.FILE_EVIDENCE})

    class _HC:
        type = "hermes"
        connection = {"model": "m", "provider": "openrouter", "api_key": "k"}
    a = create_adapter(_HC())
    assert type(a).__name__ == "HermesAdapter"
    assert a._launch.env.get("LLM_MODEL") == "m"
    assert a._launch.env.get("OPENROUTER_API_KEY") == "k"
    print("✓ test_capabilities_registry")


# ---------------------------------------------------------------------------
# 5. 本地文件证据:put → get → read_workspace
# ---------------------------------------------------------------------------

async def test_file_evidence():
    ws = tempfile.mkdtemp()
    a, _ = _adapter_with()
    await a.ensure_agent(AgentSpec(name="main3", workspace=ws))

    await a.put_file("main3", "out/ans.md", "上海")
    fc = await a.get_file("main3", "out/ans.md")
    assert fc.missing is False and fc.content == "上海", fc

    missing = await a.get_file("main3", "nope.md")
    assert missing.missing is True

    truth = await a.read_workspace("main3")
    names = [f.name for f in truth.files]
    assert "out/ans.md" in names, names
    print("✓ test_file_evidence")


# ---------------------------------------------------------------------------
# 6. 端到端 execute(收集器经 prompt 流式喂入)
# ---------------------------------------------------------------------------

async def test_execute_collects_stream():
    updates = [
        update_agent_message_text("答案"),
        start_tool_call(tool_call_id="t", title="search", kind="search", raw_input={"q": "x"}),
        update_tool_call(tool_call_id="t", status="completed", raw_output="hit"),
    ]
    a, conn = _adapter_with(updates_per_prompt=updates)
    await a.ensure_agent(AgentSpec(name="main3", workspace=tempfile.mkdtemp()))
    tr = await a.execute("main3", "test", "问题")
    assert tr.content == "答案", repr(tr.content)
    assert tr.tool_calls and tr.tool_calls[0].tool == "search"
    assert tr.tool_calls[0].output == "hit"
    # 回合结束后活跃收集器已清理
    assert a._sink.end("uuid-1") is None
    print("✓ test_execute_collects_stream")


# ---------------------------------------------------------------------------
# 7. 结构化兜底重试(harness 无关,经无 STRUCTURED_OUTPUT 能力的 adapter;对齐主线 Evaluator)
# ---------------------------------------------------------------------------

async def test_structured_fallback_retry():
    from harness import HarnessAdapter
    from harness.types import TurnResult
    from evaluator import Evaluator, EvaluateConfig

    class _BadThenGood(HarnessAdapter):
        capabilities = frozenset({Capability.FILE_EVIDENCE})  # 无 STRUCTURED_OUTPUT / SESSION_RESET
        def __init__(self): self.calls = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *e): return None
        async def ensure_agent(self, spec): ...
        async def execute(self, agent, session, query, *, timeout=None):
            self.calls += 1
            if self.calls == 1:
                return TurnResult(content="抱歉我不会输出 JSON")  # 解析失败
            return TurnResult(content='{"completion": 0.8, "inclination": "accept", '
                                       '"violations": [], "improvements": [], '
                                       '"citations": [], "reason": "ok", "rubric_checks": []}')

    adapter = _BadThenGood()
    ev = Evaluator(EvaluateConfig(agent_name="evaluator"), adapter, run_id="r1", session_name="eval_sess")
    result = await ev._run_structured("评估这个")
    assert adapter.calls == 2, adapter.calls           # 第一次失败、第二次成功
    assert result.completion == 0.8, result
    assert result.inclination == "accept"
    print("✓ test_structured_fallback_retry")


async def _main():
    await test_session_mapping()
    await test_collector_assembly()
    await test_permission()
    await test_capabilities_registry()
    await test_file_evidence()
    await test_execute_collects_stream()
    await test_structured_fallback_retry()
    print("\nALL HERMES ADAPTER TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(_main())
