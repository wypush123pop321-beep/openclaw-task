## 1. 结构化 rubric 与评分模型

- [x] 1.1 在 `evaluator.py` 新增 `Rubric` 模型(`id/when/evaluator/text/formula/gt_ref`),并提供 `from_raw()`:dict→`Rubric`、str→`Rubric(when='final', evaluator='llm_judge', text=str)`(向后兼容字符串)
- [x] 1.2 新增 `ScoringSpec`(`gate_ids`、`buckets{name:{weight,rubric_ids}}`、`gate_zero`)与其构建器:由 `weights`×`bucket_map`×rubric 的 `when` 合成,聚合算法不感知 JSON 布局
- [x] 1.3 新增 `Scorer.score(checks: dict[id,0|1]) -> {R, bucket_scores, gate_status}`,实现 `R=(∏gate)×Σ_bucket[w·(桶内通过/桶内总)]`,无 scoring 时退回「无 gate、单桶等权」
- [x] 1.4 为 `Scorer` 写单元测试:全过=1.0、任一 gate=0→R=0、分桶加权比例、空 scoring 退回路径;用目标样本 8 条 rubric 全过断言 `R==1.0`

## 2. config 解析适配

- [x] 2.1 `EvaluateConfig` 增字段别名归一:`evaluator_agent↔agent_name`、`evaluate_every_n_turns↔eval_step`、`feedback_to_user↔feedback_to_simulator`(pydantic alias/validator),旧 config 零改动可用
- [x] 2.2 `EvaluateConfig` 增可选字段 `oracle_ref`/`rubrics_ref`/`scoring`,缺省为空 → 退回旧行为
- [x] 2.3 实现 JSON-Pointer 解引用(标准库手解 `文件名#/a/b/c`,数字段转下标),以「query 配置文件所在目录」为基准;路径缺失显式报错
- [x] 2.4 实现 `oracle_ref` 加载(相对路径),解析为供 `oracle_cmp` 比对的结构;`rubrics_ref` 解引用得到结构化 rubric 数组并冻结
- [x] 2.5 实现多文件 `scoring` 合成优先级:以 `rubrics_ref` 指向的 `evaluate` 块为权威源(含完整 bucket_map),`q1.json` 内联 `scoring` 作覆盖/兜底

## 3. evaluator 投喂与二值化输出

- [x] 3.1 `RubricCheck` 状态由四态收敛为 0/1(`passed: bool` 或 `score: 0|1`),移除 `partial/unverifiable`
- [x] 3.2 `_build_prompt` 投喂结构化 rubric(含 `text/formula/gt_ref`)+ oracle 对应字段,指令要求 evaluator 逐条输出 0/1 + 引证,核验受阻判 0
- [x] 3.3 `EvaluationResult.completion` 改由 `Scorer` 算出(不取模型自报);保留 `rubric_checks`(逐条 0/1)、新增 `bucket_scores`/`gate_status`
- [x] 3.4 落盘日志(`evaluator_use.log`)字段更新:含逐条 0/1、分桶得分、gate 状态、最终 R,供离线一致率校准
- [x] 3.5 保留「无 rubric→rubric_checks 置空」的确定性归一(沿用现逻辑)

## 4. 用户画像 profile_file 收敛

- [x] 4.1 画像加载收敛到装配层 `openclaw_automation.py`(已支持 `profile_file or 'user_profile.json'`),把读好的画像文本传入 `UserSimulator`
- [x] 4.2 `user_simulator.py:48` 删除自读 `user_profile.json` 分支,只认传入值,消除双读/覆盖

## 5. 轨迹数据落盘保留

- [x] 5.1 `trajectory.py`:为 `Trajectory` 增序列化落盘能力(`model_dump`→JSON),含 `query/agent_name/outcome/turns(tool_calls/generated_files)`
- [x] 5.2 各评审点评分(逐条 0/1、gate 状态、bucket_scores、R)累积进 `Trajectory.evaluations`,可标识终局评审点
- [x] 5.3 query 结束(`outcome` 落定)后落盘到 `logs/trajectories/<run_id>/<session_name>.json`,跑完即留可离线查

## 6. 端到端验证目标样本

- [x] 6.1 准备目标样本运行配置:`profile_file=user_profile_1_商务出行者_HZS.json`、`map_file=MAP_Windows.json`,CSV 经 map 铺到真实路径
- [x] 6.2 端到端跑 `04_出行助手_task1_班次时刻表核对`,断言最终 `R≈1.0`(对齐 `results_4pilot.json`),8 条 rubric 全过
  - 已真实跑通(网关 18789 + gemini-3-flash-preview 裁判):`run_config_smoke.json`(内嵌时刻表变体,rubric PT1 gt_ref=embedded_timetable)。
  - 实测:别名归一、8 条 rubric 解引用、oracle 加载、scoring 权威源兜底合成;裁判逐条判 0/1 全过,Scorer 算出 `R=1.0 / completion=100`,gate{G1:1,G2:1},correctness 4/4·0.786 + process 2/2·0.214。
  - 未覆盖:真实文件环境版(map→D盘 + agent LIST/READ);本冒烟时刻表内嵌故 agent 未读文件(tool_calls=0)。
- [x] 6.3 核对轨迹与评分落盘:文件存在、含逐轮 tool_calls/产物指针、含各评审点 0/1 与终局 R
  - 已真实验证:`logs/trajectories/20260629T093641/smoke_banci.json` 含 `query/turns/outcome/evaluations`;评审点含逐条 0/1、gate_status、bucket_scores、R,可加载回读。
- [x] 6.4 回归:用旧 `config_session.json`(字符串 rubrics、无 scoring)跑一遍,确认评估流程不破坏、completion 仍可算

## 7. 补充修订(真实文件环境跑通 + map 解析 + completion 口径)

- [x] 7.1 真实文件环境版端到端跑通 `04_出行助手_task1_班次时刻表核对`(以 `*_q1.json` 为入口,agent 实际 LIST/READ `D:\出行\杭州东-上海虹桥车次.csv`)。补齐 6.2 标注「未覆盖:真实文件环境版」。
  - 实测:CSV 经 map 铺到 `D:\出行\`,agent 读真实文件并按约束(出发≥14:00 且 到达≤16:00)过滤,多轮纠正后 8 条 rubric 全过、gate{G1:1,G2:1}、`completion=1.0`、outcome=done、轨迹落盘 `logs/trajectories/<run_id>/query1.json`。
  - 已知问题(不影响 completion):轨迹 `tool_calls` 未捕获(agent 实际读了文件但记为 0),provenance 桶本任务权重=0 故不扣分;裁判会就此反复提示「无证据」。后续可补轨迹工具调用捕获。
- [x] 7.2 map 模式源路径解析改为相对 `user_dir.path`(design D8):`_setup_workspaces` map 模式 `base_dir=user_dir.path`,同名子文件夹存在时仍兼容旧布局;整体复制模式不变。配套:样本 `D/` 置于 config 目录直下,`MAP_Windows.json` key 由 `../D/...` 复原为 `D/...`。
- [x] 7.3 移除 `R` 字段、completion 改 0~1(非百分制):
  - `evaluator.py` `Scorer.score()` 返回 `{completion, bucket_scores, gate_status, gate_passed}`(去 `R`),`completion = round((∏gate)×Σ桶加权, 4)`;`EvaluationResult.completion: float`(0~1);反馈渲染去 `/100`;`_build_prompt` 声明 completion 0~1。
  - 波及:`trajectory.py`/`openclaw_automation.py` 注释口径,`test/test_scoring.py` 断言由 `out["R"]` 改 `out["completion"]`(`==1.0`/`==0.0`)。
- [x] 7.4 单测回归:`python test/test_scoring.py` 全 7 项通过(全过 `completion==1.0`、gate 否决 `completion==0`、分桶加权、空 scoring 退回)。
