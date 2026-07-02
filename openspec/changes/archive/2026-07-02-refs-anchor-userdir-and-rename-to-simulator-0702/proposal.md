## Why

当前 `evaluate` 块的 `oracle_ref`/`rubrics_ref`/`scoring_ref` 以 **q1.json 所在目录**为解析基准,而被引用文件(`oracle.json`/`user_queries.json`)其实就住在 `user_dir.path` 目录里。这导致 refs 必须写成 `../environments/<任务名>/...`,把任务目录名在每条 ref 里冗余抄一遍;而 `task-config-schema` spec 里"区分两类相对路径基准"(refs 锚 q1.json、`user_dir.path` 锚 cwd)所声称的"整包搬迁时 refs 原样存活"收益是虚的——`user_dir.path` 本就必须随搬迁更新,并非省了一处维护,反而多了一套基准和一层任务名冗余。

`user_dir.path` 是"任务环境在哪"的单一真源(评估答案/元数据放其顶层、用户可见数据经 MAP 或子目录投放),refs 理应也锚定它。此外,`feedback_to_simulator` 字段名偏长,统一收敛为 `to_simulator`。

## What Changes

- **refs 改锚 `user_dir.path`**:`oracle_ref`/`rubrics_ref`/`scoring_ref` 的相对基准从 q1.json 所在目录改为 `input_dir.user_dir.path`。配置里三条 ref 由 `../environments/<任务名>/xxx` 塌缩为自包含裸名(`oracle.json`、`user_queries.json#/0/...`)。**删除**"两类相对路径基准"规则,收敛为单一基准。
- **`user_dir` 缺失时 fail-fast**:当任一 `*_ref` 非空却 `user_dir` 为 `None`(或被重定向到"虚空地址")时,加载期抛显式 `ValueError`(配置矛盾:要评估却没给环境目录)。`*_ref` 全空时 `user_dir=None` 仍完全合法(纯 agent 跑、无评估)。
- **`feedback_to_simulator` → `to_simulator`**:规范字段名改为 `to_simulator`,`feedback_to_simulator`/`feedback_to_user` 降为历史别名(`AliasChoices`),旧配置零改动仍可读。
- **bulk 数据根显式化 `user_dir.user_workspace`**:新增 `UserDirConfig.user_workspace`(相对 `user_dir.path` 的相对路径,默认 `user_dir.path.name`)。bulk 模式的数据根由"写死的同名子文件夹"改为该字段派生;默认值即当前同名子文件夹行为,向后兼容。map 模式的 map key 基准同步用该数据根(存在则用、否则退回 `user_dir.path`)。示例配置落在 `configs/task_configs_0701/0701_任务管线产物标准模板/task_configs/08_科研助手_描述统计相关分析_q1.json`。

## Capabilities

### Modified Capabilities
- `task-config-schema`: `oracle_ref`/`rubrics_ref`/`scoring_ref` 解析基准由 q1.json 目录改为 `user_dir.path`;删除"两类基准"、新增"refs 需 user_dir 且缺失 fail-fast";新增 `user_dir.user_workspace` 字段显式声明 bulk 数据根。
- `trajectory-evaluation`: `evaluate` 块回流开关的规范名由 `feedback_to_simulator` 改为 `to_simulator`,历史名降为别名。

## Impact

- **代码 `openclaw_automation.py`**:`_resolve_evaluate_refs` 解析基准改为 `user_dir.path`、新增 fail-fast 前置校验;回流判断 `:735` `if evaluator.feedback_to_simulator` → `if evaluator.to_simulator`;`UserDirConfig` 新增 `user_workspace` 字段;`_setup_workspaces`/`setup_agent_files` 的 `content_root` 由 `user_path/user_path.name` 改为 `user_path/(user_workspace or user_path.name)`。
- **代码 `evaluator.py`**:`EvaluateConfig.feedback_to_simulator` 字段与 `feedback_to_simulator` property 改名 `to_simulator`,`AliasChoices` 保留旧名;`to_dict`/日志字段同步。
- **配置**:`configs/task_configs_0701/0701_任务管线产物标准模板/task_configs/08_..._q1.json` 三条 ref 改裸名、`feedback_to_simulator` → `to_simulator`;`configs/config_session.json` 同步改名。
- **文档**:`docs/CONFIG_STRUCTURE.md`、`docs/DESIGN.md`、`README.md` 字段名与基准说明同步。
- **测试**:`test/test_evaluator.py`(`to_simulator` 开关用例)、`test/test_scoring_ref.py`(加载基准从 user_dir 解析、user_dir 缺失报错)。
