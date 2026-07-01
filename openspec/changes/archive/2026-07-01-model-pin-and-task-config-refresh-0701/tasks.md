## 1. 前置:网关侧登记新模型(仓库外)

- [x] 1.1 在 `~/.openclaw/openclaw.json` 的 `models.providers.anthropic.models` 增加 `glm-5.2` 与 `gemini-3.5-flash` 条目
- [x] 1.2 在 `agents.defaults.models` 允许表增加 `anthropic/glm-5.2` 与 `anthropic/gemini-3.5-flash`
- [x] 1.3 重启/重载网关后,用 `gateway.models_list()` 确认两个新模型出现在可路由白名单内（需网关重启，与 7.3/7.4 一并由用户运行）

## 2. 模型钉死加固(openclaw_automation.py)

- [x] 2.1 setup 期一次性调用 `gateway.models_list()`,解析出可路由模型 id 集合并缓存到实例
- [x] 2.2 `_pin_model` 下发前断言目标模型 id(取 `provider/model` 的 model 段)在缓存白名单内;不在则 `raise` 显式错误终止装配,错误信息含目标 id 与 `models_list()` 返回的可用 id 列表,并提示在网关 `providers.<p>.models`/`agents.defaults.models` 登记
- [x] 2.3 校验通过后再执行既有 `agents.update` 下发;保留裸名+`model_provider` 拼 `provider/model` 逻辑,`{ok:True}` 不再单独视为成功依据
- [x] 2.4 确认白名单获取与校验仅在 setup 期发生,不进入 per-turn/per-query 路径

## 3. evaluator 截断告知(evaluator_user_prompt.md)

- [x] 3.1 在 `skeleton` 段 `# 最近 {window} 轮执行证据` 附近增加截断披露文案:工具结果/文件为截断预览,注明上限(全量 2000/500、压缩 800/300),需全量时走产物指针核验
- [x] 3.2 声明"截断 ≠ 证据缺失/造假",与现有反造假条款衔接不冲突
- [x] 3.3 核对文案上限值与 `trajectory.py` 实际截断常量一致(2000/500/800/300)

## 4. 切换更强模型(配置数据)

- [x] 4.1 `configs/user_proxy_model.json` 的 `model` 改为 `gemini-3.5-flash`
- [x] 4.2 task config 中执行 agent 的 `model` 改为 `glm-5.2` 并补 `model_provider: anthropic`
- [x] 4.3 task config 中 evaluator agent 的 `model` 改为 `gemini-3.5-flash` 并补 `model_provider: anthropic`

## 5. 目录收纳与路径修正

- [x] 5.1 将 `0701_任务管线产物标准模板` 与 `dailyclawbench_2026-06-30_tasks` 移入 `configs/task_configs_0701/`
- [x] 5.2 更新受影响 task config 的 `input_dir.user_dir.path` 前缀为收纳后路径(cwd 基准)
- [x] 5.3 确认 `oracle_ref`/`rubrics_ref`/`scoring_ref` 等 `*_ref`(q1.json 目录基准)整体平移后原样有效,无需改写
- [x] 5.4 更新 `scripts/migrate_dailyclawbench_to_standard.py` 中硬编码的任务目录名为收纳后路径

## 6. 键名收敛到规范新名(task config 数据)

- [x] 6.1 task config `evaluate` 块 `evaluator_agent` → `agent_name`
- [x] 6.2 task config `evaluate` 块 `evaluate_every_n_turns` → `eval_step`
- [x] 6.3 task config `evaluate` 块 `feedback_to_user` → `feedback_to_simulator`

## 7. 验证

- [x] 7.1 确认 `system_prompt.md` 仍含"当前是2026年7月"(item 4 不回归)
- [x] 7.2 全量加载校验:所有收纳后 task config 能被 ConfigLoader 正常解析,`user_dir.path` 与 `*_ref` 均可定位(无 FileNotFoundError)
- [x] 7.3 (需活网关) 小样跑一条 query:确认 assistant 实际走 `glm-5.2`(pin 通过白名单校验、日志无回退告警),evaluator 走 `gemini-3.5-flash`
- [x] 7.4 (需活网关；离线逻辑已过) 负例验证:配一个白名单外的模型,确认装配按设计大声报错终止而非静默回退
