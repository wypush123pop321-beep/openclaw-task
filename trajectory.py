"""逐轮轨迹证据捕获(能力: trajectory-capture)。

在多轮对话执行中,为每个 turn 留存 agent 的可核验证据:
- `tool_calls`(由调用方经 `adapter.fetch_history` 取数后用 `extract_tool_calls` 解析传入;
  harness 原生 `TurnResult.tool_calls` 对服务端自主 agent 恒空)
- 生成文件(以 `adapter.read_workspace/get_file(被测 agent)` 读取的**磁盘真相**为准,
  而非采信 `TurnResult.files` 自报)
并标注证据完整性:经 `history_fallback` 兜底、只剩文本的 turn 标 `evidence_incomplete`。

本模块只依赖中立 `harness` 接口与类型,不直接 import 任何具体 harness SDK,也不依赖
openclaw_automation(避免循环导入)。中立证据类型 `ToolCallEvidence`/`FileEvidence`
收敛于 `harness.types`,本模块重导出以保持既有 import 不破。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from harness import Capability, HarnessAdapter
from harness.types import FileEvidence, ToolCallEvidence, TurnResult

logger = logging.getLogger("openclaw_automation")

# OpenClaw 新建 agent 时铺设的脚手架文件;发现工作区新产物时排除这些,
# 以便把 agent 本轮真正"创建"的文件 surface 给 evaluator。
SCAFFOLDING_FILES = {
    "AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md",
    "HEARTBEAT.md", "BOOTSTRAP.md", "MEMORY.md", "CLAUDE.md",
}


# ============================================================================
# 轨迹模型(证据类型 ToolCallEvidence/FileEvidence 自 harness.types 重导出于顶部)
# ============================================================================

class TurnRecord(BaseModel):
    """单个 turn 的执行记录。"""
    turn: int
    user_input: str
    agent_content: str
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    files: list[FileEvidence] = Field(default_factory=list)
    stop_reason: Optional[str] = None
    evidence_incomplete: bool = False


class Trajectory(BaseModel):
    """一个 query 的完整运行记录(可落盘为 RL 样本:轨迹 + 各评审点评分)。"""
    query: str
    agent_name: str
    turns: list[TurnRecord] = Field(default_factory=list)
    outcome: Optional[str] = None  # "done" | "failed" | "max_turn"
    # 各评审点的评分结果(逐条 0/1、gate 状态、分桶得分、completion(0~1)、所在 turn);终局评审点的 completion 即最终成绩
    evaluations: list[dict] = Field(default_factory=list)

    def save(self, path: Any) -> None:
        """把完整轨迹(含 turns/tool_calls/产物指针/outcome/evaluations)序列化落盘为 JSON。

        跑完即留,供离线查阅与 RL 训练样本使用(能力: trajectory-persistence)。
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    def render_full(self, exclude_last: bool = False) -> str:
        """渲染历轮全文,供 evaluator 审阅(D4: 全文,不压缩摘要)。"""
        turns = self.turns[:-1] if exclude_last else self.turns
        if not turns:
            return "（暂无历史轮次）"
        return "\n\n".join(_render_turn(t) for t in turns)

    def render_recent(self, window: int) -> str:
        """渲染最近 window 轮的轨迹(压缩版:保留 tool_calls,文件仅给指针不内联全文)。
        建议window = eval_step, 正好覆盖两次评审之间的全部 turn,不留上下文空洞。
        """
        turns = self.turns[-window:] if window and window > 0 else self.turns
        if not turns:
            return "（暂无轮次）"
        return "\n\n".join(_render_turn_compact(t) for t in turns)

    def generated_file_pointers(self) -> list[dict]:
        """累积全部产物的指针 {filename, workspace_path}(去重按 name,后出现覆盖)。

        产物指针覆盖整段对话(非仅最近 X 轮)——避免 reset 后窗口外早期产物丢失;
        evaluator 据指针用自身工具打开核验,而非凭文件名臆断。
        """
        seen: dict[str, Optional[str]] = {}
        for t in self.turns:
            for f in t.files:
                if f.checked and f.exists:
                    seen[f.name] = f.path
        return [{"filename": n, "workspace_path": p} for n, p in seen.items()]


def _render_turn(t: TurnRecord) -> str:
    lines = [f"── Turn {t.turn} ──", f"[用户]: {t.user_input}", f"[Agent]: {t.agent_content}"]
    if t.tool_calls:
        lines.append("[工具调用]:")
        for tc in t.tool_calls:
            out = (tc.output or "")[:2000]
            lines.append(f"  - {tc.tool}(input={_fmt_input(tc.input, 500)}) -> {out}")
    if t.files:
        lines.append("[文件证据(磁盘真相)]:")
        for f in t.files:
            src = "工作区发现" if f.discovered else "agent 自报"
            sz = f" size={f.size}" if f.size is not None else ""
            if not f.checked:
                lines.append(f"  - {f.name}: (未核验,仅声称)")
            elif f.exists and f.content is not None:
                preview = f.content[:2000]
                lines.append(f"  - {f.name}: 存在 ✓ [{src}{sz}]\n{preview}")
            elif f.exists:
                lines.append(f"  - {f.name}: 存在 ✓ [{src}{sz}](内容未取到,以存在性为准)")
            elif f.error:
                lines.append(f"  - {f.name}: 核验受阻({f.error})→ 证据缺失,不得当负面证据")
            else:
                lines.append(f"  - {f.name}: 声称生成,但磁盘上不存在 ✗")
    if t.stop_reason:
        lines.append(f"[stop_reason]: {t.stop_reason}")
    if t.evidence_incomplete:
        lines.append("[注意]: 本轮证据不完整(经 history 兜底恢复)——证据缺失 ≠ 证据为负")
    return "\n".join(lines)


def _render_turn_compact(t: TurnRecord) -> str:
    """压缩渲染单轮:保留 tool_calls(反幻觉底线),但文件**不内联全文**——
    产物以指针(由 `Trajectory.generated_file_pointers` 统一汇总)交给 evaluator 用工具自查。
    """
    lines = [f"── Turn {t.turn} ──", f"[用户]: {t.user_input}", f"[Agent]: {t.agent_content}"]
    if t.tool_calls:
        lines.append("[工具调用]:")
        for tc in t.tool_calls:
            out = (tc.output or "")[:800]
            lines.append(f"  - {tc.tool}(input={_fmt_input(tc.input, 300)}) -> {out}")
    if t.files:
        # 仅列出本轮涉及的产物名(指针清单另行统一给出),不贴内容
        names = ", ".join(f.name for f in t.files)
        lines.append(f"[本轮产物]: {names}")
    if t.stop_reason:
        lines.append(f"[stop_reason]: {t.stop_reason}")
    if t.evidence_incomplete:
        lines.append("[注意]: 本轮证据不完整(经 history 兜底恢复)——证据缺失 ≠ 证据为负")
    return "\n".join(lines)


# ============================================================================
# 捕获辅助
# ============================================================================

def _normalize_input(args: Any) -> Any:
    """把工具入参归一为**原生 JSON**:

    - dict/list:原样保留(落盘即为嵌套 JSON,不再 `json.dumps` 成转义字符串);
    - 形如 JSON 的字符串(以 `{`/`[` 开头):尝试 `json.loads` 解析回对象,失败则保留原字符串;
    - 其余(纯文本命令、数字等):原值返回;None → 空字符串。
    """
    if args is None:
        return ""
    if isinstance(args, (dict, list)):
        return args
    if isinstance(args, str):
        s = args.strip()
        if s and s[0] in "{[":
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return args
        return args
    return args


def _fmt_input(val: Any, limit: int) -> str:
    """把 `input`(原生 JSON 或字符串)渲染为带长度上限的字符串,供轨迹文本预览。"""
    s = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    return s[:limit]


def _strip_nul(s: Optional[str]) -> Optional[str]:
    """剥离空字节 `\\x00`(U+0000)。

    二进制产物(如 .xlsx)的工具返回/文件内容可能混入原始 NUL,而它属合法
    UTF-8,`errors="replace"` 不会过滤;若随证据流入评估 prompt,会被模型网关
    以 "message must not contain null bytes" 拒收。统一在采集咽喉点剥离。
    """
    return s.replace("\x00", "") if s else s


def _block_text(content: Any) -> str:
    """把 OC 消息的 content(块数组或字符串)拍平为纯文本(并剥离 NUL)。"""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
        text = "".join(parts)
    else:
        text = "" if content is None else str(content)
    return _strip_nul(text)


def extract_tool_calls(messages: list[dict[str, Any]]) -> list[ToolCallEvidence]:
    """从 OC `chat_history` 消息解析工具调用证据(能力: trajectory-capture)。

    OC 结构:`role==assistant` 的 `content` 块中 `type=="toolCall"`(含 `id`/`name`/
    `arguments`)为一次调用;`role=="toolResult"` 消息(含 `toolCallId`/`toolName`/
    `content`/`isError`)为其返回。按 `id`↔`toolCallId` 配对,保持调用出现顺序。

    入参 messages 应为**本轮新增**的消息子集(增量截取由调用方负责)。
    SDK 的 `ExecutionResult.tool_calls` 对服务端自主 agent 恒空,故采集改以本函数为准。
    """
    # 1. 按 toolCallId 索引所有 toolResult
    results_by_id: dict[str, dict[str, Any]] = {}
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "toolResult":
            cid = m.get("toolCallId")
            if cid:
                results_by_id[cid] = m
    # 2. 顺序遍历 assistant 消息里的 toolCall 块,配对其结果
    calls: list[ToolCallEvidence] = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "toolCall":
                continue
            cid = block.get("id")
            name = block.get("name") or block.get("toolName") or ""
            input_val = _normalize_input(block.get("arguments"))
            output: Optional[str] = None
            res = results_by_id.get(cid) if cid else None
            if res is not None:
                output = _block_text(res.get("content"))
                if res.get("isError"):
                    output = f"[error] {output}"
            calls.append(ToolCallEvidence(tool=name, input=input_val, output=output))
    return calls


def build_turn_record(
    turn: int,
    user_input: str,
    result: TurnResult,
    evidence_incomplete: bool,
    tool_calls: Optional[list[ToolCallEvidence]] = None,
) -> TurnRecord:
    """从中立 `TurnResult` 构建 TurnRecord(纯内存,不触网)。

    tool_calls 优先取调用方经 `adapter.fetch_history` + `extract_tool_calls` 解析的结果;
    未提供时回退 `TurnResult.tool_calls`(对服务端自主 agent 恒空,仅作兼容)。
    files 仅记录声称的文件名(checked=False),磁盘真相由 `capture_file_evidence` 补齐。
    """
    if tool_calls is None:
        tool_calls = [
            ToolCallEvidence(
                tool=tc.tool,
                input=_normalize_input(tc.input),
                output=tc.output,
                duration_ms=tc.duration_ms,
            )
            for tc in (result.tool_calls or [])
        ]
    files = [FileEvidence(name=(gf.name or gf.path or "")) for gf in (result.files or [])]  # gf = generated_file
    return TurnRecord(
        turn=turn,
        user_input=user_input,
        agent_content=result.content or "",
        tool_calls=tool_calls,
        files=files,
        stop_reason=result.stop_reason,
        evidence_incomplete=evidence_incomplete,
    )


def _read_local(path: Optional[str]) -> Optional[str]:
    """同机时按绝对路径直读磁盘内容(agents.files.get 对用户新建文件有白名单限制时的回退)。"""
    if not path:
        return None
    try:
        p = Path(path)
        if p.is_file():
            return _strip_nul(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        logger.debug("本地读盘失败 %s: %s", path, e)
    return None


async def _resolve_file_evidence(
    adapter: HarnessAdapter,
    agent_id: str,
    fe: FileEvidence,
    inventory: dict[str, dict],
    workspace_path: Optional[str],
) -> None:
    """把单个 FileEvidence 解析为磁盘真相。

    取证优先级:
    1. `adapter.get_file`(可移植、可跨 agent;但本网关对用户新建文件有白名单限制);
    2. 同机按绝对路径读盘(get 读不到用户文件时的真相来源);
    3. 工作区清点的存在性(白名单可见但内容读不到时)。
    全部受阻才降级为 error(证据缺失,不得判负);adapter 明确报"缺失"则权威判 exists=False
    (用于拆穿"声称生成但磁盘无此文件")。
    """
    info = inventory.get(fe.name)
    if info is not None:
        fe.size = info.get("size")
        fe.path = info.get("path")
    fe.checked = True

    get_missing = False
    get_error: Optional[str] = None
    try:
        parsed = await adapter.get_file(agent_id, fe.name)
        if not parsed.missing and parsed.content is not None:
            fe.exists = True
            fe.content = _strip_nul(parsed.content)
            return
        get_missing = True  # adapter 权威:该文件缺失
    except Exception as e:  # noqa: BLE001
        get_error = str(e)  # get 不支持该文件 / adapter 异常

    # 同机读盘回退
    local_path = (info.get("path") if info else None) or (
        str(Path(workspace_path) / fe.name) if workspace_path else None
    )
    if fe.path is None:
        fe.path = local_path
    content = _read_local(local_path)
    if content is not None:
        fe.exists = True
        fe.content = content
        if fe.size is None and local_path:
            try:
                fe.size = Path(local_path).stat().st_size
            except Exception:  # noqa: BLE001
                pass
        return

    if info is not None:  # 白名单可见但内容读不到 → 以存在性为准
        fe.exists = bool(info.get("exists"))
        return

    if get_missing:  # 网关权威缺失 → 拆穿声称
        fe.exists = False
    else:  # 既读不到也无法判定 → 降级为证据缺失(不判负)
        fe.exists = False
        fe.error = get_error or "文件不可达/无法核验"
        logger.debug("capture_file_evidence 取证受阻 %s/%s: %s", agent_id, fe.name, get_error)


async def capture_file_evidence(
    adapter: HarnessAdapter, agent_id: str, record: TurnRecord, *, discover: bool = True
) -> None:
    """就地把 record.files 升级为磁盘真相,并主动清点工作区发现 agent 新建文件。

    D5 落实:不采信 `TurnResult.files` 自报(常为空)。流程:
    1. `adapter.read_workspace` 取被测工作区**路径**与白名单文件清单;
    2. 升级 agent 自报的文件证据(get → 同机读盘 → 清点);
    3. `discover=True` 时**直接扫描本地工作区目录**(主动去发现 agent 未自报的新文件)。

    当 adapter 不具备 `FILE_EVIDENCE` 能力时,跳过磁盘核验(按"证据不完整"语义降级),
    MUST NOT 报错中断。取证受阻一律降级为证据缺失,MUST NOT 当负面证据(由下游 evaluator 规则保证)。
    """
    # 能力降级:缺文件证据能力 → 跳过磁盘核验,record.files 保持"仅声称"(checked=False)
    if Capability.FILE_EVIDENCE not in getattr(adapter, "capabilities", frozenset()):
        logger.debug("adapter 无 FILE_EVIDENCE 能力,跳过文件取证(证据不完整降级)")
        return

    inventory: dict[str, dict] = {}
    workspace_path: Optional[str] = None
    if discover:
        try:
            truth = await adapter.read_workspace(agent_id)
            workspace_path = truth.workspace_path
            for wf in (truth.files or []):
                nm = wf.name or wf.path or ""
                if not nm:
                    continue
                inventory[nm] = {
                    "exists": bool(wf.exists),  # adapter 会判断对应文件是否存在,避免虚假声称
                    "size": wf.size,
                    "path": wf.path,
                }
        except Exception as e:  # noqa: BLE001
            logger.debug("read_workspace 不可用,降级为仅核验自报文件: %s", e)

    # 2. 升级 agent 自报的文件
    for fe in record.files:
        await _resolve_file_evidence(adapter, agent_id, fe, inventory, workspace_path)

    # 3. 直接扫描本地工作区目录,发现用户新建产物(网关 list 受白名单限制看不到)
    if discover and workspace_path:
        claimed = {fe.name for fe in record.files}
        try:
            for child in sorted(Path(workspace_path).iterdir()):
                if not child.is_file():
                    continue
                nm = child.name
                if nm in claimed or nm in SCAFFOLDING_FILES:
                    continue
                fe = FileEvidence(name=nm, discovered=True, checked=True, exists=True, path=str(child))
                try:
                    fe.size = child.stat().st_size
                except Exception:  # noqa: BLE001
                    pass
                fe.content = _read_local(str(child))
                record.files.append(fe)
        except Exception as e:  # noqa: BLE001
            logger.debug("本地工作区清点失败 %s: %s", workspace_path, e)
