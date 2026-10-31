## Why

被测模型在不同 system prompt 下表现差异明显,鲁棒性不足;需要在批跑框架里对 assistant 注入多样化的系统提示词,产出覆盖多样提示词的 RL 训练样本。同时排查发现:现有 `agents[].system_prompt` 字段对 assistant **在 OpenClaw 上完全不生效**(只下发 model,prompt 被丢弃;网关也拒绝任何动态下发通道),各 harness 的解析/下发路径还各写各的、不统一。本变更既补齐多样性能力,又把 assistant 系统提示词的"解析 + 下发"收拢成一条统一、可扩展的链路。

## What Changes

- 新增配置字段 `agents[].auto_gen_system_prompt`(布尔,默认 `false`),放在现有 `agents` 项下,与 `system_prompt` / `model` 并列。未配置时行为与现状一致,既有 config 零影响。
- 新增**统一的 assistant 系统提示词解析器**(harness 无关),按两步产出一个 prompt 字符串:
  - **step 1 选 base**:`system_prompt` 非空 → 用它;为空 → 用内置 `DEFAULT_SYSTEM_PROMPT`。
  - **step 2 是否变异**:`auto_gen_system_prompt=true` → 以 base 为 meta-prompt,调 LLM **热采样改写**出一个新变体(每会话一份,**不追求可复现**);否则原样返回 base。
- 新增**每 harness 的下发接口** `deliver_system_prompt(agent, prompt_str)`:
  - **OpenClaw**:把 prompt 写入 agent workspace 的 `SOUL.md`(唯一可用官方通道,不碰网关 API)。**修复**当前 assistant `system_prompt` 不生效的问题。
  - **ClaudeCode / Hermes**:接入各自已有的 SDK/register 通道,统一从解析器取 prompt(替换当前分散写法)。
- 变异用的 LLM **复用 simulator 的模型配置**(`simulator_config` / `user_proxy_model.json`),不新增模型配置块。
- **溯源落盘**:把实际下发给 assistant 的 prompt 及其来源(`auto_gen` / `config` / `default`)写入该任务的 trajectory JSON,作为 RL 样本标签。
- **移除**上一轮未落地、未跟踪的探索产物:归档变更 `openspec/changes/archive/2026-07-13-random-system-prompts/` 与三个未跟踪 spec(`prompt-pool` / `prompt-sampling` / `assistant-prompt-delivery`)。本提案以 auto-gen 方案取代其"人工池 + 三角色采样"设计;其中 assistant 下发走 SOUL.md 的探针结论并入本变更 design。
- **不涉及** evaluator 与 user_simulator 的提示词多样性(evaluator 易致 reward 漂移;simulator 多样性已由任务配置保证)。

## Capabilities

### New Capabilities
- `assistant-system-prompt`: assistant 系统提示词的统一解析(base 选取 + auto-gen 变异开关)与按 harness 下发的机制,含 `auto_gen_system_prompt` 配置契约、LLM 变异来源、各 harness 下发通道(OpenClaw=SOUL.md)、以及实际 prompt + 来源的 trajectory 溯源。

### Modified Capabilities
<!-- 现有已跟踪 specs(trajectory-evaluation / user-simulation)的 REQUIREMENTS 不变;被移除的 3 个 spec 为未跟踪的探索产物,不作为既有 capability 的 delta 处理,在 Impact/tasks 中物理删除。 -->

## Impact

- 代码:
  - `src/config.py`:`AgentConfigItem` 增加 `auto_gen_system_prompt: bool = False`。
  - 新增解析器模块(harness 无关):两步解析 + 内置 `DEFAULT_SYSTEM_PROMPT` + auto-gen 变异(调用 simulator 模型)。
  - `src/openclaw_client.py`(`setup_agent`):新增 `deliver_system_prompt` → 写 workspace `SOUL.md`;修复 assistant prompt 不生效。
  - `src/claudecode_client.py` / `src/hermes_client.py`:各自的下发接入统一解析器。
  - `src/executor.py` / `src/evaluator/trajectory.py`:trajectory 增加实际 prompt + 来源字段并落盘。
  - `harness_automation.py`:装配处调用解析器,并把变异所需的 simulator 模型配置传入。
- 依赖:无新增第三方依赖(变异调用复用现有 LLM client)。
- 兼容:`auto_gen_system_prompt` 默认 `false`;未配置时解析器退回 base(`system_prompt` 或默认),既有 config 与行为不受影响。OpenClaw 上 assistant 首次真正拿到 system_prompt(此前为死字段,非 BREAKING)。
- 移除文件:`openspec/changes/archive/2026-07-13-random-system-prompts/`、`openspec/specs/prompt-pool/`、`openspec/specs/prompt-sampling/`、`openspec/specs/assistant-prompt-delivery/`(均为未跟踪探索产物)。
