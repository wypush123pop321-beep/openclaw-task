## Context

批跑框架支持三种 harness(OpenClaw / ClaudeCode / Hermes),assistant 的系统提示词现状是**解析分散、下发不一致**:

| 环节 | 现状 |
|------|------|
| 配置来源 | `agents[].system_prompt`(`config.py:73`) |
| 汇聚 | `harness_automation` 各 `_run_*` 里建 `agent_system_prompts = {name: system_prompt}` 传入 `execute_queries` |
| 实际消费 | `executor.py:239` **只有 evaluator** 读该 dict;assistant 从不在此链路 |
| OpenClaw 下发 | `openclaw_client.py:542` `setup_agent` 只 `agents_update(model=…)`,`system_prompt` 被丢弃;网关拒绝一切动态下发字段(`agents.update`/`sessions.patch` 的 `systemPrompt`)。唯一官方通道是 workspace 引导文件(`SOUL.md` 注入 Project Context 段) |
| ClaudeCode 下发 | `claudecode_client.py:572` 把 `system_prompt` 传给 SDK,生效 |
| Hermes 下发 | 经 `get_agent`/register 的 `system_message`,生效 |

结论:**OpenClaw(当前唯一在跑的 harness)上 assistant 的 `system_prompt` 是死字段**;`config_simple_eval.json` 里 `main` 的 `config: []` 又不带 SOUL.md,assistant 实跑网关默认。

上一轮探索(归档变更 `2026-07-13-random-system-prompts` + 三个未跟踪 spec)提出"人工池 + 三角色随机采样 + seed 可复现",但**从未落地**(无 `prompt_pools/`、无采样/seed 代码)。本变更以"LLM 以 base 为 meta-prompt 热改写、仅 assistant、布尔开关"的方案取代之,并保留其唯一有价值的实测结论:assistant 下发走 workspace `SOUL.md`。

运行模型锁定 **1 任务 = 1 容器 = 1 网关 = 1 agent = 1 组 system prompt**,不存在 per-session 热切换/并发串扰。

## Goals / Non-Goals

**Goals:**
- 修复 OpenClaw 上 assistant `system_prompt` 不生效的问题。
- 把 assistant 系统提示词的"解析"收拢为一份 harness 无关逻辑,"下发"抽象为每 harness 一个接口,便于扩展到未来 harness。
- 提供 `auto_gen_system_prompt` 开关:开启时以配置的 base 为 meta-prompt,LLM 热改写出多样变体,产出覆盖多样提示词的 RL 样本。
- 实际下发 prompt + 来源落盘 trajectory,作为样本标签。
- 未配置时行为与现状完全一致(向后兼容)。

**Non-Goals:**
- 不对 evaluator / user_simulator 做提示词多样性。
- 不追求 auto-gen 变体的可复现(不落 seed)。
- 不做 per-session / per-turn 的提示词热切换。
- 不引入人工提示词池(取代旧方案,不共存)。
- 不改动 OpenClaw 网关侧配置或引入新网关 API 通道。

## Decisions

### D1. `auto_gen_system_prompt` 落在 `AgentConfigItem`,布尔默认 false
- 位置:`src/config.py` 的 `AgentConfigItem`,与 `system_prompt`/`model` 并列。默认 `False`。
- 理由:字段就近于既有语义;pydantic 默认值保证既有 config 零改动、零影响。
- 备选:放在顶层或单独 `prompt` 配置块——放弃,因该开关本就是 per-agent 语义,且用户明确要求放 `agents` 下。

### D2. 解析器 = 两步纯函数,harness 无关,只产字符串
```
resolve_system_prompt(agent_cfg, gen_fn) -> (prompt_str, source)
  base   = agent_cfg.system_prompt or DEFAULT_SYSTEM_PROMPT
  source = "config" if agent_cfg.system_prompt else "default"
  if agent_cfg.auto_gen_system_prompt:
      variant = gen_fn(base)            # LLM 改写;失败回退 base
      return (variant, "auto_gen") if variant else (base, source)
  return (base, source)
```
- 理由:`auto_gen` 塌成"在 base 之上要不要变异"的正交装饰,而非第三个生成源;7.1/7.2/7.3 自然收敛为两步。base 恒定 → 变体天然贴着真实任务/工具语义,不会跑偏。
- 解析只产字符串、不下发 → 与 harness 解耦,是扩展性的关键切面。
- `gen_fn` 注入(依赖倒置):解析器不认识具体 LLM client,只收一个 `base->str` 回调,便于测试与替换。

### D3. auto-gen 变异:复用 simulator 模型,热采样,不可复现
- 用哪个模型:复用 `simulator_config`(`user_proxy_model.json`)构建的 LLM client。理由:已接好、本就是工具模型、配置不用动;需要独立控温时再加 `prompt_gen` 块。
- 采样:高温单次调用,meta-prompt 要求"在保持任务/工具语义前提下,产出人设/语气/风格明显不同的变体"。不落 seed、不保证可复现(用户已确认)。
- 已知局限:仅靠温度取得多样性,存在跨会话变体趋同的风险(见 Risks R1)。meta-prompt 里的"明显不同"指令是低成本对冲,不加额外机制。

### D4. 下发接口:每 harness 实现 `deliver_system_prompt(agent, prompt_str)`
- OpenClaw:把 `prompt_str` 写入 agent workspace 的 `SOUL.md`(现有 `setup_agent_files`/workspace 铺文件路径),经网关 Project Context 段注入。不碰任何被拒的网关字段。
- ClaudeCode:走现有 SDK `system_prompt` 通道,值改由解析器产出。
- Hermes:走现有 register 的 `system_message`,值改由解析器产出。
- 装配顺序:在各 `AgentManager.setup_agent` 内,先 `resolve_system_prompt` 再 `deliver_system_prompt`。
- 理由:三 harness 已各有下发入口,把"下发"提为同名方法即完成收拢;新增 harness 照抄该方法。
- 轻收拢(无基类,贴合现状:AgentManager 本就无基类、只有鸭子契约):三家 `AgentManager` 各实现同名 `deliver_system_prompt(agent_name, prompt, source)`,由统一签名的 `setup_agent(agent_config, resolved_prompt=None)` 调用。副作用形态因 agent 生命周期而异:
  - **OpenClaw**:立即写 workspace `SOUL.md`(建 agent 时就要文件在位)。
  - **ClaudeCode**:收进 `manager.system_prompts`,`setup_agent` 里 `register_agent_defaults` 时取用。
  - **Hermes**:agent 在 `get_agent` 时惰性构造,故 `deliver` 收进 `manager.system_prompts`,`make_hermes_get_agent` 工厂取用注入(现状 hermes 从未传该字段,一并修复)。
- 不引入 `BaseAgentManager` ABC:仅 3 个实现且 Hermes 形态特殊,同名方法+统一签名已达可读性目标,加基类属过度设计(YAGNI)。
- 边界:仅覆盖 `SOUL.md`;`USER.md`/`AGENTS.md` 不动(USER.md 与 simulator 的 `{user_profile}` 语义重叠,同时随机化会产生矛盾信号)。
- **OpenClaw 默认分支的防覆盖规则(向后兼容关键)**:`_setup_workspaces` 会在 `setup_agent` 之前把 `config:[...]` 里的文件(含文件版 `SOUL.md`)拷进 workspace。因此下发规则:
  - `auto_gen` 或非空 `system_prompt`(显式意图)→ **总是**写 `SOUL.md`(覆盖拷来的),显式 prompt 胜过文件版并告警。
  - 空 `system_prompt`(默认分支,7.3)→ **仅当 workspace 尚无 `SOUL.md` 时**才写 `DEFAULT_SYSTEM_PROMPT`;已有文件版则保留(等同现状),避免 clobber 既有文件版人设。这样 7.3 的"默认兜底"只在 agent 本无人设时补齐,不回归既有 config。

### D5. 溯源落盘
- `execute_queries` / `Trajectory`(`src/evaluator/trajectory.py`)增加 `assistant_system_prompt`(全文)与 `system_prompt_source`(`auto_gen`/`config`/`default`)两字段,随该任务 trajectory JSON 落盘。
- 理由:RL 样本需知道"这条轨迹的 assistant 到底挂了什么系统提示词"。这是从旧方案唯一保留的能力(去掉 seed)。

### D6. 移除被取代的探索产物
- 物理删除 `openspec/changes/archive/2026-07-13-random-system-prompts/` 与 `openspec/specs/{prompt-pool,prompt-sampling,assistant-prompt-delivery}/`。
- 理由:三者均为未跟踪、未落地的探索产物,与本方案冲突;其 SOUL.md 下发结论已并入 D4。已跟踪的 `trajectory-evaluation`/`user-simulation` spec 不动。

### D7. evaluator 开启 auto-gen 在校验期硬报错(fail-fast)
- "evaluator agent" 的判定:凡被任一 query 的 `evaluate.agent_name` 引用的 agent。此判定需跨 `agents` 与 `queries` 交叉引用,故不能只在 `AgentConfigItem` 单项校验,而是在整份 config 组装后做一次全局校验。
- 行为:命中即抛错中止启动,错误信息带 agent 名与冲突字段,不进入任务执行。
- 理由:evaluator 是 reward 来源,变异会让训练目标漂移;比"运行期静默不生效"更早、更明确地拦住误配(用户要求错误拦在前端/校验期)。
- 备选:仅 spec 约定 + 运行期忽略——放弃,误配会静默通过、难排查。

## Risks / Trade-offs

- **R1 变体趋同**:仅靠温度,LLM 可能每会话产出相似 prompt → meta-prompt 显式要求"明显不同的人设/语气/风格" + 高温;不可复现是已接受的取舍。若后续覆盖度不足,再引入轴轮换/few-shot 反例。
- **R2 auto-gen 调用失败**:LLM 超时/报错/空返回 → D2 回退 base 并告警,任务不崩。
- **R3 变体破坏任务语义**(改写把工具/约束改跑偏)→ base 恒为真实 persona 作锚 + meta-prompt 限定"保持任务/工具语义";严重时该腿可单独关闭(设 `auto_gen_system_prompt=false`)。
- **R4 SOUL.md 超 `bootstrapMaxChars`(默认 20000)被截断** → 变体/默认 prompt 控制在限内;超限告警。
- **R5 evaluator 被误开 auto-gen 污染 reward** → 配置校验期硬报错(fail-fast):凡被 query `evaluate.agent_name` 引用的 agent 若设 `auto_gen_system_prompt=true`,启动即中止(见 D7)。
- **R6 跨 harness 行为一致性** → 解析逻辑单一实现,三 harness 共用同一字符串;仅下发通道不同,降低分叉风险。

## Migration Plan

1. 加 `auto_gen_system_prompt` 字段(默认 false)+ 解析器 + `DEFAULT_SYSTEM_PROMPT`。
2. 三 harness `setup_agent` 接入 `resolve → deliver`;OpenClaw 落 `SOUL.md`。
3. trajectory 增加两字段并落盘。
4. 删除被取代的探索产物(D6)。
5. 灰度:既有 config 不带该字段 → 解析退回 base,行为不变,可无风险合入。
6. 回滚:字段置 false(或删除)即恢复静态/默认 prompt 行为;移除下发接入即回退到变更前。

## Open Questions

- ~~是否需要在校验期禁止对 evaluator agent 设 `auto_gen_system_prompt=true`?~~ **已定:需要,校验期硬报错(见 D7)。**
- ~~变异是否需要可配置温度/独立 `prompt_gen` 模型块?~~ **已定:一期不做,复用 simulator 模型固定策略;后续视覆盖度再议。**
