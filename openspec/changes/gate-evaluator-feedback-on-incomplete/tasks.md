## 1. 数据结构

- [x] 1.1 在 `src/evaluator/evaluator.py` 的 `EvaluationResult` 增加字段 `task_declared_complete: bool = Field(True, description="前置检测:actor 本轮是否声明/呈现已交付姿态;默认 True 保持现状回流")`

## 2. 提示词(前置检测)

- [x] 2.1 在 `DEFAULT_EVAL_PROMPT` 增补【前置检测】原则段:判姿态不判对错、"松进严出"(仅明确"执行中"信号才判 false)、只看当前轮
- [x] 2.2 在 `src/evaluator/evaluator_user_prompt.md` 的 skeleton 片段增补输出说明:据前置检测设置 `task_declared_complete`(false=执行中 / true=已交付或模棱两可)

## 3. 回流门控

- [x] 3.1 在 `src/executor.py` 的 `process_turn` 回流门(约 line 164)条件追加 `and ev.task_declared_complete`,使"执行中"时返回 None(走已有空反馈降级路径)

## 4. 验证

- [x] 4.1 新增/调整单测:`task_declared_complete=false` 时 `process_turn` 返回 None(不回流);`=true` 时正常回流
- [x] 4.2 回归:在 `openclaw-task:latest` 容器内(挂载本分支)跑 `test_evaluator.py` scorer/config/gating 三模式全绿,默认 True 下既有行为不变、评估仍落盘。`test_evaluator_e2e.py` 因缺外部数据集(`260702/…` 未入库)+ 需 API key 而无法运行,但其不触及本次改动代码路径(不涉及 task_declared_complete/process_turn),非回归
- [x] 4.3 运行 `openspec validate gate-evaluator-feedback-on-incomplete` 确认 change 结构通过
