## Why

上一个变更(gate-evaluator-feedback-on-incomplete)只在"执行中"时抑制反馈回流,但 rubric 逐条评分仍照常执行——这在任务尚未交付时是无意义的算力消耗,且会给中间轮产出一个语义可疑的 completion(通常被 gate 判 0)。本变更把语义推进一步:**执行 agent 本轮未交付时,直接跳过 rubric 逐条校验,不产出 completion**,只有已交付才评分。这样中间轮不再有"假 0 分",评估算力只花在真正的终轮。

## What Changes

- 执行中(`task_declared_complete=false`)时,Evaluator SHALL 跳过 rubric 逐条判定与 Scorer 评分,`rubric_checks` 置空、`completion` 置 `None`(未评估)。
- `EvaluationResult.completion` 由必填 `float` 改为 `Optional[float]`,默认 `None`,用以表达"未评估"这一态(区别于"评估后判 0")。
- 提示词补充:前置检测判为执行中时,`rubric_checks` 返回空数组、不做逐条评分。
- `format_feedback` 兜住 `completion=None`(防御性,不渲染"完成度: None")。
- **BREAKING(数据层)**:evaluator_use.log / trajectory.evaluations 中的 `completion` 可能为 `null`;下游取样 MUST 以 `completion is not None`(或 `task_declared_complete`)筛选有效评分。

## Capabilities

### New Capabilities
<!-- 无新增能力;沿用 trajectory-evaluation。 -->

### Modified Capabilities
- `trajectory-evaluation`: 由"未完成时仅门控回流、评分照常"演进为"未完成时跳过 rubric 评分且 completion=None"。修改既有"未完成时门控反馈回流"需求中关于"评估照常落盘"的表述,并新增"未完成时跳过 rubric 评分"需求。

## Impact

- `src/evaluator/evaluator.py`:`EvaluationResult.completion` 改 `Optional[float]=None`;`evaluate_turn` 评分门追加 `and result.task_declared_complete`(执行中不评分、completion=None);`format_feedback` 兜 None。
- `src/evaluator/evaluator_user_prompt.md`:前置检测输出说明补"执行中→rubric_checks=[]、不评分"。
- `src/executor.py`:回流门(`and ev.task_declared_complete`)已存在,无需再改;`trajectory.evaluations` 记录的 completion 可能为 None(仅数据语义变化)。
- 下游/取样:凡消费 completion 处 MUST 处理 None(以 `task_declared_complete` 或非空为准)。
