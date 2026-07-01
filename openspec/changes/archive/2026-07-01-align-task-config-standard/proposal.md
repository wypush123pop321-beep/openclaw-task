## Why

任务管线产出的单任务配置(`q1.json`)与批跑管线的接口需要对齐到新标准(`0701_任务管线产物标准模板`)。当前配置存在冗余字段(`is_noise`、`role`)、隐式耦合(`scoring` 靠"缺 bucket_map 就回退 rubrics_ref 父块"的兜底)、以及文件布局与相对路径基准的不一致(`q1.json` 与被引用文件同目录,而新布局要求 `q1.json` 独立到 `task_configs/`)。不对齐会导致两条管线在字段语义和路径解析上各说各话,批跑时易出 `FileNotFoundError` 或评分口径漂移。

## What Changes

- **文件布局**:`q1.json` 从 `environments/<task>/` 移出,统一放到 `task_configs/`;被引用文件(`oracle.json`、`user_queries.json`)留在 `environments/<task>/`。
- **相对引用基准**:`oracle_ref`/`rubrics_ref`/`scoring_ref` 改为指向 `../environments/<task>/...`(仍以 `q1.json` 所在目录为解析基准);`user_dir.path` 为相对运行脚本的路径。
- **`is_noise` 收窄为派生**:**BREAKING**(对外接口) 从 `q1.json` 移除 `is_noise` 字段;内部由加载后校验器派生 `is_noise = (not use_simulator) and (evaluate is None)`,三处下游分支逻辑不变。
- **`scoring` → `scoring_ref`**:**BREAKING** 内联 `scoring` dict 退场,改为 JSON-Pointer 字符串 `scoring_ref`(如 `user_queries.json#/0/evaluate/0/scoring`);显式解析,并**删除**旧的"缺 bucket_map 回退父块"兜底逻辑。
- **删除 `role` 字段**:`agents[]` 不再写 `role`(代码本无此字段,纯接口清稿),agent 与 evaluator 靠 `model` 区分。
- **`system_prompt` 显式化**:`agents[]` 每个 agent 显式写 `system_prompt`(默认 `null`)。
- **新增 `Harness_Type` 顶层占位字段**:声明于 `AutomationConfig` 顶层(`Optional[str] = None`),当前不消费,预留后续特性。
- 确认既有行为:`oracle_ref` 支持 `NULL`(不填则不加载 oracle),无需改动。

**搁置(不在本次范围)**:`custom_rubrics.evaluator=program` 的真实执行、以及评估器判题过程 tool_call 的可观测性,后续单独探索。

## Capabilities

### New Capabilities
- `task-config-schema`: 任务管线单任务配置(`q1.json`)对外契约与加载解析规则——文件布局(`task_configs/` vs `environments/`)、相对引用基准、`is_noise` 派生、`scoring_ref`/`oracle_ref`/`rubrics_ref` 的 JSON-Pointer 解析、`role` 移除、`system_prompt` 显式化、`Harness_Type` 占位。

### Modified Capabilities
<!-- 评估语义(LLM 逐条判 0/1 + Scorer 聚合)不变,仅配置契约与 scoring 来源变化,归入新 capability。此处无既有 spec 的需求级变更。 -->

## Impact

- **配置文件**:`configs/<task>/q1.json` 及新标准模板 `0701_任务管线产物标准模板/task_configs/*.json`(迁移 + 字段调整)。
- **代码 `openclaw_automation.py`**:`AgentConfigItem`(删 `role` 无操作、`system_prompt` 保留)、`QueryItem`(`is_noise` 改派生校验器)、`AutomationConfig`(加 `Harness_Type`)、`_resolve_evaluate_refs`(新增 `scoring_ref` 解析、删除 scoring 兜底分支 `1247-1258`)。
- **代码 `evaluator.py`**:`EvaluateConfig` 用 `scoring_ref: Optional[str]` 取代内联 `scoring: Optional[dict]`,`scoring_spec` 运行时字段不变。
- **测试**:`test/test_scoring.py` 中"空 scoring 退回单桶"用例需对齐新的 scoring 来源路径。
