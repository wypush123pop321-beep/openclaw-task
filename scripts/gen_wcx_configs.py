# -*- coding: utf-8 -*-
"""WCX2K_WIN_WITHFILES delivery 配置生成：文件部署型(with_files)。

与 query-only 批次(gen_allrub_configs.py)的关键差异:
- map_file=MAP_Windows.json(非空): user_files/data/* -> ~/data/* (~=agent workspace)
- user_workspace 不设(None): content_root 默认回退 path/<basename> == 同名嵌套目录(交付结构正好命中),
  MAP 从嵌套目录读源文件;部署目标是 C:\\...\\workspace-<agent>\\data\\
- evaluate 无 eval_step(默认1)/无 oracle_ref
- custom_rubrics 的 formula 已是 str(脚本仍做归一化保险)
"""

import json
import os
from pathlib import Path

# 加载本机私有凭据(gitignored configs/local.env;净化提交,真值不入库,见 local_env.py)
import local_env
local_env.load()

# 环境变量可覆盖(供 oneclick_run.sh 传自定义交付根/config 输出目录):
BASE = Path(os.environ.get("WCX_DELIV_ROOT",
    r"D:\Users\w00802407\0616-work\trae_workspace\deliveries_260827")) / "environments"
OUT = Path(os.environ.get("WCX_CONFIG_DIR",
    r"D:\Users\w00802407\0616-work\trae_workspace\openclaw-task-main\configs\wcx_260827"))
GATEWAY = os.environ.get("WCX_GATEWAY", "ws://127.0.0.1:18789/gateway")
API_KEY = os.environ.get(
    "WCX_GATEWAY_TOKEN", "<gateway-token: 见 configs/local.env>")
WORKSPACE = r"C:\Users\w00802407\.openclaw\workspace"
SIM_CFG = r"D:\Users\w00802407\0616-work\trae_workspace\openclaw-task-main\configs\user_proxy_model.json"

TASKS = [
    "wcx_wfx_r01_20010_zh_187e0034",
    "wcx_wfx_r01_20011_zh_63096185",
    "wcx_wfx_r01_20020_zh_3e9f5644",
    "wcx_wfx_r01_20033_zh_65302075",
    "wcx_wfx_r01_20037_zh_49f69777",
    "wcx_wfx_r01_20039_en_2639b094",
]


def normalize_formula(r: dict) -> dict:
    """formula dict/list → JSON 字符串(本批次已是 str,保险处理)。"""
    r = dict(r)
    if isinstance(r.get("formula"), (dict, list)):
        r["formula"] = json.dumps(r["formula"], ensure_ascii=False)
    return r


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="WCX2K delivery 配置生成")
    ap.add_argument("--tasks", nargs="*", default=None,
                    help="覆盖 TASKS 列表;不给且 WCX_PENDING 环境变量存在时读该清单(逐行任务名)")
    args = ap.parse_args()
    pending = os.environ.get("WCX_PENDING")
    if args.tasks is None and pending:
        tasks = [l.strip() for l in Path(pending).read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        tasks = args.tasks or TASKS
    OUT.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        env = BASE / t
        if not env.is_dir():
            print(f"✗ 环境目录不存在: {env}")
            continue
        uq = json.loads((env / "user_queries.json").read_text(encoding="utf-8"))
        item = uq[0]
        ev0 = item["evaluate"][0]

        # 归一化副本(写环境目录根;MAP 部署从同名嵌套目录读 user_files,不会带上副本)
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
                    "map_file": "MAP_Windows.json",   # 非空映射:部署 user_files 到 workspace
                    "profile_file": "user_profile.json",
                    # user_workspace 不设(None):content_root 回退同名嵌套目录,正好命中交付结构
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
        print(f"✓ {out.name}")


if __name__ == "__main__":
    main()
