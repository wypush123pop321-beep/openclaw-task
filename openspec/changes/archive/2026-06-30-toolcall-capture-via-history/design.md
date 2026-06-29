## Context

当前 `TurnRecord.tool_calls` 直取 `ExecutionResult.tool_calls`(`trajectory.py:build_turn_record`)。而 OC-SDK 只在 WebSocket 实时事件流里采集工具调用:`EventType.AGENT` 且 `stream=="tool"`,需 `phase=="call"`→`phase=="result"` 配对才 append(`core/agent.py:1077-1117`);收到 chat `state=="final"` 立即 `break`(1043)。OpenClaw 是服务端自主 agent——内部跑完工具、最后一次性返回 final message,工具事件没在 `final` 前到达,于是 `tool_calls` 恒空。rl14 批次 5 个任务、每一轮均为 0,包括必然读过文件的满分任务。

`chat_history` 通道已经可用:`openclaw_automation.py:684` 的 `fetch_history()` 调 `agent._client.gateway.chat_history(session_key, limit=…)`,但目前仅在「`result.content` 为空」的兜底路径触发,且只用 `extract_message_text` 提取 assistant 纯文本、`is_assistant_message` 只认 `role=="assistant"`,把工具消息全过滤了。

## Goals / Non-Goals

**Goals:**
- 每个 turn 从 OC 服务端 `chat_history` 解析 `tool_use`/`tool_result` 并配对,回填 `TurnRecord.tool_calls`,使其对服务端自主 agent 真实非空。
- evaluator 不再因「空 `tool_calls`」误判 agent 造假/未读文件。
- 解析失败时安全降级,不阻断任务执行。

**Non-Goals:**
- `files` 证据采集修复(同源问题,另立 change)。
- 修改 OC-SDK 源码(在项目侧解析,不动 site-packages)。
- 改动评分公式、权重或 bucket 映射。

## Decisions

**D1:数据源选 `chat_history`,不修事件流、不用回调。**
回调(`on_tool_call`/`on_tool_result`)与 `ExecutionResult.tool_calls` **同源**——都在 SDK 那个 `stream=="tool"` 分支里被同一批事件驱动(1089/1110 紧邻 1102 的 append),工具事件没来则两者一起空,且同受 `final → break` 制约。换消费姿势填不平数据缺口。`chat_history` 是 OC 服务端的权威会话记录,工具步骤在那里(待探针确认)。
- 备选(否决):扩展 SDK `ContentBlock` + `_parse_content` 从 final message 解析 `tool_use` 块。否决因 final message 不一定承载工具块、且需改 SDK 模型(`ContentBlock` 仅有 text/thinking)。

**D2:每轮采集 + 增量截取。**
`fetch_history()` 由「仅空内容兜底」提升为**每轮**调用一次。用「本轮发送前 `before_history` / 本轮结束后 `after_history`」做 diff(复用现有 `find_new_assistant_text` 的同款 before/after 思路),只把本轮**新增**的工具消息计入当前 turn,避免往轮工具步骤被重复计入。配对优先用 `tool_use_id` 关联 `tool_use`↔`tool_result`;无 id 时按出现顺序配对。

**D3:解析在 harness 侧,采集与 build 解耦。**
新增 `extract_tool_calls(messages) -> list[ToolCallEvidence]`(放 `trajectory.py` 或 automation),把解析结果经 `build_turn_record` 的入参传入(而非依赖 `result.tool_calls`)。`build_turn_record` 签名扩展以接收外部解析的 `tool_calls`;`result.tool_calls` 退化为「有则合并、无则忽略」的兼容来源。

**D4:会话寻址用被测 agent 的 `session_key`。**
`chat_history` MUST 取**被测执行 agent**(如 `assistant1`)的 `session_key`,而非 evaluator 的。evaluator 会话每轮 `sessions.reset` 不影响被测 agent 历史,两者隔离。

**D5:evaluator 兜底防误判。**
`evaluator.py:_build_prompt` 增加判定指引:空 `tool_calls` 与 `evidence_incomplete` 同等对待,MUST NOT 据此判造假;「声称与证据矛盾」须以可确证反证(磁盘真相/oracle 冲突)为据。

**D6:探针前置。**
实现第一步先用最小探针 dump 一个真实 agent 的 `chat_history` 原始消息结构,确认含 `tool_use`/`tool_result`、记录其字段名(role/type/tool_use_id 等)。探针结果决定解析器字段映射;若历史不含工具步骤,触发降级方案(见 Open Questions)。

## Risks / Trade-offs

- [chat_history 不持久化工具步骤] → 探针先验证。若确不含,降级:(a) 查 OC 是否有 run 详情/审计接口取工具轨迹;(b) 退守仅 D5(evaluator 不误判),正面工具证据暂缺但消除假阴性。
- [增量截取错位,工具步骤算到错误 turn] → 用 before/after 历史 diff + 消息唯一标识(id/timestamp)定位本轮边界,不用纯计数。
- [tool_use/tool_result 跨消息配对失败] → 优先 `tool_use_id` 关联;缺 id 时顺序配对并标注不确定。
- [每轮多一次 chat_history 调用的开销] → `limit` 受控、与现有兜底同 API,单轮一次,开销可忽略。
- [解析异常阻断任务] → 解析包 try/except,失败则降级为空 `tool_calls` + 记录,绝不抛断主流程(沿用现有 `capture_file_evidence` 的容错姿势)。

## Migration Plan

1. 探针验证 `chat_history` 结构(不改主流程)。
2. 实现 `extract_tool_calls` + 每轮采集,**先只落盘对比**:跑 rl14 子集,确认 `tool_calls` 非空且与 agent 实际行为吻合。
3. 接入 D5 evaluator 兜底。
4. 回归:重跑 02_task1 / 08_task1,确认 02 turn2 不再被误判为「硬编码造假」。
- 回滚:解析逻辑独立、默认容错降级;如需关闭,可加开关回退到当前「仅兜底拉历史」的行为。

## Open Questions

- `chat_history` 返回的工具消息确切结构:`role`/`type` 取值、是否带 `tool_use_id`、`input`/`output` 字段名?(探针确认)
- OC 是否对工具步骤的持久化有保留期或截断?长会话下 `limit` 是否够覆盖本轮?
- 若历史确无工具步骤,OC 是否提供 run 级别的工具轨迹接口可替代?(降级路径选型)
