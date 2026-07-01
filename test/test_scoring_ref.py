"""scoring_ref 显式解析 + 相对引用基准 单测(能力: task-config-schema)。

用法:  python test/test_scoring_ref.py
不依赖网关/网络/LLM。验证 align-task-config-standard 的加载契约:
- scoring_ref(JSON-Pointer)显式解析为运行时 scoring,并合成 scoring_spec。
- 无 scoring_ref → ev.scoring 保持 None → ScoringSpec 单桶等权兜底(唯一保留的兜底)。
- scoring_ref 指向缺失文件 → 显式报错(不静默退空)。
- oracle_ref/rubrics_ref/scoring_ref 均以 q1.json 所在目录为基准(支持 ../ 跨目录)。
- is_noise 由 (not use_simulator) and (evaluate is None) 派生。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from openclaw_automation import ConfigLoader

# ---- 被引用的环境文件(user_queries.json:含 custom_rubrics 与 scoring)----
USER_QUERIES = [
    {
        "queries": ["t"],
        "evaluate": [
            {
                "custom_rubrics": [
                    {"id": "G1", "when": "gate", "evaluator": "program", "text": "gate"},
                    {"id": "C1", "when": "final", "evaluator": "oracle_cmp", "text": "c1"},
                ],
                "scoring": {
                    "gate_zero": True,
                    "weights": {"correctness": 0.9, "provenance": 0.0, "process": 0.0, "soft": 0.1},
                    "bucket_map": {"correctness": ["C1"], "provenance": [], "process": [], "soft": []},
                },
            }
        ],
    }
]
ORACLE = {"task_id": "T", "derived": {}}


def _build_env(root: Path, *, with_scoring_ref: bool, scoring_ref_override: str = None):
    """构造 task_configs/q1.json + environments/<task>/{oracle,user_queries}.json 布局。"""
    task = "08_demo"
    env = root / "environments" / task
    env.mkdir(parents=True, exist_ok=True)
    (env / "oracle.json").write_text(json.dumps(ORACLE, ensure_ascii=False), encoding="utf-8")
    (env / "user_queries.json").write_text(json.dumps(USER_QUERIES, ensure_ascii=False), encoding="utf-8")

    tc = root / "task_configs"
    tc.mkdir(parents=True, exist_ok=True)
    evaluate = {
        "evaluator_agent": "evaluator",
        "oracle_ref": f"../environments/{task}/oracle.json",
        "rubrics_ref": f"../environments/{task}/user_queries.json#/0/evaluate/0/custom_rubrics",
    }
    if with_scoring_ref:
        evaluate["scoring_ref"] = scoring_ref_override or f"../environments/{task}/user_queries.json#/0/evaluate/0/scoring"
    cfg = {
        "agents": [
            {"name": "assistant1", "system_prompt": None, "model": "m1"},
            {"name": "evaluator", "system_prompt": None, "model": "m2"},
        ],
        "queries": [
            {"agent_name": "assistant1", "text": "t", "use_simulator": True, "evaluate": evaluate}
        ],
        "Harness_Type": None,
    }
    q1 = tc / "q1.json"
    q1.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return q1


def test_scoring_ref_resolved():
    """scoring_ref 显式解析 → ev.scoring 填充 + scoring_spec 合成;跨 ../ 引用成功。"""
    with tempfile.TemporaryDirectory() as d:
        q1 = _build_env(Path(d), with_scoring_ref=True)
        cfg = ConfigLoader.load_from_file(str(q1))
        ev = cfg.queries[0].evaluate
        assert ev.oracle_data is not None and ev.oracle_data["task_id"] == "T"
        assert len(ev.structured_rubrics) == 2
        assert ev.scoring is not None and "bucket_map" in ev.scoring
        assert ev.scoring_spec is not None and ev.scoring_spec.gate_ids == ["G1"]
        assert cfg.Harness_Type is None
        assert cfg.queries[0].is_noise is False  # use_simulator=True
    print("✓ scoring_ref 显式解析 + 跨目录引用 + scoring_spec 合成")


def test_no_scoring_ref_single_bucket_fallback():
    """无 scoring_ref → ev.scoring 为 None → ScoringSpec 单桶等权兜底(唯一保留的兜底)。"""
    with tempfile.TemporaryDirectory() as d:
        q1 = _build_env(Path(d), with_scoring_ref=False)
        cfg = ConfigLoader.load_from_file(str(q1))
        ev = cfg.queries[0].evaluate
        assert ev.scoring is None
        assert ev.scoring_spec is not None
        assert ev.scoring_spec.gate_ids == ["G1"]  # gate 仍从 rubric.when 识别
    print("✓ 无 scoring_ref → 单桶等权兜底(不再回退 rubrics_ref 父块)")


def test_missing_scoring_ref_raises():
    """scoring_ref 指向缺失文件 → 显式报错,不静默退空。"""
    with tempfile.TemporaryDirectory() as d:
        q1 = _build_env(Path(d), with_scoring_ref=True,
                        scoring_ref_override="../environments/08_demo/nope.json#/x")
        try:
            ConfigLoader.load_from_file(str(q1))
        except FileNotFoundError:
            print("✓ scoring_ref 缺失文件 → FileNotFoundError")
            return
        raise AssertionError("应对缺失 scoring_ref 抛 FileNotFoundError,但未抛")


if __name__ == "__main__":
    tests = [
        test_scoring_ref_resolved,
        test_no_scoring_ref_single_bucket_fallback,
        test_missing_scoring_ref_raises,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 项通过 ✓")
