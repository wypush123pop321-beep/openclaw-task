"""
DeepSeek-Harness (DSH) 客户端封装 —— 经 Node 桥壳驱动 DSH runtime 子进程。

DSH 的对外 SDK 是 TypeScript 的 `DeepSeekHarness`(@deepseek-ai/dsh-sdk-client),
Python 无法直接 import。本模块通过一个常驻的 Node 桥壳(sdk-bridge.mts,位于 DSH 仓库根)
以「每行一条 JSON」的 stdio 协议驱动它:

    Python DshAgent.execute(query)
      → 写 {"cmd":"run","prompt":..,"sessionId":..} 到桥壳 stdin
      → 桥壳调用 harness.run(prompt,{sessionId}) → DSH runtime 子进程 → LLM
      → 桥壳把 {sessionId, finalResponse} 写回 stdout
      → DshAgent 收敛成 ExecutionResult

关键设计(与 DSH 的能力边界对齐):
- **系统提示词是进程级**:DSH 无 per-run/per-session system 入口,persona 由 cordis
  agent-spine 读环境变量 `DSH_SYSTEM_PROMPT`。因此「每个 agent」独占一个桥进程,
  通过 launch env 注入该 agent 的 system_prompt;同一 agent 的多个 session 共享 persona。
  好处:系统提示词不污染用户消息,轨迹保持纯净(DSH 的核心诉求)。
- **多轮记忆靠 sessionId**:桥进程常驻整个 run,DshAgent 记住首轮返回的 sessionId,
  后续轮带上它 → runtime 复用 session → 会话记忆生效(跨进程重启不保真,故进程常驻)。
- **模型/provider**:provider/model 走桥壳构造(DSH_PROVIDER/DSH_MODEL 环境变量或默认
  deepseek-official/deepseek-v4-flash);base_url/api_key 走 DEEPSEEK_BASE_URL/DEEPSEEK_API_KEY
  环境变量。per-agent override 通过该 agent 桥进程的 env 注入。

公开 API:
  DshClient / DshAgent / ExecutionResult / ExecutionOptions / DshError
  build_dsh_client()
  DshWorkspaceManager / DshAgentManager
  make_dsh_execute_with_retry / make_dsh_get_agent
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.workspace import BaseWorkspaceManager, copy_path
from src.config import AgentModelConfig, warn_agent_model_conflict

logger = logging.getLogger("harness_automation")


# ============================================================================
# 常量 / DSH 仓库定位
# ============================================================================

_DSH_REPO_ENV = "DSH_REPO"
_DSH_REPO_DEFAULT = (
    "/home/w00802407/workspace/0730_prometheus_agents/prometheus_agents/"
    "third_party/deepseek-harness"
)
_DSH_BRIDGE_SCRIPT = "sdk-bridge.mts"

DEFAULT_PROVIDER = "deepseek-official"
DEFAULT_MODEL = "deepseek-v4-flash"
# 输出上限:DSH 的 deepseek 适配器默认 reasoningEffort=high(思维链很长),
# 叠加大体量交付物(如整页 HTML)时 8192 会被截断 → finalResponse 空。放宽到 32768。
DEFAULT_MAX_TOKENS = 32768

EXECUTION_MAX_ATTEMPTS = 5
EXECUTION_RETRY_WAIT_SECONDS = 60

# 桥壳启动握手超时(等 {"event":"ready"});runtime 懒启动 + initialize 握手一般数秒内。
_BRIDGE_READY_TIMEOUT = 120.0


def _dsh_repo() -> Path:
    return Path(os.environ.get(_DSH_REPO_ENV, _DSH_REPO_DEFAULT)).expanduser()


# ============================================================================
# 异常类型
# ============================================================================

class DshError(RuntimeError):
    """DSH 桥壳 / runtime 调用失败。"""


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ExecutionResult:
    success: bool = True
    content: str = ""
    stop_reason: Optional[str] = "complete"
    error_message: Optional[str] = None
    usage: Optional[Dict[str, Any]] = field(default=None)
    session_id: Optional[str] = None

    def model_copy(self, *, update: Optional[Dict[str, Any]] = None) -> "ExecutionResult":
        data = {
            "success": self.success,
            "content": self.content,
            "stop_reason": self.stop_reason,
            "error_message": self.error_message,
            "usage": self.usage,
            "session_id": self.session_id,
        }
        if update:
            data.update(update)
        return ExecutionResult(**data)


@dataclass
class ExecutionOptions:
    timeout_seconds: Optional[int] = None


# ============================================================================
# _DshBridgeProcess —— 一个常驻 Node 桥进程(= 一个 DeepSeekHarness/runtime 子进程)
# ============================================================================

class _DshBridgeProcess:
    """封装一个 `npx tsx sdk-bridge.mts` 子进程,串行地发 run / close。

    一个桥进程绑定一份 env(含该 agent 的 DSH_SYSTEM_PROMPT / 模型 / provider 凭据),
    内部按 sessionId 多路复用多轮会话。请求是串行的(管线本身顺序执行)。
    """

    def __init__(
        self,
        *,
        cwd: Path,
        env: Dict[str, str],
        request_timeout_ms: Optional[int] = None,
    ):
        self._repo = _dsh_repo()
        self._cwd = cwd
        self._env = env
        self._request_timeout_ms = request_timeout_ms
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0
        self._lock = asyncio.Lock()
        self._stderr_task: Optional[asyncio.Task] = None

    async def _ensure_started(self) -> asyncio.subprocess.Process:
        if self._proc is not None and self._proc.returncode is None:
            return self._proc

        bridge = self._repo / _DSH_BRIDGE_SCRIPT
        if not bridge.is_file():
            raise DshError(f"DSH 桥壳脚本不存在: {bridge}(检查 {_DSH_REPO_ENV})")

        # 优先用 DSH 仓库内已安装的 tsx(避免 npx 联网下载);回退 `npx tsx`。
        vendored_tsx = self._repo / "node_modules" / ".bin" / "tsx"
        if vendored_tsx.is_file():
            argv = [str(vendored_tsx), str(bridge)]
        else:
            argv = ["npx", "tsx", str(bridge)]

        child_env = os.environ.copy()
        child_env.update(self._env)
        # 桥壳自身也读这些定位变量(默认已能推断,这里显式钉死)
        child_env.setdefault("DSH_REPO", str(self._repo))
        # DSH runtime cwd = 该 agent 的 workspace(sandbox 文件读写落点)
        child_env["DSH_CWD"] = str(self._cwd)
        if self._request_timeout_ms is not None:
            child_env["DSH_REQUEST_TIMEOUT_MS"] = str(self._request_timeout_ms)

        logger.debug(
            "启动 DSH 桥进程: cwd=%s persona=%r model=%r provider=%r",
            self._cwd,
            (self._env.get("DSH_SYSTEM_PROMPT") or "")[:60],
            self._env.get("DSH_MODEL"),
            self._env.get("DSH_PROVIDER"),
        )
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._repo),
            env=child_env,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        # 等 ready 事件
        try:
            line = await asyncio.wait_for(
                self._proc.stdout.readline(), timeout=_BRIDGE_READY_TIMEOUT
            )
        except asyncio.TimeoutError as e:
            await self._kill()
            raise DshError("DSH 桥壳启动超时(未收到 ready)") from e
        if not line:
            await self._kill()
            raise DshError("DSH 桥壳启动即退出(stdout EOF,见 stderr 日志)")
        try:
            ev = json.loads(line.decode("utf-8").strip())
        except Exception as e:
            await self._kill()
            raise DshError(f"DSH 桥壳首行非法 JSON: {line!r}") from e
        if ev.get("event") == "error":
            await self._kill()
            raise DshError(f"DSH 桥壳启动失败: {ev.get('error')}")
        if ev.get("event") != "ready":
            logger.warning("DSH 桥壳首行非 ready(继续): %s", ev)
        logger.info("DSH 桥进程就绪 (cwd=%s)", self._cwd)
        return self._proc

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                logger.debug("[dsh-bridge stderr] %s", line.decode("utf-8", "replace").rstrip())
        except Exception:  # noqa: BLE001
            pass

    async def run(
        self,
        prompt: str,
        session_id: Optional[str],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发一条 run 请求,返回桥壳响应 dict({ok, sessionId, finalResponse} 或 {ok:false,error})。"""
        async with self._lock:
            proc = await self._ensure_started()
            self._req_id += 1
            req = {"id": self._req_id, "cmd": "run", "prompt": prompt}
            if session_id:
                req["sessionId"] = session_id
            proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
            await proc.stdin.drain()

            async def _read_resp() -> Dict[str, Any]:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        raise DshError("DSH 桥壳 stdout EOF(子进程退出)")
                    s = line.decode("utf-8").strip()
                    if not s:
                        continue
                    obj = json.loads(s)
                    # 忽略非本请求的事件行(理论上不会有,串行协议)
                    if obj.get("id") == self._req_id or "ok" in obj:
                        return obj

            try:
                if timeout is not None:
                    return await asyncio.wait_for(_read_resp(), timeout=timeout)
                return await _read_resp()
            except asyncio.TimeoutError:
                # 超时:该桥进程状态不可信,杀掉以便下次重启
                await self._kill()
                raise

    async def close(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        if proc.returncode is None:
            try:
                self._req_id += 1
                proc.stdin.write(
                    (json.dumps({"id": self._req_id, "cmd": "close"}) + "\n").encode()
                )
                await proc.stdin.drain()
                await asyncio.wait_for(proc.wait(), timeout=8.0)
            except Exception:  # noqa: BLE001
                await self._kill()
        self._proc = None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None

    async def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:  # noqa: BLE001
            pass


# ============================================================================
# DshAgent —— 一个 (agent_name, session_name) 句柄
# ============================================================================

class DshAgent:
    """对应一个 agent_name + session_name。

    - 复用所属 agent 的常驻桥进程(同 agent 同 persona)。
    - 记住 DSH 侧的 sessionId(首轮 None → runtime 铸新;后续复用 → 多轮记忆)。
    """

    def __init__(
        self,
        client: "DshClient",
        agent_name: str,
        session_name: str,
        bridge: _DshBridgeProcess,
    ):
        self._client = client
        self.agent_name = agent_name
        self.session_name = session_name
        self.session_id = session_name        # 管线侧标识(与 hermes/claudecode 对齐)
        self.session_key = session_name
        self._bridge = bridge
        self._dsh_session_id: Optional[str] = None   # DSH runtime 侧真实 sessionId
        self._history: List[Dict[str, Any]] = []

    async def execute(
        self,
        query: str,
        options: Optional[ExecutionOptions] = None,
    ) -> ExecutionResult:
        timeout = (
            float(options.timeout_seconds)
            if options and options.timeout_seconds
            else None
        )
        try:
            resp = await self._bridge.run(query, self._dsh_session_id, timeout=timeout)
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False, content="", stop_reason="timeout",
                error_message=f"DSH run timed out after {timeout}s",
            )
        except DshError as e:
            logger.exception("DSH 桥壳调用失败 (agent=%s session=%s)", self.agent_name, self.session_name)
            return ExecutionResult(
                success=False, content="", stop_reason="error", error_message=str(e),
            )

        if not resp.get("ok"):
            return ExecutionResult(
                success=False, content="", stop_reason="error",
                error_message=str(resp.get("error") or "DSH bridge returned ok=false"),
            )

        # 记住 runtime 侧 sessionId,后续轮复用 → 多轮记忆
        new_sid = resp.get("sessionId")
        if new_sid:
            self._dsh_session_id = new_sid
        content = (resp.get("finalResponse") or "").strip()
        if content:
            self._history.append({"role": "user", "content": query})
            self._history.append({"role": "assistant", "content": content})
        return ExecutionResult(
            success=True,
            content=content,
            stop_reason="complete",
            session_id=new_sid,
        )


# ============================================================================
# DshClient —— 进程内 client,按 agent_name 缓存桥进程,按 (agent,session) 缓存 DshAgent
# ============================================================================

class DshClient:
    """DSH 进程内客户端。

    每个 agent_name 一个常驻桥进程(独立 persona/模型 env);
    每个 (agent_name, session_name) 一个 DshAgent(复用该 agent 的桥进程)。
    """

    def __init__(self) -> None:
        self._agents: Dict[tuple, DshAgent] = {}
        self._bridges: Dict[str, _DshBridgeProcess] = {}
        self._agent_defaults: Dict[str, Dict[str, Any]] = {}

    async def __aenter__(self) -> "DshClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        for br in list(self._bridges.values()):
            try:
                await br.close()
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as e:  # noqa: BLE001
                logger.debug("DSH 桥进程 close 异常(忽略): %s", e)
        self._bridges.clear()
        self._agents.clear()

    def register_agent_defaults(
        self,
        agent_name: str,
        *,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        max_tokens: Optional[int] = None,
        cwd: Optional[Path] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._agent_defaults[agent_name] = {
            "system_prompt": system_prompt,
            "model": model,
            "provider": provider,
            "max_tokens": max_tokens,
            "cwd": cwd,
            "base_url": base_url,
            "api_key": api_key,
        }

    def _get_bridge(self, agent_name: str, cwd: Path) -> _DshBridgeProcess:
        if agent_name in self._bridges:
            return self._bridges[agent_name]

        d = self._agent_defaults.get(agent_name, {})
        env: Dict[str, str] = {}
        if d.get("system_prompt"):
            env["DSH_SYSTEM_PROMPT"] = d["system_prompt"]
        if d.get("model"):
            env["DSH_MODEL"] = d["model"]
        if d.get("provider"):
            env["DSH_PROVIDER"] = d["provider"]
        if d.get("max_tokens"):
            env["DSH_MAX_TOKENS"] = str(d["max_tokens"])
        # per-agent 模型端点覆盖(如 evaluator 走不同 provider):落到 DSH_deepseek 适配器读的 env
        if d.get("base_url"):
            env["DEEPSEEK_BASE_URL"] = d["base_url"]
        if d.get("api_key"):
            env["DEEPSEEK_API_KEY"] = d["api_key"]

        bridge = _DshBridgeProcess(cwd=cwd, env=env)
        self._bridges[agent_name] = bridge
        return bridge

    def get_agent(
        self,
        agent_name: str,
        session_name: str,
        *,
        cwd: Optional[Path] = None,
    ) -> DshAgent:
        key = (agent_name, session_name)
        if key in self._agents:
            return self._agents[key]
        d = self._agent_defaults.get(agent_name, {})
        eff_cwd = cwd or d.get("cwd") or _dsh_repo()
        bridge = self._get_bridge(agent_name, Path(eff_cwd))
        agent = DshAgent(self, agent_name, session_name, bridge)
        self._agents[key] = agent
        return agent


# ============================================================================
# 工厂函数
# ============================================================================

async def build_dsh_client() -> DshClient:
    client = DshClient()
    logger.info(
        "DSH 客户端就绪(经 Node 桥壳 %s 驱动 DeepSeekHarness runtime);"
        "DSH 仓库=%s。需要 node/pnpm 且 DSH 已 build。",
        _DSH_BRIDGE_SCRIPT, _dsh_repo(),
    )
    return client


# ============================================================================
# DshWorkspaceManager
# ============================================================================

class DshWorkspaceManager(BaseWorkspaceManager):
    """DSH 工作空间管理器: workspace 作为 runtime 子进程的 cwd(agent 在此读写文件)。"""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_agent_workspace(self, agent_name: str) -> Path:
        if agent_name == "main":
            workspace = self.base_dir
        else:
            parent = self.base_dir.parent
            base_name = self.base_dir.name
            workspace = parent / f"{base_name}-{agent_name}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _copy_agent_configs(
        self,
        workspace: Path,
        config_files: List[str],
        agent_dir: str,
    ) -> None:
        # DSH 的 persona 走 DSH_SYSTEM_PROMPT,不消费 SOUL.md/USER.md;
        # 但仍把 agent 配置文件复制进 workspace(best-effort,便于 agent 用工具读取)。
        agent_source = Path(agent_dir).expanduser()
        if not agent_source.exists():
            logger.debug("DSH: agent 源目录不存在(忽略): %s", agent_source)
            return
        for config_file in config_files:
            src = agent_source / config_file
            if src.exists():
                dst = workspace / config_file
                copy_path(src, dst)
                logger.info("复制 Agent 配置: %s -> %s", config_file, dst)
            else:
                logger.debug("DSH: Agent 配置文件不存在(忽略): %s", src)


# ============================================================================
# DshAgentManager
# ============================================================================

class DshAgentManager:
    """DSH Agent 管理器: 把 AgentConfigItem → DshClient 默认参数(persona/model/cwd)。"""

    def __init__(
        self,
        client: DshClient,
        workspace_manager: DshWorkspaceManager,
        agent_overrides: Optional[Dict[str, AgentModelConfig]] = None,
    ):
        self.client = client
        self.workspace_manager = workspace_manager
        self.agent_overrides: Dict[str, AgentModelConfig] = agent_overrides or {}

    async def setup_agent(self, agent_config) -> None:
        agent_name = agent_config.name
        override = self.agent_overrides.get(agent_name)
        if override:
            warn_agent_model_conflict(agent_name, agent_config.model, override)
        if agent_config.model:
            logger.info("设置 Agent: %s | model=%s", agent_name, agent_config.model)
        else:
            logger.info("设置 Agent: %s", agent_name)
        workspace = self.workspace_manager.get_agent_workspace(agent_name)

        # 关键:DSH 的 str-replace-editor 等文件工具**只接受绝对路径**,而模型并不知道
        # runtime 的 cwd(工作目录),会浪费思维链去猜 "." / "/repo",导致建错位置或空转。
        # 因此在 persona 里显式告知绝对工作目录,并给出写文件的绝对路径范例。
        base_prompt = getattr(agent_config, "system_prompt", None) or ""
        cwd_hint = (
            f"\n\n[运行环境] 你的工作目录(绝对路径)= {workspace}。"
            f"str-replace-editor 等文件工具要求绝对路径:创建/查看/编辑文件时,"
            f"path 必须是该目录下的绝对路径(例如 {workspace}/index.html),"
            f"不要使用相对路径 \".\" 或猜测其它目录。所有交付物请写入该目录。"
            f"请尽量用一次 create 直接写出完整文件,不要反复试探路径或过度推敲,"
            f"以免耗尽输出预算导致产物截断。"
        )
        system_prompt = (base_prompt + cwd_hint) if base_prompt else cwd_hint.lstrip()

        # 模型解析:override(simulator_config)优先,其次 agent_config.model,再退默认。
        model = DEFAULT_MODEL
        provider = None
        base_url = None
        api_key = None
        if getattr(agent_config, "model", None):
            model = agent_config.model
        if override:
            if override.model:
                model = override.model
            if override.provider:
                provider = override.provider
            if override.base_url:
                base_url = override.base_url
            if override.api_key:
                api_key = override.api_key

        self.client.register_agent_defaults(
            agent_name=agent_name,
            system_prompt=system_prompt,
            model=model,
            provider=provider,
            max_tokens=DEFAULT_MAX_TOKENS,
            cwd=workspace,
            base_url=base_url,
            api_key=api_key,
        )


# ============================================================================
# make_dsh_execute_with_retry —— 供 src.executor.execute_queries 注入
# ============================================================================

def make_dsh_execute_with_retry(client: DshClient):
    """返回 dsh 专用的 execute_with_retry 闭包(简单重试,无 history fallback)。

    返回 `(result, evidence_incomplete)`,签名与其它 harness 对齐。
    """

    async def execute_with_retry(agent: DshAgent, query_text: str, options):
        last_exc: Optional[BaseException] = None
        for attempt in range(1, EXECUTION_MAX_ATTEMPTS + 1):
            try:
                result = await agent.execute(query_text, options=options)
                if result is None:
                    raise DshError("DSH returned None")
                if result.success and result.content:
                    evidence_incomplete = (result.stop_reason or "complete") != "complete"
                    return result, evidence_incomplete
                if not result.success:
                    raise DshError(result.error_message or "DSH returned error")
                raise DshError("DSH returned empty content")
            except (DshError, asyncio.TimeoutError) as e:
                last_exc = e
                if attempt >= EXECUTION_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "DSH 调用失败 (第 %d/%d 次): %s; %ds 后重试",
                    attempt, EXECUTION_MAX_ATTEMPTS, e, EXECUTION_RETRY_WAIT_SECONDS,
                )
                await asyncio.sleep(EXECUTION_RETRY_WAIT_SECONDS)
        if last_exc is not None:
            raise last_exc
        raise DshError("DSH: unknown error after retries")

    return execute_with_retry


def make_dsh_get_agent(
    client: DshClient,
    workspace_manager: Optional[DshWorkspaceManager] = None,
):
    """返回 dsh 专用的 get_agent_fn 闭包(cwd 由 workspace_manager 注入)。"""

    def get_agent(agent_name: str, session_name: str) -> DshAgent:
        cwd = (
            workspace_manager.get_agent_workspace(agent_name)
            if workspace_manager is not None
            else None
        )
        return client.get_agent(agent_name, session_name, cwd=cwd)

    return get_agent
