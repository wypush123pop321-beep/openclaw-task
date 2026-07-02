## MODIFIED Requirements

### Requirement: rubric 原文不进入 simulator 且回流受开关控制

rubric 原文 SHALL 仅作用于 evaluator;系统 MUST NOT 将 rubric 准则原文注入 `user_simulator` 的判定上下文。evaluator 基于 rubric 质检后得到的反馈(未满足项/改进点)SHALL 复用既有反馈回流通道交给 `user_simulator`,使其在不感知 rubric 的前提下仍能据反馈调整判定。是否将本轮反馈真正回流给 simulator SHALL 由配置开关 `to_simulator`(历史别名 `feedback_to_simulator`、`feedback_to_user`,经等价解析)控制:为真时回流,为假时仅评估落盘而不影响 simulator。规范配置数据 SHALL 采用新名 `to_simulator`,历史别名仅为向后兼容的可读输入而非规范写法。

#### Scenario: simulator 不感知 rubric 原文

- **WHEN** evaluator 使用 rubric 完成质检并产出反馈
- **THEN** 注入 `user_simulator` 的内容 SHALL 仅为提炼后的反馈(未满足项/改进点),MUST NOT 包含 rubric 准则原文

#### Scenario: 回流开关控制反馈是否影响 simulator

- **WHEN** `to_simulator` 为假
- **THEN** 系统 SHALL 仍执行评估并落盘,但 MUST NOT 把本轮反馈注入 `user_simulator` 的判定上下文

#### Scenario: 新名与历史别名等价解析

- **WHEN** 配置以 `to_simulator` 或历史别名 `feedback_to_simulator`/`feedback_to_user` 声明回流开关
- **THEN** 系统 SHALL 解析为同一语义;规范数据 SHALL 采用 `to_simulator`

### Requirement: 评估配置随 query 内联且可自选 evaluator agent

系统 SHALL 支持在 query 上以内联 `evaluate` 块声明本 query 的评估配置,并 SHALL 实际解析该块。该块的规范字段名 SHALL 为:`agent_name`(历史别名 `evaluator_agent`)、`eval_step`(历史别名 `evaluate_every_n_turns`)、`to_simulator`(历史别名 `feedback_to_simulator`、`feedback_to_user`)、`session_name`;新名与历史别名 SHALL 经等价解析,读取上二者等价,但**规范配置数据 SHALL 采用新名**。该块并 SHALL 支持新增字段 `oracle_ref`(指向 ground-truth 文件,解析后供 `oracle_cmp` 类 rubric 比对)、`rubrics_ref`(JSON-Pointer 指向结构化 rubric)、`scoring`(含 `gate_zero`/`weights`/`bucket_map`,解析为 `ScoringSpec`)。每个 query SHALL 能从顶层 `agents` 列表中**自选**一个已声明 agent 作为本 query 的 evaluator;所选 evaluator agent MUST NOT 与本 query 的执行 agent 同名。

#### Scenario: 解析新名与历史别名

- **WHEN** 某 query 的 `evaluate` 块使用 `agent_name`/`eval_step`/`to_simulator`(或其历史别名 `evaluator_agent`/`evaluate_every_n_turns`/`feedback_to_simulator`/`feedback_to_user`)
- **THEN** 系统 SHALL 正确解析为同一组语义并据此驱动评估,新名与别名 SHALL 等价

#### Scenario: 规范数据采用新名

- **WHEN** 产出规范任务配置数据
- **THEN** `evaluate` 块 SHALL 采用新名 `agent_name`/`eval_step`/`to_simulator`,历史别名仅为向后兼容的可读输入而非规范写法
