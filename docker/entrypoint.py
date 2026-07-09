#!/usr/bin/env python3
"""
容器入口（repo 解耦版）：patch 挂载进来的 harness repo 的 task_config，再跑 harness。

- 环境层资产烧在镜像 /opt/kit（entrypoint、网关配置、identity、serper、模型 key）。
- 目标 workspace 的 repo 运行时挂载到 /app —— 不同版本随便换，无需重建镜像。

本脚本做的事（都不改动挂载的 repo，产物写 /tmp）：
1. 定位任务配置（TASK 号或 CONFIG_FILE），兼容不同 repo 的 task_configs 布局。
2. evaluate.*_ref 相对路径 → 绝对路径。
3. simulator_config 强制指向 /opt/kit/user_proxy_model.json（带真实 key）。
4. 注入 serper-plus：把 /opt/kit/serper-plus + repo 原有 skills 汇集到 /tmp/skills，
   改 skill_dir 指向它，并给执行 agent 加上 serper-plus。
5. 写 /tmp/patched_config.json，调 /app/harness_automation.py（cwd=/app）。

环境变量：TASK / CONFIG_FILE / HARNESS / USER_MAX_TURN / QUERY_TIMEOUT /
          DISABLE_SERPER / GATEWAY_WS_URL / WORKSPACE_BASE / TASK_CONFIG_DIR
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/app")          # 运行时挂载的目标 repo
KIT = Path("/opt/kit")       # 镜像内烧死的环境层资产
TMP_SKILLS = Path("/tmp/skills")


def resolve_config_path() -> Path:
    explicit = os.environ.get("CONFIG_FILE")
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            sys.exit(f"[entrypoint] CONFIG_FILE 不存在: {p}")
        return p

    task = os.environ.get("TASK")
    if not task:
        sys.exit("[entrypoint] 必须设置 TASK（如 02）或 CONFIG_FILE")

    # 优先用显式 TASK_CONFIG_DIR；否则在挂载 repo 下搜 */task_configs/<TASK>_*.json
    search_dirs = []
    if os.environ.get("TASK_CONFIG_DIR"):
        search_dirs.append(Path(os.environ["TASK_CONFIG_DIR"]))
    matches = []
    for d in search_dirs:
        matches += sorted(d.glob(f"{task}_*.json"))
    if not matches:
        matches = sorted(ROOT.rglob(f"task_configs/{task}_*.json"))
    if not matches:
        sys.exit(f"[entrypoint] 在 {ROOT} 下未找到 TASK={task} 的 task 配置")
    if len(matches) > 1:
        print(f"[entrypoint] 警告: TASK={task} 命中多个，取第一个: {[m.name for m in matches]}")
    return matches[0]


def to_absolute_ref(ref: str, base: Path) -> str:
    if not ref:
        return ref
    file_part, sep, ptr = ref.partition("#")
    abs_file = (base / file_part).resolve()
    return f"{abs_file}#{ptr}" if sep else str(abs_file)


def inject_serper(data: dict) -> None:
    """把 serper-plus(来自 /opt/kit) + repo 原有 skills 汇集到 /tmp/skills，
    改 skill_dir 指向它，并给执行 agent 加 serper-plus。不改动挂载的 repo。"""
    src = KIT / "serper-plus"
    if not src.is_dir():
        print("[entrypoint] 警告: /opt/kit/serper-plus 缺失，跳过 serper 注入")
        return

    if TMP_SKILLS.exists():
        shutil.rmtree(TMP_SKILLS)
    TMP_SKILLS.mkdir(parents=True)

    # 保留 repo 原有 skill_dir 里的技能（若存在）
    orig = data.get("input_dir", {}).get("skill_dir")
    if orig:
        orig_path = (ROOT / orig)
        if orig_path.is_dir():
            for child in orig_path.iterdir():
                dst = TMP_SKILLS / child.name
                if child.is_dir():
                    shutil.copytree(child, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, dst)

    shutil.copytree(src, TMP_SKILLS / "serper-plus", dirs_exist_ok=True)

    data.setdefault("input_dir", {})["skill_dir"] = str(TMP_SKILLS)
    exec_agents = {q.get("agent_name") for q in data.get("queries", [])}
    for a in data.get("agents", []):
        if a.get("name") in exec_agents:
            skills = a.setdefault("skills", [])
            if "serper-plus" not in skills:
                skills.append("serper-plus")
    print(f"[entrypoint] serper-plus 已注入 (skill_dir={TMP_SKILLS}, agents={sorted(x for x in exec_agents if x)})")


def main() -> int:
    cfg_path = resolve_config_path()
    base = cfg_path.parent
    data = json.loads(cfg_path.read_text(encoding="utf-8"))

    # 1) evaluate.*_ref 相对 → 绝对
    for q in data.get("queries", []):
        ev = q.get("evaluate")
        if not ev:
            continue
        for key in ("rubrics_ref", "scoring_ref", "oracle_ref"):
            if ev.get(key):
                ev[key] = to_absolute_ref(ev[key], base)

    # 2) simulator/evaluator 模型配置：用 kit 里带真实 key 的那份
    kit_sim = KIT / "user_proxy_model.json"
    if kit_sim.is_file():
        data["simulator_config"] = str(kit_sim)

    # 3) serper 注入
    if os.environ.get("DISABLE_SERPER") != "1":
        inject_serper(data)

    # 4) 其它覆盖
    if os.environ.get("GATEWAY_WS_URL"):
        data["gateway_ws_url"] = os.environ["GATEWAY_WS_URL"]
    if os.environ.get("WORKSPACE_BASE"):
        data["workspace_base"] = os.environ["WORKSPACE_BASE"]
    if os.environ.get("USER_MAX_TURN"):
        data["user_max_turn"] = int(os.environ["USER_MAX_TURN"])
    if os.environ.get("QUERY_TIMEOUT"):
        qt = int(os.environ["QUERY_TIMEOUT"])
        for q in data.get("queries", []):
            q["timeout"] = qt

    patched = Path("/tmp/patched_config.json")
    patched.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    harness = os.environ.get("HARNESS", "openclaw")
    print(f"[entrypoint] repo(/app)  : {ROOT}")
    print(f"[entrypoint] task config : {cfg_path}")
    print(f"[entrypoint] harness     : {harness}")
    print(f"[entrypoint] simulator   : {data.get('simulator_config')}")
    print(f"[entrypoint] patched cfg : {patched}")
    sys.stdout.flush()

    cmd = [sys.executable, "harness_automation.py",
           "--harness", harness, "--config", str(patched)]
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
