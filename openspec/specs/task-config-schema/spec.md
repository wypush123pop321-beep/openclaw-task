# task-config-schema Specification

## Purpose

规范任务管线单任务配置文件(`q1.json`)的目录布局、字段来源与派生规则,使任务配置与其引用的环境文件分离,并令噪声判定、评分来源、agent 声明、顶层占位字段与 oracle 引用遵循统一、显式、可校验的约定。

## Requirements

### Requirement: 任务配置与被引用文件分目录布局

任务管线的单任务配置文件 `q1.json` SHALL 放置于 `task_configs/` 目录下,与其被引用的环境文件(`oracle.json`、`user_queries.json`、`user_profile*.json`、`MAP_*.json`、真实数据文件)分离;后者 SHALL 位于 `environments/<task>/` 目录下。系统解析 `q1.json` 中相对引用时,SHALL 以 `q1.json` 所在目录为基准。

#### Scenario: q1.json 与环境文件分目录
- **WHEN** 加载 `task_configs/<task>_q1.json`
- **THEN** 系统 SHALL 以该 `q1.json` 所在目录为基准解析 `oracle_ref`/`rubrics_ref`/`scoring_ref`,被引用文件位于 `../environments/<task>/` 下时能被正确定位

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
