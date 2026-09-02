# -*- coding: utf-8 -*-
"""从 ALLRUB delivery 环境目录生成 q1.json 配置 + 归一化 rubrics/scoring 副本。

关键点(对照 memory usersim-quality-batch-run-recipe / dailyclawbench-run-config-pitfalls):
- delivery 的 custom_rubrics 中 P_WEB 的 formula 是 dict,而 src.evaluator.evaluator.Rubric.formula
  是 Optional[str],直接引用会在 ConfigLoader 加载时抛 ValidationError → 归一化为 json 字符串。
- 空 MAP_Linux.json 作为 map_file(空映射)防止 bulk 复制把 user_queries.json 泄进 agent workspace。
- rubrics_ref/scoring_ref 指向 user_dir 下的归一化副本,file_vault 隔离/还原以副本为粒度。
"""

import json
import os
from pathlib import Path

# 加载本机私有凭据(gitignored configs/local.env;净化提交,真值不入库,见 local_env.py)
import local_env
local_env.load()

BASE = Path(r"D:\Users\w00802407\0616-work\trae_workspace\deliveries_260822\DELIVERY_20260821_ALLRUB10K_RUB\environments")
OUT = Path(r"D:\Users\w00802407\0616-work\trae_workspace\openclaw-task-main\configs\allrub_260822")
GATEWAY = "ws://127.0.0.1:18789/gateway"
API_KEY = os.environ.get("WCX_GATEWAY_TOKEN", "<gateway-token: 见 configs/local.env>")
WORKSPACE = r"C:\Users\w00802407\.openclaw\workspace"
SIM_CFG = r"D:\Users\w00802407\0616-work\trae_workspace\openclaw-task-main\configs\user_proxy_model.json"

TASKS = [
    "00001_投资助手_离婚财产分割规则_8084828a",
    "00002_基础信息获取_文件效力状态核验_1f50f1ed",
]


def normalize_formula(r: dict) -> dict:
    """formula dict/list → JSON 字符串(evaluator 无 program 执行器,formula 只喂 LLM 文本,无损)。"""
    r = dict(r)
    if isinstance(r.get("formula"), (dict, list)):
        r["formula"] = json.dumps(r["formula"], ensure_ascii=False)
    return r


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for t in TASKS:
        env = BASE / t
        if not env.is_dir():
            print(f"✗ 环境目录不存在: {env}")
            continue
        uq = json.loads((env / "user_queries.json").read_text(encoding="utf-8"))
        item = uq[0]
        ev0 = item["evaluate"][0]

        # 归一化副本(写入 user_dir,供 rubrics_ref/scoring_ref 引用)
        rubrics = [normalize_formula(r) for r in ev0["custom_rubrics"]]
        (env / "rubrics_normalized.json").write_text(
            json.dumps(rubrics, ensure_ascii=False, indent=2), encoding="utf-8")
        (env / "scoring.json").write_text(
            json.dumps(ev0["scoring"], ensure_ascii=False, indent=2), encoding="utf-8")

        config = {
            "harness_type": "openclaw",
            "system": {"platform": ["windows"], "python": "3.12", "tools": []},
            "input_dir": {
                "skill_dir": None,
                "agent_dir": None,
                "user_dir": {
                    "path": str(env),
                    # 空串 → content_root 拍平到 path 本身(环境目录无同名子目录),
                    # 否则默认回退 path/<basename> 不存在 + map_file → _setup_workspaces assert 失败。
                    "user_workspace": "",
                    "map_file": "MAP_Linux.json",
                    "profile_file": "user_profile.json",
                },
            },
            "agents": [
                {"name": "assistant1", "config": [], "skills": [],
                 "system_prompt": None, "model": "anthropic/glm-5.2"}
            ],
            "queries": [
                {
                    "agent_name": "assistant1",
                    "text": item["queries"][0],
                    "session_name": "q1",
                    "timeout": 3600,
                    "evaluate": {
                        "agent_name": "evaluator",
                        "eval_step": ev0["eval_step"],
                        "to_simulator": ev0.get("to_simulator", True),
                        "rubrics_ref": "rubrics_normalized.json",
                        "scoring_ref": "scoring.json",
                    },
                }
            ],
            "gateway_ws_url": GATEWAY,
            "api_key": API_KEY,
            "workspace_base": WORKSPACE,
            "simulator_config": SIM_CFG,
            "user_max_turn": 5,
        }
        out = OUT / f"{t}_q1.json"
        out.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ {out.name} (query={item['queries'][0][:30]}..., rubrics={len(rubrics)})")


if __name__ == "__main__":
    main()
