## Context

第三方 Evaluator（`src/evaluator/evaluator.py`）逐轮评估执行 agent，并在评审点通过 `src/executor.py` 的 `process_turn` 把提炼后的软反馈回流给 user_simulator。当前回流门为：

```python
# executor.py:164
if evaluator.to_simulator and ev is not None:
    return evaluator.format_feedback(ev)
```

问题在于：只要评估成功且开启回流，无论执行 agent 本轮是否"还在做"，反馈都会回流。任务未完成阶段回流裁决性文本（完成度、不符合项）会诱导 simulator 过早判 `【Task_Failed】` 或对中间产物做无意义裁决。

本变更是一个**最小、低风险**的门控：仅在"执行中"姿态时抑制反馈回流。评估自身（打分/落盘）完全不动。更细的迭代（未完成时跳过评分、completion 置 None、反馈分级）留到后续阶段。

## Goals / Non-Goals

**Goals:**
- Evaluator 能判断执行 agent 最新一轮是"执行中"还是"已交付"（判姿态、不判对错）。
- "执行中"时不把 evaluator_feedback 回流给 simulator，走已有空反馈降级路径。
- 向后兼容：既有 config 与"模型漏填字段"两种情形行为等同于改动前。

**Non-Goals:**
- 不改 Scorer / ScoringSpec 加权评分逻辑与 completion 计算。
- 不在"执行中"时跳过评估或把 completion 置 None（本阶段仍照常评估、照常落盘）。
- 不改 `format_feedback` 的渲染格式。
- 不把 Evaluator 的完成判定当作循环结束信号（结束仍由 simulator 的 `【Task_Done】`/`【Task_Failed】` 拍板）。

## Decisions

### D1: 用一个布尔字段承载前置检测，而非复用 inclination
`EvaluationResult` 新增 `task_declared_complete: bool = Field(True, ...)`。
- 为什么不复用 `inclination`(accept/reject/uncertain)：inclination 语义是"倾向放行/继续/存疑"，与"是否已交付姿态"是两条正交轴；复用会污染 simulator 侧对 inclination 的解读。独立布尔字段最清晰。
- 为什么默认 `True`：作为安全阀——模型漏填该字段时行为等同于今天（照常回流），避免"新字段导致反馈被全部吞掉"的回归。

### D2: 门控只加在 process_turn 的回流处
`executor.py:164` 的条件追加 `and ev.task_declared_complete`。
- 为什么在这里：这是反馈进入 simulator 的唯一收口点，改动面最小；返回 None 会自然复用已有的空反馈降级路径（simulator 早已能处理 `（本轮无第三方评估）`），没有新增边界。
- 为什么不在 `evaluate_turn` 里拦：那样会牵扯"要不要跳过 Scorer / completion 置什么"，引入不必要的不确定性——本阶段刻意不碰评估与落盘。

### D3: 前置检测规则"松进严出",写进提示词
在 `DEFAULT_EVAL_PROMPT` 增补前置检测原则，在 `evaluator_user_prompt.md` 的 skeleton 增补输出说明：仅当有明确"执行中"信号才判 `false`，其余（含完整答复、模棱两可）判 `true`。
- 为什么偏向判 `true`：被误判为"已交付"最多多回流一次反馈（无害，且评分是以磁盘真相为准的安全网）；反向漏判会让真正的终轮反馈被吞。故宁可多回流。
- 前置检测只看**当前轮**姿态,不被 window 内更早轮的"我接下来会…"带偏。

## Risks / Trade-offs

- [模型不稳定地判定 `task_declared_complete`] → 默认 `True` + "松进严出"规则把失败方向偏向"照常回流"，最坏退化为现状，不会把有价值的终轮反馈吞掉。
- [单轮 Q&A 任务不显式说"完成"] → 规则明确：无"执行中"信号即判 `true`，一次性答复照常回流并评估。
- [Evaluator 完成判定与 simulator 的 Task_Done 可能不一致] → 二者是不同轴、且 Evaluator 仅顾问；完成判定只门控"是否回流",不作结束信号,不一致无害。
- [新字段的向后兼容] → Pydantic 默认值 `True` 覆盖旧 config 与漏填两种情形;已有落盘结构只增字段不改语义。

## Migration Plan

1. 加字段 `task_declared_complete`(默认 True)——纯增量,无破坏。
2. 改 `process_turn` 回流门条件。
3. 增补提示词两处文案。
4. 回归:既有测试(test_evaluator.py / e2e)应全绿(默认 True 保持现状);新增/调整一条断言覆盖"false → 不回流"。
- 回滚:三处改动相互独立且小;移除门控条件即可恢复原行为。
