## Context

agent workspace 的内容来源目录当前由硬编码约定 `user_path / user_path.name` 决定，出现在两处彼此独立的代码里：

- `src/workspace.py:87` — `BaseWorkspaceManager.setup_agent_files` 中 `content_root = user_path / user_path.name`，真正的内容复制根。
- `harness_automation.py:311` — `AutomationEngine._setup_workspaces` 中同样的 `content_root = user_path / user_path.name`，用于存在性检查 + 决定是否走 `map_file` 分支。

约定不可见、不可覆盖，用户被迫制造重复同名层（`.../paper_reader/paper_reader/`）。此外系统里已存在**两个不同基准**需要保持清醒：evaluate 引用（`oracle_ref`/`rubrics_ref`/`scoring_ref`，`src/config.py:_resolve_evaluate_refs`）以 `user_dir.path` **父层**为基准，而内容复制以**同名子层**为基准。本次改动只动后者。

## Goals / Non-Goals

**Goals:**
- 在 `UserDirConfig` 增加可选 `user_workspace`，让用户显式指定内容子目录名。
- 三档语义：未设置=同名（兼容）、`"name"`=`path/name`、`""`=`path`。
- 把两处硬编码收敛到单一 `content_root` 计算来源。
- 老配置零改动、零行为变化。

**Non-Goals:**
- 不支持相对多级路径或绝对路径（仅子目录名一档）。
- 不改变 evaluate 引用的解析基准（仍相对 `path` 父层）。
- 不改动 `map_file` / `profile_file` 的语义与解析基准。

## Decisions

**决策 1：把解析逻辑做成 `UserDirConfig.content_root` property（单一来源）。**
- 在 `UserDirConfig` 上暴露一个只读 property 计算 `content_root`，两处调用点都改用它。
- 备选：在两处各自内联新逻辑 → 否决，等于把「两处硬编码」换成「两处新逻辑」，收敛目标落空。
- 备选：放到独立 util 函数 → 可行，但字段与其派生路径同居一个模型上内聚性最好。

```python
@property
def content_root(self) -> Path:
    base = Path(self.path).expanduser()
    sub = base.name if self.user_workspace is None else self.user_workspace
    return base / sub    # sub == "" 时 Path/"" == Path,天然拍平
```

**决策 2：用 `is None` 区分「未设置」与空字符串,而非真值判断。**
- 空串 `""` 是有意义的一档（拍平），`or` / 真值判断会把它并入「未设置」,直接违反 spec。这是本改动最易错的点,单测必须覆盖三档。

**决策 3：`Path(x) / "" == Path(x)`,不特判空串。**
- Python `pathlib` 语义:`Path("/a/b") / "" == Path("/a/b")`。因此空串自然得到 `content_root == path`,无需 if 分支。

**决策 4：调用点改写方式。**
- `src/workspace.py` 的 `setup_agent_files` 目前只接收 `user_dir: Optional[str]`(纯路径字符串),自己算 `content_root`。为收敛,让它改用统一逻辑——最小侵入是把 `user_path / user_path.name` 替换为对同一 property/util 的调用;若签名不便传对象,可让 util 接收 `(path, user_workspace)` 两个原始值,property 内部委托同一 util。二者取其一,保持单一实现体。
- `harness_automation.py:_setup_workspaces` 已持有 `user_dir_config` 对象,直接改用 `user_dir_config.content_root`。

## Risks / Trade-offs

- [空串语义被真值判断吞掉] → 单测显式覆盖 `None` / `"ws"` / `""` 三档 content_root 断言;code review 关注 `is None`。
- [两处收敛后仍漂移] → 断言两处使用同一来源(property 或同一 util);spec 已有「存在性检查与内容复制一致」场景兜底。
- [`user_workspace` 含路径分隔符被误用为多级/绝对路径] → 本档不支持,但 `Path/"a/b"` 会静默生效。可选:在校验器里拒绝含分隔符的值,或文档明确「仅子目录名」。列为开放项,倾向文档约束+不主动报错以免过度设计。
- [signature 传递] → 若选择 util 双参形式,注意 workspace.py 调用点当前拿不到 `user_workspace`(只传了 path 字符串);需从上游 `harness_automation.py` 把该值一并传下,或直接把 `content_root` 算好后传路径。评估两者后在 tasks 里定一种。

## Migration Plan

无数据迁移。字段可选且默认等价旧行为,老配置无需改动。回滚=还原代码,无状态残留。

## Open Questions

- 是否要在校验器主动拒绝 `user_workspace` 含 `/` 或绝对路径的值?(当前倾向:不拒绝,文档说明仅子目录名。)
- 收敛实现选「property 单一来源 + 上游传对象」还是「util 双参 + 传 content_root 路径下去」?两者都满足单一实现体,tasks 阶段定稿。
