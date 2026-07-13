"""assistant 系统提示词解析器 + auto_gen 配置校验单测(独立脚本,不依赖网关/LLM)。

覆盖:
1. resolve_system_prompt 三分支:config / default / auto_gen(mock gen_fn);
2. auto_gen 回退:gen_fn 抛异常 / 返回空 → 回退 base,来源保持 base 来源;
3. 配置校验(D7):evaluator agent 设 auto_gen_system_prompt=true → 校验期报错;
   仅作 assistant 时通过。

用法:
  cd <repo>
  python test/test_system_prompt.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError

from src.config import AutomationConfig
from src.system_prompt import (
    DEFAULT_SYSTEM_PROMPT,
    SOURCE_AUTO_GEN,
    SOURCE_CONFIG,
    SOURCE_DEFAULT,
    resolve_system_prompt,
)


class _AgentStub:
    def __init__(self, name="main", system_prompt=None, auto_gen_system_prompt=False):
        self.name = name
        self.system_prompt = system_prompt
        self.auto_gen_system_prompt = auto_gen_system_prompt


_passed = 0
_failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name}")


def test_resolver():
    print("== resolver 三分支 + 回退 ==")

    # 7.2 config:非空 system_prompt 原样返回,不调 gen_fn
    p, s = resolve_system_prompt(_AgentStub(system_prompt="ABC"), gen_fn=lambda b: "SHOULD_NOT_RUN")
    check("config 分支原样返回", p == "ABC" and s == SOURCE_CONFIG)

    # 7.3 default:空 system_prompt → 默认,不调 gen_fn
    p, s = resolve_system_prompt(_AgentStub(system_prompt=""), gen_fn=lambda b: "SHOULD_NOT_RUN")
    check("default 分支用内置默认", p == DEFAULT_SYSTEM_PROMPT and s == SOURCE_DEFAULT)

    # 7.1 auto_gen:以 base 改写
    seen = {}

    def gen_ok(base):
        seen["base"] = base
        return "  VARIANT  "

    p, s = resolve_system_prompt(
        _AgentStub(system_prompt="BASE", auto_gen_system_prompt=True), gen_fn=gen_ok
    )
    check("auto_gen 用变体且 strip", p == "VARIANT" and s == SOURCE_AUTO_GEN)
    check("auto_gen 以配置 system_prompt 为 base", seen.get("base") == "BASE")

    # auto_gen 但 system_prompt 空 → base=默认
    p, s = resolve_system_prompt(
        _AgentStub(system_prompt="", auto_gen_system_prompt=True), gen_fn=lambda b: "V2"
    )
    check("auto_gen 空 system_prompt 用默认作 base(结果为变体)", p == "V2" and s == SOURCE_AUTO_GEN)

    # 回退:gen_fn 抛异常 → base,来源保持
    def gen_boom(base):
        raise RuntimeError("boom")

    p, s = resolve_system_prompt(
        _AgentStub(system_prompt="BASE", auto_gen_system_prompt=True), gen_fn=gen_boom
    )
    check("auto_gen 异常回退 base(config)", p == "BASE" and s == SOURCE_CONFIG)

    # 回退:gen_fn 返回空 → base
    p, s = resolve_system_prompt(
        _AgentStub(system_prompt="", auto_gen_system_prompt=True), gen_fn=lambda b: "   "
    )
    check("auto_gen 空返回回退默认(default)", p == DEFAULT_SYSTEM_PROMPT and s == SOURCE_DEFAULT)

    # auto_gen 但无 gen_fn → base
    p, s = resolve_system_prompt(
        _AgentStub(system_prompt="BASE", auto_gen_system_prompt=True), gen_fn=None
    )
    check("auto_gen 无生成器回退 base", p == "BASE" and s == SOURCE_CONFIG)


def _base_cfg(agents):
    return {
        "harness_type": "openclaw",
        "agents": agents,
        "queries": [
            {
                "agent_name": "main",
                "text": "hello",
                "session_name": "s",
                "evaluate": {"agent_name": "evaluator", "eval_step": 1},
            }
        ],
    }


def test_config_validation():
    print("== 配置校验 D7 ==")

    # evaluator 开 auto_gen → 报错
    raised = False
    try:
        AutomationConfig(
            **_base_cfg(
                [
                    {"name": "main"},
                    {"name": "evaluator", "auto_gen_system_prompt": True},
                ]
            )
        )
    except ValidationError as e:
        raised = "evaluator" in str(e) and "auto_gen_system_prompt" in str(e)
    check("evaluator 开 auto_gen 校验期报错", raised)

    # assistant(main)开 auto_gen、evaluator 不开 → 通过
    ok = False
    try:
        cfg = AutomationConfig(
            **_base_cfg(
                [
                    {"name": "main", "auto_gen_system_prompt": True},
                    {"name": "evaluator"},
                ]
            )
        )
        ok = cfg.agents[0].auto_gen_system_prompt is True
    except ValidationError:
        ok = False
    check("仅 assistant 开 auto_gen 校验通过", ok)

    # 既有 config 不带该字段 → 默认 False,零影响
    cfg = AutomationConfig(**_base_cfg([{"name": "main"}, {"name": "evaluator"}]))
    check("缺省字段默认 False", cfg.agents[0].auto_gen_system_prompt is False)


def test_openclaw_soul_delivery():
    """OpenClaw SOUL.md 下发的防覆盖规则(design D4)。"""
    print("== OpenClaw SOUL.md 下发防覆盖 ==")
    import tempfile

    from src.openclaw_client import OpenclawAgentManager, OpenclawWorkspaceManager

    with tempfile.TemporaryDirectory() as tmp:
        wm = OpenclawWorkspaceManager(str(Path(tmp) / "ws"))
        mgr = OpenclawAgentManager(client=None, workspace_manager=wm)

        # config/auto_gen 显式意图:覆盖既有文件版 SOUL.md
        soul = wm.get_agent_workspace("main") / "SOUL.md"
        soul.write_text("FILE_VERSION", encoding="utf-8")
        mgr.deliver_system_prompt("main", "EXPLICIT", SOURCE_CONFIG)
        check("config 覆盖文件版 SOUL.md", soul.read_text(encoding="utf-8") == "EXPLICIT")

        mgr.deliver_system_prompt("main", "VARIANT", SOURCE_AUTO_GEN)
        check("auto_gen 覆盖 SOUL.md", soul.read_text(encoding="utf-8") == "VARIANT")

        # default 分支 + 已有 SOUL.md → 保留(不 clobber)
        soul.write_text("KEEP_ME", encoding="utf-8")
        mgr.deliver_system_prompt("main", DEFAULT_SYSTEM_PROMPT, SOURCE_DEFAULT)
        check("default 不覆盖既有 SOUL.md", soul.read_text(encoding="utf-8") == "KEEP_ME")

        # default 分支 + 无 SOUL.md → 写默认兜底
        soul2 = wm.get_agent_workspace("assistant2") / "SOUL.md"
        assert not soul2.exists()
        mgr.deliver_system_prompt("assistant2", DEFAULT_SYSTEM_PROMPT, SOURCE_DEFAULT)
        check("default 无 SOUL.md 时写默认", soul2.exists() and soul2.read_text(encoding="utf-8") == DEFAULT_SYSTEM_PROMPT)


def test_deliver_stores_prompt():
    """CC / Hermes 的 deliver_system_prompt 把 prompt 收进 manager.system_prompts。

    这两家的 client 模块依赖各自 SDK(claude_agent_sdk / hermes),openclaw 镜像未装 →
    缺依赖时优雅 SKIP(不代表失败),在装齐依赖的环境才实测。
    """
    print("== CC/Hermes deliver 收下 prompt ==")
    managers = []
    try:
        from src.claudecode_client import ClaudecodeAgentManager
        managers.append(("claudecode", ClaudecodeAgentManager))
    except ImportError as e:
        print(f"  [SKIP] claudecode 依赖缺失({e.name});deliver 逻辑与 hermes 同构")
    try:
        from src.hermes_client import HermesAgentManager
        managers.append(("hermes", HermesAgentManager))
    except ImportError as e:
        print(f"  [SKIP] hermes 依赖缺失({e.name})")

    for label, cls in managers:
        mgr = cls(client=None, workspace_manager=None)
        mgr.deliver_system_prompt("main", "PROMPT_X", SOURCE_AUTO_GEN)
        check(f"{label} deliver 存入 system_prompts", mgr.system_prompts.get("main") == "PROMPT_X")


if __name__ == "__main__":
    test_resolver()
    test_config_validation()
    test_openclaw_soul_delivery()
    test_deliver_stores_prompt()
    print(f"\n结果: {_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)
