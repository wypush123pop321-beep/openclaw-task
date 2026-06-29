## ADDED Requirements

### Requirement: 确定性评分聚合(Scorer)算出 completion

系统 SHALL 提供一个确定性的评分聚合器(`Scorer`),据一份评分规格(`ScoringSpec`)由各条 rubric 的 0/1 判定计算最终完成度 `completion`,完成度 MUST NOT 再由裁判模型直接给出。`completion` 的取值域 SHALL 为 `0~1`(非百分制),系统 MUST NOT 输出独立的 `R` 字段或百分制(0-100)数值——`completion` 即聚合公式的直接结果。聚合公式 SHALL 为:

`completion = (∏ gate_i) × Σ_bucket [ w_bucket × (该桶内通过数 / 该桶内总数) ]`

其中:`gate` 项参与一票否决(任一 gate 判 0 → `completion = 0`);非 gate 项按其所属 `bucket` 归类,桶内取通过比例后乘以桶权重 `w_bucket`,再桶间相加。`when` 字段 SHALL 仅用于识别 `gate`;`per_turn` 与 `final` 一视同仁,均作为参与加权的 reward 项,系统 MUST NOT 因 `when` 不同而改变某条 rubric 是否在本评审点参与计算。`EvaluationResult.completion` SHALL 由该公式算出并落在 `[0,1]`(实现上对结果做 4 位小数取整)。

权重与分桶映射的来源 SHALL 经一层抽象(`ScoringSpec`)归一后供聚合器消费,聚合算法 MUST NOT 直接依赖 `weights`/`bucket_map` 在 JSON 中的具体位置,以隔离未来字段位置变动。

#### Scenario: gate 全过才计加权分
- **WHEN** 某评审点所有 `gate` 项判定均为 1
- **THEN** 系统 SHALL 按分桶加权公式计算 `completion`,`completion` 取值落在 `[0,1]`

#### Scenario: 任一 gate 失败则归零
- **WHEN** 某评审点存在至少一个 `gate` 项判定为 0
- **THEN** 系统 SHALL 令 `completion = 0`,MUST NOT 再计入任何桶的加权分

#### Scenario: 按桶加权而非按单条 rubric
- **WHEN** 多条非 gate rubric 落在同一 `bucket`
- **THEN** 系统 SHALL 先取该桶内通过比例(通过数/总数),再乘以该桶权重 `w_bucket`,各桶结果相加;单条 rubric MUST NOT 各自携带独立权重

#### Scenario: completion 由公式算出而非模型直接给
- **WHEN** evaluator 产出各条 rubric 的 0/1 判定
- **THEN** `EvaluationResult.completion` SHALL 由 `Scorer` 按公式算出,MUST NOT 取用裁判模型自报的完成度数值

#### Scenario: 权重来源经抽象隔离
- **WHEN** `weights`/`bucket_map` 在配置中的位置或承载文件发生变化
- **THEN** 聚合算法 SHALL 仅依赖归一后的 `ScoringSpec`,无需改动即可适配,新位置仅需在解析层接线

### Requirement: 用户画像按 profile_file 装配

系统在装配某 query 的运行环境时,SHALL 按 `input_dir.user_dir.profile_file` 指定的文件名读取用户画像并注入 `user_simulator`,MUST NOT 写死固定文件名 `user_profile.json`。当未声明 `profile_file` 时,系统 SHALL 回退到缺省文件名 `user_profile.json` 以保持向后兼容。

#### Scenario: 按 profile_file 读取画像
- **WHEN** query 的 `input_dir.user_dir.profile_file` 指向一个存在的画像 JSON(如 `user_profile_1_商务出行者_HZS.json`)
- **THEN** 系统 SHALL 读取该文件内容并作为用户画像注入 `user_simulator`

#### Scenario: 未声明时回退缺省名
- **WHEN** query 未声明 `profile_file`
- **THEN** 系统 SHALL 回退按 `user_profile.json` 读取,行为与既有逻辑一致

## MODIFIED Requirements

### Requirement: rubric 随 query 传入并在整段对话中冻结

系统 SHALL 支持在 query 上携带一份验收清单(rubric),作为该任务的逐条质检依据。rubric 的每一条目 SHALL 既可为**纯字符串**(向后兼容旧格式),也可为**结构化对象**,含 `id`、`when`(取值 `gate`/`per_turn`/`final`)、`evaluator`(判定方式,如 `program`/`oracle_cmp`/`llm_judge`)、`text`(自然语言描述)与可选 `formula`(半形式化判据)。rubric 既可在 `evaluate` 块内联,也可经 `rubrics_ref`(形如 `文件名#/json/pointer/path` 的 JSON-Pointer)指向外部文件并由系统解引用得到。该 rubric SHALL 随用户首次 query 一起传入(或解引用得到),并在该 query 的整段多轮对话(全部 turn)中**冻结固定**:系统 MUST NOT 在对话过程中重新生成或修改它。rubric 为可选;当 query 未提供 rubric(空清单)时,系统 SHALL 退回原有的自由维度评估行为,不影响任务推进。

#### Scenario: rubric 随 query 传入并跨轮冻结
- **WHEN** 某 query 携带了非空 rubric 且 evaluator 已启用
- **THEN** 系统 SHALL 在该 query 的每一个 turn 评估中使用同一份 rubric,且各轮所用 rubric 内容 MUST 完全一致(冻结)

#### Scenario: 经 rubrics_ref 解引用结构化 rubric
- **WHEN** `evaluate.rubrics_ref` 形如 `user_queries.json#/0/evaluate/0/custom_rubrics`
- **THEN** 系统 SHALL 按 JSON-Pointer 解引用该路径,得到结构化 rubric 数组并冻结使用

#### Scenario: 向后兼容纯字符串 rubric
- **WHEN** 某 query 直接内联 `rubrics: ["...","..."]` 的字符串清单
- **THEN** 系统 SHALL 照常将每条字符串作为一条 rubric 处理,行为与既有逻辑一致

#### Scenario: 未提供 rubric 时退回自由评估
- **WHEN** 某 query 未提供 rubric(清单为空)
- **THEN** evaluator SHALL 按原有自由维度方式评估,任务流程 MUST NOT 因缺少 rubric 而中断或报错

### Requirement: evaluator 对 rubric 逐条质检 agent 产物

当存在冻结 rubric 时,evaluator SHALL 把该 rubric 注入评估上下文,并基于本轮可核验证据(`tool_calls` 与磁盘真相文件)对**每一条** rubric 准则逐条裁定。每条裁定 SHALL 收敛为 **0/1 二值**(1=通过、0=不通过),系统 MUST NOT 再使用"部分满足/无法核验"等中间态。对带 `formula` 的 `program`/`oracle_cmp` 类 rubric,evaluator SHALL 据 `formula` 与 oracle ground-truth 做精确比对得出 0/1。核验受阻(证据缺失、文件读不到等)SHALL 一律判 0(不通过)——本变更刻意接受由此带来的"环境抖动可能误判"的风险,后续视实际问题再行迭代。每条裁定 SHALL 附带引用本轮证据的具体依据。

#### Scenario: 逐条二值裁定并附引证
- **WHEN** evaluator 在存在冻结 rubric 的情况下完成一轮评估
- **THEN** 其结果 SHALL 为 rubric 中每一条准则给出一个 0/1 判定,且每条 SHALL 引用本轮证据中的具体依据

#### Scenario: 据 formula 与 oracle 精确比对
- **WHEN** 某条 rubric 为 `oracle_cmp` 且带 `formula`(如 `set(out.eligible)=={'G7305','G7309'}`)及 `gt_ref`
- **THEN** evaluator SHALL 据 oracle 对应字段与 agent 输出做精确比对,得出 0 或 1

#### Scenario: 核验受阻判 0
- **WHEN** 某条 rubric 准则因证据缺失/核验受阻而无法确证通过
- **THEN** evaluator SHALL 将该条判为 0(不通过),MUST NOT 输出任何中间态

### Requirement: 评估输出结构化、带引证、可落盘

evaluator 的输出 SHALL 为结构化结果,至少包含:任务完成度、改进点列表、不符合要求项、整体倾向(是否倾向放行)。**任务完成度 SHALL 由确定性 `Scorer` 按评分公式算出,MUST NOT 取裁判模型自报数值。** 当存在冻结 rubric 时,该结构化结果 SHALL 额外包含一份**逐条 rubric 质检结果**,每条含准则标识、0/1 判定与引证。当不存在冻结 rubric(空清单)时,该逐条质检结果 SHALL 为空;系统 MUST NOT 让 evaluator 自拟 rubric 准则,也 MUST NOT 把评估维度当作 rubric 准则填入逐条质检结果。其中关键判断 SHALL 引用轨迹中的具体语句、工具返回或文件内容作为引证。系统 SHALL 将每次评估追加到独立评估日志,字段足以离线复现该评估依据,且当存在 rubric 时 SHALL 包含逐条 0/1 质检结果、分桶得分与各 gate 状态,以供离线质检与一致率校准。

为保证"无 rubric 即为空"在模型偶发幻觉下仍然成立,系统 SHALL 在两个层面共同约束:在评估提示词中显式声明无 rubric 时逐条质检结果必须为空;并在解析评估输出后做确定性归一——当本轮无冻结 rubric 时,将逐条 rubric 质检结果强制置空。该归一 SHALL 在评估落盘日志之前完成。

#### Scenario: 完成度由 Scorer 算出
- **WHEN** evaluator 完成一轮含 rubric 的评估
- **THEN** 结构化结果中的 `completion` SHALL 等于 `Scorer` 按 `(∏gate)×Σ桶加权` 算出的 `0~1` 值,MUST NOT 等于模型自报数值,且 MUST NOT 为百分制

#### Scenario: 含 rubric 时输出逐条 0/1 质检结果
- **WHEN** evaluator 在存在冻结 rubric 的情况下完成一轮评估
- **THEN** 其结构化结果 SHALL 额外包含逐条 rubric 质检结果(准则标识/0-1判定/引证)

#### Scenario: 无 rubric 时逐条质检结果为空
- **WHEN** 某 query 未提供冻结 rubric(清单为空),evaluator 完成一轮评估
- **THEN** 其结构化结果中的逐条 rubric 质检结果 SHALL 为空数组,且落盘日志中该字段亦 SHALL 为空——即便模型在生成时自拟了准则,系统也 SHALL 在落盘前将其归一为空

#### Scenario: 评估落盘供校准
- **WHEN** evaluator 完成任意一次评估
- **THEN** 系统 SHALL 追加一条结构化记录到评估日志(含轨迹标识、各项结论、引证、所用裁判模型,以及存在 rubric 时的逐条 0/1 质检结果、分桶得分与 gate 状态),供离线复核与一致率校准

### Requirement: 评估配置随 query 内联且可自选 evaluator agent

系统 SHALL 支持在 query 上以内联 `evaluate` 块声明本 query 的评估配置,并 SHALL 实际解析该块。该块 SHALL 支持以下字段及其历史别名:`evaluator_agent`(别名 `agent_name`)、`evaluate_every_n_turns`(别名 `eval_step`)、`feedback_to_user`(别名 `feedback_to_simulator`)、`session_name`;并 SHALL 支持新增字段 `oracle_ref`(指向 ground-truth 文件,解析后供 `oracle_cmp` 类 rubric 比对)、`rubrics_ref`(JSON-Pointer 指向结构化 rubric)、`scoring`(含 `gate_zero`/`weights`/`bucket_map`,解析为 `ScoringSpec`)。每个 query SHALL 能从顶层 `agents` 列表中**自选**一个已声明 agent 作为本 query 的 evaluator;所选 evaluator agent MUST NOT 与本 query 的执行 agent 同名。

#### Scenario: 解析新名与历史别名
- **WHEN** 某 query 的 `evaluate` 块使用 `evaluator_agent`/`evaluate_every_n_turns`/`feedback_to_user`(或其历史别名)
- **THEN** 系统 SHALL 正确解析为同一组语义并据此驱动评估,新名与别名 SHALL 等价

#### Scenario: 加载 oracle_ref 与解析 scoring
- **WHEN** `evaluate` 块含 `oracle_ref` 与 `scoring`
- **THEN** 系统 SHALL 加载 oracle 文件供比对,并把 `scoring` 解析为 `ScoringSpec` 供 `Scorer` 使用

#### Scenario: 自选 agents 列表中的 agent 作为 evaluator
- **WHEN** query 的 `evaluate.evaluator_agent` 指向顶层 `agents` 列表中的某个已声明 agent
- **THEN** 系统 SHALL 用该 agent 充当本 query 的 evaluator

#### Scenario: evaluator 与执行 agent 不同名
- **WHEN** query 的 `evaluate.evaluator_agent` 与该 query 的执行 `agent_name` 相同
- **THEN** 系统 SHALL 报错或拒绝装配,以保证裁判独立
