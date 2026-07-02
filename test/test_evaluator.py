"""Evaluator 单测(能力: trajectory-evaluation)。

用法:  python test/test_evaluator.py
不依赖网关/网络/LLM,只验证纯逻辑:结构化解析、证据渲染、反馈格式化。
LLM 裁判本身的判准需后续用校准集验证(本测试不覆盖)。
"""

import sys
from pathlib import Path

# 控制台可能是 GBK(Windows),输出中的 ✓/✅ 等字符需 utf-8 才能打印
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from openclaw_sdk.output.structured import StructuredOutput

from evaluator import EvaluateConfig, EvaluationResult, Evaluator, Rubric, RubricCheck
from trajectory import FileEvidence, TurnRecord, Trajectory, _render_turn


def test_structured_eval_output_parses():
    """评估结构化输出可解析(completion 为 0~1 浮点)。"""
    raw = (
        "好的,这是我的裁决:\n```json\n"
        '{"completion": 0.4, "inclination": "reject", '
        '"violations": ["声称生成 b.md 但磁盘上不存在"], '
        '"improvements": ["先真正写出文件"], '
        '"citations": ["b.md: 声称生成,但磁盘上不存在 ✗"], '
        '"reason": "声称与磁盘证据矛盾"}\n```'
    )
    ev = StructuredOutput.parse(raw, EvaluationResult)
    assert ev.completion == 0.4
    assert ev.inclination == "reject"
    assert ev.violations and "b.md" in ev.violations[0]
    print("✓ 评估结构化输出解析")


def test_false_positive_surfaced_to_evaluator():
    """话术型假阳性(声称 vs 磁盘矛盾)在喂给裁判的证据里被点名。"""
    rec = TurnRecord(
        turn=1,
        user_input="帮我写 b.md",
        agent_content="我已经生成了 b.md",
        files=[FileEvidence(name="b.md", checked=True, exists=False)],
    )
    text = _render_turn(rec)
    assert "磁盘上不存在" in text  # 裁判能看到矛盾
    print("✓ 声称但磁盘无的文件被暴露给裁判")


def test_evidence_incomplete_marked_non_negative():
    """evidence_incomplete 样本被标注为"不得当负面证据"。"""
    rec = TurnRecord(turn=1, user_input="q", agent_content="...", evidence_incomplete=True)
    text = _render_turn(rec)
    assert "证据缺失 ≠ 证据为负" in text
    print("✓ 证据不完整被标注为非负面")


def test_format_feedback():
    """反馈文本格式化(给 simulator 看)。"""
    ev_obj = Evaluator(EvaluateConfig(), client=None, run_id="t", session_name="t")
    fb = ev_obj.format_feedback(
        EvaluationResult(
            completion=0.8, inclination="accept",
            improvements=["补充数据来源"], violations=[],
            citations=["report.md: 存在 ✓"], reason="基本达成",
        )
    )
    assert "完成度: 0.8" in fb
    assert "倾向: accept" in fb
    assert "改进点" in fb
    print("✓ 反馈格式化")


def _mk_eval(**cfg) -> Evaluator:
    return Evaluator(EvaluateConfig(**cfg), client=None, run_id="t", session_name="t")


def _mk_turn() -> tuple[Trajectory, TurnRecord]:
    traj = Trajectory(query="帮我订一张去北京的往返机票", agent_name="main")
    rec = TurnRecord(turn=1, user_input="订票", agent_content="已为你预订")
    traj.turns.append(rec)
    return traj, rec


RUBRIC_TEXTS = ["机票为往返程", "出发地与目的地正确", "已给出订单确认号"]
RUBRIC = [Rubric.from_raw(t, i) for i, t in enumerate(RUBRIC_TEXTS, 1)]


def test_rubric_check_and_result_parse():
    """RubricCheck/EvaluationResult.rubric_checks 结构化解析(0/1 二值)。"""
    raw = (
        '{"completion": 0.6, "inclination": "reject", '
        '"violations": ["缺少返程"], "improvements": ["补订返程"], '
        '"citations": ["无往返工具调用记录"], '
        '"rubric_checks": ['
        '{"rubric_id": "R1", "criterion": "机票为往返程", "passed": 0, "evidence": "仅见单程预订"},'
        '{"rubric_id": "R3", "criterion": "已给出订单确认号", "passed": 1, "evidence": "工具返回确认号 ABC123"}'
        '], "reason": "返程未完成"}'
    )
    ev = StructuredOutput.parse(raw, EvaluationResult)
    assert len(ev.rubric_checks) == 2
    assert ev.rubric_checks[0].passed == 0
    assert ev.rubric_checks[1].passed == 1
    assert ev.rubric_checks[0].rubric_id == "R1"
    print("✓ rubric_checks 解析(0/1)")


def test_build_prompt_injects_rubric_when_present():
    """有 rubric 时注入逐条清单; 空 rubric 时不注入清单, 且声明 rubric_checks 须为空。"""
    ev = _mk_eval()
    traj, _ = _mk_turn()
    with_rubric = ev._build_prompt(traj, rubric=RUBRIC)
    assert "验收清单(Rubric · 逐条 0/1 判定)" in with_rubric
    for c in RUBRIC_TEXTS:
        assert c in with_rubric  # 注入给 evaluator(非 simulator)
    without = ev._build_prompt(traj, rubric=[])
    # 空 rubric 不注入逐条清单, 也不出现任一准则原文
    assert "逐条 0/1 判定" not in without
    for c in RUBRIC_TEXTS:
        assert c not in without
    # 空 rubric 时显式声明 rubric_checks 必须为空数组(prompt 层约束)
    assert "rubric_checks" in without and "空数组" in without
    print("✓ rubric 注入/缺省分支")


def test_build_prompt_states_blocked_rule():
    """提示词明确"核验受阻一律判 passed=0"(替代旧 unverifiable 概念)。"""
    ev = _mk_eval()
    traj, _ = _mk_turn()
    p = ev._build_prompt(traj, rubric=RUBRIC)
    assert "核验受阻" in p
    assert "passed=0" in p
    print("✓ 提示词含核验受阻判 0 铁律")


def test_format_feedback_does_not_leak_rubric():
    """回流 simulator 的反馈不含 rubric 准则原文(边界 X)。"""
    ev_obj = _mk_eval()
    fb = ev_obj.format_feedback(
        EvaluationResult(
            completion=0.6, inclination="reject",
            improvements=["补订返程"], violations=["缺少返程"],
            citations=["无往返工具调用记录"],
            rubric_checks=[
                RubricCheck(rubric_id="R1", criterion="机票为往返程", passed=0, evidence="仅见单程"),
            ],
            reason="返程未完成",
        )
    )
    assert "机票为往返程" not in fb  # rubric 准则原文 MUST NOT 泄漏给 simulator
    assert "补订返程" in fb           # 提炼后的改进点仍回流
    print("✓ format_feedback 不泄漏 rubric 原文")


def test_to_simulator_switch():
    """to_simulator 开关值; 默认 False(安全不回流);历史别名等价读取。"""
    assert EvaluateConfig().to_simulator is False  # 安全默认
    assert _mk_eval(to_simulator=True).to_simulator is True
    assert _mk_eval(to_simulator=False).to_simulator is False
    # 历史别名 feedback_to_simulator / feedback_to_user 经 AliasChoices 等价读取
    assert EvaluateConfig(feedback_to_simulator=True).to_simulator is True
    assert EvaluateConfig(feedback_to_user=True).to_simulator is True
    print("✓ to_simulator 开关/默认/别名")


def test_no_rubric_normalizes_rubric_checks_empty():
    """无 rubric 时即便模型自拟 rubric_checks, 也被确定性归一为空(落盘前)。"""
    import asyncio
    from openclaw_sdk.core.types import ExecutionResult

    # 伪造一个会"幻觉"出 rubric_checks 的裁判 agent(无网络/无 LLM)
    hallucinated = (
        '{"completion": 0.5, "inclination": "uncertain", '
        '"violations": [], "improvements": [], "citations": [], '
        '"rubric_checks": [{"rubric_id": "R1", "criterion": "自拟准则", "passed": 1, "evidence": "X"}], '
        '"reason": "无 rubric 也乱填了"}'
    )

    class _FakeAgent:
        async def execute(self, query: str) -> ExecutionResult:
            return ExecutionResult(success=True, content=hallucinated, stop_reason="complete")

    class _FakeClient:
        gateway = None  # 触发 _push_review_files / _reset_session 早退
        def get_agent(self, name, session):
            return _FakeAgent()

    ev = Evaluator(
        EvaluateConfig(log_evaluations=False), client=_FakeClient(), run_id="t", session_name="t"
    )
    traj, rec = _mk_turn()
    result = asyncio.run(ev.evaluate_turn(traj, rec, rubric=[]))
    assert result is not None
    assert result.rubric_checks == []  # 归一保底生效
    assert result.completion == 0.5    # 无 rubric 时不被 Scorer 覆盖
    print("✓ 无 rubric 时 rubric_checks 被归一为空")


if __name__ == "__main__":
    test_structured_eval_output_parses()
    test_false_positive_surfaced_to_evaluator()
    test_evidence_incomplete_marked_non_negative()
    test_format_feedback()
    test_rubric_check_and_result_parse()
    test_build_prompt_injects_rubric_when_present()
    test_build_prompt_states_blocked_rule()
    test_format_feedback_does_not_leak_rubric()
    test_to_simulator_switch()
    test_no_rubric_normalizes_rubric_checks_empty()
    print("\n全部通过 ✅ (test_evaluator)")
