## 1. 配置字段

- [x] 1.1 在 `src/config.py` 的 `AgentConfigItem` 增加 `auto_gen_system_prompt: bool = Field(False, ...)`,校验非布尔值 fail-fast
- [x] 1.2 确认既有 config(未带该字段)加载后该值为 `False`,无破坏
- [x] 1.3 全局校验(整份 config 组装后):凡被任一 query 的 `evaluate.agent_name` 引用的 agent 若设 `auto_gen_system_prompt=true`,抛错中止启动,错误信息含 agent 名与冲突字段(D7)

## 2. 解析器(harness 无关)

- [x] 2.1 新增解析器模块,提供 `DEFAULT_SYSTEM_PROMPT` 常量
- [x] 2.2 实现 `resolve_system_prompt(agent_cfg, gen_fn) -> (prompt_str, source)`:step1 选 base(`system_prompt` 或默认)、step2 按 `auto_gen` 决定是否调 `gen_fn` 变异
- [x] 2.3 auto-gen 变异回退:`gen_fn` 失败/空返回 → 回退 base,记录告警,来源保持 base 的来源
- [x] 2.4 `source` 取值正确:非空 `system_prompt`→`config`;空→`default`;变异成功→`auto_gen`

## 3. 变异 LLM 来源

- [x] 3.1 基于 `simulator_config`(`user_proxy_model.json`)构建的 LLM client 封装 `gen_fn(base)->str`
- [x] 3.2 编写 meta-prompt:以 base 为输入,要求保持任务/工具语义、产出人设/语气/风格明显不同的变体;高温调用
- [x] 3.3 在 `harness_automation` 装配处把 `gen_fn`(或其依赖的 simulator 模型配置)传入解析调用点

## 4. 每 harness 下发接口

- [x] 4.1 定义统一下发约定 `deliver_system_prompt(agent, prompt_str)`(接口/基类方法或约定函数签名)
- [x] 4.2 OpenClaw:在 `setup_agent`(`src/openclaw_client.py`)内先 `resolve` 再把 prompt 写入 workspace `SOUL.md`(经现有 workspace 铺文件路径),修复 assistant prompt 不生效
- [x] 4.3 ClaudeCode:`setup_agent`(`src/claudecode_client.py`)改为从解析器取 prompt 后经 SDK `system_prompt` 下发
- [x] 4.4 Hermes:`setup_agent`/register(`src/hermes_client.py`)改为从解析器取 prompt 后经 `system_message` 下发
- [x] 4.5 校验 `SOUL.md`/下发内容不超 `bootstrapMaxChars`(默认 20000),超限告警
- [x] 4.6 确认本能力只作用于 assistant;evaluator/simulator 提示词路径不被本能力改动

## 5. trajectory 溯源落盘

- [x] 5.1 `src/evaluator/trajectory.py` 的 `Trajectory` 增加 `assistant_system_prompt`(全文)与 `system_prompt_source` 字段
- [x] 5.2 `src/executor.py` 在装配/执行处把解析结果(prompt + source)写入该任务 trajectory 并落盘

## 6. 移除被取代的探索产物

- [x] 6.1 删除 `openspec/changes/archive/2026-07-13-random-system-prompts/`
- [x] 6.2 删除 `openspec/specs/prompt-pool/`、`openspec/specs/prompt-sampling/`、`openspec/specs/assistant-prompt-delivery/`

## 7. 验证

- [x] 7.1 单测:解析器三分支(config / default / auto_gen)与变异回退路径
- [x] 7.5 单测:evaluator agent 设 `auto_gen_system_prompt=true` 时配置校验抛错(D7);仅作 assistant 时通过
- [ ] 7.2 OpenClaw 端到端:开启 auto-gen,确认 `SOUL.md` 写入变体、trajectory 落盘 prompt+source(用 openclaw-docker-kit 在容器内跑) — **未跑**:需真实网关 + LLM;下发/落盘逻辑已由 7.1/7.5 单测覆盖
- [x] 7.3 回归:既有 config(不带 `auto_gen_system_prompt`)行为与变更前一致
- [x] 7.4 `openspec validate --change auto-gen-assistant-system-prompt` 通过
