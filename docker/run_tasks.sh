#!/usr/bin/env bash
# 以沙箱形式并发启动任意数量的 dailyclawbench 任务（repo 解耦版）。
# 镜像只含「环境层」（openclaw 网关/依赖/配置/key/serper）；harness 代码来自 --repo 挂载，
# 所以换 workspace / 换 repo 版本只需换 --repo 路径，无需重建镜像。
#
# 用法：
#   run_tasks.sh --repo /path/to/workspace/openclaw-task 02 03 04
#   run_tasks.sh --repo /path/to/repo all
#   TASKS_DETACH=0 run_tasks.sh --repo /path/to/repo 02      # 前台跑单个
#   (在 repo 内直接跑可省略 --repo，默认取本脚本所在 repo)
#
# 可覆盖环境变量：IMAGE / OUT_BASE / USER_MAX_TURN / QUERY_TIMEOUT
set -euo pipefail

IMAGE="${IMAGE:-openclaw-task:latest}"
DETACH="${TASKS_DETACH:-1}"
USER_MAX_TURN="${USER_MAX_TURN:-3}"
QUERY_TIMEOUT="${QUERY_TIMEOUT:-600}"

# 默认 repo = 本脚本所在仓库根（docker/ 的上一级）
DEFAULT_REPO="$(cd "$(dirname "$0")/.." && pwd)"
REPO=""
TASKS=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        *) TASKS+=("$1"); shift ;;
    esac
done
REPO="${REPO:-$DEFAULT_REPO}"
REPO="$(cd "$REPO" && pwd)"
[ -f "$REPO/harness_automation.py" ] || { echo "错误: $REPO 不是 harness repo（缺 harness_automation.py）" >&2; exit 2; }

OUT_BASE="${OUT_BASE:-$REPO/docker/out}"

# 代理：公网端点走代理；localhost 直连。如需让某内网端点绕过代理，追加到 NO_PROXY_EXTRA。
PROXY_HTTP="${HTTP_PROXY:-}"; PROXY_HTTPS="${HTTPS_PROXY:-}"
NOPROXY="localhost,127.0.0.1,::1${NO_PROXY_EXTRA:+,$NO_PROXY_EXTRA}"

if [ "${#TASKS[@]}" -eq 0 ]; then
    echo "用法: $0 [--repo <repo>] <任务号...|all>" >&2; exit 2
fi
if [ "${TASKS[0]}" = "all" ]; then
    mapfile -t TASKS < <(find "$REPO" -path "*/task_configs/*.json" 2>/dev/null \
        | sed -E 's#.*/([0-9]+)_.*#\1#' | sort -u)
fi

echo "镜像: $IMAGE | repo: $REPO | 任务: ${TASKS[*]} | detach=$DETACH | max_turn=$USER_MAX_TURN timeout=$QUERY_TIMEOUT"
for T in "${TASKS[@]}"; do
    name="openclaw-task${T}"
    out="${OUT_BASE}/task${T}"
    mkdir -p "$out/logs" "$out/workspace" 2>/dev/null || true
    docker rm -f "$name" >/dev/null 2>&1 || true

    args=(--rm --name "$name"
        -e TASK="$T" -e HARNESS=openclaw
        -e USER_MAX_TURN="$USER_MAX_TURN" -e QUERY_TIMEOUT="$QUERY_TIMEOUT"
        -e HTTP_PROXY="$PROXY_HTTP" -e HTTPS_PROXY="$PROXY_HTTPS"
        -e http_proxy="$PROXY_HTTP" -e https_proxy="$PROXY_HTTPS"
        -e NO_PROXY="$NOPROXY" -e no_proxy="$NOPROXY"
        -v "$REPO:/app"                              # 目标 repo（不同版本随便换）
        -v "$out/logs:/app/logs"                     # 日志/轨迹落宿主机
        -v "$out/workspace:/root/.openclaw/workspace")

    if [ "$DETACH" = "1" ]; then
        id=$(docker run -d "${args[@]}" "$IMAGE")
        echo "  启动 $name (${id:0:12})  日志→ $out/logs"
    else
        docker run "${args[@]}" "$IMAGE"
    fi
done

[ "$DETACH" = "1" ] && {
    echo ""
    echo "状态:  docker ps --filter name=openclaw-task"
    echo "日志:  docker logs -f openclaw-task${TASKS[0]}"
    echo "收轨迹: OUT_BASE=$OUT_BASE $(dirname "$0")/collect_trajectories.sh"
}
