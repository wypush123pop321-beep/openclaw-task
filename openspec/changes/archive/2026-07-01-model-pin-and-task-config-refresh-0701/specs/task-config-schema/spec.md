## ADDED Requirements

### Requirement: 任务包收纳于 configs/task_configs_0701/ 且区分两类相对路径基准

任务管线的成套产物(`task_configs/` 与 `environments/` 两个子树)SHALL 收纳于 `configs/task_configs_0701/` 目录下统一管理。在该收纳布局下,系统 SHALL 区分两类相对路径的解析基准:query 的 `evaluate.oracle_ref`/`rubrics_ref`/`scoring_ref` SHALL 继续以其所在 `q1.json` 目录为基准解析(收纳后 `../environments/<task>/...` 形式的内部引用原样存活);而 `input_dir.user_dir.path` SHALL 以运行时工作目录(cwd/项目根)为基准解析,收纳导致其前缀变化时 SHALL 同步更新为收纳后的路径。迁移脚本中对任务目录名的硬编码 SHALL 同步更新为收纳后的路径。

#### Scenario: 收纳后内部 *_ref 引用原样存活
- **WHEN** 任务包被收纳到 `configs/task_configs_0701/` 且 `q1.json` 与 `environments/` 保持相对结构不变
- **THEN** 系统 SHALL 仍以 `q1.json` 所在目录为基准正确解析 `oracle_ref`/`rubrics_ref`/`scoring_ref`,无需改写这些引用

#### Scenario: user_dir.path 按 cwd 基准更新前缀
- **WHEN** 任务包收纳导致 `user_dir.path` 相对项目根的前缀发生变化
- **THEN** 该 `user_dir.path` SHALL 更新为收纳后的完整相对路径,使系统据 cwd 基准仍能定位到环境目录

#### Scenario: 迁移脚本硬编码目录名同步更新
- **WHEN** 迁移脚本中硬编码了旧任务目录名
- **THEN** 该硬编码 SHALL 更新为收纳后的路径,脚本据新路径正确定位任务包
