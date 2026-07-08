## 1. 数据结构

- [x] 1.1 `src/evaluator/evaluator.py` 的 `EvaluationResult.completion` 由 `float` 改为 `Optional[float] = Field(None, ...)`,语义:None=未评估、0~1=评估得分

## 2. 评分门

- [x] 2.1 `evaluate_turn` 评分门改为:`if not rubric or not result.task_declared_complete:` → `rubric_checks=[]`、`completion=None`、不调 Scorer;`else` 走既有 Scorer 评分
- [x] 2.2 `format_feedback` 兜底:`completion is None` 时不渲染"完成度: None"(改渲染占位或省略该行)

## 3. 提示词

- [x] 3.1 `src/evaluator/evaluator_user_prompt.md` 前置检测输出段补:`task_declared_complete=false` 时 `rubric_checks` 返回空数组、不逐条评分

## 4. 验证

- [x] 4.1 扩展 `test_feedback_gating`(或新增):执行中断言 `completion is None`、`rubric_checks==[]`、Scorer 未被调用;已交付断言 completion 为 float 且正常回流
- [x] 4.2 docker 内跑 `test_evaluator.py` scorer/config/gating 三模式(镜像 openclaw-task:latest,挂载本分支),确认全绿、无回归
- [x] 4.3 `openspec validate skip-rubric-eval-when-incomplete` 通过
