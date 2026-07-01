## Context

轨迹校验(0701)暴露:task config 给 assistant 配的模型全部落到网关默认 `gemini-3-flash-preview`。经 `~/.openclaw/openclaw.json` 坐实,网关 `models.providers.anthropic.models` 是一道白名单(仅 `deepseek-v3`、`gemini-3-flash-preview`),`agents.defaults.model.primary = anthropic/gemini-3-flash-preview` 为兜底。`agents_update` 会把任意模型串写进 `agents.list` 并回 `{ok:True}`,但白名单外的 id(如 `deepseek-v4-pro`)在路由时被静默回退到默认——`{ok:True}` 只证明"写入成功",不证明"可路由"。

现状约束(经代码/SDK 核实):
- `_pin_model`(`openclaw_automation.py:498`)仅在 `model_provider` 存在时拼 `provider/model`,且把 `{ok:True}` 当成功。
- task config(如 `08_..._q1.json`)只写裸 `model`(无 `model_provider`),且 `evaluate` 块用历史键名 `evaluator_agent`/`evaluate_every_n_turns`/`feedback_to_user`。
- 代码侧 `EvaluateConfig`(`evaluator.py:157`)已用 `AliasChoices` 以**新名为规范**、旧名为别名——与 `trajectory-evaluation` 旧 spec(以旧名为规范)相反。
- SDK 具备只读 `gateway.models_list()`(`gateway/base.py:574`,网关 `models.list`,配置层 RPC,毫秒级);`config_mgr().get_agent_model()` 只回读"存了啥",抓不到静默回退。
- yibuapi `/v1/models` 探测确认可用 id:`glm-5.2`、`gemini-3.5-flash`、`deepseek-v4-pro` 均真实存在——bug 在网关白名单,不在 yibuapi。
- `user_dir.path` 按 cwd 解析;`*_ref` 按 `q1.json` 目录解析——两类基准不同,收纳目录时须区别对待。
- `system_prompt.md:3` 已含"当前是2026年7月"——item 4 已就位,仅需不回归。

## Goals / Non-Goals

**Goals:**
- 让"配什么模型跑什么模型"成立:pin 前白名单校验,不可路由即失败终止而非静默回退。
- 评测切换到更强模型:assistant→`glm-5.2`,simulator/evaluator→`gemini-3.5-flash`。
- 告知 evaluator 工具结果为截断预览及其上限。
- 把两个任务目录收纳进 `configs/task_configs_0701/`,同步修相对路径与迁移脚本硬编码。
- task config 数据键名收敛到新名(代码已兼容别名)。

**Non-Goals:**
- 不改 SDK(仅新增只读 `models_list()` 调用)。
- 不做事后真实探针请求校验(贵且非必要;白名单成员检查已覆盖本 bug)。
- 不在仓库内改写网关 `openclaw.json`——网关侧登记模型为部署前置,由使用者在网关侧完成。
- 不改 `system_prompt.md` 日期文案(已就位)。

## Decisions

**决策 1:白名单成员校验,而非回读生效模型。**
pin 前用缓存的 `models_list()` id 集合断言目标模型可路由;不在则 `raise` 终止。
- 为何不用 `get_agent_model` 回读:它读 config 里"存了啥",对静默回退返回的仍是我们写入的值(如 `deepseek-v4-pro`),看着正确却抓不到 bug——与 `{ok:True}` 同源无效。
- 为何不用真实探针请求:要花一次推理、可能抖动;而本 bug 的本质就是"id 不在白名单",成员检查已充分且近零成本。

**决策 2:白名单 setup 期一次性拉取并缓存。**
`models.list` 是配置层 RPC(毫秒级),但仍只在 setup 调一次、缓存供所有 agent 校验复用,严禁进入 per-turn/per-query 热路径。相对每轮数秒的评测 LLM 调用,开销可忽略。

**决策 3:task config 显式声明 `model` + `model_provider`。**
pin 据此拼完整 `anthropic/<id>` 下发(provider 字面就叫 `anthropic`,尽管指向 yibuapi,须与 `defaults` 引用风格对齐)。simulator 直连 yibuapi、不过网关闸门,故 `user_proxy_model.json` 只需改 `model` 字段。

**决策 4:截断告知放在 evaluator 提示词骨架。**
文案落在 `evaluator_user_prompt.md` 的 `skeleton` 段(靠近 `# 最近 {window} 轮执行证据`),声明工具结果/文件为截断预览并注明上限(全量 2000/500、压缩 800/300),引导裁判走产物指针核验全量,不把截断当缺失。上限值取自 `trajectory.py` 现有常量,避免文案与代码漂移。

**决策 5:收纳目录时区分两类路径基准。**
`*_ref`(相对 `q1.json` 目录)在整体平移收纳后原样存活,不改;仅 `user_dir.path`(相对 cwd)需按新前缀 `configs/task_configs_0701/...` 更新。迁移脚本 `migrate_dailyclawbench_to_standard.py` 的硬编码目录名同步更新。

**决策 6:数据键名收敛到新名,不改代码别名。**
代码 `AliasChoices` 已以新名为规范、兼容旧名读取;本次仅把 task config JSON 的 `evaluator_agent`/`evaluate_every_n_turns`/`feedback_to_user` 改为 `agent_name`/`eval_step`/`feedback_to_simulator`,并把 `trajectory-evaluation` spec 的规范/别名方向翻转以与代码一致。

## Risks / Trade-offs

- **网关未登记新模型 → 校验按设计报错终止** → 这是刻意行为(fail loud 优于静默错模型);须在 proposal/tasks 中明确"网关侧登记 `glm-5.2`/`gemini-3.5-flash` 为部署前置",并在报错信息里指明"请在 `openclaw.json` 的 `providers.<p>.models` 与 `agents.defaults.models` 登记该模型"。
- **`models_list()` 与实际路由白名单口径可能不完全一致** → 若网关 `models.list` 返回集合与路由裁定集合有偏差,校验可能漏判/误判;缓解:以 `models.list` 为准并在报错中打印其返回的可用 id 列表,便于人工比对。
- **收纳时 `user_dir.path` 前缀漏改 → FileNotFoundError** → 约 40 个文件,人工易漏;缓解:改完后跑一次全量加载校验(或 dry-run 解析所有 `user_dir.path` 存在性)。
- **simulator 模型 id 在 yibuapi 端命名与预期不符** → 已用 `/v1/models` 探测坐实 `gemini-3.5-flash` 存在,风险已消。

## Migration Plan

1. **前置(仓库外,网关侧)**:在 `~/.openclaw/openclaw.json` 的 `providers.anthropic.models` 增 `glm-5.2`、`gemini-3.5-flash`;`agents.defaults.models` 增 `anthropic/glm-5.2`、`anthropic/gemini-3.5-flash`。
2. 代码:`_pin_model` 加白名单校验 + setup 期 `models_list()` 缓存;`evaluator_user_prompt.md` 加截断告知。
3. 数据:`user_proxy_model.json` 改 simulator 模型;收纳目录 + 改 `user_dir.path` 前缀 + task config 加 `model_provider`/改模型/改键名;迁移脚本改硬编码。
4. 验证:全量加载校验(路径/键名),小样跑一条确认 assistant 实际走 `glm-5.2`(pin 通过白名单、无回退告警)。
- **回滚**:代码改动可单独 revert(校验退回旧"仅告警"行为);目录收纳与键名为纯数据变更,git revert 即可。

## Open Questions

- 网关侧登记新模型由谁执行、何时完成?(校验加固上线后,未登记会导致装配终止——需与网关配置节奏对齐。)
