#!/bin/bash
# 在 openclaw-task 容器内顺序跑 3 个 DSH 任务(单轮、真 API)。
# 每个任务:清空 agent workspace → 跑 harness_automation(harness=dsh)→ 归档产物到 /out/<slug>。
set -u

CFGDIR=/app/docker/dsh_run/configs
OUT=/out
WS=/root/.dsh/workspace-assistant1

SLUGS="dsh_pong dsh_starfield dsh_reaction"

for slug in $SLUGS; do
  echo "########## RUN ${slug} ##########"
  rm -rf "$WS"; mkdir -p "$WS"
  mkdir -p "$OUT/$slug/workspace"
  python3 /app/harness_automation.py \
      --config "$CFGDIR/$slug.json" --harness dsh \
      --traj_stats_result "$OUT/$slug/traj_stats.json" 2>&1 | tee "$OUT/$slug/run.log"
  echo "---- workspace files for ${slug} ----"
  ls -la "$WS" || true
  cp -r "$WS"/. "$OUT/$slug/workspace/" 2>/dev/null || true
  # PASS 判定:workspace 里有非空 index.html
  if [ -s "$WS/index.html" ]; then
    echo "RESULT ${slug}: PASS (index.html $(wc -c < "$WS/index.html") bytes)"
  else
    echo "RESULT ${slug}: NO_INDEX_HTML"
  fi
  echo "########## DONE ${slug} ##########"
done
echo "ALL_DSH_TASKS_DONE"
