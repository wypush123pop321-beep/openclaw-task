# user-simulation Specification

## Purpose
TBD - created by archiving change eval-must-contain-completion-and-simulator-optimization. Update Purpose after archive.
## Requirements
### Requirement: 仿真用户感知当前时间

user_simulator 的 system prompt SHALL 注入**当前系统时间**。该时间在 simulator **初始化(`__init__`)时**取一次 `datetime.now()`(人类可读格式,如 `2026-07-09 21:30:00`)并缓存,整个会话复用。

仿真用户在判定任务完成度与追问涉及时间相对语义(如"最近""今年""本周""当前赛季")的内容时,SHALL 以注入的当前时间为"现在"。

#### Scenario: 渲染的提示词含当前时间

- **WHEN** simulator 渲染 system prompt(`_render`)
- **THEN** 输出包含当前时间串,且 `{current_time}` 占位符已被替换(无残留占位)

#### Scenario: 会话内复用初始化时刻的时间

- **WHEN** 同一 simulator 实例在一场会话内多次调用 `chat`
- **THEN** 每次注入的当前时间均为 `__init__` 时取得并缓存的同一值

### Requirement: 仿真用户纠错反馈脱敏

user_simulator 在向 agent 指出结果不对或不完整时,SHALL 只给出**方向性提示**(哪个方面/哪一类结果不对或不全),SHALL NOT 披露具体缺项数量、缺失的具体条目、或正确答案值。

第三方 evaluator feedback 中的具体错处(如缺哪几项、正确值)MUST 仅用于 simulator **自身**对 `Task_Done`/继续 的判定,MUST NOT 被原样转述或复述给 agent。

#### Scenario: 指出结果不全时只给方向

- **WHEN** agent 给出的结果不完整(如漏了若干比赛场次),simulator 决定继续追问
- **THEN** simulator 回复只提示"结果不对/不全、请再核对"这一方向,不说明缺失的数量、具体条目或正确答案

#### Scenario: 不转述 evaluator 的具体错处

- **WHEN** evaluator feedback 列出了具体的不符合项(含缺失条目/正确值)
- **THEN** simulator 据此判定是否继续,但对 agent 的回复不包含这些具体错处的原文或等价复述

### Requirement: 仿真用户返回值健壮性

`user_simulator.chat()` SHALL NOT 返回空字符串。当底层模型（含 reasoning 类模型经 OpenAI 兼容接口）返回的主文本通道（`choices[0].message.content`）为空时，simulator SHALL 依次尝试以下兜底，直到得到非空文本或显式失败标记：

1. 回退读取 reasoning 文本通道（如 `reasoning_content` 等模型返回体中承载思考/最终文本的备用字段）；
2. 若仍为空，SHALL 以相同输入有限次重试模型调用（复用既有的调用重试上限，即 3 次）；
3. 若重试 3 次后仍为空，SHALL 判定为 simulator 自身故障，返回显式的失败标记（`【Task_Failed】` 语义），MUST NOT 返回空串或纯空白。将连续吐不出内容判为失败而非完成，是为了避免虚高成功率、掩盖 simulator 故障。

该健壮性约束仅治理 `chat()` 的返回值契约，不改变仿真用户的判定策略与脱敏策略。

#### Scenario: 主 content 为空时回退到 reasoning 字段

- **WHEN** 模型返回 `usage.completion_tokens` 非零但 `choices[0].message.content` 为空、且返回体含非空 reasoning 文本字段
- **THEN** `chat()` 返回该 reasoning 文本（去除首尾空白），不返回空串

#### Scenario: 主 content 与 reasoning 均为空时重试

- **WHEN** 首次调用主 content 与 reasoning 通道均为空
- **THEN** simulator 以相同输入有限次重试模型调用

#### Scenario: 重试仍为空时判为失败

- **WHEN** 达到重试上限（3 次）后仍未取得任何非空文本
- **THEN** `chat()` 返回含 `【Task_Failed】` 语义的显式失败标记，MUST NOT 返回空串或纯空白
