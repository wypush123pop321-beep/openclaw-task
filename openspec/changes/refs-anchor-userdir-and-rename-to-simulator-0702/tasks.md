## 1. 代码:refs 改锚 user_dir + fail-fast

- [x] 1.1 `openclaw_automation.py` 抽出"虚空地址" sentinel 常量(供 `coerce_user_dir` 与 refs 校验共用),`coerce_user_dir` 改用该常量
- [x] 1.2 `_resolve_evaluate_refs` 解析基准由 `config_dir`(q1.json 目录)改为 `Path(config.input_dir.user_dir.path).expanduser()`;三处 `config_dir / xxx` → `user_base / xxx`,`file_part#ptr` 拆分逻辑不变
- [x] 1.3 `_resolve_evaluate_refs` 新增前置 fail-fast:某 ev 任一 `oracle_ref`/`rubrics_ref`/`scoring_ref` 非空,但 `user_dir` 为 None 或 path 为虚空地址 → 抛显式 `ValueError`
- [x] 1.4 收敛签名 `_resolve_evaluate_refs(config)`(删 `config_dir` 参数),`load_from_file:1381` 调用点同步

## 2. 代码:to_simulator 改名

- [x] 2.1 `evaluator.py:183` 字段 `feedback_to_simulator` → `to_simulator`,`validation_alias=AliasChoices("to_simulator","feedback_to_simulator","feedback_to_user")`
- [x] 2.2 `evaluator.py:363` property `feedback_to_simulator` → `to_simulator`;`to_dict`(`:571`)key 与日志(`:357-358`)同步
- [x] 2.3 `openclaw_automation.py:735` `if evaluator.feedback_to_simulator` → `if evaluator.to_simulator`

## 3. 代码:user_workspace 数据根显式化

- [x] 3.1 `openclaw_automation.py` `UserDirConfig` 新增 `user_workspace: Optional[str] = Field(None, ...)`(相对 `user_dir.path`)
- [x] 3.2 `_setup_workspaces:1178` `content_root` 派生改为 `user_path / (user_dir_config.user_workspace or user_path.name)`;map 模式 `data_dir` 沿用该 content_root
- [x] 3.3 `setup_agent_files:317` 不再自行重算 content_root,改由 `_setup_workspaces` 下传数据根(新增参数);默认回退同名子文件夹行为不变

## 4. 配置与文档

- [x] 4.1 `08_..._q1.json` 三条 ref 改裸名:`oracle.json` / `user_queries.json#/0/evaluate/0/custom_rubrics` / `user_queries.json#/0/evaluate/0/scoring`
- [x] 4.2 `08_..._q1.json` `feedback_to_simulator` → `to_simulator`
- [x] 4.3 `08_..._q1.json` `input_dir.user_dir` 下显式写出 `user_workspace`(规范示例)
- [x] 4.4 `config_session.json` `feedback_to_simulator` → `to_simulator`
- [x] 4.5 `docs/CONFIG_STRUCTURE.md`、`docs/DESIGN.md`、`README.md` 同步字段名、"refs 相对 user_dir.path"与 `user_workspace` 说明

## 5. 测试与验证

- [x] 5.1 `test/test_evaluator.py`:`to_simulator` 开关默认 False / True-False 行为、别名 `feedback_to_simulator`/`feedback_to_user` 等价读取
- [x] 5.2 `test/test_scoring_ref.py`:refs 相对 user_dir.path 正确解析(裸名 + JSON-Pointer);`../environments/...` 旧写法在新基准下 `FileNotFoundError`
- [x] 5.3 fail-fast 测试:设 ref 但 `user_dir=None` → `ValueError`;`{path:null}`(虚空地址)+ ref → `ValueError`;无 ref + `user_dir=None` → 正常加载
- [x] 5.4 `user_workspace` 测试:显式 `user_workspace` 指向的子目录被用作数据根;不填时回退同名子文件夹(与现状一致)
- [x] 5.5 加载测试:迁移后 `08_..._q1.json` 裸名 ref 从 user_dir.path 正确解析、scoring_spec gate 正常、无 `FileNotFoundError`
- [x] 5.6 端到端:`python openclaw_automation.py --config .../task_configs/08_..._q1.json` exit 0。验证通过:map 部署(`user_files` 子目录不存在→基准回退 user_dir.path,`D/论文数据/调研数据.xlsx` 正确投放)、`Evaluator 已启用(...to_simulator=True)`、oracle/user_queries 从 user_dir.path 解析并被文件隔离删除→结束后已还原(git 无改动)。注:任务本身在首轮 solver LLM 调用触发上游 `Concurrency limit exceeded for account`(账号并发限流,环境问题、与本变更无关),harness 优雅收尾、环境文件完整还原、进程 exit 0。
