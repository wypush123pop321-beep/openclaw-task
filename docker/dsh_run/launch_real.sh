#!/bin/bash
# 宿主启动器:跑【stage_last10k 真实任务】的 DSH 多轮验证。
# 挂载 0819_dsh_adapter(/app,内含 run_root)、DSH 仓库、OUT;注入真 deepseek key + 带凭据公司代理。
# simulator(Python httpx)走 SIMULATOR_PROXY;DSH agent(Node fetch)走 NODE_USE_ENV_PROXY + HTTP(S)_PROXY。
set -eu

source ~/.bashrc 2>/dev/null || true

APP=/home/w00802407/workspace/harness_task_exec_pipeline/0819_dsh_adapter
DSH=/home/w00802407/workspace/0730_prometheus_agents/prometheus_agents/third_party/deepseek-harness
OUT=$APP/docker/dsh_run/out_real

: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY 未设置(检查 ~/.bashrc)}"
: "${https_proxy:?https_proxy 未设置(检查 ~/.bashrc)}"
DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"

mkdir -p "$OUT"

docker run --rm \
  -v "$APP":/app \
  -v "$DSH":"$DSH" \
  -v "$OUT":/out \
  -w /app \
  -e DEEPSEEK_BASE_URL="$DEEPSEEK_BASE_URL" \
  -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  -e DSH_CONFIG="$DSH/examples/jsonrpc-agent/minimal.nopty.cordis.yml" \
  -e NODE_USE_ENV_PROXY=1 \
  -e HTTP_PROXY="$https_proxy" -e HTTPS_PROXY="$https_proxy" \
  -e http_proxy="$https_proxy" -e https_proxy="$https_proxy" \
  -e SIMULATOR_PROXY="$https_proxy" \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  --entrypoint bash \
  openclaw-task:latest \
  /app/docker/dsh_run/run_real_in_container.sh
