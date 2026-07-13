## ADDED Requirements

### Requirement: user_workspace 字段声明

`input_dir.user_dir`（`UserDirConfig`）SHALL 提供一个可选字符串字段 `user_workspace`，用于指定 agent workspace 内容所在的子目录名。该字段缺省值 MUST 为「未设置」（`None`），且 MUST 与空字符串 `""` 在语义上区分。

#### Scenario: 字段缺省

- **WHEN** 配置的 `input_dir.user_dir` 未提供 `user_workspace` 键
- **THEN** 该字段的值为 `None`（未设置），不报错

#### Scenario: 字段以字符串形式提供

- **WHEN** 配置提供 `user_workspace: "ws"`
- **THEN** 该字段保存字符串 `"ws"`，可被后续 content_root 解析使用

### Requirement: content_root 三档解析语义

系统 SHALL 依据 `user_workspace` 的取值，从 `user_dir.path` 解析出 agent workspace 的内容来源目录 `content_root`，遵循以下三档语义（`path` 先经 `~` 展开）：

- 未设置（`None`）→ `content_root = path / basename(path)`（同名子目录）。
- 非空子目录名 `S` → `content_root = path / S`。
- 空字符串 `""` → `content_root = path`。

该解析 MUST 使用「是否为 `None`」来区分未设置与空字符串，MUST NOT 用真值判断（如 `or`）将 `""` 误判为未设置。

#### Scenario: 未设置回退同名目录（向后兼容）

- **WHEN** `path = /data/tasks/paper_reader` 且 `user_workspace` 未设置
- **THEN** `content_root` 解析为 `/data/tasks/paper_reader/paper_reader`

#### Scenario: 指定子目录名

- **WHEN** `path = /data/tasks/paper_reader` 且 `user_workspace = "ws"`
- **THEN** `content_root` 解析为 `/data/tasks/paper_reader/ws`

#### Scenario: 空字符串拍平嵌套

- **WHEN** `path = /data/tasks/paper_reader` 且 `user_workspace = ""`
- **THEN** `content_root` 解析为 `/data/tasks/paper_reader`

### Requirement: content_root 单一来源

所有依赖「用户内容来源目录」的位置 SHALL 使用统一的 `content_root` 解析结果，MUST NOT 各自重复硬编码 `user_path / user_path.name`。这至少包括 workspace 内容复制（原 `src/workspace.py`）与编排期的存在性检查 / map 分支门控（原 `harness_automation.py`）。

#### Scenario: 内容复制使用 content_root

- **WHEN** 装配某 agent 的 workspace 且 `user_dir` 已配置
- **THEN** 被复制进 workspace 的内容取自解析后的 `content_root`，而非任何独立硬编码路径

#### Scenario: 存在性检查与内容复制一致

- **WHEN** 编排期判断 `content_root` 是否存在以决定是否走 map_file 分支
- **THEN** 所用的 `content_root` 与实际内容复制所用的 `content_root` 完全一致

### Requirement: evaluate 引用基准保持不变

引入 `user_workspace` MUST NOT 改变 evaluate 外部引用的解析基准。`oracle_ref` / `rubrics_ref` / `scoring_ref` SHALL 继续以 `user_dir.path` 父层为相对基准，不受 `content_root` 影响。

#### Scenario: evaluate 引用仍相对 path

- **WHEN** 某 query 的 evaluate 块含 `oracle_ref` 且配置了 `user_workspace`
- **THEN** 该 ref 仍相对 `user_dir.path` 解析，而非相对 `content_root`
