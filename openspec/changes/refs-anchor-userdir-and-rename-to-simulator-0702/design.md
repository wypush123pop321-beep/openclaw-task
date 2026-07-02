## Context

`_resolve_evaluate_refs(config, path.parent)`(`openclaw_automation.py:1381`)当前以 q1.json 所在目录(`path.parent` = `task_configs/`)为基准解析三条 ref,故配置里写成 `../environments/<任务名>/oracle.json`。但 `oracle.json`/`user_queries.json` 物理上就在 `user_dir.path`(= `environments/<任务名>/`)里。`user_dir.path` 相对运行时 cwd/项目根解析(`_setup_workspaces:1177` `Path(user_dir_config.path).expanduser()`)。

`coerce_user_dir` 校验器(`:125`)对 `user_dir` 有两种处理:整个键缺失/`null` → `input_dir.user_dir = None`;`{path: null}` → 重定向到"虚空地址"(`%TEMP%/openclaw_void_dir`,一个真实空目录,**非 None**)。

`feedback_to_simulator`(`evaluator.py:183`)已带 `AliasChoices("feedback_to_simulator","feedback_to_user")`,是第三次改名(`dry_run` → `feedback_to_simulator` → 本次 `to_simulator`)。

## Decisions

### D1: refs 改锚 `user_dir.path`,删除"两类基准"

`_resolve_evaluate_refs` 的解析基准从 `path.parent` 改为 `Path(config.input_dir.user_dir.path).expanduser()`。三处 `config_dir / xxx` 相应改为 `user_base / xxx`;`rubrics_ref`/`scoring_ref` 的 `file_part#ptr` 拆分逻辑不变,仅基准变。`file_vault` 仍存 `.resolve()` 绝对路径,执行期隔离/还原不受影响。

- 函数签名由 `_resolve_evaluate_refs(config, config_dir)` 收敛为 `_resolve_evaluate_refs(config)`(不再需要 config 目录),`load_from_file:1381` 调用点同步。
- 配置里三条 ref 塌缩为裸名:`oracle.json`、`user_queries.json#/0/evaluate/0/custom_rubrics`、`user_queries.json#/0/evaluate/0/scoring`。
- `task-config-schema` spec 删除"任务包收纳…区分两类相对路径基准"这条(其"两类基准"前提被推翻),把仍有效的"收纳布局""迁移脚本硬编码同步"并入新的单一基准需求。

**为何单一基准更优**:`user_dir.path` 无论如何都是任务环境的唯一真源、搬迁必改;refs 骑在它上面 → 搬迁只改一处、ref 永远裸名、无任务名冗余。旧设计"refs 原样存活"的收益是虚的,代价是两套基准 + 每条 ref 抄任务名。

### D2: `user_dir` 缺失且设了 ref → 加载期 fail-fast

在 `_resolve_evaluate_refs` 遍历 query 前(或逐 query 判定时)加前置校验,按**意图**判定:

```
任一 ev 的 oracle_ref/rubrics_ref/scoring_ref 非空
   ├─ user_dir 有正常 path        → 相对它解析 ✓
   ├─ user_dir 为 None            → raise ValueError(配置矛盾)
   └─ user_dir.path 为虚空地址     → raise ValueError(同上,勿掉进含糊 FileNotFound)
所有 *_ref 为空 → 不需基准 → user_dir=None 合法(纯 agent 跑)
```

- 选 fail-fast 而非"退回 q1.json 基准":后者把刚消灭的两套基准又请回来,且违背既有 spec"引用缺失显式报错、MUST NOT 静默退空"(`task-config-schema:17-19`)。
- 虚空地址边界:`coerce_user_dir` 把 `{path:null}` 变成真实空目录,若不特判则 refs 会 `FileNotFoundError` 于 `%TEMP%/openclaw_void_dir`(报错含糊)。故显式识别该 sentinel 路径并给出清晰错误。实现上把虚空地址常量抽出(coerce_user_dir 与本校验共用),避免字符串重复。
- 错误信息示例:`evaluate.*_ref 已设置但 input_dir.user_dir 缺失/为空,无法确定引用解析基准`。

### D3: `feedback_to_simulator` → `to_simulator`

`evaluator.py`:字段 `:183` 改名 `to_simulator`,`validation_alias=AliasChoices("to_simulator","feedback_to_simulator","feedback_to_user")`;property `:363`、`to_dict` key `:571`、日志 `:357-358` 同步。`openclaw_automation.py:735` 回流判断改 `evaluator.to_simulator`。旧配置/别名读取零改动。

**语义提醒(已确认接受)**:`to_simulator: true` 去掉了 `feedback` 语义修饰,可读性略降,换取字段名简洁;用户拍板直接改。

### D4: bulk 数据根显式化 `user_dir.user_workspace`

`UserDirConfig` 新增 `user_workspace: Optional[str] = None`(相对 `user_dir.path` 的相对路径,可多段如 `data/files`)。bulk 数据根 `content_root` 的派生由写死的 `user_path / user_path.name` 改为:

```python
sub = user_dir_config.user_workspace or user_path.name   # 默认回退同名子文件夹
content_root = user_path / sub
```

- **默认值 = `user_dir.path.name`**:不填 `user_workspace` 时行为与现状完全一致(同名子文件夹),向后兼容、零迁移压力。
- **两处调用点统一**:`_setup_workspaces:1178` 与 `setup_agent_files:317` 目前各自 `user_path / user_path.name` 重算一遍 content_root。为避免两处派生逻辑漂移,`_setup_workspaces` 计算出的数据根 SHALL 下传给 `setup_agent_files`(新增参数,如 `data_root`/或传 `user_workspace` 值),`setup_agent_files` 不再自行重算。
- **map 模式同步**:map key 基准 `data_dir = str(content_root) if content_root.is_dir() else str(user_path)` 中的 `content_root` 用新派生值。对当前 08 任务(未设 `user_workspace`、无同名子文件夹)仍退回 `user_path`,行为不变。
- **示例落点**:在 `configs/task_configs_0701/0701_任务管线产物标准模板/task_configs/08_科研助手_描述统计相关分析_q1.json` 的 `input_dir.user_dir` 下显式写出 `user_workspace`(值即约定的数据根子目录名),作为该字段的规范示例。
- **边界**:`user_workspace` 为相对路径,SHALL 落在 `user_dir.path` 之内;含 `..` 逃逸出 `user_dir.path` 的写法视为非法(实现可选校验,至少不鼓励)。本次不做 `user_workspace` 与 `map_file` 的互斥约束——map 模式仍以 map 为准,`user_workspace` 仅影响 map key 基准的选择。

**范围说明**:仅显式化"数据根子目录",不改 bulk 复制的平铺/覆盖/per-agent 语义。

## Migration

- 规范配置数据统一采用新名 `to_simulator` 与裸名 ref;历史别名/旧 ref 写法仍可读(别名兼容),但非规范写法。
- 本次仅迁移仓内样本(`08_..._q1.json`、`config_session.json`);外部遗留配置靠别名 + 旧基准…—— 注意:**refs 基准变更对旧配置是行为变更**,写 `../environments/...` 的旧 ref 在新基准下会解析失败(相对 user_dir.path 找不到 `../environments/...`)。这是 refs 语义收敛的必然代价,迁移时须把旧 ref 改为裸名。

## Risks

- **BREAKING(refs 基准)**:任何仍写 `../environments/<任务名>/...` 形式 ref 的配置在新基准下失效,须改裸名。缓解:仓内样本本次同步迁移;错误是 fail-fast 的 `FileNotFoundError`,不会静默。
- 改名 `to_simulator`:靠 `AliasChoices` 兼容,风险低。
