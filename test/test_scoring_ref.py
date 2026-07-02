"""scoring_ref 显式解析 + 引用基准(user_dir.path) + fail-fast + user_workspace 单测。

用法:  python test/test_scoring_ref.py
不依赖网关/网络/LLM。验证 refs-anchor-userdir-and-rename-to-simulator 的加载契约:
- oracle_ref/rubrics_ref/scoring_ref 以 input_dir.user_dir.path 为相对基准(裸名引用)。
- scoring_ref(JSON-Pointer)显式解析为运行时 scoring,并合成 scoring_spec。
- 无 scoring_ref → ev.scoring 保持 None → ScoringSpec 单桶等权兜底(唯一保留的兜底)。
- scoring_ref 指向缺失文件 → 显式报错(不静默退空)。
- 设了 *_ref 却无有效 user_dir(None / 虚空地址) → 加载期 ValueError(fail-fast)。
- 无 *_ref 时 user_dir 缺省合法。
- user_workspace 显式指定 bulk 数据根子目录;缺省回退同名子文件夹。
- is_noise 由 (not use_simulator) and (evaluate is None) 派生。
"""

import json
import sys
import tempfile
from pathlib import Path

# 控制台可能是 GBK(Windows),输出中的 ✓ 等字符需 utf-8 才能打印
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from openclaw_automation import ConfigLoader, UserDirConfig, WorkspaceManager

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


def _build_env(root: Path, *, with_scoring_ref: bool, scoring_ref_override: str = None,
               with_user_dir: bool = True):
    """构造 task_configs/q1.json + environments/<task>/{oracle,user_queries}.json 布局。

    refs 以 user_dir.path(= environments/<task>/ 的绝对路径)为基准,故写为裸名。
    with_user_dir=False 时不写 user_dir(用于 fail-fast 用例)。
    """
    task = "08_demo"
    env = root / "environments" / task
    env.mkdir(parents=True, exist_ok=True)
    (env / "oracle.json").write_text(json.dumps(ORACLE, ensure_ascii=False), encoding="utf-8")
    (env / "user_queries.json").write_text(json.dumps(USER_QUERIES, ensure_ascii=False), encoding="utf-8")

    tc = root / "task_configs"
    tc.mkdir(parents=True, exist_ok=True)
    evaluate = {
        "evaluator_agent": "evaluator",
        "oracle_ref": "oracle.json",
        "rubrics_ref": "user_queries.json#/0/evaluate/0/custom_rubrics",
    }
    if with_scoring_ref:
        evaluate["scoring_ref"] = scoring_ref_override or "user_queries.json#/0/evaluate/0/scoring"
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
    # refs 相对 user_dir.path 解析,故须显式给出环境目录(绝对路径)
    if with_user_dir:
        cfg["input_dir"] = {"user_dir": {"path": str(env)}}
    q1 = tc / "q1.json"
    q1.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return q1


def test_scoring_ref_resolved():
    """scoring_ref 显式解析 → ev.scoring 填充 + scoring_spec 合成;裸名相对 user_dir.path 解析成功。"""
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
    print("✓ scoring_ref 显式解析 + 裸名相对 user_dir.path + scoring_spec 合成")


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
                        scoring_ref_override="nope.json#/x")
        try:
            ConfigLoader.load_from_file(str(q1))
        except FileNotFoundError:
            print("✓ scoring_ref 缺失文件 → FileNotFoundError")
            return
        raise AssertionError("应对缺失 scoring_ref 抛 FileNotFoundError,但未抛")


def test_ref_without_userdir_raises():
    """设了 *_ref 却无 user_dir → 加载期 ValueError(fail-fast)。"""
    with tempfile.TemporaryDirectory() as d:
        q1 = _build_env(Path(d), with_scoring_ref=True, with_user_dir=False)
        try:
            ConfigLoader.load_from_file(str(q1))
        except ValueError as e:
            assert "user_dir" in str(e)
            print("✓ 设了 ref 却无 user_dir → ValueError")
            return
        raise AssertionError("应对无 user_dir 的 ref 抛 ValueError,但未抛")


def test_ref_with_void_userdir_raises():
    """user_dir.path 为 null(→ 虚空地址)且设了 *_ref → ValueError。"""
    with tempfile.TemporaryDirectory() as d:
        q1 = _build_env(Path(d), with_scoring_ref=True, with_user_dir=False)
        # 手动注入 user_dir.path=null,触发 coerce_user_dir 重定向到虚空地址
        cfg = json.loads(q1.read_text(encoding="utf-8"))
        cfg["input_dir"] = {"user_dir": {"path": None}}
        q1.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        try:
            ConfigLoader.load_from_file(str(q1))
        except ValueError:
            print("✓ user_dir 虚空地址 + ref → ValueError")
            return
        raise AssertionError("应对虚空地址 user_dir 的 ref 抛 ValueError,但未抛")


def test_no_ref_without_userdir_ok():
    """无 *_ref 时 user_dir 缺省合法(纯 agent 跑、评估用内联 rubrics)。"""
    with tempfile.TemporaryDirectory() as d:
        tc = Path(d) / "task_configs"
        tc.mkdir(parents=True, exist_ok=True)
        cfg = {
            "agents": [
                {"name": "assistant1", "system_prompt": None, "model": "m1"},
                {"name": "evaluator", "system_prompt": None, "model": "m2"},
            ],
            "queries": [
                {"agent_name": "assistant1", "text": "t", "use_simulator": True,
                 "evaluate": {"evaluator_agent": "evaluator", "rubrics": ["r1"]}}
            ],
        }
        q1 = tc / "q1.json"
        q1.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        loaded = ConfigLoader.load_from_file(str(q1))  # 不应抛
        ev = loaded.queries[0].evaluate
        assert ev.scoring_spec is not None  # 内联 rubrics 仍合成
    print("✓ 无 ref + 无 user_dir → 正常加载")


def test_data_root_subdir():
    """UserDirConfig.data_root_subdir():user_workspace 优先,否则回退 path 目录名。"""
    assert UserDirConfig(path="/x/task", user_workspace="user_files").data_root_subdir() == "user_files"
    assert UserDirConfig(path="/x/task").data_root_subdir() == "task"
    print("✓ data_root_subdir:user_workspace 优先 / 缺省回退同名")


def test_user_workspace_bulk_deploy():
    """bulk 模式:显式 data_subdir 指向的子目录内容被部署到 workspace;缺省回退同名子文件夹。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        # 显式 user_workspace = user_files
        udir = root / "udir"
        (udir / "user_files").mkdir(parents=True, exist_ok=True)
        (udir / "user_files" / "hello.txt").write_text("hi", encoding="utf-8")
        wm = WorkspaceManager(str(root / "ws"))
        wm.setup_agent_files(agent_name="a1", config_files=[], skill_base_dir=None,
                             agent_skills=[], user_dir=str(udir), data_subdir="user_files")
        ws = wm.get_agent_workspace("a1")
        assert (ws / "hello.txt").read_text(encoding="utf-8") == "hi"

        # 缺省回退同名子文件夹(udir/udir)
        (udir / "udir").mkdir(parents=True, exist_ok=True)
        (udir / "udir" / "def.txt").write_text("d", encoding="utf-8")
        wm.setup_agent_files(agent_name="a2", config_files=[], skill_base_dir=None,
                             agent_skills=[], user_dir=str(udir), data_subdir=None)
        ws2 = wm.get_agent_workspace("a2")
        assert (ws2 / "def.txt").read_text(encoding="utf-8") == "d"
    print("✓ user_workspace 显式数据根 + 缺省回退同名子文件夹")


if __name__ == "__main__":
    tests = [
        test_scoring_ref_resolved,
        test_no_scoring_ref_single_bucket_fallback,
        test_missing_scoring_ref_raises,
        test_ref_without_userdir_raises,
        test_ref_with_void_userdir_raises,
        test_no_ref_without_userdir_ok,
        test_data_root_subdir,
        test_user_workspace_bulk_deploy,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 项通过 ✓")
