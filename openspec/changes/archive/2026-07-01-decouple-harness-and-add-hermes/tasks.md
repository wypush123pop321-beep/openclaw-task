## 1. 阶段A·脚手架:harness 包与中立类型

- [x] 1.1 建 `harness/` 包:`capabilities.py`(`Capability` 枚举,含新增 `SESSION_RESET`)、`errors.py`(`HarnessError`/传输/执行子类)
- [x] 1.2 `harness/types.py`:`TurnResult`/`AgentSpec`(`model`/`skills`)、`ToolCallEvidence`(`input: Any`)/`FileEvidence`(含 `path`)、`FileContent`/`WorkspaceFile`/`WorkspaceTruth`/`HealthStatus`(可直接搬 tag `pre-rebase-0630` 版本)
- [x] 1.3 `harness/base.py`:`HarnessAdapter` 抽象(必需 `ensure_agent`/`execute`;能力面 `fetch_history`/`read_workspace`/`get_file`/`put_file`/`structured`/`health`/**`reset_session`**)
- [x] 1.4 `harness/registry.py`:`create_adapter(harness_config)` 按 `type` 惰性构造;未知 type 报错

## 2. 阶段A·OpenClawAdapter(行为保持地收拢)

- [x] 2.1 迁 `utils/connection.py` 的 `ResilientGateway` + `build_openclaw_client` + `/healthz` 进 `harness/openclaw/connection.py`
- [x] 2.2 `harness/openclaw/adapter.py`:`__aenter__/__aexit__` 建/拆 client;`execute` 收纳 `get_agent.execute` + `chat_history` 兜底,映射 `ExecutionResult→TurnResult`
- [x] 2.3 `ensure_agent` 收纳 `create_agent` + **`_pin_model`(按 `AgentSpec.model` 经 `agents_update` 钉模型)**
- [x] 2.4 文件证据:`read_workspace`/`get_file`/`put_file`(`agents_files_list/get/set`);`fetch_history`(`chat_history`);`structured`(`StructuredOutput`);**`reset_session`(`sessions_reset`)**
- [x] 2.5 声明全能力集(含 `SESSION_RESET`);`GatewayError`/超时 → 中立 `HarnessError`

## 3. 阶段A·核心三层改为面向 adapter

- [x] 3.1 `trajectory.py`:去 `openclaw_sdk`;`build_turn_record` 接 `TurnResult`;`capture_file_evidence` 用 `adapter.read_workspace/get_file`(缺 `FILE_EVIDENCE` 降级);保留 `extract_tool_calls`(中立 dict 解析)+ NUL 剥离
- [x] 3.2 `evaluator.py`:去 `openclaw_sdk`;结构化走 `adapter.structured`,缺能力则解析兜底 + 重试 + 强约束(D5);每轮重置走 `adapter.reset_session`(缺 `SESSION_RESET` 跳过);保留 per-query 配置/oracle/rubric 隔离/ScoringSpec
- [x] 3.3 `openclaw_automation.py`:`AgentManager` 改经 `adapter.ensure_agent`(下沉 `_pin_model`);`create_evaluator` 面向 adapter;`chat_history` 采集 tool_calls 经 `adapter.fetch_history`;`run` 用 `create_adapter` 构造并经 `async with` 管理生命周期
- [x] 3.4 `AutomationConfig` 加可选 `harness` 段 + `_fold_harness_connection` 校验器(顶层连接字段折叠;默认 openclaw)

## 4. 阶段A·测试与回归对齐

- [x] 4.1 改 `test/test_trajectory.py`/`test/test_evaluator.py` 构造中立类型(不再造 `openclaw_sdk` 类型),行为断言不变
- [x] 4.2 新增 `test/test_config_compat.py`(顶层折叠 / 显式 harness / 未知 type 报错)与 `test/test_adapter_mapping.py`(原生→中立映射)
- [x] 4.3 验收门:`grep -rn openclaw_sdk` 核心三层为零;既有测试全绿(纯逻辑测试 trajectory/evaluator/scoring/config_compat/adapter_mapping 全绿;test_simulator 因公司代理拦截真实 LLM 调用失败,非本变更回归)
- [x] 4.4 回归对齐:同一份 OpenClaw config 解耦后经真实 gateway 端到端跑通(`configs/01_…时效冲突检测_q1.json`,run `20260630T190418`):tool_calls 经 `adapter.fetch_history` 采集(turn1/2 各 3 次 read,input 原生 JSON)、裁判模型 `gemini-3-flash-preview` 独立钉死、每轮 `reset_session` 防锚定(completion 0.0→1.0)、12 条 rubric_checks + gate_status、文件证据 18/轮、轨迹落盘 outcome=done;隔离文件字节级还原无 git diff

## 5. 阶段B·Hermes 适配(复用 tag 成果)

- [x] 5.1 依赖加 `agent-client-protocol`;核对安装版方法签名记于 docstring
- [x] 5.2 搬入 `harness/hermes/`:`config.py`(launch + 凭证→env + `use_unstable_protocol`)、`collector.py`(`HermesClientSink` + `TurnCollector`,session_update 累加、request_permission 自动放行)、`adapter.py`(spawn 生命周期、`(agent,session)→uuid` 映射、收集器式 execute、本地文件证据)
- [x] 5.3 `registry` 注册 `hermes`(惰性导入);仅声明 `FILE_EVIDENCE`
- [x] 5.4 新增 `configs/config_hermes.json`(仅加 `harness` 段)

## 6. 阶段B·测试与端到端

- [x] 6.1 搬入/对齐 `test/test_hermes_adapter.py`(会话映射/收集器组装/权限/能力/本地文件证据/execute 流/兜底重试),全绿
- [x] 6.2 端到端:用 `config_hermes.json` 经真实 `hermes-acp` 子进程跑通(`HERMES_HOME=~/.hermes`,provider=custom 指向 yibuapi 经代理):多会话记忆 Q1(test)答"上海"→ Q3(test 复用同一 ACP 会话 `60c00bbd`)从记忆答"上海"、Q2(eval 隔离会话)答"没有上下文";`(agent,session)→ACP session_id` 忠实映射、权限自动放行、本地文件证据均验证;`所有任务执行完成` exit 0。环境前置:`~/.hermes/config.yaml`(model.api_key)+ `~/.hermes/.env`(OPENAI_*/代理)
- [x] 6.3 回归:阶段 B 落地后 OpenClaw 路径既有测试仍全绿(证明 Hermes 为纯增量)
