## ADDED Requirements

### Requirement: evaluator 投喂须披露工具结果为截断预览

系统在为 evaluator 构建投喂上下文时,SHALL 在提示词中显式披露"喂入的工具调用结果与文件内容为**截断预览**"及其字符上限,使裁判据此把"证据被截断"与"证据缺失/agent 未产出"区分开。披露的上限 SHALL 与 trajectory 渲染实际采用的截断长度一致(全量渲染:tool 输出 `[:2000]`、tool 入参 `[:500]`、文件内容 `[:2000]`;压缩渲染:tool 输出 `[:800]`、tool 入参 `[:300]`,文件以指针代替全文)。evaluator MUST NOT 因看到的工具结果被截断而判定 agent 输出不完整或造假;需要完整内容时 SHALL 走产物指针用自身工具核验。

#### Scenario: 提示词披露截断及上限
- **WHEN** 系统构建某评审点的 evaluator 投喂
- **THEN** 提示词 SHALL 含一段说明,告知工具结果/文件内容为截断预览且注明对应字符上限

#### Scenario: 截断不被当作证据缺失
- **WHEN** 某工具结果因超过上限被截断
- **THEN** evaluator MUST NOT 据"结果看起来不完整"判定 agent 未完成或造假,SHALL 视需要经产物指针用自身工具取全量核验

## MODIFIED Requirements

### Requirement: 评估配置随 query 内联且可自选 evaluator agent

系统 SHALL 支持在 query 上以内联 `evaluate` 块声明本 query 的评估配置,并 SHALL 实际解析该块。该块的规范字段名 SHALL 为:`agent_name`(历史别名 `evaluator_agent`)、`eval_step`(历史别名 `evaluate_every_n_turns`)、`feedback_to_simulator`(历史别名 `feedback_to_user`)、`session_name`;新名与历史别名 SHALL 经等价解析,读取上二者等价,但**规范配置数据 SHALL 采用新名**。该块并 SHALL 支持新增字段 `oracle_ref`(指向 ground-truth 文件,解析后供 `oracle_cmp` 类 rubric 比对)、`rubrics_ref`(JSON-Pointer 指向结构化 rubric)、`scoring`(含 `gate_zero`/`weights`/`bucket_map`,解析为 `ScoringSpec`)。每个 query SHALL 能从顶层 `agents` 列表中**自选**一个已声明 agent 作为本 query 的 evaluator;所选 evaluator agent MUST NOT 与本 query 的执行 agent 同名。

#### Scenario: 解析新名与历史别名
- **WHEN** 某 query 的 `evaluate` 块使用 `agent_name`/`eval_step`/`feedback_to_simulator`(或其历史别名 `evaluator_agent`/`evaluate_every_n_turns`/`feedback_to_user`)
- **THEN** 系统 SHALL 正确解析为同一组语义并据此驱动评估,新名与别名 SHALL 等价

#### Scenario: 规范数据采用新名
- **WHEN** 新建或维护 task config 的 `evaluate` 块
- **THEN** 规范配置 SHALL 采用新名 `agent_name`/`eval_step`/`feedback_to_simulator`,历史别名仅为向后兼容的可读输入而非规范写法

#### Scenario: 加载 oracle_ref 与解析 scoring
- **WHEN** `evaluate` 块含 `oracle_ref` 与 `scoring`
- **THEN** 系统 SHALL 加载 oracle 文件供比对,并把 `scoring` 解析为 `ScoringSpec` 供 `Scorer` 使用

#### Scenario: 自选 agents 列表中的 agent 作为 evaluator
- **WHEN** query 的 `evaluate.agent_name` 指向顶层 `agents` 列表中的某个已声明 agent
- **THEN** 系统 SHALL 用该 agent 充当本 query 的 evaluator

#### Scenario: evaluator 与执行 agent 不同名
- **WHEN** query 的 `evaluate.agent_name` 与该 query 的执行 `agent_name` 相同
- **THEN** 系统 SHALL 报错或拒绝装配,以保证裁判独立
