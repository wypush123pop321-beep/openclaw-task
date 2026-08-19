#!/bin/bash
# 容器内:用【stage_last10k 的真实任务配置】(未改写) 跑 DSH,多轮真 simulator(deepseek 扮演 user_profile 人设)。
# 每个任务:清空 agent workspace → cd run_root(让 config 里的相对路径 environments//configs/ 生效)
#   → 跑 harness_automation(--harness dsh 覆盖,use_simulator=true 走多轮)→ 归档 workspace + 日志。
# PASS 判定:日志出现 "任务完成(Turn"(simulator 发【Task_Done】→ outcome=done)。
set -u

ROOT=/app/docker/dsh_run/run_root
OUT=/out
WS=/root/.dsh/workspace-assistant1

# 运行期生成 simulator/evaluator 模型配置(deepseek,真 key 从 env 注入,不落库)
: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY 未设置}"
DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
cat > "$ROOT/configs/user_proxy_model.json" <<EOF
{
  "user_simulator": {
    "model": "deepseek-v4-flash",
    "base_url": "${DEEPSEEK_BASE_URL}",
    "api_key": "${DEEPSEEK_API_KEY}"
  }
}
EOF

cd "$ROOT"

PASS=0; TOTAL=0
for cfg in "$ROOT"/task_configs/*.json; do
  slug=$(basename "$cfg" .json)
  TOTAL=$((TOTAL+1))
  echo "########## RUN ${slug} ##########"
  rm -rf "$WS"; mkdir -p "$WS"
  mkdir -p "$OUT/$slug/workspace"
  python3 /app/harness_automation.py \
      --config "task_configs/$(basename "$cfg")" --harness dsh \
      --traj_stats_result "$OUT/$slug/traj_stats.json" 2>&1 | tee "$OUT/$slug/run.log"
  echo "---- workspace files for ${slug} ----"
  ls -la "$WS" || true
  cp -r "$WS"/. "$OUT/$slug/workspace/" 2>/dev/null || true
  # PASS 判定:多轮 simulator 判定任务完成
  if grep -q "任务完成(Turn" "$OUT/$slug/run.log"; then
    html=$(ls -S "$WS"/*.html 2>/dev/null | head -1)
    if [ -n "$html" ] && [ -s "$html" ]; then
      echo "RESULT ${slug}: PASS (Task_Done; deliverable $(basename "$html") $(wc -c < "$html") bytes)"
    else
      echo "RESULT ${slug}: PASS_NO_HTML (Task_Done but no .html deliverable)"
    fi
    PASS=$((PASS+1))
  else
    echo "RESULT ${slug}: FAIL (no Task_Done — outcome max_turn/failed)"
  fi
  echo "########## DONE ${slug} ##########"
done
echo "ALL_DSH_REAL_TASKS_DONE  PASS=${PASS}/${TOTAL}"

# 收尾:容器以 root 写出的产物(含 root 属主、0700 的 workspace/.sessions 轨迹目录)归还给宿主用户,
# 否则 host 侧 ls/cat 会 Permission denied。HOST_UID/HOST_GID 由 launch_real.sh 注入。
if [ -n "${HOST_UID:-}" ] && [ -n "${HOST_GID:-}" ]; then
  chown -R "${HOST_UID}:${HOST_GID}" "$OUT" 2>/dev/null || true
  echo "已将 $OUT 归属改为 ${HOST_UID}:${HOST_GID}(轨迹 .sessions 原地可读,位置不变)"
fi
