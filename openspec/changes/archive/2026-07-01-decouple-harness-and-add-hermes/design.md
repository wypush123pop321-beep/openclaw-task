## Context

核心三层(`openclaw_automation.py`/`trajectory.py`/`evaluator.py`,及 `utils/connection.py`)直接依赖 `openclaw_sdk`:`chat_history`(9 处,采集 tool_calls)、`create_agent`、`agents_update`(`_pin_model` 钉裁判模型)、`agents_files_*`(文件证据)、`sessions_reset`(持久 evaluator 每轮重置)、`StructuredOutput`(结构化裁决)、`/healthz`。本变更在**当前主线**上做两件事:解耦到 `HarnessAdapter`,并接入第二个 harness(Hermes/ACP)。

此前的解耦与 Hermes 探索(tag `pre-rebase-0630`)基于**解耦前**的旧 evaluator/trajectory;主线随后重写了评估管线(per-query `EvaluateConfig`、持久 evaluator + `sessions_reset`、`_pin_model`、oracle/rubric 文件隔离、`chat_history` 采集、`ScoringSpec`)。直接 rebase 等于在冲突标记里重做重构,故改为在主线上重新落接缝。可复用资产:tag 中**零冲突**的 `harness/**` 包、`HermesAdapter`、`test_hermes_adapter.py`、`config_hermes.json` 与两份归档设计;主要新工作是把核心接缝对接主线新结构。

## Goals / Non-Goals

**Goals:**
- 编排/轨迹/评估只依赖 `HarnessAdapter` + 中立类型;`openclaw_sdk` 仅存于 `OpenClawAdapter` 内部。
- `OpenClawAdapter` 行为保持:同一份 OpenClaw config 解耦前后跑出一致 trajectory/评估日志、既有测试全绿。
- `HermesAdapter`(ACP)经 config 可选,端到端跑通(多会话记忆/文件证据/评估兜底)。
- 主线既有特性(per-query 评估、持久 evaluator + 每轮重置、`_pin_model`、oracle/rubric 隔离、`chat_history` 采集)在解耦后全部保留。

**Non-Goals:**
- 不改任何外部行为(多轮编排、simulator、rubric、ScoringSpec、评估输出格式)。
- 不支持"多任务共用单 Hermes 子进程的并发在途"(本期一任务一进程·多会话·顺序驱动)。
- 不接入除 OpenClaw / Hermes 外的 harness。

## Decisions

### D1 中立契约:`HarnessAdapter` + `Capability`
必需面 `ensure_agent`/`execute`;能力位 `MULTI_AGENT`/`FILE_EVIDENCE`/`STRUCTURED_OUTPUT`/`HEALTHZ`/`HISTORY_FALLBACK`/**`SESSION_RESET`(新增)**。核心调用可选能力前查 `adapter.capabilities`,缺失即降级。中立类型 `TurnResult`/`AgentSpec`(`model`/`skills`),证据 `ToolCallEvidence`(`input: Any` 原生 JSON)/`FileEvidence`(含 `path`)。

### D2 主线耦合点 → adapter 的映射(本变更相对旧探索的增量)
| 主线直接调用 | 解耦后 |
|---|---|
| `gateway.chat_history` 采集 tool_calls | adapter history 能力;`extract_tool_calls`(操作中立 dict)留核心层,经 `adapter.fetch_history` 取数 |
| `_pin_model` via `gateway.agents_update` | `OpenClawAdapter.ensure_agent` 按 `AgentSpec.model` 钉模型(内部 agents_update) |
| `gateway.sessions_reset`(每轮重置) | 新增 `SESSION_RESET` 能力 + `adapter.reset_session`;OpenClaw 实现 sessions_reset,Hermes 不声明→跳过 |
| `agents_files_get/list/set` | `get_file`/`read_workspace`/`put_file` |
| `StructuredOutput.execute` | `adapter.structured`;缺该能力→解析兜底 + 重试(核心层,harness 无关) |

### D3 OpenClawAdapter:行为保持地收拢
`utils/connection.py` 的 `ResilientGateway` + 工厂整体迁入;`build_openclaw_client`/`create_agent`/`get_agent.execute`/`chat_history`/`agents_files_*`/`sessions_reset`/`agents_update`/`StructuredOutput`/`/healthz` 收于内部。声明全能力集(含 `SESSION_RESET`)。

### D4 HermesAdapter:ACP 子进程 + 收集器(复用 tag 成果)
`spawn_agent_process` 起 `hermes-acp`(`use_unstable_protocol=True`),`Client.session_update`/`request_permission`(自动放行)收集成 `TurnResult`;`(agent,session)→ACP session_id` 忠实映射;仅声明 `FILE_EVIDENCE`(cwd 本地);config `connection` 托管 `model`/`provider`/`api_key`/`base_url`→子进程 env + `set_session_model`。

### D5 结构化兜底重试(核心层,harness 无关)
无 `STRUCTURED_OUTPUT` 时:`execute` 取自由文本 → `parse_structured_text`;失败则追加"仅输出 JSON"强约束重试有限次(默认 3),耗尽抛 `StructuredParseError`。

### D6 配置后向兼容
`harness.type` 默认 `openclaw`;顶层 `gateway_ws_url`/`api_key`/`gateway_timeout`/`workspace_base` 在无 `harness` 段时折叠进 OpenClaw 连接;未知 type 显式报错;adapter 惰性导入。

### D7 实施顺序:先 A 后 B,各自可验收
阶段 A 解耦完成即用 OpenClaw config 跑回归对齐基线;再叠加阶段 B Hermes。降低单步风险、便于 review。

## Risks / Trade-offs

- [解耦遗漏某个 `openclaw_sdk` 调用 → 核心仍耦合] → 以 `grep -rn openclaw_sdk` 核心三层为零作为验收门;CI/测试覆盖。
- [`_pin_model`/`sessions_reset` 下沉后行为偏移(模型没钉上/会话没重置)] → 阶段 A 回归比对 `evaluator_use.log`(裁判模型字段)与防锚定行为。
- [`chat_history` 采集移到 adapter 后 tool_calls 丢失] → 保留 `extract_tool_calls` 中立解析 + 对齐基线 trajectory 的 tool_calls。
- [Hermes 经公司 MITM 代理的 TLS 信任] → 环境前置(代理 env + 企业 CA 信任),非 adapter 逻辑,文档明示。
- [ACP SDK 命名/版本差异] → 钉 `agent-client-protocol` 版本,封装薄 client 层。

## Migration Plan

1. 阶段 A:建 `harness/` 包 + `OpenClawAdapter`(迁 `utils/connection.py`);改 `openclaw_automation`/`trajectory`/`evaluator` 面向 adapter;改测试构造中立类型。回归:OpenClaw config 对齐基线 + 既有测试全绿。
2. 阶段 B:加 `agent-client-protocol` 依赖;搬入 `harness/hermes/` + 注册 `hermes`;evaluator 兜底重试;加 `config_hermes.json` + `test_hermes_adapter.py`。验证:Hermes 端到端跑通。
3. 回滚:`harness.type` 改回 `openclaw` 或移除 `harness` 段即恢复 OpenClaw 路径;Hermes 为纯增量。

## Open Questions

- `SESSION_RESET` 能力的接口形态(`reset_session(agent, session)` 单方法 vs execute 选项)——实现首步定。
- `chat_history` 采集究竟留核心层(经 `fetch_history`)还是下沉进 `OpenClawAdapter.execute` 填充 `TurnResult.tool_calls`——倾向前者(改动小、保留主线 `extract_tool_calls`),实现时确认对齐基线。
- Hermes provider→env 变量名映射表(照 `.env.example` 钉);ACP SDK 安装版方法签名核对。
