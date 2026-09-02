# -*- coding: utf-8 -*-
"""批量跑任务:对每个任务串行执行「跑前清理 workspace → harness_automation.py → collect_task.py --clean 归档」。

背景:openclaw 共享 assistant1 workspace,必须串行且任务间清理防污染;产物靠 collect_task 归到
outputs/<任务名>/。本脚本把三步串起来,批量跑完输出汇总表 outputs/_batch_summary.json。

用法:
  python scripts/run_batch.py configs/wcx_260827/wcx_wfx_r01_10009_en_acc0ea68_q1.json \
                               configs/wcx_260827/wcx_wfx_r01_10010_zh_e05cd920_q1.json
  或 glob / 目录:
  python scripts/run_batch.py configs/wcx_260827/*.json
  python scripts/run_batch.py configs/wcx_260827
  (Windows cmd 不展开 glob,脚本内部用 glob 展开)

每个任务:
  1. 跑前清理 workspace 残留(data/ + 历史 html/产物脚本,防上次任务污染)
  2. python harness_automation.py --config <q1.json>(串行,实时输出)
  3. python scripts/collect_task.py <任务名> --clean(归档 + 清理)
全部完成后汇总各任务 completion 到 outputs/_batch_summary.json。
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK:打印 ✓/⚠/🧹 等非 ASCII 字符会抛 UnicodeEncodeError
# 崩掉整个批次(实测:harness 跑完、collect 归档前崩在 print ✓)。强制 UTF-8 + errors=replace。
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

# 加载本机私有凭据(gitignored configs/local.env;净化提交,真值不入库,见 local_env.py)
import local_env
local_env.load()

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
# 认证代理(净化默认占位;真值从 env/local.env 注入 —— WCX_PROXY 或 SIMULATOR_PROXY)
DEFAULT_PROXY = (os.environ.get("WCX_PROXY")
                 or os.environ.get("SIMULATOR_PROXY")
                 or "http://<user>:<pwd_urlencoded>@proxysg-spl.huawei.com:8080")
DEFAULT_TIMEOUT = 7200  # 单任务超时(秒)=2h,文件型任务常见 20-30min

# workspace 基础设施(跑前清理时排除,与 collect_task 一致)
_INFRA = {
    "AGENTS.md", "HEARTBEAT.md", "IDENTITY.md", "SOUL.md", "USER.md",
    "TOOLS.md", "README.md", "system_prompt.md", "evaluator_user_prompt.md",
    "openclaw_automation.py", "trajectory.py", "user_simulator.py",
    "evaluator.py", "requirements.txt", ".gitignore",
}
# 基础设施目录(跑前清理/归档时整目录保留);其余目录视为 agent 自建产物 → 递归清理/归档
_INFRA_DIRS = {".git", ".openclaw", "agents", "configs", "docs", "scripts",
               "skills", "test", "utils", "openspec", "nanobot", "memory",
               "temp_iccv_oral", "WideSearch", "_under_review"}
# 任务产物扩展名(agent 可能生成,根级/自建目录内都算)
_ART_SUFFIXES = {".html", ".json", ".py", ".png"}


def get_workspace(cfg_path: Path) -> Path:
    """从 config 解析执行 agent 的 workspace 路径(与 collect_task 同逻辑)。"""
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    primary = next((a["name"] for a in cfg.get("agents", [])
                    if a.get("name") != "evaluator"), "assistant1")
    ws_base = Path(cfg.get("workspace_base") or "").expanduser()
    if primary != "main":
        return ws_base.parent / f"{ws_base.name}-{primary}"
    return ws_base


def clean_workspace(ws: Path) -> list[str]:
    """清理 workspace 任务残留,保留基础设施。

    清除范围:
    - data/ 部署目录
    - 根级任务产物文件(_ART_SUFFIXES,排除 _INFRA 基础设施文件)
    - 不在 _INFRA_DIRS 的自建产物目录(如 reports/、中文报告目录)整目录递归删除
    """
    removed: list[str] = []
    if not ws.is_dir():
        return removed
    data_dir = ws / "data"
    if data_dir.is_dir():
        try:
            shutil.rmtree(data_dir)
            removed.append("data/")
        except PermissionError as e:
            # 残留 http.server 等进程锁文件时容错:不崩,跳过清理,部署会覆盖
            print(f"⚠️ data/ 清理被占用(文件锁),跳过该项: {e}")
    for item in ws.iterdir():
        if item.name in _INFRA:
            continue
        if item.is_dir():
            if item.name in _INFRA_DIRS:
                continue
            try:
                shutil.rmtree(item)
                removed.append(f"{item.name}/")
            except PermissionError as e:
                print(f"⚠️ {item.name}/ 清理被占用(文件锁),跳过该项: {e}")
        else:
            if item.suffix.lower() in _ART_SUFFIXES:
                try:
                    item.unlink()
                    removed.append(item.name)
                except PermissionError as e:
                    print(f"⚠️ {item.name} 删除被占用,跳过该项: {e}")
    return removed


def expand_configs(patterns: list[str]) -> list[str]:
    """展开 config 路径:支持绝对/相对路径、glob(*?)、目录(扫描 *.json)、configs/ 下递归名匹配。"""
    files: list[str] = []
    for pat in patterns:
        p = Path(pat)
        if "*" in pat or "?" in pat:
            files += glob.glob(str(ROOT / pat))
        elif p.is_absolute() and p.exists():
            files.append(str(p))
        elif (ROOT / p).exists():
            if (ROOT / p).is_dir():
                files += [str(x) for x in sorted((ROOT / p).glob("*.json"))]
            else:
                files.append(str(ROOT / p))
        elif (ROOT / "configs" / pat).exists():
            files.append(str(ROOT / "configs" / pat))
        else:
            hits = [str(h) for h in (ROOT / "configs").rglob(p.name)]
            files += hits if hits else []
            if not hits:
                print(f"✗ 找不到: {pat}")
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for f in sorted(files):
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def run_harness(cfg_path: str, proxy: str, timeout: int) -> int:
    """跑 harness_automation.py,实时输出;返回 exit code(timeout/异常→-1)。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", SIMULATOR_PROXY=proxy)
    cmd = [sys.executable, str(ROOT / "harness_automation.py"), "--config", str(cfg_path)]
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=env, timeout=timeout)
        return r.returncode
    except subprocess.TimeoutExpired:
        print(f"✗ 任务超时(>{timeout}s),已终止")
        return -1


def read_completion(task_dir: Path) -> dict:
    """从归档读 completion:stats.json 的 best_completion + 轨迹的最终 completion/accept。"""
    result = {"best_completion": None, "final_completion": None, "inclination": None}
    stats = task_dir / "stats.json"
    if stats.exists():
        try:
            d = json.loads(stats.read_text(encoding="utf-8"))
            result["best_completion"] = d.get("best_completion")
        except Exception:
            pass
    traj = task_dir / "harness_trajectory.json"
    if traj.exists():
        try:
            d = json.loads(traj.read_text(encoding="utf-8"))
            evs = d.get("evaluations", [])
            if evs:
                last = evs[-1]
                result["final_completion"] = last.get("completion")
                result["inclination"] = last.get("inclination")
        except Exception:
            pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="批量跑任务并归档")
    ap.add_argument("configs", nargs="+", help="config 路径/glob/目录(支持通配符)")
    ap.add_argument("--simulator-proxy", default=os.environ.get("SIMULATOR_PROXY", DEFAULT_PROXY))
    ap.add_argument("--no-clean-first", action="store_true", help="跳过每任务跑前清理")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单任务超时秒数")
    args = ap.parse_args()

    files = expand_configs(args.configs)
    if not files:
        print("没有可跑的任务,退出")
        return 1
    print(f"共 {len(files)} 个任务,串行执行:\n  " + "\n  ".join(Path(f).stem for f in files))

    env = dict(os.environ, PYTHONIOENCODING="utf-8", SIMULATOR_PROXY=args.simulator_proxy)
    summary = []

    for i, cfg in enumerate(files, 1):
        cfg_path = Path(cfg)
        # collect_task 归档目录是去掉 _q1 的任务名(与 config stem 区分)
        stem = cfg_path.stem.removesuffix("_q1")
        print(f"\n========== [{i}/{len(files)}] {stem} ==========")

        # 1. 跑前清理
        if not args.no_clean_first:
            ws = get_workspace(cfg_path)
            removed = clean_workspace(ws)
            if removed:
                print(f"🧹 跑前清理 workspace: {', '.join(removed)}")

        # 2. 跑 harness
        rc = run_harness(cfg, args.simulator_proxy, args.timeout)
        ok = rc == 0
        print(f"harness exit={rc} {'✓' if ok else '✗'}")

        # 3. 归档(即使 harness 失败也收集,便于复盘)
        # Windows 默认用 GBK 解码子进程 stdout,collect_task 输出 UTF-8 中文会崩
        # (_readerthread UnicodeDecodeError)→ 显式 utf-8 + errors=replace
        coll = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "collect_task.py"), stem, "--clean"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300)
        if coll.stdout:
            print(coll.stdout.rstrip())
        if coll.returncode != 0:
            # collect 失败不静默:打印 stderr,便于定位(如 parse_run_id 失败/递归清理异常)
            print(f"⚠ collect 归档失败(exit={coll.returncode}):")
            if coll.stderr:
                print(coll.stderr.rstrip()[-2000:])

        comp = read_completion(OUT / stem)
        summary.append({"task": stem, "harness_exit": rc, **comp})

    # 汇总
    out_path = OUT / "_batch_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n========== 汇总 → {out_path} ==========")
    print(f"{'任务':<48} {'exit':>4} {'best':>5} {'final':>5} {'倾向':>7}")
    for s in summary:
        print(f"{s['task']:<48} {str(s['harness_exit']):>4} "
              f"{'' if s['best_completion'] is None else str(s['best_completion']):>5} "
              f"{'' if s['final_completion'] is None else str(s['final_completion']):>5} "
              f"{str(s['inclination'] or ''):>7}")
    fails = [s for s in summary if s["harness_exit"] != 0]
    if fails:
        print(f"\n⚠ {len(fails)} 个任务失败: {', '.join(s['task'] for s in fails)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
