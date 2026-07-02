# task-config-schema Specification

## Purpose

规范任务管线单任务配置文件(`q1.json`)的目录布局、字段来源与派生规则,使任务配置与其引用的环境文件分离,并令噪声判定、评分来源、agent 声明、顶层占位字段与 oracle 引用遵循统一、显式、可校验的约定。

## Requirements

### Requirement: 任务配置与被引用文件分目录布局

任务管线的单任务配置文件 `q1.json` SHALL 放置于 `task_configs/` 目录下,与其被引用的环境文件(`oracle.json`、`user_queries.json`、`user_profile*.json`、`MAP_*.json`、真实数据文件)分离;后者 SHALL 位于 `environments/<task>/` 目录下。系统解析 `q1.json` 中 `evaluate.oracle_ref`/`rubrics_ref`/`scoring_ref` 时,SHALL 以 `input_dir.user_dir.path` 为相对基准(不再以 `q1.json` 所在目录为基准)。由于被引用环境文件物理上位于 `user_dir.path`(即 `environments/<task>/`)之内,规范 ref SHALL 写为相对 `user_dir.path` 的自包含裸名(如 `oracle.json`、`user_queries.json#/0/...`),MUST NOT 再写 `../environments/<task>/...` 形式的跨目录引用。

#### Scenario: refs 相对 user_dir.path 解析

- **WHEN** 加载 `task_configs/<task>_q1.json`,其 `user_dir.path` 指向 `environments/<task>/`
- **THEN** 系统 SHALL 以 `user_dir.path` 为基准解析 `oracle_ref`/`rubrics_ref`/`scoring_ref`,裸名 `oracle.json` 定位到 `environments/<task>/oracle.json`

#### Scenario: 引用路径缺失显式报错

- **WHEN** `oracle_ref`/`rubrics_ref`/`scoring_ref` 指向的文件或指针不存在
- **THEN** 系统 SHALL 抛出显式错误(如 `FileNotFoundError`),MUST NOT 静默退空

### Requirement: is_noise 由派生规则决定而非外部输入

`q1.json` 的 query 对象 SHALL NOT 再包含外部可填的 `is_noise` 字段。系统在配置加载后 SHALL 派生 `is_noise = (not use_simulator) and (evaluate is None)`,并以派生值为准;即使外部遗留配置写入了 `is_noise`,系统 SHALL 以派生值无条件覆盖。

#### Scenario: 无 simulator 且无评估视为噪声
- **WHEN** 某 query 的 `use_simulator` 为 `false` 且 `evaluate` 为 `null`
- **THEN** 系统 SHALL 令 `is_noise` 为真,agent 仅执行一次,evaluator 与 user_simulator 均不参与

#### Scenario: 有评估的单发执行不视为噪声
- **WHEN** 某 query 的 `use_simulator` 为 `false` 但 `evaluate` 非空
- **THEN** 系统 SHALL 令 `is_noise` 为假,不启动多轮 simulator,但 SHALL 执行评估

#### Scenario: 遗留 is_noise 输入被覆盖
- **WHEN** 外部配置仍写入 `is_noise` 字段
- **THEN** 系统 SHALL 忽略该输入值并以派生规则计算的值为准

### Requirement: scoring 来源改为 scoring_ref JSON-Pointer 显式引用

query 的 `evaluate` 块 SHALL 使用 `scoring_ref`(JSON-Pointer 字符串,如 `user_queries.json#/0/evaluate/0/scoring`)引用评分规格,MUST NOT 再内联 `scoring` dict。系统 SHALL 解析 `scoring_ref` 指向的评分块作为唯一评分来源,MUST NOT 依赖"内联缺 bucket_map 时回退 rubrics_ref 父块"的隐式兜底逻辑。

#### Scenario: 显式解析 scoring_ref
- **WHEN** `evaluate.scoring_ref` 为有效 JSON-Pointer 且指向 `user_queries.json` 中的 scoring 块
- **THEN** 系统 SHALL 解析该块为运行时 `scoring_spec`,并据其驱动确定性评分聚合

#### Scenario: scoring_ref 解析失败显式报错
- **WHEN** `scoring_ref` 文件或指针无法解析
- **THEN** 系统 SHALL 抛出显式错误,MUST NOT 静默退回任何默认评分

### Requirement: agent 声明去除 role 并显式声明 system_prompt

`agents[]` 中每个 agent 声明 SHALL NOT 包含 `role` 字段——agent 与 evaluator 的区分 SHALL 由 `model`(及其它配置)承担。每个 agent 声明 SHALL 显式包含 `system_prompt` 字段,默认值为 `null`。

#### Scenario: 无 role 字段仍可区分 agent 与 evaluator
- **WHEN** 配置中 agent 声明不含 `role`
- **THEN** 系统 SHALL 正常加载,并按 query 的 `agent_name` 与 `evaluate.agent_name` 引用区分执行 agent 与 evaluator

#### Scenario: system_prompt 显式为 null
- **WHEN** agent 声明中 `system_prompt` 为 `null`
- **THEN** 系统 SHALL 使用内置默认提示词行为(evaluator 回退内置评估模板),不因显式 `null` 而报错

### Requirement: 顶层 Harness_Type 占位字段

配置的顶层对象 SHALL 支持一个可选的 `Harness_Type` 字段(字符串,默认 `null`)。当前系统 SHALL 声明但不消费该字段,其存在或缺省 MUST NOT 影响任何运行时行为,预留后续特性支持。

#### Scenario: Harness_Type 声明但不影响行为
- **WHEN** 顶层配置包含或缺省 `Harness_Type`
- **THEN** 系统 SHALL 正常加载配置,运行时行为与该字段取值无关

### Requirement: oracle_ref 支持 NULL

query 的 `evaluate.oracle_ref` SHALL 允许为 `null`(或缺省)。当 `oracle_ref` 为空时,系统 SHALL NOT 加载任何 ground-truth oracle 数据,评估在无 oracle 的情况下继续进行。

#### Scenario: oracle_ref 为空不加载 oracle
- **WHEN** `evaluate.oracle_ref` 为 `null` 或缺省
- **THEN** 系统 SHALL 跳过 oracle 加载,评估器提示词中不含 oracle 片段,评估流程正常继续

### Requirement: 评估引用需 user_dir 且缺失时 fail-fast

当某 query 的 `evaluate` 块设置了任一 `oracle_ref`/`rubrics_ref`/`scoring_ref`(非空)时,系统 SHALL 要求 `input_dir.user_dir` 已配置且其 `path` 为有效环境目录,以作为引用解析基准。当 `user_dir` 为 `None`,或其 `path` 被重定向为"虚空地址"(空的临时占位目录)时,系统 SHALL 在配置加载期抛出显式 `ValueError`,MUST NOT 静默退空或退回其它基准。当所有 `*_ref` 均为空时,`user_dir` 为 `None` SHALL 合法(纯 agent 执行、无评估)。

#### Scenario: 设了 ref 却无 user_dir 报错

- **WHEN** 某 query 的 `evaluate` 设置了 `oracle_ref`/`rubrics_ref`/`scoring_ref` 之一,但 `input_dir.user_dir` 为 `None`
- **THEN** 系统 SHALL 抛出显式 `ValueError`(配置矛盾:要评估却无环境目录),MUST NOT 继续加载

#### Scenario: user_dir 为虚空地址且设了 ref 报错

- **WHEN** `user_dir` 因 `path` 为 `null` 被重定向到虚空地址,且某 `evaluate` 设置了任一 `*_ref`
- **THEN** 系统 SHALL 识别该虚空地址并抛出与 `user_dir=None` 一致的显式 `ValueError`,MUST NOT 让引用解析退化为指向虚空目录的含糊 `FileNotFoundError`

#### Scenario: 无 ref 时 user_dir 可缺省

- **WHEN** 某 query 的 `evaluate` 未设置任何 `*_ref`(或无 `evaluate` 块),且 `user_dir` 为 `None`
- **THEN** 系统 SHALL 正常加载,agent 照常执行,不因无 `user_dir` 报错

### Requirement: bulk 数据根由 user_dir.user_workspace 显式声明

`UserDirConfig` SHALL 支持可选字段 `user_workspace`(相对 `user_dir.path` 的相对路径),用于显式声明 bulk 模式的"用户数据根"子目录。当 `user_workspace` 缺省时,系统 SHALL 回退到 `user_dir.path` 的目录名(`user_dir.path.name`)作为数据根子目录,使不填该字段时行为与既有"同名子文件夹"约定完全一致。bulk 模式下系统 SHALL 以该数据根子目录的内容为待部署用户文件;map 模式下 map key 的相对基准 SHALL 在该数据根子目录存在时用它、否则退回 `user_dir.path`。规范任务配置 SHALL 在 `input_dir.user_dir` 下显式写出 `user_workspace`(以 `configs/task_configs_0701/0701_任务管线产物标准模板/task_configs/08_科研助手_描述统计相关分析_q1.json` 为示例)。

#### Scenario: 显式 user_workspace 指定数据根

- **WHEN** `input_dir.user_dir.user_workspace` 指向 `user_dir.path` 下的某子目录
- **THEN** 系统 SHALL 以该子目录为 bulk 数据根,部署其内容到 agent workspace(map 模式则以其为 map key 基准)

#### Scenario: user_workspace 缺省回退同名子文件夹

- **WHEN** `input_dir.user_dir` 未声明 `user_workspace`
- **THEN** 系统 SHALL 以 `user_dir.path.name`(同名子文件夹)为数据根,行为与既有约定一致

### Requirement: 任务包收纳于 configs/task_configs_0701/ 且统一以 user_dir.path 为评估引用基准

任务管线的成套产物(`task_configs/` 与 `environments/` 两个子树)SHALL 收纳于 `configs/task_configs_0701/` 目录下统一管理。在该收纳布局下,系统 SHALL 采用**单一**引用解析基准:query 的 `evaluate.oracle_ref`/`rubrics_ref`/`scoring_ref` SHALL 以 `input_dir.user_dir.path` 为基准解析(裸名引用,不含 `../environments/` 前缀);而 `input_dir.user_dir.path` 自身 SHALL 以运行时工作目录(cwd/项目根)为基准解析,收纳导致其前缀变化时 SHALL 同步更新为收纳后的路径。迁移脚本中对任务目录名的硬编码 SHALL 同步更新为收纳后的路径。

#### Scenario: 收纳后裸名 ref 相对 user_dir.path 存活

- **WHEN** 任务包被收纳到 `configs/task_configs_0701/`,`user_dir.path` 已更新为收纳后路径,ref 写为裸名
- **THEN** 系统 SHALL 以 `user_dir.path` 为基准正确解析 `oracle_ref`/`rubrics_ref`/`scoring_ref`,无需在 ref 中重复任务目录名

#### Scenario: user_dir.path 按 cwd 基准更新前缀

- **WHEN** 任务包收纳导致 `user_dir.path` 相对项目根的前缀发生变化
- **THEN** 该 `user_dir.path` SHALL 更新为收纳后的完整相对路径,使系统据 cwd 基准仍能定位到环境目录

#### Scenario: 迁移脚本硬编码目录名同步更新

- **WHEN** 迁移脚本中硬编码了旧任务目录名
- **THEN** 该硬编码 SHALL 更新为收纳后的路径,脚本据新路径正确定位任务包
