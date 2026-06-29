## Why

光钰提供的 RL 评测任务（如 `04_出行助手_task1_班次时刻表核对`）把评分从「LLM 主观拍 completion」升级为「结构化 rubric + 确定性公式聚合」，目的是产出**不可被模型欺骗的可验证奖励信号**（任务注脚：「机器判分占比 100% → 诚信 → 进 RL」）。现有 evaluator 只接受纯字符串 rubric、completion 由裁判模型直接给出（`evaluator.py:73`），无法解析 `oracle_ref` / `rubrics_ref` / `scoring`，也无法把每条 rubric 判成 0/1 再按权重聚合，因此跑不通这类任务。同时，完整轨迹（turns / tool_calls / 产物指针 / outcome）当前只存在内存中、跑完即丢，无法作为 RL 训练样本留存。

## What Changes

- **rubric 结构化**：rubric 从 `List[str]` 升级为带 `id / when / evaluator / text / formula` 的结构化对象；保留对旧字符串格式的向后兼容。
- **确定性评分聚合**：新增 `ScoringSpec` + `Scorer` 抽象，按公式 `completion = (∏ gate) × Σ_bucket [ w_bucket × (桶内通过数/桶内总数) ]` 计算 completion，不再由裁判模型直接拍分。**BREAKING**：`EvaluationResult.completion` 的来源从「模型直接给」改为「Scorer 算出」。
- **completion 取值域 0~1、移除 R 字段**：completion 改为 `0~1`（**非百分制**，不再 `round(R*100)`），即聚合公式的直接结果；移除独立的 `R` 字段（原 `R` 即此 `completion`）。**BREAKING**：`Scorer.score()` 返回值不再含 `R`，`completion` 由 0-100 改为 0~1。
- **map 模式按 `user_dir.path` 解析源路径**：`_setup_workspaces` 的 map 模式让 `MAP_*.json` 的 key 直接相对 `user_dir.path` 解析，不再强制走同名子文件夹 `path/path.name`（同名子文件夹存在时仍兼容旧布局）。整体复制模式不变。详见 design D8。
- **rubric 二值化**：每条 rubric 由 evaluator-agent 判定为 0/1（通过/不通过），不再使用 `pass/partial/unverifiable` 四态；核验受阻一律判 0（接受该风险，后续迭代）。
- **`when` 仅用于识别 gate**：`gate` 项参与一票否决（`∏ gate`，全过才非 0），`per_turn` 与 `final` 一视同仁、每个评审点都评、按 `bucket` 加权，不区分评审时机。
- **config 解析适配**：支持 `evaluator_agent` / `evaluate_every_n_turns` / `feedback_to_user` 三处改名（兼容旧名），新增 `oracle_ref` 加载、`rubrics_ref` 的 JSON-Pointer 解引用、`scoring`（`gate_zero` / `weights` / `bucket_map`）解析；权重来源做抽象，隔离未来字段位置变动。
- **用户画像按 `profile_file` 装配**：simulator 改读 `input_dir.user_dir.profile_file`，不再写死 `user_profile.json`（`user_simulator.py:48`）。
- **轨迹数据落盘保留**：每条 query 的完整轨迹与各评审点的评分结果落盘为结构化文件，跑完案例后可查、可作 RL 样本。

## Capabilities

### New Capabilities
- `trajectory-persistence`: 把每条 query 的完整轨迹（query / turns / tool_calls / 产物指针 / outcome）与每个评审点的评分结果（每条 rubric 的 0/1、分桶得分、gate 状态、最终 completion（0~1））持久化为结构化文件。

### Modified Capabilities
- `trajectory-evaluation`: rubric 升级为结构化对象并向后兼容字符串；completion 改由确定性 `Scorer`（∏gate × Σ桶加权）算出而非模型直接给；rubric 判定收敛为 0/1；新增 `oracle_ref` / `rubrics_ref`(JSON-Pointer) / `scoring` 解析与改名字段兼容；用户画像按 `profile_file` 装配。

## Impact

- **代码**：
  - `evaluator.py`：`EvaluateConfig`（新字段+兼容）、`RubricCheck`/`EvaluationResult`（二值化、`completion: float` 0~1）、新增 `ScoringSpec`/`Scorer`（`score()` 返回 `completion`(0~1)，不再含 `R`）、`_build_prompt`（投喂结构化 rubric 与 formula、要求 0/1 输出、声明 completion 0~1）。
  - `openclaw_automation.py`：config 解析（oracle/rubrics ref 加载、scoring 装配、profile_file 已部分支持于 `:369`）、轨迹落盘接线、`_setup_workspaces` map 模式按 `user_dir.path` 解析源路径（design D8）。
  - `user_simulator.py`：按 `profile_file` 读取用户画像（`:48` 写死项修复）。
  - `trajectory.py`：轨迹序列化/落盘支持。
  - `test/test_scoring.py`：断言由 `R` 改为 `completion`（0~1）。
- **验收基线**：能跑通 `task_test/rl14_clean/04_出行助手_task1_班次时刻表核对`，最终 `completion ≈ 1.0`（对齐 `results_4pilot.json` 的 `R=1.0`），且轨迹与评分结果落盘可查。
- **依赖**：无新增第三方依赖（JSON-Pointer 可用标准库手解或轻量实现）。
- **兼容性**：旧 `config_session.json`（字符串 rubrics、无 scoring）继续可用，走默认聚合（无 gate、等权或单桶）。
