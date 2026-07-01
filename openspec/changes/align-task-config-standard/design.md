## Context

任务管线产出的 `q1.json` 与批跑管线的接口需对齐到新标准 `0701_任务管线产物标准模板`。当前实现的关键约束(经代码核实):

- `ConfigLoader.load_from_file` 以 `path.parent`(即 `q1.json` 所在目录)为基准调用 `_resolve_evaluate_refs`,解析 `oracle_ref`/`rubrics_ref`(`openclaw_automation.py:1294,1225,1235`)。
- `user_dir.path` 经 `Path(...).expanduser()` 解析(`1124`),基准为 CWD/运行脚本——与上一条基准不同,存在"双基准"。
- `is_noise` 为 `QueryItem` 实体字段,被 3 处引用:noise 单发日志(`927`)、起 simulator(`933`)、建 evaluator(`953-957`)。
- scoring 现由 `_resolve_evaluate_refs` 的兜底逻辑合成:内联 `scoring` 缺 `bucket_map` 时回退 rubrics_ref 父块(`1247-1258`)。
- `AgentConfigItem` 无 `role` 字段;pydantic 未设 `extra="forbid"`,未知字段被静默忽略。
- 评估语义(LLM 逐条判 0/1 + `Scorer` 聚合)不变,本次仅动配置契约与 scoring 来源。

## Goals / Non-Goals

**Goals:**
- 让 `q1.json` 迁到 `task_configs/` 后,`oracle_ref`/`rubrics_ref`/`scoring_ref` 以 `../environments/<task>/...` 正确解析。
- `is_noise` 收窄为内部派生,下游 3 处分支零改动。
- `scoring` 改为显式 `scoring_ref`(JSON-Pointer),删除隐式兜底。
- `role` 移除、`system_prompt` 显式化、`Harness_Type` 顶层占位。

**Non-Goals:**
- 不实现 `custom_rubrics.evaluator=program` 的真实执行(formula 仍为伪代码,由 LLM 语义判定)。
- 不新增评估器判题过程 tool_call 的观测/落盘。
- 不改动评估聚合算法、trajectory 采集、file-isolation 等既有能力。

## Decisions

### D1: is_noise 派生而非内联展开(改一处)
在 `QueryItem` 上加 `@model_validator(mode="after")`,设 `self.is_noise = (not self.use_simulator) and (self.evaluate is None)`,**无条件覆盖**任何外部输入。保留 `is_noise` 为内部字段,下游 `927/933/953` 三处分支原样不动。
- **为何**:代入派生定义后,`933`/`953` 的 `not is_noise` 在其各自前置条件下恒真,行为不变;仅 `927` 实质使用。保留语义名比把 `(!use_simulator ∧ evaluate==None)` 内联到 3 处更可读、改动面更小。
- **备选**:内联到 3 处分支——被否,改动面大、易漏、可读性差。

### D2: scoring_ref 显式解析 + 删兜底
`EvaluateConfig` 用 `scoring_ref: Optional[str]`(JSON-Pointer)取代内联 `scoring: Optional[dict]`。`_resolve_evaluate_refs` 新增一段:拆分 `file_part#ptr` → 读文件 → `_resolve_json_pointer` 定位 scoring 块 → 赋给运行时,再 `resolve_runtime()` 合成 `scoring_spec`。**删除** `1247-1258` 的兜底分支。
- **为何**:与 `rubrics_ref`/`oracle_ref` 对称,来源唯一、显式、缺失即报错;消除"内联 vs 父块"的隐式耦合与新旧路径打架风险。
- **备选**:保留空 dict `{}` 靠约定回退——被否,脆弱且不显式。

### D3: 相对引用基准维持 config_dir,靠路径写法对齐
`oracle_ref`/`rubrics_ref`/`scoring_ref` 继续以 `q1.json` 所在目录为基准解析(不改解析代码),配置里写成 `../environments/<task>/...` 即可跨目录定位。`user_dir.path` 写成相对运行脚本的路径。
- **为何**:最小改动即满足新布局;避免大改解析基准带来的回归风险。
- **权衡/遗留**:`user_dir.path`(运行脚本基准)与 refs(config_dir 基准)仍是双基准。本次接受此现状,若后续要彻底统一到单一基准,另立变更。

### D4: role 删除为纯清稿
`AgentConfigItem` 本无 `role`,配置移除后行为不变。不引入 `extra="forbid"`,以免遗留配置(含 `is_noise`/`role`)加载即报错;派生/忽略策略已足够。

### D5: Harness_Type 顶层声明不消费
在 `AutomationConfig` 顶层加 `Harness_Type: Optional[str] = None`,声明但不读取。显式声明(而非依赖"被忽略")可保证将来若开启 `extra="forbid"` 不会误伤该占位字段。

## Risks / Trade-offs

- **[双基准混淆]** `user_dir.path`(运行脚本基准)与 refs(config_dir 基准)并存,配置作者可能写错相对路径 → 缓解:在模板与文档中给出明确示例(`../environments/<task>/...`),并保留缺失即报错的行为让错误尽早暴露。
- **[scoring 迁移遗漏]** 删兜底后,凡未提供有效 `scoring_ref` 的历史配置会报错 → 缓解:迁移所有现存 `configs/*/q1.json` 与模板;更新 `test/test_scoring.py`。
- **[is_noise 语义变化]** 新模型下"单发 + 评估"(`use_simulator=false, evaluate!=null`)不再是 noise → 这是表达力增强,需在评审中确认符合预期。
- **[program 误解]** 相关方可能以为 `evaluator=program` 会真执行 → 缓解:在提案与文档中显式声明"当前为 LLM 语义判定,非真实执行",真实执行列为后续独立探索。

## Migration Plan

1. 代码:改 `EvaluateConfig`(`scoring`→`scoring_ref`)、`QueryItem`(is_noise 派生校验器)、`AutomationConfig`(加 `Harness_Type`)、`_resolve_evaluate_refs`(加 scoring_ref 解析、删兜底)。
2. 配置:迁移 `q1.json` 到 `task_configs/`,改写 refs 为 `../environments/<task>/...`,删 `is_noise`/`role`,`scoring`→`scoring_ref`,agent 补 `system_prompt:null`。
3. 测试:更新 `test/test_scoring.py`;跑一个真实任务样本(如 08_科研助手)端到端验证加载 + 评估。
4. 回滚:配置与代码改动均在本分支,回滚即 revert 本变更提交。

## Open Questions

- 是否在本次一并迁移全部 `configs/*` 样本,还是仅先落地 08_科研助手 + 新标准模板作为参考实现?(倾向:先落 08 + 模板,其余批量跟进。)
