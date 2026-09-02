# Windows 批量任务执行流水线（0902）

> 文档目的：梳理 openclaw 任务批跑（WCX 系列 100 个）涉及的全部**代码修改**与**环境配置**，
> 以及运行中遇到过的失败模式与处置办法。适用于后续任何「批量跑任务 → 归档 → 留档」的需求。
>
> 安全约定：涉及密钥/令牌的地方一律用占位符，真值仅存在于本机
> `configs/user_proxy_model.json`（skip-worktree，见 §3.5）与
> `C:\Users\<user>\.openclaw\openclaw.json`，不进 PR。

---

## 1. 快速开始（前置条件 + 一键运行 + 架构）

### 1.1 前置条件

> 首次在一台新机器跑批前,先按本节装齐依赖、做一次性配置。密钥类一律用占位符,
> 真值仅留在本机(见 §3.5 与开头的安全约定)。

#### 1.1.1 软件依赖

| 软件 | 版本 | 用途 | 安装 |
|---|---|---|---|
| **Node.js**(含 npm) | ≥ 18 | openclaw 网关/agent 运行时 | https://nodejs.org;`node -v` 验证 |
| **openclaw** | 2026.6.x | 核心网关(WebSocket 收任务→驱动 agent) | `npm install -g openclaw`;Windows 全局装到 `%APPDATA%\npm\node_modules\openclaw\openclaw.mjs` |
| **Python** | 3.10 ~ 3.12 | 批跑脚本 / harness_automation | python.org;`python --version` 验证,PATH 含 python |
| **obsutil**(华为 OBS 客户端) | 5.8.x | 从 OBS 下载交付任务数据 | 任意目录解压,`obsutil config` 配 AK/SK/endpoint(见下) |
| **Git Bash** | — | 本套一键命令/批跑均在 Git Bash 下运行 | Git for Windows 自带 |

> ⚠ 华为内网用 npm/obsutil 等联网操作需走认证代理(见 §1.1.4)。

#### 1.1.2 openclaw 首次初始化（一次性）

1. 生成网关配置: `openclaw configure`(选 local mode)→ 产出 `C:\Users\<user>\.openclaw\openclaw.json`
2. 手工改配置(必须,否则模型直连失败/agent 无法用,详见 §3.1):
   - `models.providers.anthropic.baseUrl` → `http://127.0.0.1:18888/v1`(指向本地中继,见 §2.5)
   - `models.providers.anthropic.api` → `"openai-completions"`
   - 注册模型 deepseek-v3 / gemini-3-flash-preview / glm-5.2 / gemini-3.5-flash 等
   - `agents.list.<name>.model` → 每个 agent 的执行模型(assistant1→anthropic/glm-5.2,evaluator→anthropic/gemini-3.5-flash)
   - `gateway.auth.token` → 自定 token(批跑配置 `api_key` 用它)
   - 模型 API key 填 yibuapi key(provider.apiKey)
3. `configs/user_proxy_model.json`: 填 simulator 模型 + `base_url`(yibuapi)+ `api_key`(真 key 本地,skip-worktree §3.5)
4. workspace 初始化: gateway 首次跑会给 `workspace-assistant1` 等做 seed(AGENTS.md/HEARTBEAT.md/…);
   补 AGENTS.md 的「## Environment & Paths (Windows / PowerShell)」路径节(§3.4)。
   不要手动删 workspace 目录(attestation 防护,§3.3)。

#### 1.1.3 凭据（本机保存,不进文档/PR）

| 凭据 | 放哪 | 用途 |
|---|---|---|
| yibuapi API key | `configs/user_proxy_model.json` + `openclaw.json` | 模型调用(经本地中继转发) |
| openclaw gateway token | `openclaw.json` gateway.auth.token | 批跑 config 的 `api_key` / WS 认证 |
| OBS AK / SK / endpoint | obsutil 本地配置 | `obsutil config -i=<AK> -k=<SK> -e=http://obs.cn-east-4.myhuaweicloud.com` 下载交付 |
| 认证代理账号/密码 | 各脚本 DEFAULT_PROXY | 华为内网出网(proxysg-spl,非 proxyde-spl) |
| web search API key | `openclaw.json` tools.web.search | agent 联网搜索 |

#### 1.1.4 网络

- **出网走认证代理**: `HTTP_PROXY` / `HTTPS_PROXY` = `http://<user>:<pwd_urlencoded>@proxysg-spl.huawei.com:8080`(密码含 `@`,需 URL 编码 `%40%40`)——中继、obsutil、npm、agent 联网都要。
- **本机回环绕过代理**: `NO_PROXY=127.0.0.1,localhost`——中继(18888)/网关(18789)互访必须设,否则 node/curl 会尝试走代理连本机而失败。
- 模型调用不直连 yibuapi: openclaw 的 undici 与华为认证代理不兼容,必须经本地中继 `yibu_relay.py` 转发(§2.5、§3.2)。

#### 1.1.5 任务数据（交付源）

- **OBS 源**: `obs://s3-asset-b-hd-cce-aifm-nlp-exp/task_data/260827/DELIVERY_20260827_WCX2K_WIN_WITHFILES/environments/`(obsutil ls 可枚举 → 存 `tasks_obs.txt`)
- **本地下游**: `deliveries_260827/environments/<task>/`(download_wcx_batch.py 下载+重建结构)
- **清单文件**(仓库根): `tasks_obs.txt`(OBS 全量)/ `tasks_pending.txt`(待跑,顺序取)/ `tasks_done.txt`
- **归档**: `outputs/<task>/stats.json` 存在 = 已完成(批次断点续跑依据)

### 1.2 一键运行

装好前置条件、密钥就位后,**启动/重启整条批跑**只需一条命令(仓库已带脚本)。脚本会自动
校验前置条件、按 obs 源任务下标区间挑任务 → 下载 → 生成 config → 幂等拉起服务 → 启动批次:

```bash
# 跑 obs 全量清单 tasks_obs.txt 第 50~100 个任务(1-based 含端点)
bash scripts/oneclick_run.sh 50 100

# 省略区间 = 跑清单全部未归档任务(换 obs 源后首次加 --refresh 重建清单)
bash scripts/oneclick_run.sh

# 换 obs 源 + 换 api-key + 指定区间
bash scripts/oneclick_run.sh --refresh --obs obs://<bucket>/.../environments --api-key <yibu_key> 1 100
```

**三个关键入参**(都有默认值,可按需覆盖):

| 入参 | 含义 | 默认值 / 说明 |
|---|---|---|
| `--obs URI` | OBS 交付源 prefix | WCX2K 交付源(§1.1.5) |
| `--api-key KEY` | yibuapi 模型 API key | 读 `configs/user_proxy_model.json`;传了会顺带写进该文件 |
| `START END` | obs 清单 `tasks_obs.txt` 的任务下标区间(1-based 含端点,如 `50 100`) | 省略 = 全量未归档任务 |

> ⚠ `START END` 是**位置参数**放最后;其余选项 `--obs`/`--api-key`/`--proxy`(认证代理)/
> `--openclaw`(openclaw.mjs 路径)/`--deliv-root`(交付根)/`--config-dir`(config 目录)/
> `--runlog`(批次日志名)/`--skip-download`(仅重启批次)/`--refresh`(重扫 obs 源)。

**执行前的自动校验**(脚本第一步,任何一项 ✗ 即终止):
- 软件: `node` / `python` / `curl` / `netstat` 在 PATH
- `openclaw.mjs` 存在(默认 `%APPDATA%\npm\node_modules\openclaw\openclaw.mjs`)
- `obsutil.exe` 存在 + `~/.obsutilconfig` 已配好(AK/SK/endpoint)
- 依赖脚本齐全: `yibu_relay.py`/`download_wcx_batch.py`/`gen_wcx_configs.py`/
  `regenerate_eval_files.py`/`launch_wcx_batch.py`/`collect_task.py`/`run_batch.py`/
  `harness_automation.py`
- `configs/user_proxy_model.json` 的 api_key **不是占位符**(缺失/占位时报错,提示用 `--api-key`)
- obs 清单存在(缺了或 `--refresh` 时用 obsutil 自动重建)→ 区间越界校验

脚本幂等做了八步(已在跑的中继/网关自动跳过,不会重复拉起):
① 前置校验 → ② 选区间写 `tasks_pending.txt`(过滤已归档 + 备份旧清单)→
③ 下载(`download_wcx_batch.py`)→ ④ 生成 config(`gen_wcx_configs.py`)→
⑤ 杀残留 http.server + 拉起中继(18888)+ 网关(18789)→ ⑥ 等 `readyz` →
⑦ 补 rubrics/scoring 副本 → ⑧ 启动批次(`launch_wcx_batch.py`)。

也支持环境变量覆盖: `WCX_PROXY=... WCX_RUNLOG=batch_x.log bash scripts/oneclick_run.sh 50 100`
(各子脚本均从 env 读取 `WCX_OBS_PREFIX`/`WCX_DELIV_ROOT`/`WCX_CONFIG_DIR`/`WCX_PENDING`/
`WCX_OBSUTIL`/`WCX_GATEWAY_TOKEN`,换机/换环境优先用环境变量,见各脚本顶部注释)。

> 批次串行逐个跑,单任务常 20~40min,偶发超时重跑。**下一轮启动时机**: 当前批次
> 已结束(归档数达标)后执行;不要在批次进行中重复执行(会并发再拉起一批)。
> 进度用 cron 每小时检查(归档数/当前任务/中继日志,见 §4.5);日志分别看
> `relay_18888.log` / `gateway_run.log` / `<RUNLOG>`。

### 1.3 三步流水线

每个任务串行走三步，由 `scripts/run_batch.py` 串联：

```
launch_wcx_batch.py               # 启动器:读 tasks_pending.txt → 挑未归档 → 调 run_batch
        │
        ▼
run_batch.py  (per task, 串行)
  ├─ ① 跑前清理 workspace          # clean_workspace(): 清 data/ + 根级产物 + 非基础设施自建目录
  ├─ ② python harness_automation.py --config <task>_q1.json   # 真正跑 openclaw agent
  └─ ③ python scripts/collect_task.py <task> --clean          # 归档 + 清理 workspace
        │
        ▼
outputs/<task>/
  ├─ stats.json                   # 归档完成标记(存在=已完成),由 run_batch 写入
  ├─ harness_trajectory.json
  ├─ *_session.jsonl              # agent / evaluator session
  ├─ harness.log
  └─ artifacts/                   # 任务产物
```

- `launch_wcx_batch.py` 读 `tasks_pending.txt`（按行，一行一个任务名），展开为
  `configs/wcx_260827/<task>_q1.json`，**跳过已归档**（`outputs/<task>/stats.json` 存在），
  把剩余 config 列表传给 `run_batch.py`。
- `run_batch.py` 对每个 config 串行执行「清理 → harness → collect --clean」，
  单任务超时 7200s，全部结束后写汇总 `outputs/_batch_summary.json`。
- `harness_automation.py` 内部：`_setup_workspaces` 按 `user_workspace` 三档语义部署
  user_workspace → 对每个 query 执行 openclaw agent（含 evaluator 循环评审）。
- `collect_task.py` 从 `harness.log` 解析 run_id → 匹配 agent/evaluator session jsonl →
  收集 mtime 窗口内的产物到 `artifacts/` → `--clean` 清理 workspace 防污染下一个任务。

### 1.4 关键目录

| 路径 | 作用 |
|---|---|
| `scripts/run_batch.py` | 批跑主控（清理+harness+collect 串联） |
| `scripts/launch_wcx_batch.py` | 批次启动器（读 tasks_pending，跳已归档） |
| `scripts/collect_task.py` | 单任务归档 + 清理 |
| `scripts/regenerate_eval_files.py` | 补 rubrics/scoring 副本（前置修复） |
| `scripts/yibu_relay.py` | 本地模型中继（转发 yibuapi） |
| `harness_automation.py` | openclaw agent 执行主逻辑 |
| `src/evaluator/evaluator.py` | 评估 + 文件隔离 |
| `configs/user_proxy_model.json` | simulator 模型 + base_url + key |
| `configs/wcx_260827/<task>_q1.json` | 单任务配置 |
| `tasks_pending.txt` | 待跑任务名单 |
| `outputs/<task>/` | 归档目录 |
| `C:\Users\<user>\.openclaw\openclaw.json` | 网关/模型/agent 全局配置 |

---

## 2. 代码修改清单

> 均已在分支 `run-260822` 提交。改动动机 = 修复批跑过程中实际踩到的坑。

### 2.1 `scripts/run_batch.py` —— 批跑主控

- **PermissionError 容错（根治 workspace 清理崩溃）**：`clean_workspace` 对
  `shutil.rmtree` / `item.unlink` 逐个包 `try/except PermissionError`，被锁项打印警告跳过、不崩。
  根因：agent 生成 HTML 看板后常起 `python -m http.server` 展示，任务结束进程残留锁住
  `workspace-assistant1\data\`，清理时抛 PermissionError 导致整体崩溃。
  （此前 8/31 曾因此两次整体崩溃，加容错后不再崩；残留进程还是要主动清，见 §4.5）
- **基础设施保护集**：`_INFRA`（AGENTS.md / HEARTBEAT.md / SOUL.md / TOOLS.md / system_prompt.md /
  openclaw_automation.py / trajectory.py / user_simulator.py / evaluator.py / requirements.txt 等）
  与 `_INFRA_DIRS`（.git / .openclaw / agents / configs / docs / scripts / skills / test / utils /
  openspec / nanobot / memory 等）在清理时整文件/整目录保留，防止把批跑框架自身当任务产物清掉。
- **产物扩展名**：`_ART_SUFFIXES = {.html, .json, .py, .png}`（根级 / 自建目录内都算）。
- **认证代理默认值**：`DEFAULT_PROXY = "http://<user>:<pwd_urlencoded>@proxysg-spl.huawei.com:8080"`
  （华为内网认证代理；密码含 `@`，URL 编码为 `%40%40`）。
- **collect 编码修复（防 GBK 崩溃）**：`subprocess.run(..., capture_output=True, text=True,
  encoding="utf-8", errors="replace")` —— Windows 子进程 stdout 默认 GBK 解码，
  collect_task 输出 UTF-8 中文会抛 `UnicodeDecodeError` 崩掉。显式 utf-8 + errors=replace。
- `read_completion`：从 `stats.json.best_completion` + 轨迹 `evaluations[-1]` 汇总 completion/倾向。

### 2.2 `scripts/launch_wcx_batch.py` —— 批次启动器

- **Python `splitlines()` 读名单**：`tasks_pending.txt` 最后一行**无换行符**，bash
  `while IFS= read -r` 会漏掉最后一行（read 遇 EOF 无换行返回非零）。用 Python
  `read_text().splitlines()` 正确处理，杜绝「最后一个任务漏跑 / 误判已归档」。
- **跳过已归档**：`outputs/<stem>/stats.json` 存在视为已完成，断点续跑。
- **subprocess 传 list 参数**：规避 Windows bash `$(cat ...)` 传参的编码坑。
- 注意：launch 的 print 输出在 run_batch 阻塞期间被 stdout 缓冲，`batch_run.log`
  时间顺序会「看起来滞后」，属正常现象。

### 2.3 `scripts/collect_task.py` —— 单任务归档

- `parse_run_id_from_log`：取**最后一条**「轨迹已落盘」行（防日志污染混入多条）。
- `find_agent_session`：优先 `sessions.json` 的 key 含 run_id，回退 timestamp 窗口匹配。
- `collect_artifacts`：按 mtime 窗口（run_start_ts ~ +8h）收集任务产物。
- `--clean` 清理：保护 `_INFRA` / `_INFRA_DIRS`，其余清掉。
- **已知隐患**：`--clean` 的 `shutil.rmtree(data_dir)`（line 274）**没有 PermissionError 容错**
  （run_batch 里容错了，这里没有）。若个别任务 collect 归档 exit=1，多半是这里被残留
  http.server 锁住，杀掉残留进程重跑即可。

### 2.4 `scripts/regenerate_eval_files.py` —— 补 rubrics/scoring 副本

- `BASE = D:\...\deliveries_260827\environments`（**绝对路径**，注意 deliveri 在
  openclaw-task-main 的上级目录 `trae_workspace\` 下）。
- 从 `user_queries.json` 的 `evaluate[0].custom_rubrics` / `scoring` 重新生成
  `rubrics_normalized.json` / `scoring.json`，**幂等**，输出「已生成副本: N 个」。
- 用途：批次进程被 kill 时，evaluator 的「文件隔离」机制（§2.6）可能删了 rubrics 未还原，
  重启批次前必跑一遍。

### 2.5 `scripts/yibu_relay.py` —— 本地模型中继

- 本地 HTTP 中继 `ThreadingHTTPServer(("127.0.0.1", 18888))`，把模型请求转发到
  `https://yibuapi.com`（经华为认证代理）。
- `_KEEP_REQ_HEADERS = {authorization, content-type, accept}`；转发时**剥掉**
  content-length / transfer-encoding / connection，**加 `Connection: close`**，
  让 SSE 以 EOF 判定流结束（否则 openclaw 等不到 stream end 挂死）。
- 为什么需要中继：openclaw 网关的 undici 代理与华为认证代理不兼容，改走本地中继 +
  `NO_PROXY=127.0.0.1,localhost` 绕过（见 §3.1/§3.4）。

### 2.6 `src/evaluator/evaluator.py` —— 文件隔离

- `_isolate_eval_files`（line 673）：任务执行前把该 query 的 oracle/rubrics 文件从磁盘删除
  （内容已缓存进 `file_vault`），防止 agent 读文件作弊。
- `_restore_eval_files`（line 685）：任务结束后把 file_vault 原始字节写回（best-effort 调试便利）。
- 事故联动：批次被 kill → 删了没还原 → 下次 agent 直接看到文件缺失。重启批次前必须先跑
  `regenerate_eval_files.py`（§2.4）。

### 2.7 `harness_automation.py`

- `_setup_workspaces`（line 414）：`user_workspace` 三档语义 ——
  1) `content_root` 不存在 → 不部署；
  2) 有 `map_file` → `setup_from_map` 按映射建 data 目录；
  3) 仅 `content_root` → 作为工作区部署。
  再逐 agent `setup_agent_files`（config 文件 + skills + agent_dir + content_root）。

### 2.8 `configs/user_proxy_model.json`

```json
{
  "user_simulator": {
    "model": "gemini-3-flash-preview",
    "base_url": "https://yibuapi.com/v1",
    "api_key": "<真key仅本地>"
  }
}
```

- 该文件是仓库中唯一**已跟踪但被 skip-worktree** 的文件：本地保留真 key，
  PR 用占位符净化（`git diff` 只看到 2+8- 的结构改动，不泄露密钥），见 §3.5。

### 2.9 `scripts/oneclick_run.sh` —— 一键批跑(三入参 + 前置校验)

- **三个可配置入参**: `--obs URI`(obs 交付源)、`--api-key KEY`(yibuapi 模型 key,默认读
  `configs/user_proxy_model.json`,传了会写回该文件)、位置参数 `START END`(obs 清单
  `tasks_obs.txt` 的任务下标区间,1-based 含端点;省略 = 全量未归档)。
- **前置校验**(第一步,任何 ✗ 终止): node/python/curl/netstat 在 PATH、openclaw.mjs 存在、
  obsutil.exe + `~/.obsutilconfig` 已配、依赖脚本齐全、`user_proxy_model.json` 的 api_key
  非占位符、obs 清单存在/越界检查。
- **八步幂等流程**: ① 前置校验 → ② 选区间写 `tasks_pending.txt`(过滤已归档 + 备份旧清单)
  → ③ 下载 → ④ 生成 config → ⑤ 杀残留 http.server + 拉起中继/网关 → ⑥ 等 readyz →
  ⑦ 补 rubrics/scoring → ⑧ 启动批次。已在跑的中继/网关自动跳过。
- **env 打通**(配合下游脚本): 导出 `WCX_OBS_PREFIX`/`WCX_DELIV_ROOT`/`WCX_CONFIG_DIR`/
  `WCX_PENDING`/`WCX_OBSUTIL`/`WCX_PROXY`;配合 `download_wcx_batch.py`(PENDING 改从
  `WCX_PENDING` 读)、`gen_wcx_configs.py`(`WCX_GATEWAY_TOKEN`/`WCX_GATEWAY` 可覆盖)、
  `launch_wcx_batch.py`(`WCX_PENDING`/`WCX_CONFIG_DIR` 可覆盖),整条链可整体换源换环境。
- 残留 http.server 清理用 PowerShell `Get-CimInstance`(Win11 已弃用 wmic)。

---

## 3. 环境配置

### 3.1 openclaw 网关配置 `C:\Users\<user>\.openclaw\openclaw.json`

- **模型 provider 指向本地中继**：
  `models.providers.anthropic.baseUrl = http://127.0.0.1:18888/v1`，
  `api = "openai-completions"`，`apiKey` 填 yibuapi key（中继只透传 authorization）。
- **注册的模型清单**：`deepseek-v3` / `gemini-3-flash-preview` / `deepseek-v4-pro` /
  `glm-5.2` / `gemini-3.5-flash`，各配 `contextWindow: 200000, maxTokens: 32768`。
- **per-agent 模型**（记忆要点：`agents_update` 是 no-op，真正生效的是 `agents.list.<name>.model`，
  手改后网关热重载生效）：
  - 默认 `agents.defaults.model.primary = anthropic/gemini-3-flash-preview`
  - `assistant1` / `assistant3` / `assistant5` → `anthropic/glm-5.2`（WCX 任务主执行 agent）
  - `assistant2` → `claude-opus-4-8`；`assistant4` → `anthropic/glm-5.2`
  - `evaluator` / `evaluator3` / `evaluator4` / `evaluator5` → `anthropic/gemini-3.5-flash`
  - `main` / `main3` / `probe_toolcall` → 走默认
- **网关**：`port: 18789`，`mode: local`，`bind: loopback`，`auth.mode: token`
  （token 为本地保密值，不进文档/PR）。
- **workspace 绑定**：`assistant1` → `workspace-assistant1`；evaluator → `workspace-evaluator` 等。

### 3.2 启动命令（必须 nohup 脱离，见 §4.5）

```bash
# 1) 本地模型中继
NO_PROXY=127.0.0.1,localhost nohup python scripts/yibu_relay.py >> relay_18888.log 2>&1 &

# 2) openclaw 网关
NO_PROXY=127.0.0.1,localhost nohup node \
  "C:\Program Files\nodejs\node.exe" \
  C:\Users\<user>\AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs \
  gateway run >> gateway_run.log 2>&1 &

# 3) 批次(读 tasks_pending.txt,自动跳已归档)
nohup python scripts/launch_wcx_batch.py >> batch_run.log 2>&1 &
```

> 环境变量 `NO_PROXY=127.0.0.1,localhost`：中继/网关访问本机 18888 端口必须绕过
> 华为认证代理，否则 curl/node 会尝试走代理连 127.0.0.1 而失败。
> 健康检查：`curl http://127.0.0.1:18789/readyz` 返回 OK。

### 3.3 workspace-attestation 防护（别删 workspace 目录！）

- gateway 用 `~/.openclaw/workspace-attestations/<hash>.attested` 记录 workspace 已初始化。
- **症状**：`rm -rf workspace-assistant1` 后，重启批次所有 agent 秒级失败，
  gateway 报 `WorkspaceVanishedError: ... Refusing to reseed BOOTSTRAP.md over a
  recently attested workspace`。
- **修复顺序**（已验证）：① 杀失败批次进程 → ② 删 attestations 里最新的 attestation
  （内容含 `generated: AGENTS.md`；旧的 7/7 不动）→ ③ 重启 gateway（§3.2 命令）→
  ④ 重建 workspace seed 文件（从 `workspace-assistant3` 完整模板复制
  AGENTS.md/HEARTBEAT.md/IDENTITY.md/SOUL.md/TOOLS.md/USER.md，**排除 data/**）→
  ⑤ 恢复 AGENTS.md 的「## Environment & Paths」节（见 §3.4）。
- **预防**：清理 workspace 交给 run_batch 的「跑前清理」（只清 data/ 重建）或只删 data/
  子目录，绝不 `rm -rf workspace-assistant1`。

### 3.4 workspace-assistant1 的 AGENTS.md 路径节（`~/` 歧义修复）

- 问题：agent 在 exec（PowerShell）里用 `~/data` / `$HOME/data` 会被展开成
  Windows 用户主目录，不是 workspace 内 `data\`，导致部署/读取错位。
- 修复：AGENTS.md 插入 `## Environment & Paths (Windows / PowerShell)` 节（Session
  Startup 之后 / Memory 之前），声明：
  - cwd / workspace root = `C:\Users\<user>\.openclaw\workspace-assistant1`
  - 用户说 `~/data` / `$HOME/data` = 本 workspace 的 `data\`，**不是** Windows 主目录
  - exec 里**禁用** `~/` / `$HOME`，用相对路径（相对 cwd）或绝对路径
  - 优先 read/write 工具 + 绝对路径
- 注意：`config system_prompt` 对主 agent **无效**，路径约定只能靠 AGENTS.md 落地。

### 3.5 密钥管理（skip-worktree）

```bash
git update-index --skip-worktree configs/user_proxy_model.json
```

- `user_proxy_model.json` 保留真 key（yibuapi key）在本地；
- PR / 提交只带占位符净化的版本（git 认为本地未改动，diff 里看不到真 key）；
- 换机器或 clone 时需重新放真 key 再 skip-worktree。
- 同理：`openclaw.json`（网关 token、web.search key）、`yibu_relay.py` 里的
  认证代理密码、`run_batch.py` 的 `DEFAULT_PROXY` 密码均只在本地，**不进文档/PR**。

### 3.6 认证代理

- 内网认证代理：`http://<user>:<pwd_urlencoded>@proxysg-spl.huawei.com:8080`
  （用户 `w00802407`；密码含 `@`，URL 编码 `%40%40`；是 `proxysg-spl` **不是** `proxyde-spl`）。
- 用途：中继出网访问 yibuapi（`scripts/yibu_relay.py` 的 `PROXY`）、
  run_batch 的 `SIMULATOR_PROXY` / `DEFAULT_PROXY`（传给 harness 里的 simulator）。
- 注意与 §3.2 的 `NO_PROXY` 不冲突：**出网走代理，本机回环绕代理**。

### 3.7 其他环境约束

- **路径上限（Windows MAX_PATH）**：260 字符路径会失败，用 `junction` 缩短
  （`mklink /J`）或 `\\?\` 前缀直读（build_traj_viewer 就地定位时）。
- **用户目录隔离**：`user_workspace` 留 `None` 会回退嵌套目录部署；部分批次
  （如 WCX2K）需关隔离或让 MAP 非空，视任务模板而定。
- **harness 环境变量**：`PYTHONIOENCODING=utf-8`（run_batch 统一注入子进程）。

---

## 4. 失败模式与处置

批跑全程遇到四种失败，处置如下：

| # | 症状 | 根因 | 处置 |
|---|---|---|---|
| 1 | agent 秒级报错 / 模型调用失败 | yibuapi **rate limit**（API 限流） | 等限流窗口过，重跑该任务 |
| 2 | `WorkspaceVanishedError` | workspace 被删触发了 **attestation 防护** | 按 §3.3 修复（删 attestation+重启 gateway+重建 seed） |
| 3 | `TimeoutError: Agent 'assistant1' timed out after 3600s` | **agent 单次执行 3600s 超时**（卡在工具调用/长任务） | 杀掉批次，nohup 重启补跑（曾第三次才成功） |
| 4 | `Context overflow: prompt too large for the model` | evaluator 低估 completion，**上下文超模型窗口** | 重启后 run_batch 清 workspace 重置 session 上下文，通常未复现即可过 |

### 4.5 运维检查点（cron 每小时）

1. **归档数**：用 **Python** 精确统计（bash `while read` 会漏无换行最后一行）：
   ```python
   from pathlib import Path
   tasks = [l.strip() for l in Path("tasks_pending.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
   done  = [t for t in tasks if (Path("outputs")/t/"stats.json").exists()]
   print(len(done), "/", len(tasks))
   ```
   ⚠ 不要用 `find outputs -name stats.json` 全局数（会混入旧批次 r01 的归档虚高）。
2. **残留 http.server**：agent 展示 HTML 看板会残留 `python -m http.server` 进程锁
   workspace\data。每次 cron 检查主动
   `tasklist | grep http.server` → `taskkill //F //PID <pid>`（端口不固定，全端口扫）。
3. **进程存活**：中继 18888 / gateway 18789 / 批次 run_batch，死则按 §3.2 nohup 重启；
   重启批次前**先跑 `scripts/regenerate_eval_files.py`** 补 rubrics/scoring 副本（§2.4）。
4. **当前任务日志**：`logs/` 最新 q1 日志尾部 + `relay_18888.log` 是否仍在转发模型调用。
5. **批次结束判定**：全部 stats.json 到位（或 launch 打印「全部已完成」）→ 汇总。

---

## 5. 一次批跑的标准流程（速查）

```bash
# 0) 前置:杀残留 http.server、补 eval 副本
tasklist | grep http.server
python scripts/regenerate_eval_files.py

# 1) 启动中继 + 网关(第一次时)
NO_PROXY=127.0.0.1,localhost nohup python scripts/yibu_relay.py >> relay_18888.log 2>&1 &
NO_PROXY=127.0.0.1,localhost nohup node "C:\Program Files\nodejs\node.exe" C:\Users\<user>\AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs gateway run >> gateway_run.log 2>&1 &
curl http://127.0.0.1:18789/readyz        # 应返回 OK

# 2) 启动批次
nohup python scripts/launch_wcx_batch.py >> batch_run.log 2>&1 &

# 3) 监控(每小时):归档数 / 残留进程 / 中继日志 / 当前任务日志
# 4) 结束:全部 stats.json 就位 → 汇总,归档目录 outputs/<task>/
```

---

*文档对应实际运行:2026-08-26 ~ 2026-09-02,WCX 系列累计跑满 100 个任务留档。*
*相关记忆索引:[[openclaw-intranet-relay-model-calls]] [[wcx-batch-nohup-detached-run]] [[wcx-workspace-attestation-delete-guard]] [[wcx-tilde-path-fix-agents-md]] [[keep-tracked-secret-local-skip-worktree]] [[evaluator-toolcalls-collection-broken]]*
