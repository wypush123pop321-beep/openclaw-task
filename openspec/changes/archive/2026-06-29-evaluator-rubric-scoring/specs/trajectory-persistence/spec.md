## ADDED Requirements

### Requirement: 每条 query 的完整轨迹落盘保留

系统 SHALL 在每条 query 执行结束后,把该 query 的完整轨迹持久化为一份结构化文件(如 JSON),使其跑完即留、可离线查阅、可作为 RL 训练样本,MUST NOT 让轨迹仅存在于内存而随进程退出丢失。落盘内容 SHALL 至少包含:原始 query 文本、执行 agent 名、最终结局(`outcome`:done/failed/max_turn)、以及逐轮记录(每轮的 agent 回复、`tool_calls` 证据、产物文件指针 `generated_files{filename, workspace_path}`)。

#### Scenario: query 结束后轨迹落盘
- **WHEN** 某条 query 走完(done/failed/max_turn 任一结局)
- **THEN** 系统 SHALL 将其完整轨迹序列化落盘为结构化文件,文件内容足以离线重建该 query 的执行过程

#### Scenario: 落盘含逐轮证据与产物指针
- **WHEN** 系统序列化某条 query 的轨迹
- **THEN** 落盘记录 SHALL 含每一轮的 `tool_calls` 与 `generated_files` 指针,使离线方可据此核验该轮行为

#### Scenario: 轨迹不随进程退出丢失
- **WHEN** 案例运行进程结束
- **THEN** 已执行 query 的轨迹文件 SHALL 仍存在于磁盘,可被后续读取

### Requirement: 评分结果随轨迹一并落盘

系统 SHALL 把每个评审点的评分结果与轨迹关联落盘,内容 SHALL 包含:各条 rubric 的 0/1 判定、各 `gate` 项状态、分桶得分(bucket → 通过比例与加权后得分)、以及该评审点的最终完成度 `completion`。当一条 query 含多个评审点时,系统 SHALL 保留各评审点的评分,并 SHALL 可标识哪一次为终局评审点(其 `completion` 即该 query 的最终成绩)。

#### Scenario: 评分与轨迹关联落盘
- **WHEN** 某评审点 evaluator 完成评分
- **THEN** 系统 SHALL 把该评审点的逐条 0/1、gate 状态、分桶得分与最终 `completion` 落盘,并与所属 query 轨迹关联

#### Scenario: 多评审点保留并标识终局
- **WHEN** 一条 query 经过多个评审点
- **THEN** 落盘结果 SHALL 保留各评审点评分,并 SHALL 可识别终局评审点的 `completion` 作为该 query 的最终成绩
