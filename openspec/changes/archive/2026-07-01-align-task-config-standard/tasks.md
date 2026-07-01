## 1. 代码：模型字段调整

- [x] 1.1 `openclaw_automation.py` `AutomationConfig` 顶层新增 `Harness_Type: Optional[str] = Field(None, ...)`（声明不消费）
- [x] 1.2 `openclaw_automation.py` `QueryItem` 保留 `is_noise` 为内部字段，新增 `@model_validator(mode="after")` 派生 `is_noise = (not use_simulator) and (evaluate is None)`，无条件覆盖外部输入
- [x] 1.3 `evaluator.py` `EvaluateConfig` 将内联 `scoring: Optional[dict]` 替换为 `scoring_ref: Optional[str]`（JSON-Pointer），保留运行时 `scoring_spec` 字段不变
- [x] 1.4 确认 `AgentConfigItem` 无 `role` 字段、`system_prompt` 字段保留（无需改代码，仅核对）

## 2. 代码：scoring_ref 解析与删兜底

- [x] 2.1 `openclaw_automation.py` `_resolve_evaluate_refs` 新增 `scoring_ref` 解析：拆分 `file_part#ptr` → 读文件 → `_resolve_json_pointer` 定位 scoring 块 → 赋值 → `resolve_runtime()`
- [x] 2.2 删除 `_resolve_evaluate_refs` 中 `1247-1258` 的"内联缺 bucket_map 回退 rubrics_ref 父块"兜底逻辑
- [x] 2.3 `scoring_ref` 文件/指针缺失时抛显式错误（与 `oracle_ref`/`rubrics_ref` 风格一致），不静默退空

## 3. 配置：迁移新标准模板与样本

- [x] 3.1 将 `q1.json` 移至 `task_configs/`，被引用文件保留在 `environments/<task>/`（对齐 `0701_任务管线产物标准模板` 布局，模板已就位）
- [x] 3.2 改写 `oracle_ref`/`rubrics_ref`/`scoring_ref` 为 `../environments/<task>/...` 相对路径
- [x] 3.3 `q1.json` 中 `scoring` 改为 `scoring_ref` JSON-Pointer（`../environments/<task>/user_queries.json#/0/evaluate/0/scoring`）
- [x] 3.4 删除 `q1.json` 中的 `is_noise` 与 `agents[].role` 字段（role 模板本无）
- [x] 3.5 `agents[]` 每个 agent 显式写 `system_prompt: null`
- [x] 3.6 `user_dir.path` 写为相对运行脚本的路径
- [x] 3.7 顶层加 `Harness_Type`（占位，可为 null）

## 4. 测试与验证

- [x] 4.1 `test/test_scoring.py` 注明 scoring 兜底分层（ScoringSpec 单桶兜底保留、resolve-refs 父块兜底已删）；新增 `test/test_scoring_ref.py` 覆盖 scoring_ref 解析/缺失报错/无 ref 兜底
- [x] 4.2 加载测试：加载迁移后的 `task_configs/08_..._q1.json`，`oracle_ref`/`rubrics_ref`/`scoring_ref` 均正确解析、scoring_spec gate=[G1,G2,G3]、无 `FileNotFoundError`
- [x] 4.3 派生测试：`(use_sim=false,eval=null)→True`、`(use_sim=false,eval!=null)→False`、`(use_sim=true,eval!=null)→False`、遗留 `is_noise=true` 被覆盖→False，全部通过
- [x] 4.4 端到端跑通模板 08（`python openclaw_automation.py --config .../task_configs/08_..._q1.json`，exit 0）：配置从 `task_configs/` 布局加载、`oracle_ref`/`rubrics_ref`/`scoring_ref` 均从 `../environments/` 解析、evaluator 多轮打分正常（gate={G1,G2,G3}、completion 逐轮计算、正确 reject solver 幻觉数值）。注:末尾一次 LLM 调用被华为内网代理拦截(openai.InternalServerError)属环境问题、经重试后 exit 0，与本变更无关。
