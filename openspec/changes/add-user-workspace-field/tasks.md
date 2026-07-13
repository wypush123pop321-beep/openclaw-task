## 1. 配置模型

- [x] 1.1 在 `src/config.py` 的 `UserDirConfig` 增加可选字段 `user_workspace: Optional[str] = Field(None, ...)`,description 说明三档语义与「仅子目录名」限制。
- [x] 1.2 在 `UserDirConfig` 增加 `content_root` property:`base = Path(self.path).expanduser(); sub = base.name if self.user_workspace is None else self.user_workspace; return base / sub`。务必用 `is None`,不要用 `or`。
- [x] 1.3 确认 `coerce_user_dir` 校验器对新字段无副作用(字符串路径 → `UserDirConfig(path=v)` 时 `user_workspace` 仍为 `None`)。

## 2. 收敛硬编码调用点

- [x] 2.1 改写 `harness_automation.py:311` 的 `_setup_workspaces`:把 `content_root = user_path / user_path.name` 替换为 `content_root = user_dir_config.content_root`;存在性检查 / map 分支门控沿用该值。
- [x] 2.2 让 `harness_automation.py` 把内容根传给 workspace 层:传 `content_root=str(content_root)`,使 workspace 层无需再自行推导同名目录。
- [x] 2.3 改写 `src/workspace.py:87` 的 `setup_agent_files`:移除内联 `content_root = user_path / user_path.name`,参数 `user_dir` 重命名为 `content_root` 直接使用上游传入的内容根(property 单一来源方案落地)。
- [x] 2.4 全仓 grep 确认无残留 `user_path / user_path.name` / `.name` 形式的内容根硬编码(排除无关 `.name` 用法)。

## 3. 测试

- [x] 3.1 为 `UserDirConfig.content_root` 加单测:`None` → `path/basename`、`"ws"` → `path/ws`、`""` → `path` 三档断言。(test/test_workspace_config.py)
- [x] 3.2 加回归测试:老配置(无 `user_workspace`)解析出的 content_root 与改动前一致(向后兼容)。
- [x] 3.3 加一致性测试:`setup_agent_files` 直接使用上游传入的 content_root,不再自行推导同名子目录(单一来源)。
- [x] 3.4 加保护性测试:配置了 `user_workspace` 时,evaluate `oracle_ref` 仍相对 `user_dir.path` 父层解析(基准未漂移)。

## 4. 文档与示例

- [x] 4.1 在 `docs/CONFIG_STRUCTURE.md` 补充 `user_workspace` 字段说明、对象形式、三档语义表与「仅子目录名」限制。
- [x] 4.2 新增 `configs/config_user_workspace_example.json` 作为带 `user_workspace` 的示例(现有 config 未改,默认不破坏)。
