## ADDED Requirements

### Requirement: 仿真用户返回值健壮性

`user_simulator.chat()` SHALL NOT 返回空字符串。当底层模型（含 reasoning 类模型经 OpenAI 兼容接口）返回的主文本通道（`choices[0].message.content`）为空时，simulator SHALL 依次尝试以下兜底，直到得到非空文本或显式收尾标记：

1. 回退读取 reasoning 文本通道（如 `reasoning_content` 等模型返回体中承载思考/最终文本的备用字段）；
2. 若仍为空，SHALL 以相同输入有限次重试模型调用（复用既有的调用重试上限）；
3. 若重试后仍为空，SHALL 返回一个显式的收尾标记（`【Task_Done】` 语义），MUST NOT 返回空串或纯空白。

该健壮性约束仅治理 `chat()` 的返回值契约，不改变仿真用户的判定策略与脱敏策略。

#### Scenario: 主 content 为空时回退到 reasoning 字段

- **WHEN** 模型返回 `usage.completion_tokens` 非零但 `choices[0].message.content` 为空、且返回体含非空 reasoning 文本字段
- **THEN** `chat()` 返回该 reasoning 文本（去除首尾空白），不返回空串

#### Scenario: 主 content 与 reasoning 均为空时重试

- **WHEN** 首次调用主 content 与 reasoning 通道均为空
- **THEN** simulator 以相同输入有限次重试模型调用

#### Scenario: 重试仍为空时兜底为收尾标记

- **WHEN** 达到重试上限后仍未取得任何非空文本
- **THEN** `chat()` 返回含 `【Task_Done】` 语义的显式收尾标记，MUST NOT 返回空串或纯空白
