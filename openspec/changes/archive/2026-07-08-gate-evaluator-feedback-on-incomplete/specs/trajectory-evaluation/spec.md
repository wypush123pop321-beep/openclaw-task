## ADDED Requirements

### Requirement: 前置完成度检测

Evaluator 在每次评估时 SHALL 先判断执行 agent 在最新一轮所处的姿态，并将结果记录在结构化裁决的 `task_declared_complete` 布尔字段中。该判定 MUST 只基于"姿态/意图"（是否声明或呈现出已交付），MUST NOT 依赖对答复正确性的判断——答复是否达标由 rubric 逐条核验单独决定。

判定采用"松进严出"：仅当存在明确的"执行中"信号（如明确表示尚未做完、只给阶段性进展、在向用户提问以继续、或只覆盖任务的一部分）时才判 `task_declared_complete=false`；其余情况（含看起来完整的最终答复、以及模棱两可）一律判 `true`。

`task_declared_complete` 字段默认值 MUST 为 `true`，以保证在既有配置或模型漏填该字段时，回流行为等同于本变更之前。

#### Scenario: 执行中姿态判为未完成

- **WHEN** 执行 agent 最新一轮存在明确的"执行中"信号（例如表示"接下来/我先/正在/下一步"或只给出阶段性进展）
- **THEN** Evaluator 将 `task_declared_complete` 置为 `false`

#### Scenario: 已交付姿态判为完成

- **WHEN** 执行 agent 最新一轮给出针对 Origin Query 的完整答复或最终产物且无"还要继续"的信号，或明确声明任务已完成
- **THEN** Evaluator 将 `task_declared_complete` 置为 `true`

#### Scenario: 模型漏填时按已完成处理

- **WHEN** 模型输出未包含 `task_declared_complete` 字段
- **THEN** 该字段取默认值 `true`，回流行为等同于本变更之前

### Requirement: 未完成时门控反馈回流

当 Evaluator 判定执行 agent 本轮为"执行中"（`task_declared_complete=false`）时，系统 SHALL NOT 将本轮 evaluator_feedback 回流给 user_simulator，而是走已有的空反馈降级路径（simulator 收到"（本轮无第三方评估）"并照常继续驱动对话）。

该门控 MUST NOT 影响评估自身的执行与落盘：completion、rubric_checks 及 `evaluator_use.log` 记录在两种姿态下均按既有逻辑正常产出。回流门控只作用于"是否把反馈传给 simulator"这一步，且仍受既有 `to_simulator` 开关约束。

#### Scenario: 执行中时不回流反馈

- **WHEN** 本轮评估结果 `task_declared_complete=false` 且 `to_simulator=true`
- **THEN** 本轮 user_simulator 收到的 evaluator_feedback 为空（`（本轮无第三方评估）`），任务对话照常继续

#### Scenario: 已交付时正常回流反馈

- **WHEN** 本轮评估结果 `task_declared_complete=true` 且 `to_simulator=true`
- **THEN** 本轮 evaluator_feedback 由 format_feedback 渲染后正常回流给 user_simulator

#### Scenario: 评估落盘不受门控影响

- **WHEN** 任一姿态下完成了一次评估
- **THEN** completion、rubric_checks 与 evaluator_use.log 均按既有逻辑正常产出，不因是否回流而改变
