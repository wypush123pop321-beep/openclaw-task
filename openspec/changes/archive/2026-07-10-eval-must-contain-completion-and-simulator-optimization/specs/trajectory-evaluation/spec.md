## ADDED Requirements

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
