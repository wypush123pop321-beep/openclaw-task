"""Hermes 连接配置解析(能力: harness-adapter)。

把 config 的 `harness.connection` 段翻译为:
- 子进程启动四件套(command/args/cwd/env);
- 凭证注入(provider/api_key/base_url → Hermes 认的环境变量;model → LLM_MODEL);
- 运行参数(默认模型、权限自动放行、握手超时)。

凭证翻译规则(对标 Hermes `.env.example`):provider 决定用哪组按 provider 命名的变量
`<PROVIDER>_API_KEY` / `<PROVIDER>_BASE_URL`,模型统一走 `LLM_MODEL`。`connection.launch.env`
里显式给出的键优先级最高(覆盖翻译结果),作为任意环境变量的逃生口。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

# 本期默认 launch:源码集成(方式②),在 Hermes 源码目录跑 `python -m acp_adapter`。
DEFAULT_COMMAND = "python"
DEFAULT_ARGS = ["-m", "acp_adapter"]
DEFAULT_INIT_TIMEOUT = 120.0


@dataclass
class HermesLaunch:
    """子进程启动 + 运行参数的中立载体。"""

    command: str
    args: list[str]
    cwd: Optional[str]
    env: dict[str, str]
    model: Optional[str] = None
    auto_approve_permissions: bool = True
    init_timeout: float = DEFAULT_INIT_TIMEOUT
    # Hermes 服务端以 use_unstable_protocol=True 运行,客户端须匹配,否则握手即断。
    use_unstable_protocol: bool = True


def _expand(value: Optional[str]) -> Optional[str]:
    return os.path.expanduser(value) if isinstance(value, str) and value else value


def build_launch(connection: dict[str, Any]) -> HermesLaunch:
    """从 `connection` dict 构造 `HermesLaunch`。"""
    conn = dict(connection or {})
    launch = dict(conn.get("launch") or {})

    command = launch.get("command") or DEFAULT_COMMAND
    args = list(launch.get("args") or DEFAULT_ARGS)
    cwd = _expand(launch.get("cwd"))

    # 继承当前进程环境,再叠加翻译结果与显式 env(显式 env 最后覆盖)。
    env: dict[str, str] = {k: v for k, v in os.environ.items()}

    model = conn.get("model") or None
    provider = (conn.get("provider") or "").strip()
    api_key = conn.get("api_key") or None
    base_url = conn.get("base_url") or None

    if model:
        env["LLM_MODEL"] = str(model)
    if provider and api_key:
        env[f"{provider.upper()}_API_KEY"] = str(api_key)
    if provider and base_url:
        env[f"{provider.upper()}_BASE_URL"] = str(base_url)

    for k, v in (launch.get("env") or {}).items():
        # HERMES_HOME 等路径值做 ~ 展开;其余原样(转为 str)。
        env[str(k)] = str(_expand(v) if k == "HERMES_HOME" else v)

    return HermesLaunch(
        command=command,
        args=args,
        cwd=cwd,
        env=env,
        model=str(model) if model else None,
        auto_approve_permissions=bool(conn.get("auto_approve_permissions", True)),
        init_timeout=float(conn.get("init_timeout", DEFAULT_INIT_TIMEOUT)),
        use_unstable_protocol=bool(conn.get("use_unstable_protocol", True)),
    )
