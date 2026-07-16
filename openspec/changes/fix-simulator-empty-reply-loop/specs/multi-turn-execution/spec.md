## ADDED Requirements

### Requirement: 空 simulator 回复不得下发

多轮查询循环在取得 simulator 回复（`user_reply`）后、将其作为下一轮 `current_query` 下发给执行 agent / 网关之前，SHALL 判定该回复是否为空（空串或纯空白）。空回复 MUST NOT 被原样下发给下游网关。

遇空回复时，执行循环 SHALL 采取以下之一：视作收尾（`Task_Done` 语义、结束本查询并正常落盘轨迹），或触发有限次重试（与既有 agent 空回复防护对称、不超过既定重试上限）。该防护与既有的 agent 空回复防护形成对称，二者缺一不可。

#### Scenario: simulator 返回空回复时不下发空消息

- **WHEN** 某轮 simulator 回复为空串或纯空白
- **THEN** 执行循环 MUST NOT 以该空回复作为 `current_query` 调用下游网关

#### Scenario: 空回复触发收尾并正常落盘

- **WHEN** simulator 空回复被判定为收尾
- **THEN** 本查询按 `Task_Done` 语义结束，且已采集的轨迹按既有落盘逻辑正常写出（不被拖延或丢失）

### Requirement: 确定性非法请求快速失败

openclaw 客户端的 `execute_with_retry` SHALL 区分"连接类可重试异常"与"确定性非法请求"。当网关因请求本身非法而拒绝（如 `message or attachment required` 表示消息体缺失/为空）时，该错误 MUST NOT 被并入连接类 `GatewayError` 的 history_fallback + 多次重试路径。

对确定性非法请求，客户端 SHALL 快速失败（立即上抛可辨识的错误），避免长时间（多轮 fallback 轮询）空转。连接类异常（真实断线、超时）的既有 fallback + 重连行为保持不变。

#### Scenario: message-required 错误快速失败

- **WHEN** 网关返回 `message or attachment required` 一类的确定性非法请求错误
- **THEN** `execute_with_retry` 立即上抛该错误，不进入 history_fallback 轮询、不消耗连接类重试次数

#### Scenario: 连接类异常仍走 fallback

- **WHEN** 发生真实的连接断开或超时（连接类 `GatewayError` / `TimeoutError`）
- **THEN** 既有的重连 + history_fallback 行为保持不变
