## Why

当前第三方 Evaluator 在每个评审点都会把评估反馈回流给 user_simulator，即使执行 agent 本轮明显"还在做、尚未交付"。在任务未完成阶段回流"完成度/不符合项"这类裁决性文本，容易让 simulator 误读为"任务做砸了"而过早发 `【Task_Failed】`，或对未定型的中间产物做无意义的成败判断。本阶段先做一个最小、低风险的门控：只有当 assistant 声明/呈现出"已交付"姿态时，才把 evaluator 反馈回流给 simulator。

## What Changes

- Evaluator 在评估时增加一个**前置检测**：判断执行 agent 在最新一轮处于"执行中(in_progress)"还是"已交付(complete)"姿态（判姿态、不判对错）。
- 当判定为"执行中"时，**本轮 evaluator_feedback 不回流给 user_simulator**（走已有的空反馈降级路径，simulator 照常继续驱动对话）。
- `EvaluationResult` 新增布尔字段 `task_declared_complete`，默认 `True`（缺省即保持现状回流，向后兼容）。
- Evaluator 的评估仍照常执行并落盘（completion / rubric_checks / evaluator_use.log 全部不变），**仅门控"是否回流给 simulator"这一步**。

## Capabilities

### New Capabilities
- `trajectory-evaluation`: 独立第三方 Evaluator 逐轮评估执行 agent 表现，并把提炼后的软反馈（顾问性、无硬否决）回流给 user_simulator。本次为其引入"前置完成度检测 + 反馈回流门控"这一行为。

### Modified Capabilities
<!-- 无既有 spec；相关行为以新建 trajectory-evaluation capability 承载。 -->

## Impact

- `src/evaluator/evaluator.py`：`EvaluationResult` 新增 `task_declared_complete` 字段；`DEFAULT_EVAL_PROMPT` 增补前置检测原则。
- `src/evaluator/evaluator_user_prompt.md`：skeleton 片段增补前置检测的输出说明。
- `src/executor.py`：`process_turn` 的回流门增加 `and ev.task_declared_complete` 条件。
- 不改动：Scorer / ScoringSpec 加权评分逻辑、completion 计算、format_feedback 渲染、评估落盘。
- 向后兼容：默认值 `True` 保证既有 config 与"模型漏填字段"两种情形下行为等同于改动前。
