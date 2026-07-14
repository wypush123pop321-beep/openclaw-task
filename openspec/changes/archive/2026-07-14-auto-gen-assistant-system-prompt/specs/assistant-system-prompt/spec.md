## ADDED Requirements

### Requirement: 配置字段 auto_gen_system_prompt

系统 SHALL 在每个 agent 配置项(`agents[]`)下支持一个布尔字段 `auto_gen_system_prompt`,与 `system_prompt` / `model` 并列。该字段 SHALL 默认为 `false`,未配置时不改变任何现有行为。

#### Scenario: 既有 config 未配置该字段

- **WHEN** 一个 agent 配置项没有 `auto_gen_system_prompt` 字段
- **THEN** 系统按 `false` 处理,assistant 系统提示词等同于本变更前的 base 解析结果,既有 config 零影响

#### Scenario: 该字段仅接受布尔值

- **WHEN** 配置加载时读取 `auto_gen_system_prompt`
- **THEN** 只接受 `true` / `false`;非布尔值在配置校验阶段报错(fail-fast)

### Requirement: assistant 系统提示词的两步统一解析

系统 SHALL 提供一个 harness 无关的解析器,在每次注册 assistant agent 时产出一个系统提示词字符串,分两步:
- **step 1(选 base)**:若该 agent 的 `system_prompt` 非空,base = `system_prompt`;否则 base = 内置 `DEFAULT_SYSTEM_PROMPT`。
- **step 2(是否变异)**:若 `auto_gen_system_prompt=true`,以 base 为 meta-prompt 调 LLM 改写产出一个变体作为最终 prompt;否则最终 prompt = base。

解析器 SHALL 只负责产出字符串,不负责下发。

#### Scenario: 关闭 auto-gen 且 system_prompt 非空(7.2)

- **WHEN** `auto_gen_system_prompt=false` 且 `system_prompt` 非空
- **THEN** 最终 prompt SHALL 原样等于配置的 `system_prompt`,不调用 LLM

#### Scenario: 关闭 auto-gen 且 system_prompt 为空(7.3)

- **WHEN** `auto_gen_system_prompt=false` 且 `system_prompt` 为空或缺省
- **THEN** 最终 prompt SHALL 等于内置 `DEFAULT_SYSTEM_PROMPT`,不调用 LLM

#### Scenario: 开启 auto-gen(7.1)

- **WHEN** `auto_gen_system_prompt=true`
- **THEN** 系统 SHALL 以 base(`system_prompt` 非空则为它,否则为 `DEFAULT_SYSTEM_PROMPT`)为 meta-prompt 调 LLM 改写,最终 prompt 为改写后的变体

### Requirement: auto-gen 变异的 LLM 来源与采样策略

auto-gen 变异 SHALL 复用 simulator 的模型配置(`simulator_config` / `user_proxy_model.json`)发起调用,不新增独立模型配置块。变异 SHALL 按会话热采样、每会话产出一份新样本,且**不要求可复现**(不落 seed、不保证同输入同输出)。meta-prompt SHALL 要求模型在保持原 base 的任务/工具语义前提下,产出人设/语气/风格上明显不同的变体。

#### Scenario: 每会话产出新样本

- **WHEN** 同一 config 下开启 auto-gen 的 assistant 在不同会话分别注册
- **THEN** 各会话 SHALL 各自独立调用一次 LLM 产出各自的变体,不复用上一会话结果

#### Scenario: 变异失败时的回退

- **WHEN** auto-gen 调用 LLM 失败(超时/报错/空返回)
- **THEN** 系统 SHALL 回退到 base 作为最终 prompt,并记录告警,不使该任务崩溃

### Requirement: 按 harness 下发系统提示词

系统 SHALL 为每个 harness 提供统一的下发接口 `deliver_system_prompt(agent, prompt_str)`,在注册 agent 时把解析器产出的字符串投递到该 harness 生效的通道。新增 harness 时 SHALL 只需实现该接口。

#### Scenario: OpenClaw 经 SOUL.md 下发

- **WHEN** harness 为 OpenClaw 且解析器产出了 assistant prompt
- **THEN** 系统 SHALL 把该 prompt 写入 agent workspace 的 `SOUL.md`,经网关的 Project Context 段注入;SHALL NOT 依赖任何被网关拒绝的动态下发字段(如 `agents.update` / `sessions.patch` 的 `systemPrompt`)

#### Scenario: OpenClaw 上 assistant 系统提示词真正生效(修复)

- **WHEN** OpenClaw 上一个 assistant 配置了非空 `system_prompt` 或 `DEFAULT_SYSTEM_PROMPT`
- **THEN** assistant 实际运行时 SHALL 收到该系统提示词(经 SOUL.md),而非本变更前的"字段被丢弃、只跑网关默认"

#### Scenario: ClaudeCode / Hermes 经各自通道下发

- **WHEN** harness 为 ClaudeCode 或 Hermes
- **THEN** 系统 SHALL 通过该 harness 已有的 system_prompt / system_message 通道下发解析器产出的同一字符串,不再各自读取 `agents[].system_prompt` 的分散写法

### Requirement: 实际系统提示词与来源的 trajectory 溯源

系统 SHALL 把实际下发给 assistant 的系统提示词字符串,以及其来源枚举(`auto_gen` / `config` / `default`)写入该任务的 trajectory JSON,作为 RL 样本标签。

#### Scenario: auto-gen 变体落盘

- **WHEN** 开启 auto-gen 并成功产出变体
- **THEN** trajectory JSON SHALL 记录来源 `auto_gen` 与实际下发的变体全文

#### Scenario: 静态/默认 prompt 落盘

- **WHEN** 未开启 auto-gen
- **THEN** trajectory JSON SHALL 记录来源 `config`(用了 `system_prompt`)或 `default`(用了 `DEFAULT_SYSTEM_PROMPT`)及对应全文

### Requirement: 多样性范围限定为 assistant

本能力 SHALL 只作用于被测 assistant agent 的系统提示词。系统 SHALL NOT 借本能力对 evaluator 或 user_simulator 的提示词做多样性/变异处理。凡被任一 query 的 `evaluate.agent_name` 引用的 agent 视为 evaluator agent;系统 SHALL 在配置校验期(fail-fast)拒绝对 evaluator agent 设置 `auto_gen_system_prompt=true`。

#### Scenario: evaluator 开启 auto-gen 在校验期报错

- **WHEN** 某 agent 被某 query 的 `evaluate.agent_name` 引用,且其配置项设了 `auto_gen_system_prompt=true`
- **THEN** 配置校验 SHALL 直接报错并中止启动(fail-fast),错误信息指明该 agent 名与冲突字段;SHALL NOT 进入任务执行,以免污染 reward 信号

#### Scenario: 同名 agent 仅作 assistant 时允许开启

- **WHEN** 某 agent 从不被任何 query 的 `evaluate.agent_name` 引用,且设了 `auto_gen_system_prompt=true`
- **THEN** 校验 SHALL 通过,该 agent 按 assistant 走 auto-gen 变异路径
