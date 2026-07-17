## 1. simulator 侧兜底（根因）

- [x] 1.1 `user_simulator.py:chat()`：从模型响应取文本时，主 `choices[0].message.content` 为空则回退读取 reasoning 文本字段（如 `reasoning_content`，用 getattr/dict 兼容宽松读取，字段缺失视为空不抛错）
- [x] 1.2 主 content 与 reasoning 均为空时，复用既有 3 次调用重试再取一次
- [x] 1.3 重试 3 次仍为空时判为 simulator 失败，返回含 `【Task_Failed】` 语义的显式失败标记，确保 `chat()` 永不返回空串或纯空白
- [x] 1.4 `_log_api_call` 仍记录真实取到的文本（兜底后的值），保证日志与返回值一致

## 2. executor 侧拦截（最上游防护）

- [x] 2.1 `src/executor.py` 多轮循环：`user_reply = query_simulator.chat(...)` 之后、赋值 `current_query` 之前，判定空串/纯空白
- [x] 2.2 空 `user_reply` 判为失败（设 `trajectory.outcome = "failed"`、break），MUST NOT 以空串作为 `current_query` 下发；纵深防御，与 simulator 层失败兜底语义一致

## 3. client 侧错误分类（止血）

- [x] 3.1 `src/openclaw_client.py:execute_with_retry` 的 `except (GatewayError, asyncio.TimeoutError)` 分支内，先辨识 `message or attachment required` 一类确定性非法请求（稳定子串匹配 + 注释标注来源）
- [x] 3.2 命中确定性非法请求时立即上抛可辨识错误，跳过 history_fallback 轮询与连接类重试计数；其余连接类异常保持既有重连 + fallback 行为不变

## 4. 验证

- [x] 4.1 单元验证：simulator 返回体主 content 空 + reasoning 非空 → `chat()` 返回 reasoning 文本；全空 → 返回 `【Task_Failed】` 失败标记（可用 mock 响应对象）
- [x] 4.2 单元验证：executor 多轮循环喂空 `user_reply` → 判定失败、不调用下游、轨迹正常落盘
- [x] 4.3 单元验证：`execute_with_retry` 遇 `message or attachment required` → 快速上抛、不进 fallback；遇连接类异常 → 仍走 fallback
- [ ] 4.4 端到端：用 reasoning 模型 simulator 跑一次多轮任务，确认不再出现约一小时的 history_fallback 空转、轨迹按时落盘（待真实多轮任务跑时验证；单元层已覆盖三层防护）
