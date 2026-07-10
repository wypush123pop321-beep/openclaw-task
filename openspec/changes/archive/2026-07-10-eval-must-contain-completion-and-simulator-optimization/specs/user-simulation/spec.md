## ADDED Requirements

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
