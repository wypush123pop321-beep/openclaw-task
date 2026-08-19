#!/bin/bash
# 宿主机启动器:拉起 openclaw-task 容器,挂载 0819_dsh_adapter(/app)、_run_main_main、DSH 仓库,
# 注入真 API key + 带凭据的公司代理(Node fetch 必须 NODE_USE_ENV_PROXY=1),跑 3 个 DSH 任务。
set -eu

source ~/.bashrc 2>/dev/null || true

APP=/home/w00802407/workspace/harness_task_exec_pipeline/0819_dsh_adapter
RM=/home/w00802407/workspace/harness_task_exec_pipeline/_run_main_main
DSH=/home/w00802407/workspace/0730_prometheus_agents/prometheus_agents/third_party/deepseek-harness
OUT=$APP/docker/dsh_run/out

: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY 未设置(检查 ~/.bashrc)}"
: "${https_proxy:?https_proxy 未设置(检查 ~/.bashrc)}"

DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"

mkdir -p "$OUT"

docker run --rm \
  -v "$APP":/app \
  -v "$RM":/run_main_main \
  -v "$DSH":"$DSH" \
  -v "$OUT":/out \
  -w /app \
  -e DEEPSEEK_BASE_URL="$DEEPSEEK_BASE_URL" \
  -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  -e DSH_MODEL=deepseek-v4-flash \
  -e DSH_CONFIG="$DSH/examples/jsonrpc-agent/minimal.nopty.cordis.yml" \
  -e NODE_USE_ENV_PROXY=1 \
  -e HTTP_PROXY="$https_proxy" -e HTTPS_PROXY="$https_proxy" \
  -e http_proxy="$https_proxy" -e https_proxy="$https_proxy" \
  --entrypoint bash \
  openclaw-task:latest \
  /app/docker/dsh_run/run_in_container.sh
