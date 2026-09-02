# -*- coding: utf-8 -*-
"""汇总 WCX 验证批次最终结果到 outputs/_batch_summary.json。

从各任务 outputs/<任务>/ 读取:
- stats.json 的 best_completion(首个/最优评估)
- harness_trajectory.json 的 evaluations 最后一个 completion + inclination(最终评估)
生成 6 个验证任务的权威汇总表,供 recipe memory 与汇报使用。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"

# 验证批次 6 个任务(20010/20011/20020/20033/20037/20039)
DEFAULT_TASKS = [
    "wcx_wfx_r01_20010_zh_187e0034",
    "wcx_wfx_r01_20011_zh_63096185",
    "wcx_wfx_r01_20020_zh_3e9f5644",
    "wcx_wfx_r01_20033_zh_65302075",
    "wcx_wfx_r01_20037_zh_49f69777",
    "wcx_wfx_r01_20039_en_2639b094",
]


def read_task(task: str) -> dict:
    td = OUT / task
    row = {"task": task, "best_completion": None, "final_completion": None,
           "inclination": None, "evals": []}

    stats = td / "stats.json"
    if stats.exists():
        try:
            row["best_completion"] = json.loads(stats.read_text(encoding="utf-8")).get("best_completion")
        except Exception:
            pass

    traj = td / "harness_trajectory.json"
    if traj.exists():
        try:
            d = json.loads(traj.read_text(encoding="utf-8"))
            evs = d.get("evaluations", [])
            row["evals"] = [{"turn": e.get("turn"), "completion": e.get("completion"),
                             "inclination": e.get("inclination")} for e in evs]
            if evs:
                last = evs[-1]
                row["final_completion"] = last.get("completion")
                row["inclination"] = last.get("inclination")
        except Exception as e:
            row["error"] = str(e)
    else:
        row["missing_trajectory"] = True
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="汇总 WCX 验证批次结果")
    ap.add_argument("--tasks", nargs="*", default=None,
                    help="任务目录名(默认 6 个验证任务)")
    args = ap.parse_args()

    tasks = args.tasks or DEFAULT_TASKS
    rows = [read_task(t) for t in tasks]

    out_path = OUT / "_batch_summary.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n========== 汇总 → {out_path} ==========")
    print(f"{'任务':<42} {'best':>5} {'final':>5} {'倾向':>7}  轮次")
    for r in rows:
        ev = ",".join(f"{e['turn']}:{e['completion']}" for e in r["evals"])
        flag = "⚠无轨迹" if r.get("missing_trajectory") else ""
        print(f"{r['task']:<42} {str(r['best_completion']):>5} "
              f"{str(r['final_completion']):>5} {str(r['inclination'] or ''):>7}  {ev} {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
