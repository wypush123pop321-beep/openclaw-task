"""确定性评分聚合(Scorer/ScoringSpec)单测(能力: trajectory-evaluation)。

用法:  python test/test_scoring.py
不依赖网关/网络/LLM,只验证纯逻辑:rubric 结构化、(∏gate)×Σ桶加权、空 scoring 退回。
判分基线对齐样本 04_出行助手_task1_班次时刻表核对(8 条 rubric 全过 → completion==1.0)。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluator import Rubric, ScoringSpec, Scorer

# ---- 目标样本的 rubric 与 scoring(内联,使测试自包含;对齐 user_queries.json#/0/evaluate/0)----
SAMPLE_RUBRICS_RAW = [
    {"id": "G1", "when": "gate", "evaluator": "program", "text": "可解析+含可行列表+最晚结论"},
    {"id": "G2", "when": "gate", "evaluator": "program", "text": "约束应用正确"},
    {"id": "PT1", "when": "per_turn", "evaluator": "program", "text": "逐行核验"},
    {"id": "PT2", "when": "per_turn", "evaluator": "oracle_cmp", "text": "给出排除原因"},
    {"id": "C1", "when": "final", "evaluator": "oracle_cmp", "text": "可行集合恰为{G7305,G7309}"},
    {"id": "C2", "when": "final", "evaluator": "oracle_cmp", "text": "最晚 G7309"},
    {"id": "C3", "when": "final", "evaluator": "oracle_cmp", "text": "排除 G7301"},
    {"id": "C4", "when": "final", "evaluator": "oracle_cmp", "text": "排除 G7313"},
]
SAMPLE_SCORING = {
    "gate_zero": True,
    "weights": {"correctness": 0.55, "provenance": 0.0, "process": 0.15, "soft": 0.1},
    "bucket_map": {
        "correctness": ["C1", "C2", "C3", "C4"],
        "provenance": [],
        "process": ["PT1", "PT2"],
        "soft": [],
    },
}


def _sample_scorer():
    rubrics = [Rubric.from_raw(r, i) for i, r in enumerate(SAMPLE_RUBRICS_RAW, 1)]
    spec = ScoringSpec.from_scoring(SAMPLE_SCORING, rubrics)
    return Scorer(spec), rubrics


def test_rubric_from_raw_dict_and_str():
    """rubric 结构化:dict 保留字段;str 归一为 when=final/llm_judge。"""
    r = Rubric.from_raw({"id": "C1", "when": "final", "evaluator": "oracle_cmp", "text": "x"}, 1)
    assert r.id == "C1" and r.when == "final" and r.evaluator == "oracle_cmp"
    s = Rubric.from_raw("明确给出一个具体城市", 3)
    assert s.id == "R3" and s.when == "final" and s.evaluator == "llm_judge"
    assert s.text == "明确给出一个具体城市"
    print("✓ rubric 结构化与字符串向后兼容")


def test_all_pass_completion_is_one():
    """6.2 基线:8 条 rubric 全过 → completion==1.0(空桶不参与权重归一)。"""
    scorer, rubrics = _sample_scorer()
    checks = {r.id: 1 for r in rubrics}
    out = scorer.score(checks)
    assert abs(out["completion"] - 1.0) < 1e-9, out
    assert out["gate_passed"] is True
    print("✓ 全过 completion==1.0")


def test_gate_zero_vetoes():
    """任一 gate 判 0 → completion==0,即便其余全过。"""
    scorer, rubrics = _sample_scorer()
    checks = {r.id: 1 for r in rubrics}
    checks["G2"] = 0
    out = scorer.score(checks)
    assert out["completion"] == 0.0
    assert out["gate_passed"] is False
    assert out["gate_status"]["G2"] == 0
    print("✓ gate 一票否决 → completion==0")


def test_bucket_weighting_proportional():
    """按桶取通过比例:gate 全过、C1 失败(correctness 3/4) → completion<1 且可解释。"""
    scorer, rubrics = _sample_scorer()
    checks = {r.id: 1 for r in rubrics}
    checks["C1"] = 0
    out = scorer.score(checks)
    # 非空桶权重归一:correctness 0.55/0.70, process 0.15/0.70
    expected = round((0.55 / 0.70) * (3 / 4) + (0.15 / 0.70) * 1.0, 4)
    assert abs(out["completion"] - expected) < 1e-9, (out["completion"], expected)
    cb = out["bucket_scores"]["correctness"]
    assert cb["passed"] == 3 and cb["total"] == 4
    print(f"✓ 分桶加权比例正确 (completion={out['completion']:.4f})")


def test_gate_not_in_buckets():
    """gate 项(G1/G2)只做门禁,不计入任何加权桶。"""
    scorer, _ = _sample_scorer()
    bucket_ids = [i for b in scorer.spec.buckets.values() for i in b.rubric_ids]
    assert "G1" not in bucket_ids and "G2" not in bucket_ids
    assert set(scorer.spec.gate_ids) == {"G1", "G2"}
    print("✓ gate 不进加权桶")


def test_missing_check_treated_as_zero():
    """缺失的 rubric 判定(核验受阻)由 Scorer 视为 0。"""
    scorer, rubrics = _sample_scorer()
    checks = {r.id: 1 for r in rubrics if r.id != "C3"}  # C3 缺失
    out = scorer.score(checks)
    expected = round((0.55 / 0.70) * (3 / 4) + (0.15 / 0.70) * 1.0, 4)
    assert abs(out["completion"] - expected) < 1e-9
    print("✓ 缺失判定视为 0")


def test_empty_scoring_fallback():
    """scoring 为 None(query 未配 scoring_ref):ScoringSpec 退回单桶等权、无 gate,completion 仍可算。

    注:这是 ScoringSpec 层的兜底(唯一保留);_resolve_evaluate_refs 里"缺 bucket_map 回退
    rubrics_ref 父块"的兜底已在 align-task-config-standard 中删除,scoring 只从 scoring_ref 来。
    """
    rubrics = [Rubric.from_raw(s, i) for i, s in enumerate(["条件A", "条件B", "条件C"], 1)]
    spec = ScoringSpec.from_scoring(None, rubrics)
    scorer = Scorer(spec)
    assert spec.gate_ids == []
    out = scorer.score({"R1": 1, "R2": 1, "R3": 0})
    assert abs(out["completion"] - round(2 / 3, 4)) < 1e-9, out
    print("✓ 空 scoring 退回单桶等权")


if __name__ == "__main__":
    tests = [
        test_rubric_from_raw_dict_and_str,
        test_all_pass_completion_is_one,
        test_gate_zero_vetoes,
        test_bucket_weighting_proportional,
        test_gate_not_in_buckets,
        test_missing_check_treated_as_zero,
        test_empty_scoring_fallback,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 项通过 ✓")
