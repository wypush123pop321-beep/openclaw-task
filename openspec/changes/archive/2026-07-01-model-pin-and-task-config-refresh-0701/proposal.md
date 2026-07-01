## Why

轨迹校验(0701)暴露一个静默正确性 bug:不论 task config 给 agent 配什么模型,实际都落到网关默认的 `gemini-3-flash-preview`。根因经 `openclaw.json` 坐实——网关 `providers.<p>.models` 是一道白名单闸门,`agents_update` 返回 `{ok:True}` 只代表"字符串已写入",不代表该模型在白名单内;不在白名单的 id(如 `deepseek-v4-pro`)被静默回退到默认模型。这类错误只能在跑完后靠肉眼从轨迹里发现,代价高。借这次修复一并把评测切换到更强模型,并收敛任务配置的目录布局与字段命名。

## What Changes

- **agent 模型钉死加固**:`_pin_model` 在下发前,用 `gateway.models_list()` 断言目标模型 id 在网关可路由白名单内;不在则**大声报错终止**,杜绝静默回退。setup 期一次性拉取白名单并缓存,不进入 per-turn 热路径。
- **切换更强模型**:assistant → `glm-5.2`,user_simulator → `gemini-3.5-flash`,evaluator → `gemini-3.5-flash`(id 已由 yibuapi `/v1/models` 探测坐实)。task config 中被钉死的 agent 须同时声明 `model` 与 `model_provider`,使 pin 下发完整 `provider/model` 串。
- **evaluator 截断告知**:evaluator 提示词显式告知"工具结果为截断预览"(附截断上限:全量渲染 tool 输出 `[:2000]`/入参 `[:500]`,压缩渲染 `[:800]`/`[:300]`),使裁判不把截断当证据缺失。
- **目录收纳**:`0701_任务管线产物标准模板` 与 `dailyclawbench_2026-06-30_tasks` 一并收入 `configs/task_configs_0701/`,同步修正受影响的相对路径(重点:`user_dir.path` 按 cwd 解析,须重新加前缀;`*_ref` 按 config 目录解析,原样存活)与迁移脚本中的硬编码目录名。
- **配置字段规范化**:task config JSON 内的历史键名统一到新名 `feedback_to_user`→`feedback_to_simulator`、`evaluate_every_n_turns`→`eval_step`、`evaluator_agent`→`agent_name`;代码侧已有 `AliasChoices` 兼容,本次仅收敛数据文件到规范名。
- **已就位项(仅验证)**:告知 user_simulator "当前是 2026 年 7 月" 已存在于 `system_prompt.md`,本次仅确认不回归。

## Capabilities

### New Capabilities
- `agent-model-pinning`: per-agent 模型钉死的下发契约——provider 前缀拼装、pin 前白名单成员校验(不在网关可路由模型内即失败终止而非静默回退)、以及模型不可路由时的可观测失败语义。

### Modified Capabilities
- `task-config-schema`: 新增 `configs/task_configs_0701/` 收纳布局与对应相对路径基准约定;task config 字段命名收敛到规范名(历史名保留读取别名)。
- `trajectory-evaluation`: evaluator 每轮提示词须显式披露"喂入的工具结果为截断预览及其上限",使证据截断不被误判为证据缺失。

## Impact

- **代码**:`openclaw_automation.py`(`_pin_model` 白名单校验;可能新增 setup 期 `models_list()` 缓存)、`evaluator.py` 或 `evaluator_user_prompt.md`(截断告知文案)。
- **配置/数据**:`configs/user_proxy_model.json`(simulator 模型)、`configs/task_configs_0701/**`(约 40 个 task config 的 `model`/`model_provider`、字段名、`user_dir.path` 前缀)、`scripts/migrate_dailyclawbench_to_standard.py`(硬编码目录名)。
- **网关(仓库外,前置依赖)**:`~/.openclaw/openclaw.json` 的 `providers.anthropic.models` 与 `agents.defaults.models` 须先登记 `glm-5.2`、`gemini-3.5-flash`(如仍用 deepseek 则一并登记),否则加固后的校验会按设计报错终止。
- **SDK**:仅新增只读调用 `gateway.models_list()`(配置层 RPC,毫秒级),不改 SDK。
