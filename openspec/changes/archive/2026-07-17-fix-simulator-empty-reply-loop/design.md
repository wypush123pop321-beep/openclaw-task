## Context

多轮任务端到端跑（task03）中观测到：simulator 调用 reasoning 类模型（gemini-3.5-flash 经 OpenAI 兼容接口）时，`usage.completion_tokens` 非零但 `choices[0].message.content` 为空——生成的 token 全进了 reasoning 通道，主 content 通道为空。该空串沿三个模块逐级传导、无一拦截，最终导致约一小时的 history_fallback 空转、轨迹落盘被拖延。

当前三处相关代码：
- `user_simulator.py:chat()`：`reply = response.choices[0].message.content` 直接取，无空值兜底。
- `src/executor.py` 多轮循环：`user_reply` 空时 `Task_Done`/`Task_Failed` 子串判定均 False，直接 `current_query = user_reply`（空串）进下一轮。
- `src/openclaw_client.py:execute_with_retry`：空串发给网关触发 `GatewayError("message or attachment required")`，被 `except (GatewayError, asyncio.TimeoutError)` 捕获、误当连接异常，进入 `EXECUTION_MAX_ATTEMPTS` 轮 history_fallback（每轮 40×30s 轮询 + 60s 重试等待）。

约束：不改变既有正常多轮/收尾语义；agent 空回复已有的 3 次重试防护保持不变；连接类异常的重连 + fallback 行为保持不变。

## Goals / Non-Goals

**Goals:**
- simulator `chat()` 永不返回空串——空 content 回退 reasoning 字段 → 有限重试 → 兜底显式收尾标记。
- executor 多轮循环对空 `user_reply` 有对称防护，杜绝把空消息下发网关。
- openclaw 客户端把确定性非法请求（`message or attachment required`）与连接类异常分流，快速失败，消除长时间空转。

**Non-Goals:**
- 不改仿真用户的判定策略与脱敏策略（属既有 `user-simulation` 需求）。
- 不重写 `execute_with_retry` 的连接韧性/重连机制，仅新增一条异常分类分支。
- 不改 reasoning 模型的调用参数或供应商配置；只在客户端侧对返回体做兼容取值。

## Decisions

**决策 1：三层防御全部落地，而非只修一层。**
根因在 simulator（层 1），但 executor（层 2）与 client（层 3）的缺陷各自独立、都会把小问题放大。三层叠加后，任一层的回归都不会再重演一小时空转。
- 备选：只修 simulator。否决——若未来别的路径也产生空 query，层 2/3 仍会空转；防御性冗余在无人值守批跑里价值高。

**决策 2：simulator 取值顺序 = 主 content → reasoning 字段 → 重试 → 失败兜底。**
优先主 content（正常路径不变）；空则回退 reasoning 文本通道；仍空复用 `chat()` 既有的 3 次调用重试；重试 3 次仍空返回 `【Task_Failed】` 语义标记而非空串或抛异常。
- 选失败（Task_Failed）而非完成（Task_Done）兜底：simulator 连续 3 次吐不出任何内容（主 content + reasoning 均空）= 其自身故障，不是"任务完成"。判失败比判完成诚实——判完成会把 simulator 故障计为成功、虚高成功率、掩盖问题；判失败则如实暴露这轮 simulator 未正常产出。

**决策 3：executor 空 `user_reply` 判定放在赋值 `current_query` 之前。**
在 `chat()` 返回后立即判空。空则判 `failed`（与决策 2 的失败兜底同义，双保险）。这是最靠上游的拦截点，即使 simulator 兜底失效也能挡住，且语义一致——空回复=simulator 故障=失败。

**决策 4：client 侧按错误消息特征分流，而非新增异常类型。**
`message or attachment required` 是网关对非法请求的确定性拒绝。在 `except (GatewayError, asyncio.TimeoutError)` 分支内先辨识该特征（消息体匹配），命中则立即上抛、跳过 fallback 与重试计数；其余仍走既有连接类处置。
- 备选：让 SDK 抛专门的异常子类。否决——不改 SDK；按消息特征分流改动面最小、可回溯。

## Risks / Trade-offs

- [reasoning 字段命名因供应商而异] → 取值兜底按已知字段名（如 `reasoning_content`）+ 宽松读取（getattr/dict 兼容），取不到即视为空、继续走重试/失败兜底，不因字段缺失抛错。
- [判失败可能把偶发单次空吐误计为失败] → 仅在 content + reasoning + 连续 3 次重试全空时才判失败，属极端退化路径；正常有内容的轮次不受影响。相比误判为完成（掩盖故障），误判为失败更安全、更易在结果里暴露。
- [按错误消息字符串匹配较脆弱，网关文案变动会失配] → 匹配失配时退化为现状（走 fallback），不会比修复前更差；用稳定子串匹配并加注释标注来源。

## Migration Plan

纯代码防御性修复，无数据/接口变更，无需迁移。回滚 = 还原三个文件的改动即可。部署后可用一次多轮任务端到端跑（含 reasoning 模型 simulator）验证不再空转、轨迹按时落盘。

## Open Questions

- reasoning 文本通道除 `reasoning_content` 外是否还需兼容其他供应商字段名？（实现时按当前 yibuapi 返回体确定，必要时扩展兜底字段列表。）
