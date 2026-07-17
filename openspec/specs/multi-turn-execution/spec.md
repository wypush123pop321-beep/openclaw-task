# multi-turn-execution Specification

## Purpose
多轮查询执行编排与 openclaw 客户端错误分类的行为约束。首次由 change fix-simulator-empty-reply-loop 建立,收录空 user_reply 不得下发、确定性非法请求快速失败两条需求。

## Requirements

### Requirement: 空 simulator 回复不得下发

多轮查询循环在取得 simulator 回复（`user_reply`）后、将其作为下一轮 `current_query` 下发给执行 agent / 网关之前，SHALL 判定该回复是否为空（空串或纯空白）。空回复 MUST NOT 被原样下发给下游网关。

遇空回复时，执行循环 SHALL 判定为失败（`failed` outcome、结束本查询并正常落盘轨迹），MUST NOT 判为完成。空回复表示 simulator 未正常产出（其自身故障），判失败而非完成可避免虚高成功率、掩盖故障。simulator 层已保证重试仍空时返回 `【Task_Failed】`，此处为纵深防御：任何来源的空回复都判失败。

#### Scenario: simulator 返回空回复时不下发空消息

- **WHEN** 某轮 simulator 回复为空串或纯空白
- **THEN** 执行循环 MUST NOT 以该空回复作为 `current_query` 调用下游网关

#### Scenario: 空回复判为失败并正常落盘

- **WHEN** simulator 空回复被判定
- **THEN** 本查询按 `failed` outcome 结束，且已采集的轨迹按既有落盘逻辑正常写出（不被拖延或丢失）

### Requirement: 确定性非法请求快速失败

openclaw 客户端的 `execute_with_retry` SHALL 区分"连接类可重试异常"与"确定性非法请求"。当网关因请求本身非法而拒绝（如 `message or attachment required` 表示消息体缺失/为空）时，该错误 MUST NOT 被并入连接类 `GatewayError` 的 history_fallback + 多次重试路径。

对确定性非法请求，客户端 SHALL 快速失败（立即上抛可辨识的错误），避免长时间（多轮 fallback 轮询）空转。连接类异常（真实断线、超时）的既有 fallback + 重连行为保持不变。

#### Scenario: message-required 错误快速失败

- **WHEN** 网关返回 `message or attachment required` 一类的确定性非法请求错误
- **THEN** `execute_with_retry` 立即上抛该错误，不进入 history_fallback 轮询、不消耗连接类重试次数

#### Scenario: 连接类异常仍走 fallback

- **WHEN** 发生真实的连接断开或超时（连接类 `GatewayError` / `TimeoutError`）
- **THEN** 既有的重连 + history_fallback 行为保持不变
