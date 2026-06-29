## Why

被测 assistant 跑在能访问真实文件系统的环境里(任务输入是真实绝对路径,如 `D:\出行\…csv`)。而该任务的标准答案 `oracle.json`(含 `eligible_trains` 等结果)与验收清单 `user_queries.json`(`custom_rubrics`)就躺在同一份 config 目录里。一个会"翻文件系统"的 agent 可能直接读到答案与评分标准,从而作弊或被干扰,污染评估的有效性。

evaluator 在任务开始前就已把 oracle/rubrics 读进内存(`_resolve_evaluate_refs`),整段对话期间不再读盘。因此可以在 assistant 执行任务期间把这两个文件从磁盘移除,既消除泄漏面,又不影响 evaluator 评分。

## What Changes

- 在 `_resolve_evaluate_refs` 解析 `oracle_ref` / `rubrics_ref` 时,除了把内容解析进内存,**额外留存被引用文件的原始字节与绝对路径**(挂到 `EvaluateConfig` 的一个不落盘字段)。
- 在 `execute_queries` 每个 query 的执行循环**开始前删除**该 query 引用的 oracle/rubrics 文件;assistant 全程在磁盘无答案的环境下执行。
- 在该 query 轮次结束后,**尽力(best-effort)把原始字节写回**——仅为本地调试便利;容器化运行下即使不写回也无影响,不做异常兜底。
- 作用域为 **per-query**:每个 oracle/rubrics 仅在其对应 query 执行期间从磁盘缺席,与其他 query 无关。
- 提供**配置开关** `evaluate.isolate_eval_files`(默认 `true`)控制本特性开启/关闭;关闭时不删不还原(调试用)。

## Capabilities

### New Capabilities
- `evaluation-file-isolation`: 在被测 agent 执行任务期间,把该任务的 ground-truth(oracle)与验收清单(rubrics)从磁盘隔离,使其只存在于 evaluator 内存中,任务结束后可还原。

### Modified Capabilities
<!-- 无:本变更不改动 trajectory-evaluation 的评分/质检要求,仅新增执行期文件隔离行为。 -->

## Impact

- 代码:`openclaw_automation.py`
  - `_resolve_evaluate_refs`(留存原始字节+绝对路径)
  - `EvaluateConfig`(新增不落盘字段存放 vault)— 定义在 `evaluator.py`
  - `execute_queries`(per-query 删除 / 还原)
- 受影响文件(运行期被临时删除并还原):`configs/**/oracle.json`、`configs/**/user_queries.json`(均为 git 跟踪源文件)
- 不影响:evaluator 评分逻辑、simulator(不读 `user_queries.json`)、map 模式materialize 的真实任务输入 CSV(保留)。
