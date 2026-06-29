## 1. 探针验证(前置门禁)

- [x] 1.1 写最小探针脚本(`scripts/probe_chat_history.py`):连 gateway,建临时 agent 发"建文件+读文件"指令,dump `chat_history` 原始结构到 `logs/probe_chat_history.json`
- [x] 1.2 确认历史含工具步骤,字段映射:`role==assistant` 的 `content` 块 `type=="toolCall"`(字段 `id`/`name`/`arguments`);`role=="toolResult"` 消息(字段 `toolCallId`/`toolName`/`content`/`isError`);按 `id`↔`toolCallId` 配对。同时印证 `ExecutionResult.tool_calls`=0、`content_blocks` 仅 `text`
- [x] 1.3 降级未触发:探针确认 `chat_history` 含完整工具步骤,方向1 成立,无需降级

## 2. 工具调用解析(trajectory-capture)

- [x] 2.1 在 `trajectory.py` 实现 `extract_tool_calls(messages)`:按字段映射解析,`toolCall.id`↔`toolResult.toolCallId` 配对,保持调用顺序,`isError` 标注、缺 result 时 output=None
- [x] 2.2 扩展 `build_turn_record` 签名,接收外部解析的 `tool_calls`;未提供时回退 `ExecutionResult.tool_calls`(兼容)
- [x] 2.3 单元测试 `test_extract_tool_calls_from_history` + `test_extract_tool_calls_edge_cases`:配对/字段完整 + 无工具/缺 result/isError 边界,全部通过

## 3. 每轮采集接线(openclaw_automation.py)

- [x] 3.1 新增 `_safe_chat_history(agent)`,在 turn 循环 execute 前采 `before_history`、execute 后采 `after_history`(每轮调用,不再仅兜底)
- [x] 3.2 新增 `_new_messages_since(before, after)`(按 timestamp 界增量截取),调 `extract_tool_calls` 得 `turn_tool_calls`,经 `process_turn(..., tool_calls=)` 传入 `build_turn_record`
- [x] 3.3 `_safe_chat_history` 用 `agent.session_key`(被测 agent);解析全程 try/except,失败降级为空 + debug 日志,不中断主流程
- [x] 3.4 `evidence_incomplete` 修正:兜底轮若从 history 救回了非空 `tool_calls`,则置回 `False`

## 4. evaluator 兜底防误判(trajectory-evaluation)

- [x] 4.1 改 `DEFAULT_EVAL_PROMPT`:维度2 仅认「可确证反证」;铁律新增「`tool_calls` 为空 MUST NOT 据以判造假/硬编码,与 `evidence_incomplete` 同等」,删去原「声称调用工具但无 tool_calls→点名」的误判指引
- [x] 4.2 (可选,未实现)tool_calls 来源标注:落盘 turn_record 已含 `tool_calls`,来源标注价值有限,本次不做

## 5. 验证与回归

- [x] 5.1 重跑 02_task1:轨迹 Turn1 `tool_calls`=`[read, write]`,`read` 入参正是 D 盘 CSV 真实路径,与 agent 行为吻合(此前恒空)
- [x] 5.2 回归 02_task1:turn2 violations 转为真实 HTML 排名逻辑错误(引用磁盘产物具体行),不再有「硬编码造假/无 tool_calls」误判;outcome 由 max_turn 改善为 done,completion=0.8036(准确)
- [x] 5.3 区分确认:02 正是原误判案例,修复后 evaluator 基于真实证据判定;08_task1 原为 agent **真实**未调用工具(路径僵局,非采集缺陷),不属本 change 修复对象,未重跑
- [x] 5.4 修正 `trajectory.py` 顶部 docstring 与 `process_turn`/`build_turn_record` 注释,与「从 chat_history 解析」的新来源一致

## 6. 文档与归档

- [x] 6.1 `docs/CHANGELOG.md` 新增 v1.0.4 条目:说明工具证据采集来源由「SDK 实时事件流」改为「OC `chat_history` 解析」及 evaluator 兜底
- [x] 6.2 `openspec validate toolcall-capture-via-history` 通过
