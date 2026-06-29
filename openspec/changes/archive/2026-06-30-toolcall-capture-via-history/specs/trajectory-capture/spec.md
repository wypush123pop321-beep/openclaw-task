## MODIFIED Requirements

### Requirement: 逐轮捕获带证据的执行记录

系统 SHALL 在多轮对话执行过程中,为每个 turn 留存 agent 的执行证据:用户输入、agent 文本回复(`content`)、工具调用证据(`tool_calls`,含 `tool`/`input`/`output`/`duration_ms`)、`stop_reason`。工具调用证据 SHALL 来自对 OC 服务端会话历史(`chat_history`)的解析(将 `tool_use` 与其对应 `tool_result` 配对),系统 MUST NOT 仅依赖 OC-SDK `ExecutionResult.tool_calls`——后者只从 WebSocket 实时事件流采集,对"服务端自主执行、一次性返回 final message"的 agent 恒为空。系统 MUST NOT 在执行后只保留 `content` 文本而丢弃工具证据。

#### Scenario: 正常返回的 turn 从会话历史捕获工具证据
- **WHEN** `agent.execute()` 正常返回(非兜底),且该轮在 OC 会话历史中留有工具调用记录
- **THEN** 系统 SHALL 从 `chat_history` 解析出本轮的 `tool_calls`(含工具入参与返回值)并写入该 turn 记录,而不仅是 `content` 文本;MUST NOT 因 `ExecutionResult.tool_calls` 为空就记为"无工具调用"

#### Scenario: 多轮对话按顺序累积
- **WHEN** 一个 query 经历多个 turn 的 agent⇄模拟用户往返
- **THEN** 系统 SHALL 按 turn 顺序保留每一轮的用户输入与 agent 证据,形成可供 evaluator 审阅的运行记录

## ADDED Requirements

### Requirement: 自 OC 会话历史解析工具调用证据

系统 SHALL 在每个 turn 结束后,经 `gateway.chat_history(session_key)` 拉取该会话消息,并解析其中的 `tool_use`/`tool_result`(或网关等价结构)消息,按调用顺序配对成 `tool_calls`(`tool`/`input`/`output`)写入该 turn 记录。该拉取与解析 SHALL 覆盖本轮新增的工具步骤,系统 MUST NOT 仅在空内容兜底路径才拉取历史。当解析后某轮确无工具步骤、且该轮系经 `history_fallback` 兜底恢复时,该轮仍 SHALL 标 `evidence_incomplete`。

#### Scenario: 每轮解析会话历史中的工具步骤
- **WHEN** 某 turn 的 agent 在 OC 服务端内部调用了工具(读文件/执行代码等),且这些步骤被持久化进会话历史
- **THEN** 系统 SHALL 从该会话历史解析出对应的 `tool_use`/`tool_result` 并配对为 `tool_calls` 写入该 turn 记录

#### Scenario: 仅截取本轮新增的工具步骤
- **WHEN** 会话历史中累积了此前各轮的工具步骤
- **THEN** 系统 SHALL 仅把本 turn 新增的工具步骤计入该轮 `tool_calls`,MUST NOT 把往轮工具步骤重复计入当前 turn

#### Scenario: 历史中确无工具步骤
- **WHEN** 解析某轮会话历史后未发现任何工具步骤
- **THEN** 系统 SHALL 令该轮 `tool_calls` 为空,且该空值 MUST NOT 被下游当作"agent 造假"的负面证据(由 trajectory-evaluation 保证)
