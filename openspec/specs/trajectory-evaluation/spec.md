# trajectory-evaluation Specification

## Purpose
TBD - created by archiving change gate-evaluator-feedback-on-incomplete. Update Purpose after archive.
## Requirements
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

### Requirement: 模型原始输出恒含 completion 字段

Evaluator 发给评审模型的输出 schema 中,`completion` SHALL 标注为必填(列入 schema 的 `required`),且评估提示词 SHALL 明确要求模型在**任何情况下**都输出 `completion` 字段,不得省略。呈现契约:模型做了 rubric 逐条校验(输出非空 `rubric_checks`)时 `completion` 填 0~1 的完成度估计;未做(执行中/无冻结 rubric)时填 `null`。

该约束为**尽力而为**:作用于模型原始回复层(API 层日志、`resp.content`),目的是消除"做了 `rubric_checks` 却缺 `completion` 字段"这一自相矛盾的原始输出。物理上无法 100% 保证模型不漏吐;唯一硬保证仍在解析后的最终结果层(`model_dump()` 恒带该 key)。

解析层 MUST 保持容错:`EvaluationResult.completion` 仍为 `Optional`,模型偶发漏吐时降级为 `None`,MUST NOT 因缺字段而使整条评估解析失败。

模型自报的 `completion` MUST 被视为非权威观测值:最终权威 `completion` 仍由 Scorer 据 `rubric_checks` 确定性算出并覆盖模型自报值(见"未完成时跳过 rubric 评分"需求)。下游取样/聚合 MUST 以最终结果层的 `completion` 为准,不得直接采用原始回复中模型自报的值。

#### Scenario: 做了 rubric 校验时原始输出含 completion 数值

- **WHEN** 模型判定为已交付并输出非空 `rubric_checks`
- **THEN** 模型原始回复的 `completion` 字段存在且为 0~1 的数值(自报估计,后续由 Scorer 覆盖为权威值)

#### Scenario: 未做 rubric 校验时原始输出含 completion 为 null

- **WHEN** 模型判定为执行中、或本 query 无冻结 rubric,`rubric_checks` 为空
- **THEN** 模型原始回复的 `completion` 字段存在且为 `null`

#### Scenario: 发给模型的 schema 将 completion 列为必填

- **WHEN** 构造发给评审模型的输出 JSON schema
- **THEN** 该 schema 的 `required` 包含 `completion`

#### Scenario: 模型仍漏吐时解析降级而非失败

- **WHEN** 模型原始回复未包含 `completion` 字段
- **THEN** 解析仍成功,`EvaluationResult.completion` 取默认 `None`,评估继续(由 Scorer 依 `task_declared_complete` 与 rubric 决定最终值)

