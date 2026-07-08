## ADDED Requirements

### Requirement: 未完成时跳过 rubric 评分

当 Evaluator 判定执行 agent 本轮为"执行中"（`task_declared_complete=false`）时,系统 SHALL 跳过 rubric 逐条判定与确定性评分(Scorer),不产出完成度。此时 `rubric_checks` MUST 为空数组,`completion` MUST 为 `None`(表示"未评估",区别于"评估后判 0")。

仅当判定为"已交付"（`task_declared_complete=true`）且存在冻结 rubric 时,系统才逐条判 0/1 并由 Scorer 算出 `completion`。`completion` 字段类型 SHALL 允许为空(`Optional`),以承载"未评估"这一态。

下游消费 `completion` 处(如 RL 取样、日志聚合)MUST 以 `completion is not None`(或等价的 `task_declared_complete`)筛选有效评分,不得把 `None` 当作 0 参与数值聚合。

#### Scenario: 执行中跳过评分且 completion 为空

- **WHEN** 本轮评估结果 `task_declared_complete=false`
- **THEN** `rubric_checks` 为空数组、`completion` 为 `None`,且不调用 Scorer

#### Scenario: 已交付时正常评分

- **WHEN** 本轮评估结果 `task_declared_complete=true` 且存在冻结 rubric
- **THEN** 逐条判 0/1,由 Scorer 算出 `completion`(0~1)

#### Scenario: 未评估的 completion 不参与聚合

- **WHEN** 下游取样/聚合读到某轮 `completion` 为 `None`
- **THEN** 该轮被视为"未评估"并从有效评分集中排除,不以 0 计入

## MODIFIED Requirements

### Requirement: 未完成时门控反馈回流

当 Evaluator 判定执行 agent 本轮为"执行中"（`task_declared_complete=false`）时,系统 SHALL NOT 将本轮 evaluator_feedback 回流给 user_simulator,而是走已有的空反馈降级路径（simulator 收到"（本轮无第三方评估）"并照常继续驱动对话）。

该门控仍受既有 `to_simulator` 开关约束。与本能力"未完成时跳过 rubric 评分"需求一致:执行中本轮不产出 completion（为 `None`）、`rubric_checks` 为空;已交付本轮则正常评分并（在 `to_simulator=true` 时）回流。评估日志 `evaluator_use.log` 仍逐轮记录(含"未评估"轮,其 completion 字段为 `null`）。

#### Scenario: 执行中时不回流反馈

- **WHEN** 本轮评估结果 `task_declared_complete=false` 且 `to_simulator=true`
- **THEN** 本轮 user_simulator 收到的 evaluator_feedback 为空（`（本轮无第三方评估）`）,任务对话照常继续

#### Scenario: 已交付时正常回流反馈

- **WHEN** 本轮评估结果 `task_declared_complete=true` 且 `to_simulator=true`
- **THEN** 本轮 evaluator_feedback 由 format_feedback 渲染后正常回流给 user_simulator

#### Scenario: 执行中轮仍逐轮落盘日志

- **WHEN** 某轮判为执行中(未评估)
- **THEN** evaluator_use.log 仍记录该轮,其 `completion` 字段为 `null`,`rubric_checks` 为空
