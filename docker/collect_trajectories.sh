#!/usr/bin/env bash
# 把各任务已落盘的轨迹汇总到 docker/out/collected/taskNN_<session>.json，并打印摘要。
set -euo pipefail

# OUT_BASE 与 run_tasks.sh 一致：默认本脚本所在 repo 的 docker/out，可用环境变量覆盖
OUT_BASE="${OUT_BASE:-$(cd "$(dirname "$0")/.." && pwd)/docker/out}"
DST="$OUT_BASE/collected"
mkdir -p "$DST" 2>/dev/null || { sudo mkdir -p "$DST"; sudo chmod 777 "$DST"; }

n=0
for traj in "$OUT_BASE"/task*/logs/trajectories/*/*.json; do
    [ -e "$traj" ] || continue
    task=$(echo "$traj" | sed -E 's#.*/task([0-9]+)/.*#\1#')
    sess=$(basename "$traj" .json)
    cp "$traj" "$DST/task${task}_${sess}.json"
    n=$((n+1))
done
echo "已收集 $n 条轨迹 -> $DST"
[ "$n" -gt 0 ] && ls -la "$DST"

# 摘要（outcome / turns / evals / 每轮工具调用数）
python3 - "$DST" <<'PY'
import json, sys, glob, os
dst = sys.argv[1]
for f in sorted(glob.glob(os.path.join(dst, "*.json"))):
    try:
        d = json.load(open(f))
    except Exception as e:
        print(f"{os.path.basename(f)}: 解析失败 {e}"); continue
    turns = d.get("turns", [])
    tc = sum(len(t.get("tool_calls") or []) for t in turns)
    print(f"{os.path.basename(f)}: outcome={d.get('outcome')} turns={len(turns)} "
          f"evals={len(d.get('evaluations', []))} tool_calls={tc}")
PY
