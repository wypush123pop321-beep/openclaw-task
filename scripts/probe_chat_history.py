# -*- coding: utf-8 -*-
"""任务 1.1 探针:确认 OC chat_history 是否承载 tool_use/tool_result,并 dump 原始结构。

做法:连本地 gateway → 建临时 agent → 发一条必然触发工具调用的指令(建文件+读文件)
→ 同时取 ExecutionResult.tool_calls(SDK 直采,预期空)与 chat_history(服务端权威),
→ 落盘 history 原始 JSON 并打印每条消息的 role/content 块类型,据此判断方向1可行性。
"""
import asyncio
import json
from pathlib import Path

from openclaw_sdk import OpenClawClient, AgentConfig, ExecutionOptions

GW = "ws://127.0.0.1:18789/gateway"
AGENT = "probe_toolcall"
SESSION = "probe_session"


async def main():
    client = await OpenClawClient.connect(gateway_ws_url=GW)
    ws = str(Path.home() / ".openclaw" / f"workspace-{AGENT}")

    ids = {a.agent_id for a in await client.list_agents()}
    if AGENT not in ids:
        await client.create_agent(AgentConfig(agent_id=AGENT, workspace=ws), workspace=ws)
        print(f"创建临时 agent {AGENT},等待 gateway 就绪...")
        await asyncio.sleep(6)

    agent = client.get_agent(AGENT, SESSION)
    q = ("请在你当前的工作目录里创建一个文件 probe.txt,内容写一行 hello-probe,"
         "然后用工具读取这个文件,把读到的内容原样回复给我。")
    result = await agent.execute(q, options=ExecutionOptions(timeout_seconds=180))

    print("=" * 60)
    print("ExecutionResult.tool_calls (SDK 实时事件流直采):",
          len(result.tool_calls or []), "条")
    print("ExecutionResult.content_blocks 类型:",
          [b.type for b in (result.content_blocks or [])])
    print("stop_reason:", result.stop_reason)
    print("content[:120]:", (result.content or "")[:120])

    msgs = await client.gateway.chat_history(agent.session_key, limit=100)
    out = Path("logs/probe_chat_history.json")
    out.write_text(json.dumps(msgs, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print("=" * 60)
    print("chat_history 消息数:", len(msgs), "| 原始结构已落盘:", out)
    tool_hit = 0
    for i, m in enumerate(msgs):
        role = m.get("role")
        content = m.get("content")
        ctypes = []
        if isinstance(content, list):
            ctypes = [b.get("type") for b in content if isinstance(b, dict)]
            tool_hit += sum(1 for t in ctypes if t and "tool" in str(t).lower())
        elif isinstance(content, str):
            ctypes = ["<str>"]
        # 同时看消息顶层是否有 toolName/tool/name 之类字段
        extra = {k: m.get(k) for k in ("type", "toolName", "tool", "name") if k in m}
        print(f"[{i}] role={role} top_keys={list(m.keys())} block_types={ctypes} extra={extra}")

    print("=" * 60)
    print(f"判定:content 块中出现 tool 相关类型共 {tool_hit} 处 → "
          f"{'方向1可行(history 含工具步骤)' if tool_hit else '历史疑似不含工具步骤,需看落盘 JSON 细节/走降级'}")


if __name__ == "__main__":
    asyncio.run(main())
