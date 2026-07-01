## ADDED Requirements

### Requirement: 核心层只依赖中立 Harness 适配接口

系统 SHALL 定义一个中立的 `HarnessAdapter` 接口作为框架与任意 harness 之间的唯一边界。编排层、轨迹捕获层、评估层 MUST NOT 直接 `import openclaw_sdk` 或调用任何 harness 专属类型/方法;它们 SHALL 只依赖 `HarnessAdapter` 接口与中立数据类型。harness 专属的客户端、网关、传输与韧性细节 SHALL 全部封装在具体 adapter 实现内部。

#### Scenario: 核心模块不含 harness 专属 import
- **WHEN** 检查编排层、`trajectory`、`evaluator` 模块的依赖
- **THEN** 这些模块 MUST NOT 出现 `openclaw_sdk`(或任何具体 harness SDK)的 import,所有 harness 交互 SHALL 经由 `HarnessAdapter` 接口

#### Scenario: 新增 harness 不改核心
- **WHEN** 未来要接入一个新的 harness
- **THEN** 系统 SHALL 仅需新增一个实现 `HarnessAdapter` 的 adapter 并注册,而 MUST NOT 要求修改编排/轨迹/评估的核心逻辑

### Requirement: Adapter 声明能力,核心按能力降级

`HarnessAdapter` SHALL 暴露一组声明式能力(`Capability`),至少覆盖:多 agent 供给、文件证据、结构化输出、健康检查、history 兜底、会话重置。核心层 SHALL 在调用可选能力前查询 `adapter.capabilities`;当某能力缺失时,系统 SHALL 落入既有降级路径(如标注证据不完整、退回自由维度评估、跳过会话重置),而 MUST NOT 报错中断任务。

#### Scenario: 缺失文件证据能力时降级而非报错
- **WHEN** 当前 adapter 的 `capabilities` 不含文件证据能力
- **THEN** 系统 SHALL 跳过文件取证并按"证据不完整"语义继续,任务流程 MUST NOT 因此中断

#### Scenario: 缺失结构化输出能力时走兜底并重试
- **WHEN** 当前 adapter 的 `capabilities` 不含结构化输出能力
- **THEN** evaluator SHALL 改用解析兜底路径产出结构化裁决(MUST NOT 依赖 harness 原生强制 schema);当一次解析失败时 SHALL 以"仅输出 JSON"的强约束提示重试有限次,全部失败才放弃

#### Scenario: 缺失会话重置能力时跳过而非报错
- **WHEN** 当前 adapter 的 `capabilities` 不含会话重置能力
- **THEN** 持久 evaluator 的"每轮 reset"SHALL 安全跳过(退回不重置的等价语义),任务流程 MUST NOT 因此中断

### Requirement: 中立结果与数据类型

系统 SHALL 定义与任何具体 harness 无关的中立数据类型,至少包含:单轮执行结果 `TurnResult`(含文本内容、工具调用证据、文件证据、停止原因、成败标志)与 agent 供给描述 `AgentSpec`(含 `name`/`workspace`/`model`/`skills`)。具体 adapter SHALL 负责把其 harness 原生返回映射为这些中立类型。核心层 MUST NOT 直接消费 harness 原生结果类型(如 `ExecutionResult`)。

#### Scenario: 原生结果映射为中立 TurnResult
- **WHEN** adapter 执行一轮并从 harness 取得原生结果
- **THEN** adapter SHALL 将其映射为 `TurnResult`(保留 `content`/`tool_calls`/`files`/`stop_reason`/`success` 等等价字段),核心层只读取 `TurnResult`

#### Scenario: 工具与文件证据沿用既有中立结构
- **WHEN** adapter 构建 `TurnResult` 的工具调用与文件证据
- **THEN** 其 SHALL 复用既有中立的 `ToolCallEvidence`(`tool`/`input`(原生 JSON)/`output`/`duration_ms`)与 `FileEvidence`(含 `path`),而非暴露 harness 专属字段

### Requirement: Adapter 内部消化传输异常并翻译为中立异常

具体 adapter SHALL 在其内部消化可恢复的传输抖动(如断线重连、心跳、退避、空响应兜底)。仅当故障不可恢复时,adapter SHALL 抛出中立的 `HarnessError`(含传输类子类)供核心层处理。核心层 SHALL 只捕获中立异常,MUST NOT 捕获 harness 专属异常(如 `GatewayError`),也 MUST NOT 直接调用 harness 专属的重连方法(如 `ensure_connected`)。

#### Scenario: 可恢复抖动在 adapter 内自愈
- **WHEN** 底层传输出现可恢复的断连或空响应
- **THEN** adapter SHALL 在内部完成重连/兜底,对核心层不可见;核心层 SHALL NOT 看到任何 harness 专属异常

#### Scenario: 不可恢复故障翻译为中立异常
- **WHEN** 传输故障重试耗尽、确实不可恢复
- **THEN** adapter SHALL 抛出中立 `HarnessError`,核心层 SHALL 据此做有限重试/兜底/放弃,而无需感知底层是何种 harness

### Requirement: 按配置选择 adapter 且后向兼容

系统 SHALL 通过注册表按配置项 `harness.type` 选择并构造对应的 `HarnessAdapter` 实现。`harness.type` SHALL 默认为 `openclaw`。现有顶层连接配置(`gateway_ws_url` / `api_key` / `gateway_timeout` / `workspace_base`)SHALL 在未提供 `harness` 段时继续被读取并折叠进 OpenClaw adapter 的连接配置,使所有现存 config 文件无需修改即可运行。未知 `harness.type` SHALL 显式报错。具体 adapter 类 SHALL 惰性导入,`import` 注册表本身 MUST NOT 拉起任何 harness SDK。

#### Scenario: 旧 config 无 harness 段仍可运行
- **WHEN** 加载一份不含 `harness` 段、仅有顶层 `gateway_ws_url` 等字段的旧 config
- **THEN** 系统 SHALL 默认选用 OpenClaw adapter,并把旧字段映射为其连接配置,运行行为与解耦前一致

#### Scenario: 未知 harness 类型显式报错
- **WHEN** config 指定了一个未注册的 `harness.type`
- **THEN** 系统 SHALL 给出明确错误指出该类型不可用,而 MUST NOT 静默回退到错误的 adapter

### Requirement: OpenClaw 适配实现且行为不变

系统 SHALL 提供 `OpenClawAdapter` 作为 `HarnessAdapter` 的实现,把现有全部 OpenClaw 调用(客户端构造、`ResilientGateway` 韧性、agent 供给、`_pin_model` 钉模型、单轮执行、`chat_history` 采集与兜底、文件证据读写、`sessions_reset` 会话重置、`StructuredOutput`、HTTP 健康检查)收拢于其内部,且对应逻辑保持不变。解耦前后,同一份 OpenClaw config SHALL 跑出一致的轨迹与评估日志,且既有测试 SHALL 全部通过。

#### Scenario: 解耦为行为保持的重构
- **WHEN** 用同一份 OpenClaw config 在解耦前后各运行一次
- **THEN** 产出的 `trajectory` 与 `evaluator_use.log` 关键内容 SHALL 一致,既有测试 SHALL 全绿(证明只搬迁、未改行为)

#### Scenario: 模型钉死与会话重置收拢进 adapter
- **WHEN** 核心层需要为某 agent 钉死裁判模型,或在每轮评估前重置评估会话
- **THEN** 这些 SHALL 经 `adapter.ensure_agent`(按 `AgentSpec.model`)与 adapter 的会话重置能力完成,核心层 MUST NOT 直接调用 `gateway.agents_update` / `gateway.sessions_reset`

### Requirement: Hermes 作为经 ACP 驱动的第二适配实现

系统 SHALL 提供 `HermesAdapter` 作为 `HarnessAdapter` 的第二个实现,通过 **ACP(Agent Client Protocol)** 以 stdio JSON-RPC 驱动一个 `hermes-acp` 子进程;框架进程自身担任 **ACP 客户端**。该 adapter SHALL 在生命周期进入时拉起子进程并完成协议握手(`use_unstable_protocol=True`),在退出时终止子进程;全部 ACP/子进程细节 SHALL 封装在 adapter 内部,对核心层不可见。

#### Scenario: 选用 hermes 时构造 HermesAdapter
- **WHEN** config 指定 `harness.type = "hermes"`
- **THEN** 注册表 SHALL 惰性构造 `HermesAdapter`,且在选用前 MUST NOT 导入 ACP SDK 或拉起任何子进程

#### Scenario: 生命周期管理子进程而非网络连接
- **WHEN** 进入 `HermesAdapter` 的 async 上下文
- **THEN** 其 SHALL spawn `hermes-acp` 子进程并经 ACP `initialize` 完成握手;退出上下文时 SHALL 终止该子进程;核心层 SHALL NOT 感知任何子进程或 stdio 细节

### Requirement: HermesAdapter 为忠实映射器,会话隔离归核心层

`HermesAdapter` SHALL 仅作"忠实映射器":把核心层传入的每个 `(agent, session)` 元组映射到一个 ACP 会话标识,把每个 agent 的 `workspace` 映射到该 ACP 会话的工作目录(cwd)。adapter MUST NOT 自行决定任何会话/agent 隔离策略;隔离性 SHALL 完全由核心层传入不同的 `(agent, session)` 元组决定。被测 agent 与评估 agent SHALL 走完全相同的 adapter 代码路径,adapter 对二者 MUST NOT 做任何特判。

#### Scenario: 同 agent 的不同 session 各自独立
- **WHEN** 核心层对同一 agent 以两个不同 `session` 名调用 `execute`
- **THEN** adapter SHALL 为每个 `(agent, session)` 维护各自独立的 ACP 会话(各自记忆互不串扰),并对后续相同元组复用同一会话

#### Scenario: 评估侧隔离由核心层决定,adapter 无特判
- **WHEN** 核心层以独立的评估 agent 名与每轮新建的评估 `session` 调用 `execute`
- **THEN** adapter SHALL 像对待任何普通 `(agent, session)` 一样为其建立独立 ACP 会话,MUST NOT 在 adapter 内部内置"评估专用"逻辑

### Requirement: HermesAdapter 能力声明、降级与自动放行

`HermesAdapter` SHALL 仅声明 `FILE_EVIDENCE` 能力(其工作目录为本地目录,文件证据经本地工作区读写取得),而 MUST NOT 声明 `STRUCTURED_OUTPUT` / `HEALTHZ` / `HISTORY_FALLBACK` / `MULTI_AGENT` / 会话重置。对未声明的能力,核心层 SHALL 落入既有降级路径。无人值守运行时,adapter 的 ACP 客户端 SHALL 自动放行被测 agent 的工具权限请求。

#### Scenario: 文件证据经本地工作区取得
- **WHEN** 轨迹层对 Hermes 被测 agent 做文件取证
- **THEN** adapter SHALL 经本地工作目录读写完成 `read_workspace`/`get_file`/`put_file`,无需任何远端调用

#### Scenario: 无人值守时自动放行工具权限
- **WHEN** `hermes-acp` 子进程在执行工具(如写文件)前经 ACP 回调向客户端请求权限
- **THEN** adapter 的 ACP 客户端 SHALL 自动返回"允许",使被测 agent 在无人值守下不被阻塞

### Requirement: 按配置选择 Hermes 且凭证显式托管

选用 Hermes 时 SHALL 仅需在 config 新增 `harness` 段(`type` + `connection`),其余字段保持不变。`connection` SHALL 允许在 config 中显式托管 `model`/`provider`/`api_key`/`base_url` 与子进程启动参数;adapter SHALL 将其翻译为子进程环境变量与按会话设置模型,使一份 config 自包含。

#### Scenario: 最小改动切换到 Hermes
- **WHEN** 在一份既有 config 上仅新增 `harness.type = "hermes"` 及其 `connection`
- **THEN** 系统 SHALL 据此选用 `HermesAdapter`,而 `queries`/`workspace_base`/`simulator_config` 等字段 SHALL 无需改动即可运行

#### Scenario: config 显式托管的凭证注入子进程
- **WHEN** `connection` 提供了 `model`/`provider`/`api_key`/`base_url`
- **THEN** adapter SHALL 将凭证注入 `hermes-acp` 子进程运行环境,并按会话设置请求的模型,而 MUST NOT 要求用户预先配置外部 `.env`
