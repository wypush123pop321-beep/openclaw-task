# Docker 沙箱：并发跑 dailyclawbench 任务（openclaw harness）

**一份镜像，一个容器 = 一个自包含沙箱**：容器内部自带一个 openclaw 网关 + 跑一个任务。
容器间用 bridge 网络隔离，各自的网关都监听 `127.0.0.1:18789` 但互不可见，agent 注册表各自独立，
所以 `evaluator` 等 agent 名不会撞 —— 可放心**任意数量并发**。

```
sandbox-taskNN 容器（独立 network namespace）
 ├─ openclaw gateway (自启, 127.0.0.1:18789, 独立 state)
 └─ harness_automation → 执行 agent(assistantX) + evaluator，跑该任务
```

## 文件一览

| 文件 | 作用 |
|------|------|
| `docker/Dockerfile` | 镜像：python3.12 + Node22 + openclaw CLI(2026.2.26) + 企业 CA + 依赖 |
| `docker/requirements-openclaw.txt` | openclaw harness Python 依赖（含 `cryptography`，握手签名必需）|
| `docker/entrypoint.sh` | 容器入口：播种网关配置/identity → 起网关 → 等 health → 跑 harness |
| `docker/entrypoint.py` | 修正 task_config（ref 绝对化、注入 serper-plus）后调 `harness_automation.py` |
| `docker/gateway/make_config.py` | 从本机 `~/.openclaw` 生成容器网关最小配置 + 拷 device identity |
| `docker/gateway/openclaw.json` | 生成物（含真实 key，gitignore）：网关 provider/tools/auth |
| `docker/certs/corp-ca-bundle.crt` | 企业代理 HTTPS 拦截用的 CA（放你环境的 CA；该目录已 gitignore）|
| `docker/run_tasks.sh` | **并发启动任意数量任务** |
| `docker/collect_trajectories.sh` | 汇总各任务轨迹到 `docker/out/collected/` 并打印摘要 |
| `docker-compose.yml`（仓库根）| 预置 `task02`/`task03` 两服务（等价示例，快速上手用）|

---

## 一次性准备（换机器才需重做）

### 1. 给 dockerd 配公司代理（`docker build` 拉镜像用，需 sudo）

dockerd 是独立 root 进程，不读 shell 的代理变量，必须单独配：

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null <<'EOF'
[Service]
Environment="HTTP_PROXY=http://<user>:<pass>@<proxy-host>:<port>"
Environment="HTTPS_PROXY=http://<user>:<pass>@<proxy-host>:<port>"
Environment="NO_PROXY=localhost,127.0.0.1,10.*,172.16.*"
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
```

> **坑**：systemd unit 里 `%` 是转义符，密码里的 `%` 必须双写 `%%`（如 `@@` 编码成 `%40%40` → 写 `%%40%%40`），否则该行被静默丢弃。
> 验证：`docker pull python:3.12-slim` 成功即代理生效。

### 2. 生成网关配置（从本机 `~/.openclaw` 抽 provider/key/identity）

```bash
python docker/gateway/make_config.py
```

生成 `docker/gateway/openclaw.json`（含 yibuapi provider + key、auth token 对齐 device-auth 的 operator token）
和 `docker/gateway/identity/`（device 身份，握手签名用）。二者含密钥、已 gitignore。

### 3. 构建镜像

```bash
docker compose build          # 代理由 compose 从宿主机 shell 自动透传
# 或：docker build -f docker/Dockerfile -t openclaw-task:latest .
```

### 4. 填 key

- `configs/user_proxy_model.json` —— simulator / evaluator 的 model/base_url/api_key（只读挂载，改完无需重建）。
- `skills/serper-plus/.env` —— `SERPER_API_KEY`（联网搜索用，随镜像打包；改完需重建）。
- 主 agent 模型 key 在网关配置里（步骤 2 已从本机带入）。

---

## 每次跑任务（核心 3 步）

```bash
# 1) 并发启动：任意数量任务号，或 all
docker/run_tasks.sh 02 03 04 09      # 指定若干
docker/run_tasks.sh all              # task_configs 下全部
TASKS_DETACH=0 docker/run_tasks.sh 02  # 前台跑单个（看实时输出）

# 2) 观察
docker ps --filter name=openclaw-task     # 还在跑哪些
docker logs -f openclaw-task04            # 跟某任务实时输出

# 3) 全部退出后收集轨迹
docker/collect_trajectories.sh
#  → docker/out/collected/taskNN_<session>.json + 摘要(outcome/turns/evals/tool_calls)
```

每个任务独立落盘：`docker/out/taskNN/logs/`（harness+evaluator 日志、`gateway.log`、`trajectories/`）、
`docker/out/taskNN/workspace/`（agent 工作空间）。

`docker-compose.yml` 里预置的 `task02`/`task03` 仍可用（`docker compose up task02`），
但要跑任意任务/任意数量，用 `run_tasks.sh` 更方便。

---

## 联网搜索：serper-plus skill

网关自带的 `web_search/web_fetch/browser` 在本环境不可用，改用 `skills/serper-plus`
（走 `yibuapi.com/serper` + `jina_reader` 中转，纯 Python 标准库）。entrypoint 会**自动**把它
注入每个执行 agent（拷进任务的 `skill_dir` + 加进 agent.skills），无需逐个改 task_config。
- 关闭注入：`-e DISABLE_SERPER=1`。
- key：`skills/serper-plus/.env` 的 `SERPER_API_KEY`。

---

## entrypoint 环境变量

| 变量 | 说明 |
|------|------|
| `TASK` | 任务号（如 `02`）；或 `CONFIG_FILE`（绝对路径，优先）|
| `HARNESS` | 默认 `openclaw` |
| `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` | 运行时代理；`NO_PROXY` 需含 `127.0.0.1,localhost` |
| `DISABLE_SERPER` | `=1` 关闭 serper 注入 |
| `USER_MAX_TURN` | 多轮上限（`run_tasks.sh` 默认 3；防病态任务无限多轮）|
| `QUERY_TIMEOUT` | 每轮超时秒数（`run_tasks.sh` 默认 600；覆盖 task_config 里的 3600）|
| `GATEWAY_WS_URL`/`SIMULATOR_CONFIG`/`WORKSPACE_BASE` | 可选覆盖 |

---

## 关键实现坑（排查记录，避免重踩）

- **协议版本**：`openclaw-sdk==2.1.0`(PyPI 最新)只说协议 v3，`__openclaw_compat__` = 2026.2.0~2026.2.28。
  网关 CLI 必须用 **2026.2.x**（取 `2026.2.26`）。用 2026.6.x 会 protocol mismatch。
- **握手签名**：需 `cryptography`（Ed25519）。已进 requirements。
- **鉴权**：不能用 auth=none（v3 客户端要等网关 challenge 才发 connect）。必须 auth=token+device identity；
  且客户端出示的是 `device-auth.json` 的 operator token，`make_config.py` 已把 `gateway.auth.token` 对齐它。
- **配置修正**：task_config 的 `user_dir.path=null` + `rubrics_ref` 相对路径 → 直接加载 `FileNotFoundError`；
  entrypoint 把 ref 改成绝对路径。
- **Node**：openclaw 要 node≥22.19，用官方二进制 tarball（`v22.22.1`）。
- **网关启动**：不加 `--force`（需 fuser/lsof，未装；全新容器也无需）。
- **多轮容错**：`user_simulator` 调用失败不再丢轨迹（`src/executor.py` 已捕获，优雅收尾并落盘）。

---

## 扩容与注意

- 每个沙箱 = 1 网关(Node) + 1 harness(Python)，约数百 MB 内存；建 agent 各等 90s，故起步 ~3 分钟才进 query。
- 并发数受主机 CPU/内存限制；量大时分批调用 `run_tasks.sh`。
- 首次运行 `docker/out` 会被容器以 root 写入；清理用 `sudo rm -rf docker/out`。
