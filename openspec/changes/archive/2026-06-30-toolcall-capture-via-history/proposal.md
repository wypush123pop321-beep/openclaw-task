## Why

rl14 批次验证(2026-06-29)暴露:落盘轨迹中**每个 turn 的 `tool_calls` 恒为空**——5 个任务全部如此,包括必然读过文件的满分任务。这直接违反了 `trajectory-capture` 既有 requirement「正常返回的 turn 捕获工具证据」。根因在 OC-SDK:它只从 WebSocket 实时事件流(`stream=="tool"`)采集工具调用,而 OpenClaw 是服务端自主 agent,内部跑完工具、最后一次性返回 final message,工具事件没在 `final` 触发 `break` 之前到达,于是 `ExecutionResult.tool_calls` 恒空。

后果:评测赖以反造假的工具证据全程空转,并已产生**误判**(02_task1 turn2 把数字与 oracle 逐个吻合、几乎必然真读了文件的 agent,判为「硬编码造假」)。需要换一条可靠的采集来源,并在评测侧加兜底,避免「采集为空」被错当成「agent 没调工具」。

## What Changes

- **工具证据采集改走 OC 服务端 `chat_history`**:每轮从 `gateway.chat_history(session_key)` 解析 `tool_use`/`tool_result` 消息并配对,回填 `TurnRecord.tool_calls`;不再单独依赖 SDK 易丢的实时事件流(`ExecutionResult.tool_calls`)。
- **新增探针验证前提**:实现第一步先确认 `chat_history` 返回的消息确实携带 `tool_use`/`tool_result` 块;若服务端未持久化工具步骤,则方案降级(详见 design 的开放问题)。
- **evaluator 兜底防误判**:当某 turn 的 `tool_calls` 为空时,evaluator MUST NOT 据此判定「造假 / 未真实读取文件」,与 `evidence_incomplete` 同等对待(证据缺失 ≠ 负面证据)。
- 不在本次范围:`files` 证据采集修复(同源问题,单列后续 change)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `trajectory-capture`: 工具证据的采集来源由「SDK 实时事件流」改为「OC `chat_history` 解析」,使「正常返回的 turn 捕获工具证据」这条既有 requirement 对服务端自主 agent 真正成立。
- `trajectory-evaluation`: 明确「`tool_calls` 为空 MUST NOT 作为造假 / 未达成的负面证据」,堵住采集缺口导致的假阴性误判。

## Impact

- 代码:
  - `openclaw_automation.py` — `fetch_history` 由「仅空内容兜底」提升为每轮采集;新增工具调用解析(`tool_use`/`tool_result` 配对)。
  - `trajectory.py` — `build_turn_record` 接入从 history 解析的 `tool_calls`;`TurnRecord` 采集语义更新。
  - `evaluator.py` — `_build_prompt` 增加「空 `tool_calls` 不得当负面证据」的判定指引。
- 依赖:OC-SDK `gateway.chat_history` API(已在用于兜底);依赖 OC 服务端在会话历史中持久化工具步骤(由探针验证)。
- 兼容性:无 BREAKING。仅令评测口径更准、修复假阴性,不改配置格式或对外接口。
