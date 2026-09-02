# -*- coding: utf-8 -*-
"""任务产物归档脚本:把一次运行的 agent session / HTML 工件 / harness 轨迹 / log 归到 outputs/<任务名>/。

背景:openclaw 的 agent 按名去重且 workspace 只在首次创建时绑定,无法按任务隔离
(C:\\Users\\w00802407\\.openclaw\\workspace-assistant1 全任务共享);session jsonl 文件名是
UUID、agent 名固定(main/evaluator),单个任务肉眼无法辨识。本脚本以**任务名为目录**收集归档,
解决大批量跑后的整理问题。

不依赖 logs/traj_stats_result.json(单文件,批量跑会被后一个任务覆盖),而是从
logs/<task>_q1.log 的「轨迹已落盘」行解析 run_id,再精确定位:
  - harness 轨迹: logs/trajectories/<run_id>/q1.json
  - agent session: .openclaw/agents/<agent>/sessions/*.jsonl 中 key 含 q1_<run_id>
  - 任务工件:    workspace-assistant1 根级 *.html + data/ 部署目录 + 任务窗口内的产物脚本

用法:
  python scripts/collect_task.py <任务名> [--clean]
  任务名 = config 文件名 stem,如 wcx_wfx_r01_10010_zh_e05cd920_q1
  --clean:归档后清理 workspace 里的任务残留(html/data/产物脚本),防任务间污染
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# Windows 控制台默认 GBK:打印 ✓/🗑 等非 ASCII 字符会抛 UnicodeEncodeError。强制 UTF-8。
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
TRAJ_DIR = LOGS / "trajectories"
OUT_DIR = ROOT / "outputs"

# workspace 基础设施(非任务产物),归档时排除
_INFRA = {
    "AGENTS.md", "HEARTBEAT.md", "IDENTITY.md", "SOUL.md", "USER.md",
    "TOOLS.md", "README.md", "system_prompt.md", "evaluator_user_prompt.md",
    "openclaw_automation.py", "trajectory.py", "user_simulator.py",
    "evaluator.py", "requirements.txt", ".gitignore",
}
# 基础设施目录(整目录保留);其余目录视为 agent 自建产物 → 递归归档/清理
_INFRA_DIRS = {".git", ".openclaw", "agents", "configs", "docs", "scripts",
               "skills", "test", "utils", "openspec", "nanobot", "memory",
               "temp_iccv_oral", "WideSearch", "_under_review"}
# 任务产物扩展名
_ART_SUFFIXES = {".html", ".json", ".py", ".png"}


def load_config(task_stem: str) -> dict:
    """从 configs/ 找 <task_stem>.json 或 <task_stem>_q1.json,返回原始 dict。"""
    for name in (f"{task_stem}.json", f"{task_stem}_q1.json"):
        p = ROOT / "configs" / name
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    # 递归找 configs 下匹配
    for p in (ROOT / "configs").rglob("*.json"):
        if p.stem == task_stem or p.stem == task_stem + "_q1":
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"configs/ 下找不到 {task_stem}.json 或 {task_stem}_q1.json")


def parse_run_id_from_log(log_path: Path) -> str:
    """从 harness log 的「轨迹已落盘: logs/trajectories/<run_id>/q1.json」解析 run_id。

    取**最后一条**落盘记录(最新一次运行):日志文件可能被孤儿进程/重复运行污染,
    混入多条轨迹落盘行(实测 20037 混入 212424 与 213511 两条),取首个会归档错轨迹。
    """
    if not log_path.exists():
        raise FileNotFoundError(f"harness log 不存在: {log_path}")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"轨迹已落盘[:：]\s*(?:logs[/\\\\])?trajectories[/\\\\]([^/\\\\]+)[/\\\\]q1\.json", text)
    if matches:
        return matches[-1]
    # 兜底:取最后出现的时间戳 run
    m2 = re.findall(r"logs[/\\\\]trajectories[/\\\\]([^/\\\\\\s]+)", text)
    if not m2:
        raise RuntimeError(f"log 里找不到 run_id: {log_path.name}")
    return m2[-1]


def find_agent_session(agents_dir: Path, agent_name: str, run_id: str) -> Path | None:
    """定位 .openclaw/agents/<agent>/sessions/ 下属于该 run 的 session jsonl。

    优先读 sessions.json(key 形如 agent:<name>:q1_<runid> / eval_q1_<runid>,含 run_id);
    缺失时回退用 jsonl 首行 timestamp(UTC)匹配 run_id(本地),±1h 取最近者。
    """
    import datetime as _dt
    sess_dir = agents_dir / agent_name / "sessions"
    if not sess_dir.is_dir():
        return None

    # 优先:sessions.json 的 key 含 run_id
    idx = sess_dir / "sessions.json"
    if idx.exists():
        try:
            idx_data = json.loads(idx.read_text(encoding="utf-8"))
            if isinstance(idx_data, dict):
                needle = run_id.lower()
                for key, info in idx_data.items():
                    if needle in str(key).lower():
                        sf = info.get("sessionFile") if isinstance(info, dict) else None
                        if sf and Path(sf).exists():
                            return Path(sf)
        except Exception:
            pass

    # 回退:首行 timestamp 窗口匹配
    try:
        run_epoch = _dt.datetime.strptime(run_id, "%Y%m%dT%H%M%S").timestamp()
    except ValueError:
        return None
    best, best_gap = None, None
    for jf in sess_dir.glob("*.jsonl"):
        if ".deleted." in jf.name or ".trajectory" in jf.name or jf.name == "sessions.json":
            continue
        try:
            with open(jf, encoding="utf-8") as f:
                first = json.loads(f.readline())
            ts_str = str(first.get("timestamp", ""))
            if not ts_str or "T" not in ts_str:
                continue
            ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            gap = abs(ts.timestamp() - run_epoch)
            if gap < 3600 and (best_gap is None or gap < best_gap):
                best, best_gap = jf, gap
        except Exception:
            continue
    return best


def collect_artifacts(ws: Path, run_start_ts: float, out_art: Path) -> list[str]:
    """收集 workspace 任务产物到 artifacts/。

    覆盖:
    - data/ 部署目录(整目录复制)
    - 根级任务产物文件(_ART_SUFFIXES,mtime 窗口内)
    - 不在 _INFRA_DIRS 的自建产物目录(如 reports/、中文报告目录):mtime 窗口内的
      文件递归复制,保留相对目录结构
    """
    collected: list[str] = []
    run_end_ts = run_start_ts + 8 * 3600
    out_art.mkdir(parents=True, exist_ok=True)

    def _in_window(f: Path) -> bool:
        return run_start_ts <= f.stat().st_mtime <= run_end_ts

    def _copy(src: Path, rel: str) -> None:
        dst = out_art / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # data/ 部署目录(整目录复制;仅当目录内文件在窗口内)
    data_dir = ws / "data"
    if data_dir.is_dir():
        files = [f for f in data_dir.iterdir() if f.is_file()]
        if files and all(_in_window(f) for f in files):
            dst = out_art / "data"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(data_dir, dst)
            collected.append("data/")

    for item in ws.iterdir():
        if item.name in _INFRA or item.name == "data":
            continue
        if item.is_dir():
            if item.name in _INFRA_DIRS:
                continue
            # 自建产物目录:窗口内文件递归收集
            hits = [f for f in item.rglob("*") if f.is_file() and _in_window(f)]
            if hits:
                for f in hits:
                    _copy(f, f"{item.name}/{f.relative_to(item)}")
                collected.append(f"{item.name}/")
        else:
            if not _in_window(item):
                continue
            if item.suffix.lower() in _ART_SUFFIXES:
                _copy(item, item.name)
                collected.append(item.name)
    return collected


def main() -> None:
    ap = argparse.ArgumentParser(description="归档一次任务的产物到 outputs/<任务名>/")
    ap.add_argument("task", help="config 文件名 stem,如 wcx_wfx_r01_10010_zh_e05cd920_q1")
    ap.add_argument("--clean", action="store_true", help="归档后清理 workspace 任务残留")
    args = ap.parse_args()

    task_stem = args.task.removesuffix("_q1") if args.task.endswith("_q1") else args.task
    cfg = load_config(task_stem)

    # 主 agent 名(config 里第一个非 evaluator 的执行 agent)
    agents = cfg.get("agents", [])
    primary = next((a["name"] for a in agents if a.get("name") != "evaluator"), "assistant1")

    # workspace 基址
    ws_base = Path(cfg.get("workspace_base") or "").expanduser()
    if not ws_base.is_absolute():
        ws_base = Path.home() / ".openclaw" / "workspace"
    ws = (ws_base.parent / f"{ws_base.name}-{primary}") if primary != "main" else ws_base

    harness_home = Path.home() / ".openclaw"
    agents_dir = harness_home / "agents"

    log_path = LOGS / f"{task_stem}_q1.log"
    run_id = parse_run_id_from_log(log_path)
    # run_id 形如 20260827T235223 → 解析为任务开始时间戳(用于工件 mtime 窗口)
    run_start_ts = 0.0
    try:
        import datetime as _dt
        run_start_ts = _dt.datetime.strptime(run_id, "%Y%m%dT%H%M%S").timestamp()
    except ValueError:
        pass

    out = OUT_DIR / task_stem
    out.mkdir(parents=True, exist_ok=True)

    # 1. harness 轨迹
    traj_src = TRAJ_DIR / run_id / "q1.json"
    if traj_src.exists():
        shutil.copy2(traj_src, out / "harness_trajectory.json")
        print(f"✓ harness_trajectory.json ({traj_src.stat().st_size//1024} KB)")

    # 2. harness log
    if log_path.exists():
        shutil.copy2(log_path, out / "harness.log")
        print(f"✓ harness.log")

    # 3. stats 快照 + 当前任务检测(traj_stats_result 是单文件,仅当 task 匹配才算刚跑完)
    stats = ROOT / "logs" / "traj_stats_result.json"
    is_current = False
    if stats.exists():
        try:
            sd = json.loads(stats.read_text(encoding="utf-8"))
            if sd.get("task") in (task_stem, task_stem + "_q1"):
                is_current = True
                shutil.copy2(stats, out / "stats.json")
                print(f"✓ stats.json (completion={sd.get('best_completion')})")
        except Exception:
            pass
    if not is_current:
        print("⚠ 历史补收集:traj_stats_result 已被后续任务覆盖,")
        print("  workspace 工件(html/data)可能混入后续任务的文件,请以 harness_trajectory.json 为准。")

    # 4. agent session:收集 config 里所有执行/评估 agent(primary 存 agent_session.jsonl,其余存 <name>_session.jsonl)
    agent_names = [a.get("name") for a in cfg.get("agents", []) if a.get("name")]
    for q in cfg.get("queries", []):
        ev = q.get("evaluate") or {}
        if ev.get("agent_name"):
            agent_names.append(ev["agent_name"])
    # 去重保序,primary 排最前
    agent_names = list(dict.fromkeys(agent_names))
    for name in agent_names:
        sess = find_agent_session(agents_dir, name, run_id)
        fname = "agent_session.jsonl" if name == primary else f"{name}_session.jsonl"
        if sess:
            shutil.copy2(sess, out / fname)
            print(f"✓ {fname} ({sess.stat().st_size//1024} KB) [{name}]")
        else:
            print(f"⚠ 未找到 {name} 的 session jsonl (run_id={run_id})")

    # 5. 任务工件
    arts = collect_artifacts(ws, run_start_ts, out / "artifacts")
    if arts:
        print(f"✓ artifacts/: {', '.join(arts)}")
    else:
        print("⚠ 无任务工件")

    # 6. --clean:清理 workspace 任务残留(防共享 workspace 污染下一个任务)
    if args.clean:
        rm = []
        data_dir = ws / "data"
        if data_dir.is_dir():
            shutil.rmtree(data_dir); rm.append("data/")
        for item in ws.iterdir():
            if item.name in _INFRA:
                continue
            if item.is_dir():
                if item.name in _INFRA_DIRS:
                    continue
                shutil.rmtree(item); rm.append(f"{item.name}/")
            elif item.suffix.lower() in _ART_SUFFIXES:
                item.unlink(); rm.append(item.name)
        print(f"🗑 已清理 workspace: {', '.join(rm) if rm else '无'}")

    print(f"\n归档完成 → {out}")


if __name__ == "__main__":
    main()
