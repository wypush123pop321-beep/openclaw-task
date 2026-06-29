# evaluation-file-isolation Specification

## ADDED Requirements

### Requirement: oracle/rubrics 在解析时留存原始字节供还原

系统 SHALL 在解析 query 的 `oracle_ref` / `rubrics_ref` 时,除把内容解析进内存外,额外留存被引用文件的**原始字节**与**绝对路径**,挂在该 query 的 evaluate 配置上(不落盘字段)。还原 MUST 以原始字节写回,MUST NOT 由解析后的对象重新序列化,以保证写回内容与原文件逐字节一致(git 无 diff)。

#### Scenario: 解析时留存原始字节与绝对路径
- **WHEN** `_resolve_evaluate_refs` 读取一个 query 的 `oracle_ref` 或 `rubrics_ref` 指向的文件
- **THEN** 该文件的原始文本与解析后的绝对路径被记录到该 query 的 evaluate 配置的不落盘字段中
- **AND** 内存中的 `oracle_data` / `structured_rubrics` 解析结果保持不变

#### Scenario: rubrics_ref 指向片段时仍按整文件留存
- **WHEN** `rubrics_ref` 是某文件的 JSON-Pointer 片段(如 `user_queries.json#/0/evaluate/0/custom_rubrics`)
- **THEN** 系统留存的是该**整个文件**的原始字节(而非片段),删除与还原均以整文件为单位

### Requirement: 隔离行为由配置开关控制

系统 SHALL 提供一个配置项(query 的 evaluate 块字段 `isolate_eval_files`,默认 `true`)控制本特性的开启/关闭。开关为 `true` 时执行删除+还原;为 `false` 时既不删除也不还原,文件全程保留在盘(供调试)。

#### Scenario: 开关开启时执行隔离
- **WHEN** 某 query 的 evaluate 块 `isolate_eval_files` 为 `true`(或缺省)
- **THEN** 执行期删除 oracle/rubrics、结束后还原

#### Scenario: 开关关闭时不隔离
- **WHEN** 某 query 的 evaluate 块 `isolate_eval_files` 为 `false`
- **THEN** 不删除任何文件,oracle/rubrics 全程保留在磁盘
- **AND** 结束后不触发还原(因无删除)

### Requirement: 任务执行期间从磁盘隔离 oracle/rubrics

当隔离开关开启时,系统 SHALL 在被测 agent 执行某 query 的任务**之前**,把该 query 引用的 oracle 与 rubrics 文件从磁盘删除;agent 全程 MUST 在磁盘不含这两个文件的环境下执行。隔离作用域为 per-query:文件仅在其对应 query 的执行期间缺席,与其他 query 无关。

#### Scenario: 执行前删除被引用文件
- **WHEN** 某 query 含有效 `evaluate` 块且已构建 evaluator,准备进入轮次循环
- **THEN** 该 query 引用的 oracle/rubrics 文件在第一轮 agent 执行前已从磁盘删除

#### Scenario: 执行期间 evaluator 仅依赖内存
- **WHEN** agent 执行任务、evaluator 在评审点评估
- **THEN** evaluator 据内存中的 `oracle_data` / `structured_rubrics` 评分,不读取磁盘上的 oracle/rubrics 文件
- **AND** 评分结果与未删除文件时一致

#### Scenario: 无 evaluate 块的 query 不触发隔离
- **WHEN** 某 query 为 noise 或无 `evaluate` 块(无 oracle/rubrics 引用)
- **THEN** 不执行任何删除操作

### Requirement: 任务结束后尽力还原文件

系统 SHOULD 在某 query 轮次结束后把留存的原始字节写回原路径,仅为本地调试便利。该还原为 best-effort:容器化运行下即使不还原亦不影响后续流程,系统 MUST NOT 因还原失败而中断或报错,亦 MUST NOT 依赖 `finally`/异常兜底来保证还原。

#### Scenario: 正常结束后写回原文件
- **WHEN** 某 query 的轮次循环正常结束
- **THEN** 留存的原始字节被写回原绝对路径,文件内容与删除前逐字节一致

#### Scenario: 还原失败不影响主流程
- **WHEN** 还原写回失败(如路径不可写)
- **THEN** 系统继续后续流程,不抛错中断
