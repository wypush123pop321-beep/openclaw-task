## 1. Vault 字段与留存

- [x] 1.1 在 `evaluator.py` 的 `EvaluateConfig` 增加不落盘字段 `file_vault: Dict[str, str]`(`default_factory=dict, exclude=True`),键为绝对路径、值为原始文本
- [x] 1.2 在 `openclaw_automation.py` `_resolve_evaluate_refs` 解析 `oracle_ref` 时,把已读到的原始文本与 `op` 的绝对路径存入 `ev.file_vault`(复用现有 `read_text`,不二次读盘)
- [x] 1.3 同样在解析 `rubrics_ref` 时,把 `rp`(整文件)的原始文本与绝对路径存入 `ev.file_vault`(片段引用也按整文件留存)

## 2. Per-query 删除与还原

- [x] 2.0 在 `evaluator.py` `EvaluateConfig` 增加开关 `isolate_eval_files: bool = True`;在两个 helper 内统一判定(关闭时 isolate/restore 均 no-op)
- [x] 2.1 在 `openclaw_automation.py` 新增辅助:`_isolate_eval_files(ev)` 删除 `ev.file_vault` 中各路径(`Path.unlink(missing_ok=True)`),`_restore_eval_files(ev)` 把原始字节写回(写失败仅 `logger.warning`,不抛错)
- [x] 2.2 在 `execute_queries` 中 `create_evaluator(...)` 之后、`for turn ...` 之前,当 `evaluator is not None` 时调用 `_isolate_eval_files(query.evaluate)`
- [x] 2.3 在该 query 轮次循环结束后(success/done/fail 各路径汇合处)调用 `_restore_eval_files(query.evaluate)`;不使用 `finally`/异常兜底

## 3. 验证

- [x] 3.1 用 `run_config_smoke.json` 经 `ConfigLoader.load_from_file` → `_isolate_eval_files` 验证:isolate 后磁盘上 `oracle.json` / `user_queries.json` 均不存在
- [x] 3.2 隔离后内存 `oracle_data` 非空、`structured_rubrics`=8 条仍在 —— evaluator 评分输入完全走内存,删盘不影响(完整 LLM 评分需活网关,逻辑结构上已保证)
- [x] 3.3 restore 后两文件均回写,sha256 与隔离前逐字节一致;`git status` 对这两文件无 diff
- [x] 3.3b 开关验证:默认 `True` 时删除+字节一致还原;置 `False` 时两文件全程保留、未被改动
- [x] 3.4 `test/test_evaluator.py` 在 HEAD 即已损坏(对齐到早代旧 API);本次顺手重写到当前 API(`EvaluateConfig`/`RubricCheck.passed`/0~1 completion/新 `_build_prompt` 签名+提示词/去 `last_feedback`/去 `enabled`,并加 GBK 控制台 utf-8 兜底),`python test/test_evaluator.py` 10/10 通过、exit 0
