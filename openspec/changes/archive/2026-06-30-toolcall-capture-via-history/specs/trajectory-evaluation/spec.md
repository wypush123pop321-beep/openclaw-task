## MODIFIED Requirements

### Requirement: 基于真实证据并可用工具核验

evaluator SHALL 基于本轮的可核验证据(`tool_calls` 与经磁盘真相校正的文件)进行评估,而非仅凭 agent 的文本说辞。evaluator SHALL 能使用自身工具对被审查产物做主动核验(如打开文件、检索、运行校验)。当 `tool_calls` 为空时,evaluator MUST NOT 据此推断 agent「未调用工具 / 硬编码 / 造假」——空 `tool_calls` 可能源于采集缺口(如服务端自主 agent 的工具步骤未被采集到),SHALL 与 `evidence_incomplete` 同等对待(证据缺失 ≠ 负面证据)。evaluator 指出「声称与证据矛盾」SHALL 以**可确证的反证**为据(如磁盘真相显示其声称生成的文件不存在、或输出与 oracle 事实冲突),MUST NOT 仅以「无 `tool_calls` 记录」作为造假判据。

#### Scenario: 拆穿话术型假阳性
- **WHEN** agent 声称完成了某操作,且存在可确证的反证(如磁盘真相显示其声称生成的文件不存在,或输出与 oracle 事实冲突)
- **THEN** evaluator SHALL 在反馈中明确指出「声称与证据矛盾」,据以阻止该轮被判为完成

#### Scenario: 工具核验产物
- **WHEN** 被审查的产物文件已按约定推送至 evaluator 自身工作区
- **THEN** evaluator SHALL 可用自身工具读取/核验该产物,并将核验所得作为评估依据

#### Scenario: 空 tool_calls 不得作为造假证据
- **WHEN** 某 turn 的 `tool_calls` 为空,但 agent 的输出与磁盘真相 / oracle 一致、无任何可确证的反证
- **THEN** evaluator MUST NOT 仅因「无 `tool_calls`」判定 agent 造假或未真实读取文件,SHALL 将其视为证据缺失而非负面证据
