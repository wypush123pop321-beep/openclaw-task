## Context

前一变更(已归档)在 `evaluate_turn` 里对有 rubric 的情形**总是**跑 Scorer:

```python
# evaluator.py 现状
if not rubric:
    result.rubric_checks = []
else:
    checks = self._collect_checks(result.rubric_checks, rubric)
    scored = self.scorer.score(checks)
    result.completion = scored["completion"]   # 有 rubric 就必算,覆盖模型自报
    ...
```

于是执行中(`task_declared_complete=false`)的中间轮也会被强制评分,通常 gate 挂 → completion=0,产生"假 0 分"。本变更让评分门再叠加一个完成度条件,未交付则完全不评分、completion=None。

## Goals / Non-Goals

**Goals:**
- 执行中时跳过 rubric 逐条判定与 Scorer,`completion=None`、`rubric_checks=[]`。
- `completion` 支持"未评估"态(`Optional[float]`),与"评估后判 0"区分。
- 提示词让模型在执行中时返回空 `rubric_checks`、不评分。

**Non-Goals:**
- 不改 Scorer/ScoringSpec 的加权算法本身(仅改"何时调用它")。
- 不改前置检测(`task_declared_complete`)的判定规则。
- 不改回流门控(上一变更已有 `and ev.task_declared_complete`)。

## Decisions

### D1: completion 用 `Optional[float] = None` 表达"未评估"
- 为什么不用 -1 哨兵:-1 会悄无声息污染下游 `mean/sum`(把未评估当成 0 分);`None` 会让裸算术显式报错,对 RL 取样更安全。`task_declared_complete` 作真值来源,`None` 与之同步。
- 影响面:`EvaluationResult.completion` 类型放宽;`format_feedback`、`trajectory.evaluations`、`evaluator_use.log` 均需容忍 None(前二者已有分支或天然容忍;format_feedback 加一处兜底)。

### D2: 评分门叠加完成度条件,置于"无 rubric"分支之后
```python
if not rubric or not result.task_declared_complete:
    result.rubric_checks = []
    result.completion = None
else:
    checks = ...; scored = ...; result.completion = scored["completion"]; ...
```
- 为什么合并两分支:"无 rubric"与"未交付"都归结为"本轮不评分、completion=None、rubric_checks 空",语义一致,合并最简。
- 已交付且有 rubric 才走 Scorer,completion 为 0~1 具体值。

### D3: 提示词让模型在执行中不做逐条评分
在 skeleton 的前置检测输出段补一句:`task_declared_complete=false` 时 `rubric_checks` 返回空数组、不逐条判分。
- 即便模型不听话仍填了 checks,D2 的代码门也会强制清空 + 置 None,提示词只是减少无谓输出。

## Risks / Trade-offs

- [下游把 None 当 0] → 在 spec 明确"以非空/`task_declared_complete` 筛选";`None` 触发的显式报错优于静默污染(D1)。
- [format_feedback 收到 None] → 实际上执行中会被回流门挡掉、不调 format_feedback;仍加一处防御性兜底,避免 to_simulator/字段组合下渲染"完成度: None"。
- [既有测试假设 completion 为 float] → 需检查/调整断言:未评估轮应断言 `completion is None`,已交付轮断言为 float。

## Migration Plan

1. 放宽 `completion` 类型为 `Optional[float]=None`。
2. `evaluate_turn` 评分门叠加 `and result.task_declared_complete`(或等价的合并分支)。
3. 提示词补执行中不评分说明。
4. `format_feedback` 兜 None。
5. 测试:扩展 gating 单测——执行中断言 `completion is None`、`rubric_checks==[]`、Scorer 未被调用;已交付断言正常评分。docker 内跑 scorer/config/gating。
- 回滚:恢复评分门单一条件 + completion 类型即可。
