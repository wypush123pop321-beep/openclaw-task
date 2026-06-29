## Context

现有 evaluator(`evaluator.py`)以持久 agent + 每轮 reset + 有界压缩投喂的方式工作,但其评分模型是「裁判模型直接给 `completion:int`(0-100)」(`evaluator.py:73`),rubric 仅为 `List[str]`(`EvaluateConfig.rubrics`),逐条质检为四态 `pass/fail/partial/unverifiable`(`RubricCheck`)。

光钰给的 RL 任务(样本:`task_test/rl14_clean/04_出行助手_task1_班次时刻表核对`)要求把评分升级为「结构化 rubric + 确定性公式聚合」,以产出**可验证、不可被模型欺骗**的奖励信号(任务注脚:「机器判分占比 100% → 诚信 → 进 RL」)。该样本的配置分布在多文件:`*_q1.json`(执行入口)以 `rubrics_ref` JSON-Pointer 指向 `user_queries.json` 的 `custom_rubrics`,以 `oracle_ref` 指向 `oracle.json`(ground-truth),`scoring` 块定义 `gate_zero`/`weights`/`bucket_map`。

约束:不引入新的第三方依赖;保持旧 `config_session.json`(字符串 rubrics、无 scoring)继续可用;复用现有持久 agent 投喂架构;最终需跑通该样本且 `completion ≈ 1.0`(对齐 `results_4pilot.json`),并保留轨迹数据。

## Goals / Non-Goals

**Goals:**
- rubric 升级为结构化对象(`id/when/evaluator/text/formula`)并向后兼容纯字符串。
- 新增 `ScoringSpec` + `Scorer`:据 `(∏gate)×Σ桶加权` 算出 completion(取值域 `0~1`,非百分制),取代模型直接拍分;不再有独立 `R` 字段。
- config 解析适配:改名字段兼容、`oracle_ref` 加载、`rubrics_ref` JSON-Pointer 解引用、`scoring` 装配。
- rubric 判定二值化为 0/1,由 evaluator-agent 据 oracle+formula 输出。
- 用户画像按 `profile_file` 装配(修 `user_simulator.py:48` 写死)。
- 每条 query 的完整轨迹 + 各评审点评分结果落盘保留。
- 跑通目标样本,`completion ≈ 1.0`,轨迹与评分可查。

**Non-Goals:**
- 不实现 `formula` 的纯程序 DSL 解释器(`∀/∈/∧` 等符号的可执行求值)——本期由 evaluator-agent 据 formula 语义判定;纯程序求值列为后续增强。
- 不区分 `per_turn` 与 `final` 的评审时机(二者一视同仁,每个评审点都评)。
- 不保留 `partial/unverifiable` 中间态(全 0/1,核验受阻判 0)。
- 不改动 simulator 的最终判定权与既有反馈回流通道。

## Decisions

### D1：rubric 由 evaluator-agent 据 oracle+formula 判 0/1(而非程序执行 formula)
样本的 `evaluator` 取值为 `program`/`oracle_cmp`,`formula` 是半形式化 DSL(如 `set(out.eligible)=={'G7305','G7309'}`),非可直接 `exec` 的代码。

- **选 B(采纳)**:把 oracle 对应字段(`gt_ref`)、`text`、`formula` 一并投喂给持久 evaluator-agent,要求其逐条输出 0/1 + 引证。复用现有投喂架构,实现成本低;`formula`/oracle 作为强约束把模型主观性压到最小。
- 选 A(否决):实现 formula DSL 解释器 + 结构化抽取 agent 输出再程序比对。最贴近「100% 机判」,但 DSL 求值器脆弱、抽取 agent 输出本身又引入不确定性,本期性价比低。
- **张力记录**:选 B 下「机器判分」实为「受 oracle 强约束的模型判分」,与注脚的纯机判理想有差距 → 见 Risks,作为后续向 A 演进的开放项。

### D2：`ScoringSpec` 作为聚合器的唯一输入,与 JSON 布局解耦
解析层负责把 `scoring`(无论来自 `q1.json` 内联、`rubrics_ref` 同级、还是未来新位置)+ rubric 的 `when`/`bucket` 归一为内部 `ScoringSpec`:
```
ScoringSpec = {
  gate_ids: [...],                    # when==gate 的 rubric id
  buckets: { name: {weight, rubric_ids:[...]} },  # 由 weights × bucket_map 合成
  gate_zero: bool,
}
```
`Scorer.score(checks: dict[id,0|1]) -> {completion, bucket_scores, gate_status, gate_passed}`。聚合算法只读 `ScoringSpec`,**不感知** `weights`/`bucket_map` 在 JSON 中的位置——满足「权重位置后续会变」的抽象要求。`completion = round((∏gate)×Σ桶加权, 4)`,取值域 `0~1`(**非百分制**);不再产出独立 `R` 字段(原 `R` 即此 `completion`,历史的 `round(R*100)` 百分制已废弃)。

### D3：config 字段改名采用「别名归一」而非硬替换
`EvaluateConfig` 用 pydantic alias/`model_validator` 同时接受新名与历史别名,归一到统一内部字段:`evaluator_agent↔agent_name`、`evaluate_every_n_turns↔eval_step`、`feedback_to_user↔feedback_to_simulator`。旧 `config_session.json` 零改动可用。新增可选字段 `oracle_ref`/`rubrics_ref`/`scoring`,缺省为空 → 退回旧行为(无 gate、单桶等权或自由评估)。

### D4：`rubrics_ref` 的 JSON-Pointer 解引用用标准库手解
格式 `相对文件名#/a/b/c`。以 query 配置文件所在目录为基准解析相对路径,读 JSON 后按 `/` 分段索引(数字段转下标)。不引第三方 JSON-Pointer 库。`oracle_ref` 同样按相对路径加载。

### D5：rubric 结构化模型向后兼容字符串
新增 `Rubric` 模型(`id/when/evaluator/text/formula/gt_ref`)。解析时:dict → `Rubric`;str → `Rubric(id=auto, when='final', evaluator='llm_judge', text=str)`。冻结后贯穿全 query,沿用既有「冻结」语义。

### D6：轨迹落盘——每 query 一份结构化 JSON
`Trajectory` 增加序列化能力(已是 pydantic BaseModel,可 `model_dump`)。query 结束(`outcome` 落定)后,把 `{query, agent_name, outcome, turns[含tool_calls/generated_files], evaluations[各评审点的逐条0-1/gate状态/bucket_scores/completion]}` 落盘到 `logs/trajectories/<run_id>/<session_name>.json`。评审点评分在每次评估时累积进 trajectory,终局评审点的 `completion`(0~1)即最终成绩。形态对齐 `results_4pilot.json` 的「轨迹摘要+评分」结构,便于作 RL 样本。

### D7：profile_file 单一职责
`openclaw_automation.py:369` 已支持 `profile_file or "user_profile.json"`,但 `user_simulator.py:48` 仍写死再读一次,造成双读/覆盖。决策:画像加载收敛到装配层(`openclaw_automation`),由它把读好的画像文本传入 `UserSimulator`;`user_simulator.py` 删除自读 `user_profile.json` 的分支,只认传入值。

### D8：map 模式的源基准目录改为相对 `user_dir.path`(同名子文件夹不再强制)
端到端验证真实文件环境版(task 6.x)时发现:`_setup_workspaces` 对两种部署模式统一用 `content_root = user_dir.path / user_dir.path.name`(同名子文件夹)作基准——其中
- **整体复制模式**(无 `map_file`):把同名子文件夹整体 bulk 复制进 agent workspace,顶层留给 `MAP_*.json`/`profile`/`env_config.json` 等元数据,**确实需要**这层边界以免元数据混入。
- **map 模式**(有 `map_file`):`MAP_*.json` 已**逐条**点名要复制的文件,元数据本就不会被带上,这层同名嵌套是**多余**的,反而逼迫数据目录写成 `X/X/` 这种自套结构(目标样本里还要给 map key 加 `../` 去 climb 出来),易踩坑。

决策:map 模式下 map 的 key **直接相对 `user_dir.path`** 解析(`base_dir = user_dir.path`);**向后兼容**——若同名子文件夹存在,仍以它为数据根,旧布局(如 `config_zhouzijing.json`)不破。整体复制模式维持原 `path/path.name` 约定不变。

落点:`openclaw_automation.py:_setup_workspaces`。配套样本 `configs/04_出行助手_task1_班次时刻表核对` 的 `D/` 直接置于 config 目录下,`MAP_Windows.json` 的 key 由 `../D/...` 复原为 `D/...`。

> 张力:本决策仅去掉 map 模式不必要的嵌套要求,未触及整体复制模式;同名子文件夹「用 `path.name` 当固定边界名」本身仍偏 awkward(更优做法是显式 `data_root` 字段或固定名 `data/`),列为后续可选增强。

## Risks / Trade-offs

- [选 B 引入模型主观性,偏离纯机判「诚信」理想] → oracle+formula 强约束 + 落盘逐条 0/1 与引证供离线一致率校准;后续可对 `program` 类逐步切纯程序求值(D1 选 A)。
- [核验受阻一律判 0,环境抖动可能误判 gate→completion 归零] → 用户已接受;落盘保留 gate 状态与引证,便于事后甄别是「真未达成」还是「环境抖动」,再迭代加逃生口。
- [`rubrics_ref`/`oracle_ref` 相对路径基准歧义] → 统一以「query 配置文件所在目录」为基准;路径不存在时显式报错而非静默退空。
- [多文件 `scoring` 重复(q1.json 与 user_queries.json 各一份,且前者缺 bucket_map)] → 解析层规定优先级:`rubrics_ref` 指向的 `evaluate` 块为权威源(含完整 bucket_map);`q1.json` 内联 `scoring` 仅作覆盖/兜底,合成时以权威源为底再叠加。
- [二值化丢失旧四态信息] → 旧 `config_session.json` 无 scoring 时,Scorer 退回「无 gate、所有 rubric 归单桶等权」,completion 仍可算,不破坏既有用例。

## Migration Plan

1. 加 `Rubric`/`ScoringSpec`/`Scorer` 与解析(纯新增,不动既有路径)。
2. `EvaluateConfig` 加别名归一 + 新字段(默认空 → 旧行为不变)。
3. evaluator 投喂与输出解析改为结构化 rubric + 0/1;completion 改由 Scorer 算。
4. 轨迹落盘接线;profile_file 收敛到装配层。
5. 用目标样本端到端验证 `completion≈1.0` 并核对轨迹/评分落盘;回归跑旧 `config_session.json` 确认不破坏。
- 回滚:各步独立;新字段/新类不被旧 config 触达,出问题可仅回退 evaluator 输出解析与 Scorer 接线。

## Open Questions

- `program` 类 rubric 是否在本期就抽一两条做纯程序求值试点(向 D1 选 A 探路),还是全部走 agent?
- 轨迹落盘文件名/目录约定是否需与现有 `evaluator_use.log`、`logs/` 结构统一?
- 终局评审点之外的中间评审点评分,是否需要在落盘中保留全部(供过程分析)还是仅留终局?
