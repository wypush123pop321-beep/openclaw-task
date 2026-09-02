#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# ============================================================
# WCX2K 批跑一键工具(Windows Git Bash)
#
# 从 OBS 交付源按任务下标区间取一批任务 -> 下载 -> 生成 config
# -> 幂等拉起中继(18888)/网关(18789) -> 启动批次串行跑完。
# 跑前对前置条件做全面校验(软件/密钥/obsutil/清单/区间)。
#
# 用法:
#   bash scripts/oneclick_run.sh [START END] [选项]
#
# 位置参数(可省略,省略=跑清单全部未归档):
#   START END   obs 全量清单 tasks_obs.txt 的下标区间(1-based,含端点)
#               「50 100」= 跑清单第 50~100 个任务
#
# 选项:
#   --obs URI            OBS 交付源 prefix(默认 WCX2K 交付源)
#   --api-key KEY        yibuapi 模型 API key(默认读 configs/user_proxy_model.json;
#                        传了会顺带写进该文件,供 simulator 用)
#   --proxy URI          认证代理 URL(默认内置华为代理,可被 WCX_PROXY 覆盖)
#   --openclaw PATH      openclaw.mjs 全路径(默认 %APPDATA%\npm\node_modules\openclaw\openclaw.mjs)
#   --deliv-root DIR     交付根目录(默认 D:/.../deliveries_260827)
#   --config-dir DIR     config 输出目录(默认 <repo>/configs/wcx_260827)
#   --runlog NAME        批次日志文件名(默认 batch_run_r01.log)
#   --refresh            用 obsutil ls 重扫 obs 源重建 tasks_obs.txt(换 obs 源后首次必用)
#   --skip-download      跳过 下载+生成config(仅重启批次;要求 tasks_pending.txt 与 config 已就绪)
#   -h|--help            帮助
#
# 示例:
#   bash scripts/oneclick_run.sh 50 100
#   bash scripts/oneclick_run.sh --api-key sk-xxx 101 150
#   bash scripts/oneclick_run.sh --refresh --obs obs://bucket/.../envs 1 100
# ============================================================
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
export PYTHONIOENCODING=utf-8

# 本机私有凭据(不入库,真值仅本机):local.env 存在则加载
# (WCX_PROXY / WCX_GATEWAY_TOKEN / SIMULATOR_PROXY 等,模板见 configs/local.env.example)
if [ -f "$ROOT/configs/local.env" ]; then
  set -a; . "$ROOT/configs/local.env"; set +a
fi

# ---------- 默认值(参数/环境变量可覆盖) ----------
OBS_PREFIX_DEFAULT="obs://s3-asset-b-hd-cce-aifm-nlp-exp/task_data/260827/DELIVERY_20260827_WCX2K_WIN_WITHFILES/environments"
PROXY="${WCX_PROXY:-http://<user>:<pwd_urlencoded>@proxysg-spl.huawei.com:8080}"
DELIV_ROOT="${WCX_DELIV_ROOT:-D:/Users/w00802407/0616-work/trae_workspace/deliveries_260827}"
CONFIG_DIR="${WCX_CONFIG_DIR:-$ROOT/configs/wcx_260827}"
RUNLOG="${WCX_RUNLOG:-batch_run_r01.log}"
OBS_PREFIX="${WCX_OBS_PREFIX:-$OBS_PREFIX_DEFAULT}"
API_KEY=""
OPENCLAW_MJS=""
START=""; END=""
REFRESH=0; SKIP_DOWNLOAD=0

# obsutil 自动探测:WCX_OBSUTIL > 常见安装位
OBSUTIL="${WCX_OBSUTIL:-}"
if [ -z "$OBSUTIL" ]; then
  for c in \
    "D:/Users/w00802407/0616-work/trae_workspace/obsutil_install/obsutil_windows_amd64_5.8.3/obsutil.exe" \
    "$HOME/obsutil.exe"; do
    [ -f "$c" ] && { OBSUTIL="$c"; break; }
  done
fi

# ---------- 参数解析 ----------
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      sed -n '3,34p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --obs) OBS_PREFIX="$2"; shift 2 ;;
    --api-key) API_KEY="$2"; shift 2 ;;
    --proxy) PROXY="$2"; shift 2 ;;
    --openclaw) OPENCLAW_MJS="$2"; shift 2 ;;
    --deliv-root) DELIV_ROOT="$2"; shift 2 ;;
    --config-dir) CONFIG_DIR="$2"; shift 2 ;;
    --runlog) RUNLOG="$2"; shift 2 ;;
    --refresh) REFRESH=1; shift ;;
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    --*) echo "未知选项: $1"; exit 1 ;;
    *) if [ -z "$START" ]; then START="$1"; elif [ -z "$END" ]; then END="$1"; else
         echo "多余位置参数: $1"; exit 1; fi; shift ;;
  esac
done

[ -z "$OPENCLAW_MJS" ] && OPENCLAW_MJS="${WCX_OPENCLAW:-$APPDATA/npm/node_modules/openclaw/openclaw.mjs}"

# 导出给子脚本(下载/config/regenerate/launch 共享同一套源)
export WCX_OBS_PREFIX="$OBS_PREFIX"
export WCX_DELIV_ROOT="$DELIV_ROOT"
export WCX_CONFIG_DIR="$CONFIG_DIR"
export WCX_PROXY="$PROXY"
export WCX_PENDING="$ROOT/tasks_pending.txt"
export WCX_OBSUTIL="$OBSUTIL"

ENVS_DIR="$DELIV_ROOT/environments"
OBS_LIST="$ROOT/tasks_obs.txt"
SM_CFG="$ROOT/configs/user_proxy_model.json"
FAIL=0

say() { printf '[oneclick] %s\n' "$*"; }
bad() { printf '[oneclick] ✗ %s\n' "$*"; FAIL=1; }
ok()  { printf '[oneclick] ✓ %s\n' "$*"; }
warn(){ printf '[oneclick] ⚠ %s\n' "$*"; }

# ============================================================
# [1/8] 前置条件校验
# ============================================================
echo; echo "================= [1/8] 前置条件校验 ================="
need_cmd() { command -v "$1" >/dev/null 2>&1 || bad "缺少命令: $1"; }
need_file() { [ -f "$1" ] || bad "缺少文件: $1"; }

for c in node python curl netstat; do need_cmd "$c"; done
# tasklist/taskkill 可选(仅用于杀残留 http.server,缺了跳过)
if ! command -v tasklist >/dev/null 2>&1 || ! command -v taskkill >/dev/null 2>&1; then
  warn "tasklist/taskkill 不可用(杀残留 http.server 会跳过,批次照跑)"
fi
[ -f "$OPENCLAW_MJS" ] && ok "openclaw.mjs" || bad "openclaw.mjs 不存在: $OPENCLAW_MJS (用 --openclaw 或 WCX_OPENCLAW 指定)"
if [ -n "$OBSUTIL" ] && [ -f "$OBSUTIL" ]; then ok "obsutil"; else bad "obsutil 不存在(用 WCX_OBSUTIL 指定,或装到默认位)"; fi
[ -f "$HOME/.obsutilconfig" ] && ok "obsutilconfig" || bad "~/.obsutilconfig 缺失(先跑: $OBSUTIL config -i=<AK> -k=<SK> -e=<endpoint>)"

for s in yibu_relay.py download_wcx_batch.py gen_wcx_configs.py regenerate_eval_files.py \
         launch_wcx_batch.py collect_task.py run_batch.py; do
  need_file "$ROOT/scripts/$s"
done
need_file "$ROOT/harness_automation.py"
need_file "$SM_CFG"

# api-key: --api-key 优先;否则读 user_proxy_model.json,占位符则报错
CFG_KEY=$(python -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))['user_simulator'].get('api_key',''))" "$SM_CFG" 2>/dev/null)
if [ -n "$API_KEY" ]; then
  if [ "$CFG_KEY" != "$API_KEY" ]; then
    python - "$SM_CFG" "$API_KEY" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding="utf-8"))
d["user_simulator"]["api_key"] = sys.argv[2]
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print("[oneclick] 已把 --api-key 写入 user_proxy_model.json")
PY
    CFG_KEY="$API_KEY"
  fi
fi
if [[ -z "$CFG_KEY" || "$CFG_KEY" == *"<"* || "$CFG_KEY" == *占位* \
      || "$CFG_KEY" == *placeholder* || "$CFG_KEY" == *PLACEHOLDER* ]]; then
  bad "user_proxy_model.json 的 api_key 缺失/仍是占位符,请用 --api-key <key> 提供"
else
  ok "yibuapi api-key 就绪"
  warn "若换的是模型 key,请确认 C:\\Users\\<user>\\.openclaw\\openclaw.json 的 models.providers.anthropic.apiKey 同步为同一 key"
fi

# obs 清单:优先已生成;--refresh 或缺清单时用 obsutil ls 重建
# (重建不依赖全局 FAIL 状态:即便 api-key 等前置校验没过,只要 obsutil 可用就重建,
#  避免"缺清单却不重建"的假阴性问题)
if [ "$REFRESH" = 1 ] || [ ! -f "$OBS_LIST" ]; then
  if [ -n "$OBSUTIL" ] && [ -f "$OBSUTIL" ]; then
    say "用 obsutil 重扫 obs 源生成清单 ..."
    HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" "$OBSUTIL" ls "$OBS_PREFIX/" > "$ROOT/tasks_obs.raw.txt" 2>&1 \
      || bad "obsutil ls 失败(网络/代理?源: $OBS_PREFIX)"
    python - "$OBS_PREFIX" "$OBS_LIST" <<'PY'
import sys
from pathlib import Path
prefix, out = sys.argv[1], Path(sys.argv[2])
lines = Path("tasks_obs.raw.txt").read_text(encoding="utf-8", errors="replace").splitlines()
names = set()
capture = False
for ln in lines:
    s = ln.strip()
    if s == "Folder list:":
        capture = True; continue
    if s == "Object list:":
        capture = False; continue
    if not capture or not s.startswith(prefix):
        continue
    # folder 形如 <prefix>/<task>/ → 取第一段组件
    rel = s[len(prefix):].strip("/")
    if rel and "/" in rel:
        rel = rel.split("/", 1)[0]
    if rel:
        names.add(rel)
out.write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")
print(f"[oneclick] tasks_obs.txt 重建: {len(names)} 个任务")
PY
    rm -f "$ROOT/tasks_obs.raw.txt"
  else
    bad "无法重建清单:obsutil 不可用(用 WCX_OBSUTIL 指定,或装到默认位)"
  fi
fi
need_file "$OBS_LIST"
# 清单缺失时 need_file 已置 FAIL=1,但脚本不退出;此处避免对不存在文件 open 抛 traceback,
# 统计留给下面 [ "$FAIL" = 1 ] 统一拦截
if [ -f "$OBS_LIST" ]; then
  OBS_TOTAL=$(python -c "print(len([l for l in open(r'$OBS_LIST',encoding='utf-8') if l.strip()]))")
  ok "obs 清单 $OBS_TOTAL 个任务"
else
  OBS_TOTAL=0
fi

# 区间校验
if [ -n "$START" ]; then
  [ -z "$END" ] && END="$START"
  if [ "$START" -lt 1 ] || [ "$END" -gt "$OBS_TOTAL" ] || [ "$START" -gt "$END" ]; then
    bad "区间越界: START=$START END=$END 需 1 ≤ START ≤ END ≤ $OBS_TOTAL"
  fi
  ok "区间 [$START ~ $END] 就绪"
fi

if [ "$FAIL" = 1 ]; then
  echo; echo "前置校验未通过,按上面 ✗ 项补齐后重试。"; exit 1
fi
echo "前置校验通过。"

# ============================================================
# [2/8] 选择区间任务 -> tasks_pending.txt(过滤已归档,备份旧清单)
# ============================================================
echo; echo "================= [2/8] 选择任务区间 ================="
python - "$OBS_LIST" "$START" "$END" "$ROOT" <<'PY'
import sys
from pathlib import Path
obs_list, start_s, end_s, root = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
start = int(start_s) if start_s else 0
end = int(end_s) if end_s else 0
obs = [l.strip() for l in Path(obs_list).read_text(encoding="utf-8").splitlines() if l.strip()]
done = set()
out_dir = root / "outputs"
if out_dir.is_dir():
    done = {p.name for p in out_dir.iterdir() if (p / "stats.json").exists()}
pool = obs[start-1:end] if start else obs     # start/end 1-based 含端点;0=全量
todo = [t for t in pool if t not in done]
skip = [t for t in pool if t in done]
old = root / "tasks_pending.txt"
old_tasks = [l for l in old.read_text(encoding="utf-8").splitlines() if l.strip()] if old.exists() else []
if old_tasks:
    # 备份旧清单: 以旧条数命名, 已存在则跳过不覆盖(幂等)
    bak = root / f"tasks_pending.bak_{len(old_tasks)}tasks.txt"
    if not bak.exists():
        bak.write_text("\n".join(old_tasks) + "\n", encoding="utf-8")
old.write_text("\n".join(todo) + ("\n" if todo else ""), encoding="utf-8")
print(f"obs 区间 [{start or 1}~{end or len(obs)}] 任务 {len(pool)} 个:"
      f"已归档跳过 {len(skip)},待跑 {len(todo)}")
if todo:
    print("待跑前 5:", ", ".join(todo[:5]))
PY
TODO_N=$(python -c "print(len([l for l in open(r'$ROOT/tasks_pending.txt',encoding='utf-8') if l.strip()]))" 2>/dev/null || echo 0)
if [ "$TODO_N" = 0 ]; then
  echo "区间内任务已全部归档,无需运行,退出。"; exit 0
fi

# ============================================================
# [3/8] 下载(obs -> deliveries_260827/environments)
# ============================================================
if [ "$SKIP_DOWNLOAD" != 1 ]; then
  echo; echo "================= [3/8] 下载任务(obs -> $ENVS_DIR) ================="
  python scripts/download_wcx_batch.py || { echo "下载失败,终止。"; exit 1; }

  # ==========================================================
  # [4/8] 生成 config(每任务 *_q1.json)
  # ==========================================================
  echo; echo "================= [4/8] 生成 config -> $CONFIG_DIR ================="
  python scripts/gen_wcx_configs.py || { echo "config 生成失败,终止。"; exit 1; }
fi

# ============================================================
# [5/8] 服务拉起:杀残留 http.server + 中继 18888 + 网关 18789
# ============================================================
echo; echo "================= [5/8] 服务拉起 ================="
# 5.1 杀残留 http.server(锁 workspace\data 的元凶)
say "清理残留 http.server 进程(若有)..."
pids=$(powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'http.server' } | ForEach-Object { \$_.ProcessId }" 2>/dev/null | tr -d '\r')
for pid in $pids; do
  taskkill //F //PID "$pid" >/dev/null 2>&1 && say "已杀 http.server PID $pid"
done

# 5.2 本地模型中继 18888
if netstat -ano 2>/dev/null | grep ":18888" | grep -qi listen; then
  say "中继 18888 已在跑,跳过"
else
  HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" nohup python "$ROOT/scripts/yibu_relay.py" >> "$ROOT/relay_18888.log" 2>&1 &
  say "中继已启动(PID $!)"
fi

# 5.3 openclaw 网关 18789
if netstat -ano 2>/dev/null | grep ":18789" | grep -qi listen; then
  say "网关 18789 已在跑,跳过"
else
  NO_PROXY="127.0.0.1,localhost" nohup node "$OPENCLAW_MJS" gateway run >> "$ROOT/gateway_run.log" 2>&1 &
  say "网关已启动(PID $!)"
fi

# 5.4 等网关 readyz(最多 60s)
echo; echo "================= [6/8] 等网关 readyz ================="
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' http://127.0.0.1:18789/readyz 2>/dev/null)
  if [ "$code" = "200" ]; then say "readyz OK(http $code)"; break; fi
  sleep 2
  if [ "$i" = 30 ]; then echo "网关 60s 未就绪,请查 $ROOT/gateway_run.log(必要时手动重启)"; fi
done

# ============================================================
# [7/8] 补 rubrics/scoring 副本(防 evaluator 文件隔离漏还原)
# ============================================================
echo; echo "================= [7/8] 补 rubrics/scoring 副本 ================="
python scripts/regenerate_eval_files.py

# ============================================================
# [8/8] 启动批次
# ============================================================
echo; echo "================= [8/8] 启动批次(待跑 $TODO_N 个) ================="
nohup python "$ROOT/scripts/launch_wcx_batch.py" >> "$ROOT/$RUNLOG" 2>&1 &
echo "[oneclick] 批次已后台启动 PID $! → 日志 $RUNLOG"
echo "[oneclick] 监控提示: 归档数用 python 数 outputs/<task>/stats.json;"
echo "[oneclick]           中继/网关/批次日志: relay_18888.log / gateway_run.log / $RUNLOG"
