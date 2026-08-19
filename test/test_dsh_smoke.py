"""
DSH 适配器「无真实 API」集成冒烟。

在 openclaw-task 容器内运行(有 pydantic + node);LLM 指向 llm-mock-server。
验证 src/dsh_client.py 的新代码路径:构建 client → 注册 agent → get_agent →
execute() 走通 Python↔bridge↔runtime↔mock 全链路 → 拿到 ExecutionResult → close。

mock 返回的是通用 OpenAI SSE,DeepSeek 适配器不完全解析成终结内容,故 content 可能为空——
这是 mock 的 schema 局限,不是集成缺陷。本测试只断言:链路无崩溃、ok=True、拿到 sessionId。
真实 API 下 content 会正常回填(见真机 bridge 验证)。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dsh_client import (
    build_dsh_client, DshAgentManager, DshWorkspaceManager,
    make_dsh_get_agent, ExecutionOptions,
)


class _AgentCfg:
    def __init__(self, name, system_prompt=None, model=None):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model


async def main():
    ws = DshWorkspaceManager("/tmp/dsh_smoke_pipeline_ws")
    client = await build_dsh_client()
    async with client:
        mgr = DshAgentManager(client, ws, agent_overrides={})
        await mgr.setup_agent(_AgentCfg("assistant1", system_prompt="你是简洁的助手。", model="deepseek-v4-flash"))

        get_agent = make_dsh_get_agent(client, workspace_manager=ws)
        agent = get_agent("assistant1", "main_smoke")
        print(f"[agent] name={agent.agent_name} session={agent.session_name}")

        res = await agent.execute("请回复一句问候。", options=ExecutionOptions(timeout_seconds=120))
        print(f"[result] success={res.success} stop_reason={res.stop_reason} "
              f"session_id={res.session_id} content_len={len(res.content)} "
              f"err={res.error_message}")

        # 再来一轮,验证 sessionId 线程复用(多轮记忆钩子)
        res2 = await agent.execute("再见。", options=ExecutionOptions(timeout_seconds=120))
        print(f"[result2] success={res2.success} session_id={res2.session_id} "
              f"same_session={res2.session_id == res.session_id}")

    ok = res.success and res.session_id and res2.success
    print("DSH_PIPELINE_SMOKE_OK" if ok else "DSH_PIPELINE_SMOKE_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
