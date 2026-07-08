#!/usr/bin/env bash
# 汇总两类轨迹到 <OUT_BASE>/collected/：
#   1) harness 合成轨迹  : taskNN/logs/trajectories/<run_id>/*.json  → collected/taskNN_<session>.json
#   2) openclaw 原始轨迹 : taskNN/agents/<agent>/sessions/*.trajectory.jsonl（+ 会话日志 *.jsonl）
#                          → collected/raw/taskNN_<agent>_<sessionid>.trajectory.jsonl
set -euo pipefail

OUT_BASE="${OUT_BASE:-$(cd "$(dirname "$0")/.." && pwd)/docker/out}"
DST="$OUT_BASE/collected"
RAW="$DST/raw"
mkdir -p "$RAW" 2>/dev/null || { sudo mkdir -p "$RAW"; sudo chmod -R 777 "$DST"; }

# ── 1) harness 合成轨迹 ──
n=0
for traj in "$OUT_BASE"/task*/logs/trajectories/*/*.json; do
    [ -e "$traj" ] || continue
    task=$(echo "$traj" | sed -E 's#.*/task([0-9]+)/.*#\1#')
    sess=$(basename "$traj" .json)
    cp "$traj" "$DST/task${task}_${sess}.json"
    n=$((n+1))
done
echo "[harness 合成轨迹] 收集 $n 条 -> $DST"

# ── 2) openclaw 每 session 原始轨迹 + 会话日志 ──
r=0
for traj in "$OUT_BASE"/task*/agents/*/sessions/*.trajectory.jsonl; do
    [ -e "$traj" ] || continue
    task=$(echo "$traj" | sed -E 's#.*/task([0-9]+)/.*#\1#')
    agent=$(echo "$traj" | sed -E 's#.*/agents/([^/]+)/sessions/.*#\1#')
    sid=$(basename "$traj" .trajectory.jsonl)
    cp "$traj" "$RAW/task${task}_${agent}_${sid}.trajectory.jsonl"
    # 同名会话消息日志（若在）
    slog="$(dirname "$traj")/${sid}.jsonl"
    [ -f "$slog" ] && cp "$slog" "$RAW/task${task}_${agent}_${sid}.session.jsonl"
    r=$((r+1))
done
echo "[openclaw 原始轨迹] 收集 $r 条 -> $RAW"

# ── 摘要 ──
echo "=== 合成轨迹摘要 ==="
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
echo "=== 原始轨迹（行数=事件数）==="
for f in "$RAW"/*.trajectory.jsonl; do [ -e "$f" ] || continue; echo "$(wc -l <"$f") 行  $(basename "$f")"; done
