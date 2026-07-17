## Why

多轮任务里，simulator 调用 reasoning 类模型（如 gemini-3.5-flash 经 OpenAI 兼容接口）时会出现 `usage.completion_tokens` 非零但 `choices[0].message.content` 为空的情况——token 全进了 reasoning 通道，最终 content 为空。当前三层代码对此均无防护：simulator 原样返回空串 → executor 把空串当作下一轮追问 → openclaw 客户端把空消息发给网关，网关抛 `message or attachment required`，被误分类为"连接异常"进入 history_fallback 空转约一小时才失败，轨迹落盘被拖延甚至丢失。实测于 task03 端到端跑，agent 首轮已交付合格产物却因此空转、结构化轨迹未生成。

## What Changes

- **simulator 取值兜底（根因）**：`chat()` 从模型回复取文本时，content 为空 SHALL 回退到 reasoning 字段（如 `reasoning_content`），仍空则有限重试，最终仍空返回显式收尾标记而非空串。
- **executor 空回复防护（拦截点）**：多轮循环中空 `user_reply` SHALL NOT 被原样作为下一轮 `current_query` 发给下游；视作收尾（Task_Done 语义）或有限重试，杜绝把空消息喂给网关。与既有的 agent 空回复防护形成对称。
- **client 错误分类（止血）**：`message or attachment required` 属确定性非法请求，SHALL NOT 与连接类 `GatewayError` 混走 fallback + 多次重试；应快速失败，避免长时间空转。

## Capabilities

### New Capabilities
- `multi-turn-execution`: 首次为 executor 多轮查询循环与 openclaw 客户端错误分类建立 spec，收录本次两条需求（空 user_reply 不得下发、确定性非法请求快速失败）。既有多轮编排行为暂不追溯补全，仅纳入本次改动点。

### Modified Capabilities
- `user-simulation`: 新增一条需求——simulator 返回值健壮性：`chat()` 永不返回空串，空 content 回退 reasoning 字段 / 重试 / 兜底为显式收尾标记。

## Impact

- `user_simulator.py`：`chat()` 取 `reply` 处增加 reasoning 字段回退 + 空值重试 + 兜底收尾标记。
- `src/executor.py`：多轮循环 `user_reply` 取回后、赋给 `current_query` 前增加空值判定（收尾或有限重试）。
- `src/openclaw_client.py`：`execute_with_retry` 的异常分类——把 `message or attachment required` 一类确定性非法请求从连接类 `GatewayError` fallback 路径中分流，快速失败。
- 行为影响：多轮任务遇 reasoning 模型空 content 时能正确继续或干净收尾，不再空转约一小时；轨迹按时落盘。
