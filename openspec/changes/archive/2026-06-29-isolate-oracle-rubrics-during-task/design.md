## Context

被测 assistant 运行在可访问真实文件系统的环境(任务输入经 `setup_from_map` 落到真实绝对路径,如 `D:\出行\…csv`)。同一份 config 目录里还放着 `oracle.json`(标准答案)与 `user_queries.json`(`custom_rubrics` 验收清单)。一个会浏览文件系统的 agent 可能直接读到答案/评分标准。

关键现状(已核实):
- `_resolve_evaluate_refs`(`openclaw_automation.py:1115`)在 **config 加载期**(`load_config`,`:1191`)就把 oracle 读进 `ev.oracle_data`、把 rubrics 经 JSON-Pointer 读进 `ev.structured_rubrics`。
- 它是这两个文件在**运行期的唯一读者**;evaluator 评分时只读内存(`evaluator.py:470` 取 `self.config.oracle_data`,rubrics 由 `config.rubric_items()` 经内存传入)。
- 因此「把 oracle/rubrics 载入 evaluator」这一前置条件**已天然满足**;本变更只补「执行期从磁盘隔离 + 结束后还原」。
- 样例中只有 `04_..._q1.json` 与 `run_config_smoke.json` 引用 oracle/rubrics,且**各只含 1 个 query**,均指向 `user_queries.json#/0/`;不存在「同一 config 多 query 共用一文件」。

## Goals / Non-Goals

**Goals:**
- assistant 执行某 query 任务期间,该 query 的 oracle/rubrics 文件不在磁盘上。
- evaluator 评分完全不受影响(仍走内存)。
- 任务结束后能把文件还原成与原文件逐字节一致(便于本地调试、git 无 diff)。

**Non-Goals:**
- 不做崩溃安全/`finally` 兜底:容器化运行,删了即可,还原纯为调试便利。
- 不改 evaluator 评分/质检逻辑。
- 不覆盖「任何 agent 任何时候都不可见任何答案」的强威胁模型(per-query 作用域不提供此保证,见 Risks)。
- 不处理「多 query 共用同一 oracle/rubrics 文件」(当前样例不存在;不加幂等特判)。

## Decisions

### 决策 1:在已有的读盘处顺手留存原始字节,而非二次读盘
`_resolve_evaluate_refs` 本就 `read_text()` 了这两个文件(`:1131`/`:1138`)。在那里把**原始文本 + 解析后的绝对路径**存进一个 vault 结构,挂到 `EvaluateConfig` 的不落盘字段(如 `_file_vault: Dict[str, str]`,定义在 `evaluator.py`,`exclude=True`)。
- 为什么:绝对路径事后会丢(`oracle_ref` 只存相对路径);在唯一已知 `config_dir` 的地方一次性捕获最省事。
- 替代方案:执行期重新拼 `config_dir` 再读盘——需把 `config_dir` 透传到 `execute_queries`,且多一次 IO,放弃。

### 决策 2:还原用原始字节写回,不重新序列化解析对象
- 为什么:rubrics 只是 `user_queries.json` 的一个片段,重新 `json.dumps` 解析对象会改键序/格式、且只能覆盖片段——污染 git diff。留原始字节写回则逐字节一致。
- 替代方案:序列化 `oracle_data`/`structured_rubrics` 回写——放弃。

### 决策 3:作用域 per-query,删在轮次循环前、还原在循环后
- 位置:`execute_queries` 内,`create_evaluator(...)`(`:874`)之后、`for turn ...`(`:877`)之前删除;循环结束后还原。
- 为什么:每个 oracle/rubrics 只服务于其对应 query;最小缺席窗口。
- 替代方案:run 作用域(在 `run()` 包住 `execute_queries`)——实现更省但所有 query 期间文件都缺席,且不符合 per-query 决定,放弃。

### 决策 4:整文件删除/还原
- 为什么:`user_queries.json` 在运行期的唯一读者就是 `_resolve_evaluate_refs`(已核实 simulator 用 `user_profile_*.json`/`user_proxy_model.json`,不碰它),整文件删除运行期安全;比「片段置空」实现简单。

### 决策 6:开关放在 evaluate 块,默认开启,统一在 helper 内判定
新增 `EvaluateConfig.isolate_eval_files: bool = True`。开关检查放进 `_isolate_eval_files`/`_restore_eval_files` 两个 helper 内部(`evaluate is None or not isolate_eval_files → return`),使删除与还原**对称地**响应开关:关闭时两者都 no-op,不会出现"没删却还原"的不一致。
- 为什么放 evaluate 块:与 `oracle_ref`/`rubrics_ref`/`scoring` 同级,per-query 粒度一致;呼应仓库"以 evaluate 块存在与否驱动评估、不另设全局开关"的既有约定。
- 为什么默认 True:本变更的目的即隔离;开关主要用于调试时临时关闭。

### 决策 5:删除/还原均 best-effort,不抛错
- `delete()` 用 `os.remove(..., )` 配 `missing_ok` 语义(`Path.unlink(missing_ok=True)`);`restore()` 写回失败仅记日志、不中断。

## Risks / Trade-offs

- [per-query 作用域留有缺口:文件仅在「属于它的 query」执行期间缺席,其它 query(尤其 noise query)运行时文件已还原在盘] → 已与需求方确认接受:每个 oracle/rubrics 只对应自己的 query,与其他 query 无关。若日后威胁模型升级为「全程不可见」,改为 run 作用域或开跑前一次性全删即可。
- [硬杀(SIGKILL/断电)时还原不执行,git 工作树残留已删文件] → 容器化运行可接受;本地用 `git restore <oracle.json> <user_queries.json>` 恢复(内存字节与已提交版一致)。
- [还原以解析后对象重写会污染 diff] → 由决策 2(原始字节写回)规避。

## Migration Plan

- 纯新增隔离行为,无数据/接口迁移。
- 回滚:移除 `execute_queries` 中的 delete/restore 调用与 vault 留存即可恢复旧行为;文件本身受 git 跟踪可随时 `git restore`。

## Open Questions

- 无。三处关键选择(粒度=整文件、作用域=per-query、还原=调试用 best-effort)已与需求方确认。
