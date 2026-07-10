## Why

本变更打包三处相关的评估/仿真质量修正:

**(1) Evaluator 原始回复缺 completion 字段。** Evaluator 的**模型原始回复**(API 层日志、`resp.content`)里,`completion` 字段时有时无:模型全凭采样决定填不填(因该字段挂在发给模型的 schema 里、且字段说明写着"由 Scorer 覆盖")。于是出现令人困惑的状态——模型明明做了 `rubric_checks` 逐条校验,原始回复里却没有 `completion` 字段。观测/调试时无法从原始回复稳定读到该字段,难以判断"是没做评分,还是做了但漏吐"。注:evaluator 解析后的**最终结果**(`evaluator_use.log` 的 `evaluation`、轨迹 `evaluations[]`)一直带 `completion`(由 Scorer 覆盖、`model_dump` 必带 key),不受影响;本项只治理**模型原始回复层**的字段一致性。

**(2) user_simulator 缺当前时间。** 仿真用户不感知"现在几点/今天几号",涉及时间相对语义的任务(如"最近的比赛""今年的赛程")无法正确判定与追问。需向 simulator 提示词注入**当前系统时间**。

**(3) user_simulator 反馈泄露过具体。** 当前 simulator 在纠正 agent 时会把具体错处和盘托出(如"缺了第 3、第 5 场"),等于把答案喂给 agent,削弱了基准的甄别力,也不像真实用户(真人多半只知道"结果不对",未必逐条清楚差在哪、更不会主动交答案)。需调整 simulator 的**回复策略**:只给方向性提示("你找到的场次不对/不全,请再核对"),不披露缺几项、缺哪项、正确值等具体信息。

## What Changes

**(1) Evaluator completion 字段**
- 发给模型的输出 schema 中,`completion` SHALL 标注为**必填**(进入 `required`),并在提示词加一条硬约束:**做了 rubric 逐条校验则填 0~1 的完成度估计;未做(执行中/无 rubric)则填 `null`;任何情况下 MUST 输出该字段,不得省略。**
- 保持字段"呈现契约":`rubric_checks` 非空 ⇒ `completion` 为数字;`rubric_checks` 为空 ⇒ `completion` 为 `null`;字段本身恒在。
- **不改**解析层:`EvaluationResult.completion` 仍为 `Optional[float]=None`(容错:模型偶发漏吐时不抛异常、降级为 None,而非整条评估失败)。
- **不改** Scorer 与最终结果语义:最终 `completion` 仍由 Scorer 确定性算出并覆盖模型自报值。模型自报的原始 `completion` 仅供原始回复层观测,**非权威成绩**(可能概率性错误,已知并接受)。

**(2) user_simulator 当前时间**
- simulator 提示词 SHALL 注入**当前系统时间**(在 `__init__` 时取一次 `datetime.now()` 并缓存,以人类可读格式呈现)。simulator 在判定与追问涉及时间相对语义的任务时,SHALL 以该时间为"现在"。

**(3) user_simulator 回复策略脱敏**
- simulator 在向 agent 指出结果不对/不全时,SHALL 只给**方向性提示**(哪个方面/哪类结果不对),SHALL NOT 披露具体缺项数量、缺失的具体条目、或正确答案值。
- evaluator feedback 中的具体错处**仅供 simulator 自身判定**(是否 Task_Done/继续),SHALL NOT 被原样转述给 agent。

## Capabilities

### New Capabilities
- `user-simulation`: 首次为 user_simulator 建立 spec,收录本次两条需求(当前时间注入、回复脱敏策略)。既有 simulator 行为暂不追溯补全,仅纳入本次改动点。

### Modified Capabilities
- `trajectory-evaluation`: 在"前置完成度检测"能力下新增一条需求——约束**模型原始输出**必含 `completion` 字段并遵循呈现契约(做校验→数字/未做→null),明确该原始值非权威、权威值仍由 Scorer 覆盖。

## Impact

- `src/evaluator/evaluator.py`:`evaluate_turn` 拼 `schema_suffix` 处,把发给模型的 schema 的 `required` 补入 `completion`(仅 model-facing schema,不改 Pydantic 模型);`EvaluationResult.completion` 字段说明改为纯输出指令"模型必吐、做校验填数/未做填 null",去掉"由 Scorer 覆盖"等元话术(该说明随 schema 发给模型,不放权威归属)。
- `src/evaluator/evaluator_user_prompt.md`:输出说明补一条硬约束——`completion` 必吐,呈现契约同上。
- `user_simulator.py`:`__init__` 取一次 `datetime.now()` 存为实例字段(如 `self._current_time`);`_render` 新增 `{current_time}` 占位替换,值取该缓存字段。
- `system_prompt.md`:新增"当前时间"段(填 `{current_time}`);"面对 agent 的结果""参考第三方评估反馈"两处补脱敏回复策略——只给方向、不交答案、不转述 evaluator 的具体错处。
- 解析层/Scorer/最终结果/下游取样:**不变**(仍以 Scorer 值为准,仍以 `completion is not None` 筛有效评分)。
- 边界:completion 项为**尽力而为**约束——绝大多数情况下模型会遵守,但原始回复层无法从物理上 100% 保证;唯一硬保证仍在解析后的最终结果层(本就存在)。
