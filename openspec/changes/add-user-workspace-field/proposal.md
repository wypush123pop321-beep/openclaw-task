## Why

Agent workspace 内容的来源目录当前硬编码为「同名子目录」约定 `user_path / user_path.name`（见 `src/workspace.py:87`、`harness_automation.py:311`）。这导致用户必须把内容放进形如 `.../paper_reader_0713_v2/paper_reader_0713_v2/` 的重复同名层——路径冗长、易混淆，且约定不可见、不可覆盖。用户需要一种在 config 中显式指定该子目录的方式，同时保持老配置零改动。

## What Changes

- 在 `input_dir.user_dir`（`UserDirConfig`）下新增可选字段 `user_workspace`，用于显式指定 agent workspace 内容所在的子目录名。
- 三档取值语义：
  - **未设置（`None` / 字段缺省）** → 回退到同名目录 `path/<basename(path)>`（保持现有行为，向后兼容）。
  - **具体子目录名（如 `"ws"`）** → `content_root = path/ws`。
  - **空字符串 `""`** → `content_root = path`（内容直接位于 `path` 根下，拍平多余嵌套）。
- 仅支持「子目录名」一档；不支持相对多级路径或绝对路径。
- 将 `src/workspace.py:87` 与 `harness_automation.py:311` 两处硬编码的 `user_path / user_path.name` 收敛为统一的 `content_root` 计算（建议实现为 `UserDirConfig.content_root` property）。
- evaluate 引用基准 **不变**：`oracle_ref` / `rubrics_ref` / `scoring_ref` 仍以 `user_dir.path` 父层为相对基准（`src/config.py` 的 `_resolve_evaluate_refs` 不动）。

无破坏性变更：字段可选，缺省即老行为。

## Capabilities

### New Capabilities
- `user-workspace-resolution`: 定义 agent workspace 的内容来源目录（content_root）如何从 `input_dir.user_dir` 解析，包括 `user_workspace` 字段的三档语义与向后兼容的默认行为。

### Modified Capabilities
<!-- 无现有 spec 的需求发生变化;trajectory-evaluation 与本改动无关。 -->

## Impact

- **配置模型**：`src/config.py` — `UserDirConfig` 新增 `user_workspace` 字段 + `content_root` property。
- **workspace 装配**：`src/workspace.py` — `setup_agent_files` 中 `content_root` 计算改用统一逻辑。
- **编排入口**：`harness_automation.py` — `_setup_workspaces` 中的存在性检查 / map 分支门控改用统一 `content_root`。
- **配置文件 / 文档**：`configs/config_user.json` 等示例与 `docs/CONFIG_STRUCTURE*.md` 可选补充字段说明。
- **不受影响**：evaluate 外部引用解析（`_resolve_evaluate_refs`）、trajectory-evaluation 能力。
