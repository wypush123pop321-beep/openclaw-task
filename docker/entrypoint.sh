#!/usr/bin/env bash
# 沙箱容器入口（repo 解耦版）：
#   - 环境层资产（网关配置/identity/serper/key/entrypoint）烧在镜像 /opt/kit；
#   - 目标 workspace 的 harness repo 运行时挂载到 /app（不同版本随便换）。
# 流程：播种 ~/.openclaw → 起 openclaw 网关 → 等 health → 跑挂载 repo 的 harness。
set -euo pipefail

GW_PORT="${GW_PORT:-18789}"
GW_HEALTH="http://127.0.0.1:${GW_PORT}/health"
KIT="/opt/kit"
OC_DIR="${HOME:-/root}/.openclaw"
LOG_DIR="/app/logs"
GW_LOG="${LOG_DIR}/gateway.log"

if [ ! -f /app/harness_automation.py ]; then
    echo "[entrypoint] 错误: /app 下没有 harness_automation.py。" >&2
    echo "[entrypoint] 请把目标 workspace 的 repo 挂载到 /app（run_tasks.sh --repo <path>）。" >&2
    exit 2
fi

mkdir -p "${LOG_DIR}" "${OC_DIR}/identity"

# 1) 播种网关配置 + device identity（来自镜像 /opt/kit，每容器独立可写副本）
if [ ! -f "${OC_DIR}/openclaw.json" ]; then
    cp "${KIT}/openclaw.json" "${OC_DIR}/openclaw.json"
    echo "[entrypoint] 网关配置就绪: ${OC_DIR}/openclaw.json"
fi
if [ ! -f "${OC_DIR}/identity/device.json" ] && [ -d "${KIT}/identity" ]; then
    cp "${KIT}/identity"/* "${OC_DIR}/identity/" 2>/dev/null || true
    echo "[entrypoint] device identity 就绪: ${OC_DIR}/identity"
fi

# 2) 后台起网关
echo "[entrypoint] 启动 openclaw 网关 (port=${GW_PORT}) ..."
openclaw gateway run --port "${GW_PORT}" --bind loopback --allow-unconfigured \
    > "${GW_LOG}" 2>&1 &
GW_PID=$!
cleanup() { kill "${GW_PID}" 2>/dev/null || true; wait "${GW_PID}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# 3) 等 health（最多 90s）
echo "[entrypoint] 等待网关 health: ${GW_HEALTH}"
READY=0
for i in $(seq 1 90); do
    kill -0 "${GW_PID}" 2>/dev/null || { echo "[entrypoint] 网关退出，日志："; tail -n 40 "${GW_LOG}"; exit 1; }
    if curl -fsS "${GW_HEALTH}" >/dev/null 2>&1; then READY=1; echo "[entrypoint] 网关 ready（${i}s）"; break; fi
    sleep 1
done
[ "${READY}" -eq 1 ] || { echo "[entrypoint] 等待网关超时，日志："; tail -n 40 "${GW_LOG}"; exit 1; }

# 4) 跑 harness（kit 版 entrypoint.py 负责 patch 挂载 repo 的 config + 注入 serper）
echo "[entrypoint] 启动 harness (repo=/app) ..."
python "${KIT}/entrypoint.py"
RC=$?
echo "[entrypoint] harness 退出码=${RC}"
exit "${RC}"
