# trajectory-evaluation Specification

## Purpose

在每个 turn 的 agent 回复后,由独立、无状态的 evaluator 基于真实证据(可用工具核验)对本轮执行做结构化、带引证、可落盘的评估,并将反馈注入 `user_simulator` 的判定决策;`user_simulator` 仍为最终判定方,evaluator 为顾问角色。

## Requirements

### Requirement: 每轮由独立 evaluator 评估并反馈给 simulator

系统 SHALL 在**符合评审频率**(由 `eval_step` 决定)的 turn 调用一个独立的 evaluator 对该评审点之前(含本轮)的执行做评估,并将评估结果反馈给 `user_simulator`。该 evaluator MUST 是一个独立于执行任务 agent 的 OC agent,MUST NOT 复用执行任务的那个 agent。**同一 query 的各 turn SHALL 复用同一个 evaluator agent 实体**(不每轮重建,以省去重复建连/初始化开销);该 evaluator agent SHALL 可由 query 从顶层 `agents` 列表中自选。未到评审点的 turn,系统 SHALL NOT 触发评估,并 SHALL 给 `user_simulator` 喂空反馈。

#### Scenario: 到达评审点触发评估
- **WHEN** 某 turn 满足评审频率(如第 `eval_step` 的整数倍轮),且 evaluator 已启用
- **THEN** 系统 SHALL 调用 evaluator 对当前进展评估,并在 `user_simulator` 决策前把评估结果交给它

#### Scenario: 未到评审点跳过评估并喂空
- **WHEN** 某 turn 未达到评审频率
- **THEN** 系统 SHALL NOT 触发 evaluator,且注入 `user_simulator` 的 `evaluator_feedback` SHALL 为空

#### Scenario: evaluator 不得是执行任务的 agent
- **WHEN** 系统装配 evaluator
- **THEN** evaluator SHALL 使用与执行任务 agent 不同的 OC agent(独立身份/会话),以避免自评自盖章与同源盲点

#### Scenario: 同一 query 各轮复用同一 evaluator agent
- **WHEN** 同一 query 的多个 turn 先后触发评审
- **THEN** 系统 SHALL 复用同一个 evaluator agent 实体,MUST NOT 为每个评审点新建 agent

### Requirement: 基于真实证据并可用工具核验

evaluator SHALL 基于本轮的可核验证据(`tool_calls` 与经磁盘真相校正的文件)进行评估,而非仅凭 agent 的文本说辞。evaluator SHALL 能使用自身工具对被审查产物做主动核验(如打开文件、检索、运行校验)。当 `tool_calls` 为空时,evaluator MUST NOT 据此推断 agent「未调用工具 / 硬编码 / 造假」——空 `tool_calls` 可能源于采集缺口(如服务端自主 agent 的工具步骤未被采集到),SHALL 与 `evidence_incomplete` 同等对待(证据缺失 ≠ 负面证据)。evaluator 指出「声称与证据矛盾」SHALL 以**可确证的反证**为据(如磁盘真相显示其声称生成的文件不存在、或输出与 oracle 事实冲突),MUST NOT 仅以「无 `tool_calls` 记录」作为造假判据。

#### Scenario: 拆穿话术型假阳性
- **WHEN** agent 声称完成了某操作,且存在可确证的反证(如磁盘真相显示其声称生成的文件不存在,或输出与 oracle 事实冲突)
- **THEN** evaluator SHALL 在反馈中明确指出「声称与证据矛盾」,据以阻止该轮被判为完成

#### Scenario: 工具核验产物
- **WHEN** 被审查的产物文件已按约定推送至 evaluator 自身工作区
- **THEN** evaluator SHALL 可用自身工具读取/核验该产物,并将核验所得作为评估依据

#### Scenario: 空 tool_calls 不得作为造假证据
- **WHEN** 某 turn 的 `tool_calls` 为空,但 agent 的输出与磁盘真相 / oracle 一致、无任何可确证的反证
- **THEN** evaluator MUST NOT 仅因「无 `tool_calls`」判定 agent 造假或未真实读取文件,SHALL 将其视为证据缺失而非负面证据

### Requirement: evaluator 无状态且独立投喂

evaluator 的**会话**SHALL 以无状态方式运行:**evaluator agent 实体在同一 query 内持久复用,但其会话 SHALL 在每次评估之前经 `harness-adapter` 的会话重置能力清空**——因为会话会持久化并回放 agent 自身的历史回复(含上一轮判词),若不清空将造成判词自我锚定。当 adapter 不具备会话重置能力时,系统 SHALL 安全跳过重置(退回等价语义),核心层 MUST NOT 直接调用 harness 专属重置方法。每轮评估所需上下文 SHALL 由系统从 harness 侧记录的 trajectory **显式压缩投喂**,session MUST NOT 承担跨轮记忆职责。

投喂内容 SHALL 为压缩后的 trajectory,仅包含:原始任务(`origin_query`)、冻结 rubrics、**最近 X 轮**的执行记录(含该轮 `tool_calls`)、以及产物文件指针 `generated_files{filename, workspace_path}`;系统 MUST NOT 投喂全量历轮记录,MUST NOT 内联产物文件全文,MUST NOT 把 evaluator 自身上一轮的结构化判词回投给它(防锚定)。"进步感知"SHALL 由最近 X 轮的**证据变化**体现,而非由复用自身会话记忆或回放旧判词得到。

#### Scenario: 每次评估前 reset 会话
- **WHEN** 进入一个评审点、准备调用 evaluator,且 adapter 具备会话重置能力
- **THEN** 系统 SHALL 先经 adapter 的会话重置能力清空该 evaluator 会话,确保其上一轮回复/判词不被回放进本轮评估

#### Scenario: 复用持久 agent 而非每轮重建
- **WHEN** 同一 query 的下一个评审点到来
- **THEN** 系统 SHALL 复用既有 evaluator agent 实体并仅重置其会话,MUST NOT 重新创建 agent 或重新初始化连接

#### Scenario: 有界压缩投喂(最近 X 轮 + 产物指针)
- **WHEN** 系统为某次评估构建投喂上下文
- **THEN** 投喂 SHALL 仅含 `origin_query` + rubrics + 最近 X 轮(含 `tool_calls`)+ `generated_files{filename, workspace_path}` 指针,MUST NOT 含全量历轮或产物全文

#### Scenario: 不回放自身历史判词(防锚定)
- **WHEN** evaluator 在某 query 的第二个及以后评审点工作
- **THEN** 其本轮裁定 MUST NOT 受其自身上一轮判词影响——既因 reset 使会话不回放该判词,也因投喂内容不含其上一轮结构化判决

#### Scenario: 进步感知来自证据 delta
- **WHEN** 系统投喂了最近 X 轮记录
- **THEN** evaluator SHALL 据这几轮的证据变化判断"先前问题本轮是否改进",而 MUST NOT 依赖跨轮的自身会话记忆

### Requirement: simulator 据反馈决策且仍为判定方

最终的 `【Task_Done】`/`【Task_Failed】`/继续下一轮 SHALL 仍由 `user_simulator` 输出;evaluator 为顾问角色。`user_simulator` 在做出该判定时 SHALL 参考 evaluator 的证据化反馈。

#### Scenario: 反馈注入 simulator 决策
- **WHEN** evaluator 产出本轮评估反馈
- **THEN** 系统 SHALL 把该反馈注入 `user_simulator` 的判定上下文(经 system prompt 占位符),使其在判 `Task_Done`/`Failed`/继续 时据此调整

#### Scenario: 证据矛盾时不轻易放行
- **WHEN** evaluator 反馈指出 agent 的声称与磁盘真相/工具证据矛盾
- **THEN** `user_simulator` SHALL NOT 仅凭 agent 的文本说辞判定 `Task_Done`,而应据该反馈继续追问或判失败

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

### Requirement: rubric 原文不进入 simulator 且回流受开关控制

rubric 原文 SHALL 仅作用于 evaluator;系统 MUST NOT 将 rubric 准则原文注入 `user_simulator` 的判定上下文。evaluator 基于 rubric 质检后得到的反馈(未满足项/改进点)SHALL 复用既有反馈回流通道交给 `user_simulator`,使其在不感知 rubric 的前提下仍能据反馈调整判定。是否将本轮反馈真正回流给 simulator SHALL 由配置开关 `feedback_to_simulator` 控制:为真时回流,为假时仅评估落盘而不影响 simulator。

#### Scenario: simulator 不感知 rubric 原文
- **WHEN** evaluator 使用 rubric 完成质检并产出反馈
- **THEN** 注入 `user_simulator` 的内容 SHALL 仅为提炼后的反馈(未满足项/改进点),MUST NOT 包含 rubric 准则原文

#### Scenario: 回流开关控制反馈是否影响 simulator
- **WHEN** `feedback_to_simulator` 为假
- **THEN** 系统 SHALL 仍执行评估并落盘,但 MUST NOT 把本轮反馈注入 `user_simulator` 的判定上下文

### Requirement: 裁判模型钉死且独立于被测 agent

系统 SHALL 为 evaluator agent 钉死一个固定模型,该模型 SHALL 刻意区别于被测执行 agent(建议采用更快的 flash 级模型),并在整段评估过程中保持不变。模型 SHALL 经 `harness-adapter` 的供给能力下发(`ensure_agent` 按 `AgentSpec.model` 钉死;OpenClaw adapter 内部经 `agents.update` 实现,Hermes adapter 经 `set_session_model` 实现);核心层 MUST NOT 直接调用 harness 专属的模型下发方法。evaluator 模型的连接信息(模型名/provider/URL/api-key)SHALL 可在 config 中配置。

#### Scenario: 经 adapter 钉死模型
- **WHEN** 系统装配 evaluator agent
- **THEN** 系统 SHALL 经 adapter 的 `ensure_agent`(携带 `AgentSpec.model`)下发固定模型,使其评估始终使用该模型,而 MUST NOT 在核心层直接调用 harness 专属下发方法

#### Scenario: 裁判模型独立于被测 agent
- **WHEN** 配置 evaluator 模型
- **THEN** 该模型 SHALL 不要求与被测 agent 一致,且 SHALL 倾向选用与之不同的快模型,以降低同构盲点

#### Scenario: 模型连接信息可配
- **WHEN** 在 config 中声明 evaluator 的模型连接(model/provider/URL/api-key)
- **THEN** 系统 SHALL 据此下发模型;缺失关键连接信息时 SHALL 明确告警而非静默退回被测模型

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

### Requirement: 评审频率可配且跳过轮喂空

系统 SHALL 以配置项 `eval_step` 控制评审频率:每 `eval_step` 个 turn 触发一次评审。**最近 X 轮投喂窗口的 X SHALL 等于 `eval_step`**(同一参数),以保证投喂窗口正好覆盖两次评审之间的全部 turn、不留上下文空洞。系统 SHALL 在**每个 turn** 照常捕获 trajectory(供评审窗口取数),但仅在评审点触发 evaluator。被跳过的 turn,系统 SHALL 给 `user_simulator` 喂空 `evaluator_feedback`。`eval_step` SHALL 可调,以便在不同取值下对比评估效果与资源开销。

#### Scenario: 每 eval_step 轮评审一次
- **WHEN** `eval_step = N`,对话进行到第 N、2N、… 轮
- **THEN** 系统 SHALL 在这些 turn 触发评审,其余 turn 不触发

#### Scenario: 投喂窗口 X 等于 eval_step
- **WHEN** 在某评审点构建投喂
- **THEN** 投喂的"最近 X 轮"中 X SHALL 等于 `eval_step`,使该窗口覆盖自上次评审以来的全部 turn

#### Scenario: 跳过轮仍捕获 trajectory
- **WHEN** 某 turn 未触发评审
- **THEN** 系统 SHALL 仍捕获该轮带证据的 trajectory(tool_calls/产物),以便下个评审点的窗口可取到该轮数据

#### Scenario: 跳过轮喂空反馈
- **WHEN** 某 turn 未触发评审
- **THEN** 注入 `user_simulator` 的 `evaluator_feedback` SHALL 为空,使 simulator 在该轮自主判定

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
