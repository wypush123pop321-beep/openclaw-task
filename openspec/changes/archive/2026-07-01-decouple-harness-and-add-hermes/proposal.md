## Why

框架把 OpenClaw SDK 的调用散布在 5 个文件(`openclaw_automation.py`/`trajectory.py`/`evaluator.py`/`utils/connection.py`/`scripts/probe_chat_history.py`),编排/轨迹/评估三层直接依赖 `openclaw_sdk` 的类型与网关方法(`chat_history`/`create_agent`/`agents_update`/`agents_files_*`/`sessions_reset`/`StructuredOutput`),被钉死在单一 harness 上。本变更一次性交付两件事:**(A) 把核心三层与具体 harness 解耦到中立的 `HarnessAdapter` 抽象之后;(B) 接入第二个 harness——Nous Research 的 Hermes(经 ACP)**,用一个真实的第二实现证明"换 harness 不改核心",并支持 config 在 OpenClaw / Hermes 间切换。

> 背景:解耦与 Hermes 此前各有一份已归档的设计探索(`archive/2026-06-25-decouple-harness-adapter`、`add-hermes-adapter`),但基于解耦前的旧 evaluator/trajectory。主线随后独立重写了评估管线(per-query `EvaluateConfig`、持久 evaluator + 每轮 `sessions_reset`、`_pin_model` 钉模型、oracle/rubric 文件隔离、`chat_history` 采集 tool_calls)。本变更在**当前主线**上重做解耦接缝,合并这两项特性。

## What Changes

**阶段 A — 解耦(行为保持的重构)**
- 新增 `HarnessAdapter` 抽象 + `Capability` 能力枚举;编排/轨迹/评估只依赖该接口,不再 `import openclaw_sdk`。
- 新增中立类型 `TurnResult`/`AgentSpec`(复用本就中立的 `ToolCallEvidence`/`FileEvidence`)与中立异常 `HarnessError`(传输/执行子类);adapter 内部消化可恢复抖动,不可恢复才上抛中立异常。
- 新增 `OpenClawAdapter`,把现有全部 OpenClaw 调用收拢于内部、逻辑不变;其中把主线的 **`_pin_model`(`agents_update` 钉模型)下沉为 `ensure_agent` 按 `AgentSpec.model` 钉模型**、**`sessions_reset` 表达为 adapter 的会话重置能力**、**`chat_history` 采集 tool_calls 经 adapter 的 history 能力**。
- 新增注册表 + 配置段 `harness.type`(默认 `openclaw`);顶层 `gateway_ws_url`/`api_key`/`gateway_timeout`/`workspace_base` 折叠进 OpenClaw 连接配置,**现有 config 原样可跑**。
- 可选能力(文件证据/结构化输出/健康检查/history 兜底/会话重置)由 `adapter.capabilities` 声明式驱动,缺失即落既有降级路径。

**阶段 B — 接入 Hermes**
- 新增 `HermesAdapter`(`harness/hermes/`):经 ACP(`agent-client-protocol`)以 stdio 子进程驱动 `hermes-acp`,框架担任 ACP 客户端;`spawn_agent_process` 管生命周期,`session_update`/`request_permission` 回调收集成中立 `TurnResult`,`request_permission` 自动放行。
- `(agent, session) → ACP session_id` 忠实映射(隔离决策归核心层);仅声明 `FILE_EVIDENCE`(cwd 为本地目录),其余能力不声明走降级。
- registry 注册 `harness.type="hermes"`(惰性导入);config `connection` 显式托管 `model`/`provider`/`api_key`/`base_url`,adapter 翻译为子进程 env 与 `set_session_model`;握手用 `use_unstable_protocol=True`。
- evaluator 的"无 `STRUCTURED_OUTPUT`"兜底加入**重试 + 强约束提示**(harness 无关,落核心层)。

## Capabilities

### New Capabilities
- `harness-adapter`: 框架与任意 harness 之间的中立契约——adapter 接口、`Capability` 能力枚举、中立结果/异常类型、按 `harness.type` 选择实现的注册表与配置后向兼容;`OpenClawAdapter` 与 `HermesAdapter` 两个实现;能力声明与降级、Hermes 会话映射与子进程生命周期、凭证 config 托管。

### Modified Capabilities
- `trajectory-capture`: 文件证据与 tool_calls 采集从绑定 OpenClaw 网关方法(`agents.files.*`/`chat_history`)改为绑定 `harness-adapter` 能力;缺该能力按"证据不完整"降级。磁盘真相、`chat_history` 采集语义、NUL 剥离、证据完整性标注等行为保持不变。
- `trajectory-evaluation`: evaluator 经 `harness-adapter` 驱动独立评估 agent(措辞中立化);结构化输出从 `StructuredOutput.execute` 改为绑定 adapter 能力,缺失走解析兜底**并重试**;持久 evaluator 的每轮重置经 adapter 会话重置能力。per-query 配置、oracle/rubric 隔离、ScoringSpec、引证等行为保持不变。

## Impact

- **新增代码**:`harness/` 包(接口/能力/中立类型/异常/注册表/`openclaw/`/`hermes/`);`test/test_hermes_adapter.py` 等;`configs/config_hermes.json`。
- **改核心**:`openclaw_automation.py`(`AgentManager`/`_pin_model`/`create_evaluator`/`run` 面向 `HarnessAdapter`)、`trajectory.py`/`evaluator.py`(去 `openclaw_sdk`、改中立类型与能力、兜底重试);`utils/connection.py`(`ResilientGateway`)迁入 `OpenClawAdapter`。
- **新增依赖**:`agent-client-protocol`(ACP SDK);可访问的 Hermes 源码(`python -m acp_adapter`,源码集成)。
- **配置**:新增可选 `harness` 段;旧字段兼容,无需迁移。
- **验收基线**:阶段 A 解耦前后同一份 OpenClaw config MUST 跑出一致的 `trajectory` 与 `evaluator_use.log`、既有测试全绿;阶段 B Hermes 经 `config_hermes.json` 端到端跑通(多会话记忆/文件证据/评估兜底)。
- **可复用资产**:tag `pre-rebase-0630` 中零冲突的 `harness/**` 代码、`test_hermes_adapter.py`、`config_hermes.json` 及两份归档设计可直接搬用,主要新工作在"核心接缝"对接主线新结构。
