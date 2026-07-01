"""HermesAdapter:`HarnessAdapter` 的第二个实现,经 ACP 驱动 Hermes(能力: harness-adapter)。

架构(与 OpenClaw 的"连接常驻 WS gateway"根本不同):
- 我们 **spawn `hermes-acp` 子进程**(本期 `python -m acp_adapter`,源码集成),并自己担任
  **ACP 客户端**(stdio JSON-RPC)。生命周期 = 子进程的起/停,不是 socket 重连。
- Hermes 无具名常驻 agent:adapter 维护 `(agent, session) → ACP session_id` 的**忠实映射**,
  agent 名永不发给 Hermes;workspace = ACP 会话 cwd(本地目录)。隔离策略由核心层传不同元组决定。
- `execute` 是收集器:`prompt()` 只回 stop_reason,正文/工具/文件经 `session/update` 流入
  `HermesClientSink`(见 collector.py),回合结束组装为中立 `TurnResult`。

经核对的 ACP(agent-client-protocol，安装版 0.10.1)接口:
- 实现侧(我们):`Client.session_update` / `Client.request_permission`(只覆盖这两个回调)。
- 调用侧(conn):`initialize(protocol_version)` / `new_session(cwd)` / `prompt(prompt, session_id, message_id)`
  / `set_session_model(model_id, session_id)` / `cancel(session_id)`。
- 辅助:`spawn_agent_process(to_client, command, *args, env, cwd, **connection_kwargs)`
  (async 上下文 → (ClientSideConnection, Process)、`use_unstable_protocol` 经 connection_kwargs 透传)、
  `text_block(str)`、`PROTOCOL_VERSION`。
- 仅声明 `FILE_EVIDENCE`(cwd 本地,文件证据=本地读写);其余能力缺失,核心按既有路径降级。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from acp import PROTOCOL_VERSION, spawn_agent_process, text_block

from ..base import HarnessAdapter
from ..capabilities import Capability
from ..errors import HarnessExecutionError, HarnessTransportError
from ..types import (
    AgentSpec,
    FileContent,
    TurnResult,
    WorkspaceFile,
    WorkspaceTruth,
)
from .collector import HermesClientSink
from .config import build_launch

logger = logging.getLogger("openclaw_automation")


class HermesAdapter(HarnessAdapter):
    """Hermes harness 的中立适配实现(经 ACP stdio 驱动子进程)。"""

    capabilities = frozenset({Capability.FILE_EVIDENCE})

    def __init__(self, connection: Optional[dict[str, Any]] = None) -> None:
        self._launch = build_launch(dict(connection or {}))
        self._sink = HermesClientSink(auto_approve=self._launch.auto_approve_permissions)
        self._conn: Any = None
        self._proc: Any = None
        self._spawn_cm: Any = None
        self._specs: dict[str, AgentSpec] = {}
        self._sessions: dict[tuple[str, str], str] = {}  # (agent, session) → acp session_id

    # ------------------------------------------------------------------ #
    # 生命周期:起/停子进程 + 握手
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "HermesAdapter":
        lc = self._launch
        logger.info("启动 hermes-acp 子进程: %s %s (cwd=%s)", lc.command, " ".join(lc.args), lc.cwd)
        self._spawn_cm = spawn_agent_process(
            self._sink, lc.command, *lc.args, env=lc.env, cwd=lc.cwd,
            use_unstable_protocol=lc.use_unstable_protocol,
        )
        try:
            self._conn, self._proc = await self._spawn_cm.__aenter__()
            await asyncio.wait_for(
                self._conn.initialize(protocol_version=PROTOCOL_VERSION),
                timeout=lc.init_timeout,
            )
        except Exception as e:  # noqa: BLE001
            await self._safe_close(e)
            raise HarnessTransportError(f"hermes-acp 启动/握手失败: {e}") from e
        logger.info("hermes-acp 就绪")
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._safe_close(exc[1] if len(exc) > 1 else None)

    async def _safe_close(self, exc: Any) -> None:
        if self._spawn_cm is not None:
            try:
                await self._spawn_cm.__aexit__(type(exc) if exc else None, exc, None)
            except Exception:  # noqa: BLE001
                logger.debug("关闭 hermes-acp 子进程异常", exc_info=True)
            finally:
                self._spawn_cm = None
                self._conn = None
                self._proc = None

    # ------------------------------------------------------------------ #
    # 供给:只记账,不调远端
    # ------------------------------------------------------------------ #

    async def ensure_agent(self, spec: AgentSpec) -> None:
        """记录 spec(workspace/model/skills);Hermes 无具名 agent,故不调远端。

        workspace 的建目录 + 铺 skills/config 由核心层 owning;此处仅做防御性 mkdir,
        避免 cwd 不存在导致子进程 chdir/工具执行失败。
        """
        self._specs[spec.name] = spec
        try:
            Path(os.path.expanduser(spec.workspace)).mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            logger.debug("防御性创建 workspace 失败: %s", spec.workspace, exc_info=True)

    def _workspace_of(self, agent: str) -> str:
        spec = self._specs.get(agent)
        return os.path.expanduser(spec.workspace) if spec and spec.workspace else "."

    # ------------------------------------------------------------------ #
    # 执行:收集器模式
    # ------------------------------------------------------------------ #

    async def _resolve_session(self, agent: str, session: str) -> str:
        key = (agent, session)
        sid = self._sessions.get(key)
        if sid is not None:
            return sid
        cwd = self._workspace_of(agent)
        resp = await self._conn.new_session(cwd=cwd)
        sid = resp.session_id
        self._sessions[key] = sid
        # 按 agent spec 落实模型(Hermes 的 new_session 不收 model 参数)。
        spec = self._specs.get(agent)
        model = (spec.model if spec else None) or self._launch.model
        if model:
            try:
                await self._conn.set_session_model(model_id=str(model), session_id=sid)
            except Exception:  # noqa: BLE001
                logger.debug("set_session_model(%s) 失败,沿用默认模型", model, exc_info=True)
        logger.info("新建 Hermes 会话 %s ← (%s, %s) cwd=%s", sid, agent, session, cwd)
        return sid

    async def execute(
        self,
        agent: str,
        session: str,
        query: str,
        *,
        timeout: Optional[int] = None,
    ) -> TurnResult:
        if self._conn is None:
            raise HarnessExecutionError("HermesAdapter 未进入上下文(__aenter__ 未调用)")
        try:
            sid = await self._resolve_session(agent, session)
        except Exception as e:  # noqa: BLE001
            raise HarnessTransportError(f"建立 Hermes 会话失败: {e}") from e

        collector = self._sink.begin(sid)
        try:
            coro = self._conn.prompt(
                prompt=[text_block(query)], session_id=sid, message_id=str(uuid4())
            )
            resp = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)
        except asyncio.TimeoutError as e:
            await self._cancel(sid)
            raise HarnessExecutionError(f"Hermes 单轮超时 ({timeout}s)") from e
        except Exception as e:  # noqa: BLE001
            raise HarnessTransportError(f"Hermes prompt 失败: {e}") from e
        finally:
            self._sink.end(sid)

        stop_reason = getattr(resp, "stop_reason", None)
        return collector.assemble(stop_reason=stop_reason)

    async def _cancel(self, sid: str) -> None:
        try:
            await self._conn.cancel(session_id=sid)
        except Exception:  # noqa: BLE001
            logger.debug("cancel(%s) 失败", sid, exc_info=True)

    # ------------------------------------------------------------------ #
    # 文件证据:cwd 为本地目录 → 纯文件系统
    # ------------------------------------------------------------------ #

    async def read_workspace(self, agent: str) -> WorkspaceTruth:
        root = Path(self._workspace_of(agent))
        files: list[WorkspaceFile] = []
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = None
                    files.append(
                        WorkspaceFile(
                            name=p.relative_to(root).as_posix(), path=str(p), exists=True, size=size
                        )
                    )
        return WorkspaceTruth(workspace_path=str(root), files=files)

    async def get_file(self, agent: str, name: str) -> FileContent:
        path = Path(self._workspace_of(agent)) / name
        if not path.is_file():
            return FileContent(name=name, path=str(path), missing=True)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return FileContent(
                name=name, path=str(path), missing=False, size=path.stat().st_size, content=content
            )
        except OSError as e:
            logger.debug("读取文件失败 %s: %s", path, e)
            return FileContent(name=name, path=str(path), missing=True)

    async def put_file(self, agent: str, dest: str, content: str) -> None:
        path = Path(self._workspace_of(agent)) / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
