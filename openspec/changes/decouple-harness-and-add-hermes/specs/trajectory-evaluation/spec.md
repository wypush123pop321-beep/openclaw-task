## MODIFIED Requirements

### Requirement: evaluator 无状态且独立投喂

evaluator 的**会话**SHALL 以无状态方式运行:**evaluator agent 实体在同一 query 内持久复用,但其会话 SHALL 在每次评估之前经 `harness-adapter` 的会话重置能力清空**——因为会话会持久化并回放 agent 自身的历史回复(含上一轮判词),若不清空将造成判词自我锚定。当 adapter 不具备会话重置能力时,系统 SHALL 安全跳过重置(退回等价语义),核心层 MUST NOT 直接调用 harness 专属重置方法。每轮评估所需上下文 SHALL 由系统从 harness 侧记录的 trajectory **显式压缩投喂**,session MUST NOT 承担跨轮记忆职责。

投喂内容 SHALL 为压缩后的 trajectory,仅包含:原始任务(`origin_query`)、冻结 rubrics、**最近 X 轮**的执行记录(含该轮 `tool_calls`)、以及产物文件指针 `generated_files{filename, workspace_path}`;系统 MUST NOT 投喂全量历轮记录,MUST NOT 内联产物文件全文,MUST NOT 把 evaluator 自身上一轮的结构化判词回投给它(防锚定)。"进步感知"SHALL 由最近 X 轮的**证据变化**体现,而非由复用自身会话记忆或回放旧判词得到。

#### Scenario: 每次评估前 reset 会话
- **WHEN** 进入一个评审点、准备调用 evaluator,且 adapter 具备会话重置能力
- **THEN** 系统 SHALL 先经 adapter 的会话重置能力清空该 evaluator 会话,确保其上一轮回复/判词不被回放进本轮评估

#### Scenario: 复用持久 agent 而非每轮重建
- **WHEN** 同一 query 的下一个评审点到来
- **THEN** 系统 SHALL 复用既有 evaluator agent 实体并仅重置其会话,MUST NOT 重新创建 agent 或重新初始化连接

#### Scenario: 有界压缩投喂(最近 X 轮 + 产物指针)
- **WHEN** 系统为某次评估构建投喂上下文
- **THEN** 投喂 SHALL 仅含 `origin_query` + rubrics + 最近 X 轮(含 `tool_calls`)+ `generated_files{filename, workspace_path}` 指针,MUST NOT 含全量历轮或产物全文

#### Scenario: 不回放自身历史判词(防锚定)
- **WHEN** evaluator 在某 query 的第二个及以后评审点工作
- **THEN** 其本轮裁定 MUST NOT 受其自身上一轮判词影响——既因会话重置使其不回放该判词,也因投喂内容不含其上一轮结构化判决

#### Scenario: 进步感知来自证据 delta
- **WHEN** 系统投喂了最近 X 轮记录
- **THEN** evaluator SHALL 据这几轮的证据变化判断"先前问题本轮是否改进",而 MUST NOT 依赖跨轮的自身会话记忆

### Requirement: 裁判模型钉死且独立于被测 agent

系统 SHALL 为 evaluator agent 钉死一个固定模型,该模型 SHALL 刻意区别于被测执行 agent(建议采用更快的 flash 级模型),并在整段评估过程中保持不变。模型 SHALL 经 `harness-adapter` 的供给能力下发(`ensure_agent` 按 `AgentSpec.model` 钉死;OpenClaw adapter 内部经 `agents.update` 实现,Hermes adapter 经 `set_session_model` 实现);核心层 MUST NOT 直接调用 harness 专属的模型下发方法。evaluator 模型的连接信息(模型名/provider/URL/api-key)SHALL 可在 config 中配置。

#### Scenario: 经 adapter 钉死模型
- **WHEN** 系统装配 evaluator agent
- **THEN** 系统 SHALL 经 adapter 的 `ensure_agent`(携带 `AgentSpec.model`)下发固定模型,使其评估始终使用该模型,而 MUST NOT 在核心层直接调用 harness 专属下发方法

#### Scenario: 裁判模型独立于被测 agent
- **WHEN** 配置 evaluator 模型
- **THEN** 该模型 SHALL 不要求与被测 agent 一致,且 SHALL 倾向选用与之不同的快模型,以降低同构盲点

#### Scenario: 模型连接信息可配
- **WHEN** 在 config 中声明 evaluator 的模型连接(model/provider/URL/api-key)
- **THEN** 系统 SHALL 据此下发模型;缺失关键连接信息时 SHALL 明确告警而非静默退回被测模型
