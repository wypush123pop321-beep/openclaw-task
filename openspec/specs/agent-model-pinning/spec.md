# agent-model-pinning Specification

## Purpose

规范如何为顶层 `agents[]` 中任意 agent(不限于 evaluator)钉死一个固定模型:经 `agents.update` 下发完整 `provider/model` 串,并在下发前经网关白名单校验,确保被钉死的模型可被真正路由而非被静默回退到默认模型。

## Requirements

### Requirement: per-agent 模型钉死经 agents.update 下发完整 provider/model 串

系统 SHALL 支持为顶层 `agents[]` 中任意 agent(不限于 evaluator)钉死一个固定模型:当 agent 声明含非空 `model` 时,系统 SHALL 经 `agents.update(agentId, model=…)` 下发。下发的模型串 SHALL 为完整的 `provider/model` 形式——当 `model` 已含 `/` 前缀时原样使用;当 `model` 为裸名且声明了 `model_provider` 时,系统 SHALL 拼装为 `"<model_provider>/<model>"` 再下发。系统 MUST NOT 依赖 `agents.create` 携带模型(该 RPC 仅接收 name/workspace)。

#### Scenario: 裸模型名与 provider 拼装为完整串
- **WHEN** 某 agent 声明 `model` 为裸名(不含 `/`)且声明了 `model_provider`
- **THEN** 系统 SHALL 拼装 `"<model_provider>/<model>"` 并经 `agents.update` 下发,而非下发裸名

#### Scenario: 已含前缀的模型串原样下发
- **WHEN** 某 agent 声明 `model` 已为 `"provider/model"` 形式
- **THEN** 系统 SHALL 原样下发该串,不重复拼接 provider

#### Scenario: 无 model 声明不触发钉死
- **WHEN** 某 agent 声明未含 `model`(或为空)
- **THEN** 系统 SHALL NOT 对该 agent 调用 `agents.update` 下发模型,该 agent 沿用网关默认模型

### Requirement: pin 前白名单校验,不可路由模型即失败终止

系统在下发任一 agent 模型之前,SHALL 先确认目标模型 id 在网关可路由的模型白名单内(经 `gateway.models_list()` 获取)。当目标模型不在白名单内时,系统 SHALL 大声报错并终止该 agent 的装配,MUST NOT 下发一个注定被网关静默回退到默认模型的 pin。网关返回 `{ok:True}` SHALL NOT 被单独视为钉死成功的充分证据——该返回仅表示配置串已写入,不代表模型可被真正路由。白名单 SHALL 在 setup 期一次性获取并缓存,校验全部待钉死 agent SHALL 复用同一份缓存,MUST NOT 进入 per-turn 或 per-query 热路径。

#### Scenario: 目标模型不在白名单则报错终止
- **WHEN** 某 agent 声明的目标模型 id 不在 `gateway.models_list()` 返回的可路由模型集合内
- **THEN** 系统 SHALL 抛出显式错误并终止装配,MUST NOT 静默下发并让网关回退默认模型

#### Scenario: 目标模型在白名单则正常下发
- **WHEN** 某 agent 声明的目标模型 id 存在于可路由白名单内
- **THEN** 系统 SHALL 正常经 `agents.update` 下发该模型

#### Scenario: 白名单 setup 期一次性缓存
- **WHEN** 一次运行需为多个 agent 校验并钉死模型
- **THEN** 系统 SHALL 在 setup 期仅调用一次 `models_list()` 并缓存结果,后续各 agent 校验复用该缓存,MUST NOT 每个 agent 各拉一次

#### Scenario: {ok:True} 不作为钉死成功的充分依据
- **WHEN** `agents.update` 返回 `{ok:True}` 但目标模型未通过白名单校验
- **THEN** 系统 SHALL 以白名单校验结果为准判定钉死是否可信,MUST NOT 仅凭 `{ok:True}` 认定模型已生效
