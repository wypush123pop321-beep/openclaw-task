## 1. Model-facing schema

- [x] 1.1 `src/evaluator/evaluator.py` 的 `evaluate_turn` 拼 `schema_suffix` 处:把发给模型的 JSON schema 的 `required` 补入 `completion`(只改 model-facing schema,`EvaluationResult` Pydantic 模型的 `Optional[float]=None` 不动)
- [x] 1.2 `EvaluationResult.completion` 字段说明微调为纯粹的输出指令:"模型 MUST 输出该字段;做逐条校验→填 0~1、未做→填 null"。去掉现有说明里"由 Scorer 覆盖"等元话术(该字段说明会随 `model_json_schema()` 发给模型,不应含权威归属话术)

## 2. 提示词

- [x] 2.1 `src/evaluator/evaluator_user_prompt.md` 输出说明段补一条硬约束:`completion` 必吐,做了 rubric 逐条校验则填 0~1 完成度估计、未做(执行中/无 rubric)则填 `null`;任何情况不得省略该字段。仅给输出指令,不含"权威/非权威""由 Scorer 覆盖"等元话术

## 3. user_simulator 当前时间

- [x] 3.1 `user_simulator.py`:`__init__` 取一次 `datetime.now()` 存为实例字段(如 `self._current_time`,人类可读格式如 `2026-07-09 21:30:00`);`_render` 新增 `{current_time}` 占位替换,值取该缓存字段
- [x] 3.2 `system_prompt.md`:新增"# 当前时间"段,内容为 `{current_time}`;并在核心原则/行为规范处点明"涉及时间相对语义(最近/今年/本周等)时以该时间为现在"

## 4. user_simulator 回复脱敏

- [x] 4.1 `system_prompt.md`「面对 agent 的结果」段补:指出结果不对/不全时只给方向性提示(哪方面不对),不说缺几项、缺哪项、不给正确值
- [x] 4.2 `system_prompt.md`「参考第三方评估反馈」段补:evaluator feedback 的具体错处仅供自身判定,不得原样转述给 agent

## 5. 验证

- [x] 5.1 单测:构造发给模型的 schema,断言 `completion` 在其 `required` 中;断言 `EvaluationResult` Pydantic 模型仍容忍缺 `completion`(解析降级为 None,不抛异常)
- [x] 5.2 单测/断言:`_render` 输出含当前时间串;`{current_time}` 占位被替换(无残留占位符)
- [x] 5.3 docker 内跑 `test_evaluator.py`(镜像 openclaw-task:latest,挂载本分支),确认 scorer/config/gating/skip/schema 全绿 + simulator offline 全绿、无回归
- [x] 5.4 端到端抽样:docker 跑任务 07(CEC/McNamara,带 rubric)。evaluator_use.log 确认 `completion=0.5`(G1门禁过、C1=1、C2=0)、字段恒在;simulator 回复只说"数据不对/缺口算错"、未泄露正确值 1783;system_prompt 注入当前时间 `2026-07-10 03:13:56`、无残留占位符
- [x] 5.5 `openspec validate eval-must-contain-completion-and-simulator-optimization` 通过
