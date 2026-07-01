## MODIFIED Requirements

### Requirement: 自 OC 会话历史解析工具调用证据

系统 SHALL 在每个 turn 结束后,经 `harness-adapter` 的 history 能力拉取该会话消息(OpenClaw 经 `chat_history`,其它 harness 经其等价机制如流式收集),并解析其中的 `tool_use`/`tool_result`(或等价结构),按调用顺序配对成 `tool_calls`(`tool`/`input`/`output`)写入该 turn 记录。该拉取与解析 SHALL 覆盖本轮新增的工具步骤,系统 MUST NOT 仅在空内容兜底路径才拉取历史。`tool_calls` 解析 SHALL 经 adapter 接口或中立 history 数据完成,核心层 MUST NOT 直接调用 harness 专属网关方法。当解析后某轮确无工具步骤、且该轮系经 history 兜底恢复时,该轮仍 SHALL 标 `evidence_incomplete`。

#### Scenario: 每轮解析会话历史中的工具步骤
- **WHEN** 某 turn 的 agent 在 harness 服务端内部调用了工具(读文件/执行代码等),且这些步骤被持久化进会话历史
- **THEN** 系统 SHALL 经 adapter 的 history 能力解析出对应的 `tool_use`/`tool_result` 并配对为 `tool_calls` 写入该 turn 记录

#### Scenario: 仅截取本轮新增的工具步骤
- **WHEN** 会话历史中累积了此前各轮的工具步骤
- **THEN** 系统 SHALL 仅把本 turn 新增的工具步骤计入该轮 `tool_calls`,MUST NOT 把往轮工具步骤重复计入当前 turn

#### Scenario: 历史中确无工具步骤
- **WHEN** 解析某轮会话历史后未发现任何工具步骤
- **THEN** 系统 SHALL 令该轮 `tool_calls` 为空,且该空值 MUST NOT 被下游当作"agent 造假"的负面证据(由 trajectory-evaluation 保证)

### Requirement: 以磁盘真相校正文件证据

当需要核验 agent 生成的文件时,系统 SHALL 经 `harness-adapter` 的文件证据能力(按 agent 寻址读取工作区真相:`read_workspace` / `get_file`)从**被测 agent 的真实工作区**读取文件,以此作为文件证据的事实来源。系统 MUST NOT 仅采信 `TurnResult.files` 的自报载荷,也 MUST NOT 直接调用 harness 专属网关文件方法。当 adapter 不具备文件证据能力时,系统 SHALL 跳过磁盘核验并按"证据不完整"语义降级。

#### Scenario: 声称生成文件以磁盘为准
- **WHEN** agent 在回复或 `files` 中声称生成了某文件
- **THEN** 系统 SHALL 经 adapter 的 `get_file(被测 agent, name)` 核对该文件在被测 agent 工作区是否真实存在及其内容,并以该磁盘结果(而非自报)作为下游评估依据

#### Scenario: 跨 agent 取证不依赖工具沙箱
- **WHEN** 取证方(harness 或独立 evaluator agent)与被测 agent 不是同一个 agent
- **THEN** 系统 SHALL 经 adapter 按 agent 寻址的文件证据能力读取被测 agent 文件,而不要求任一 agent 具备跨工作区的执行内工具权限
