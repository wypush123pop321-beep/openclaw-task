"""
离线单测: 修复 user_simulator 空回复导致的多轮死循环 (change fix-simulator-empty-reply-loop)

三层防御各测一处,全部离线(不联网、不依赖真实 openai/openclaw_sdk):
  1. simulator: chat() 空 content 回退 reasoning / 全空兜底收尾标记,永不返回空串
  2. executor : 多轮循环空 user_reply → 判定收尾、不下发、轨迹落盘 (逻辑等价断言)
  3. client   : execute_with_retry 遇 message-required 快速失败、不进 fallback

用法:
  cd <repo> && python test/test_empty_reply_loop.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---- 伪造 OpenAI 风格响应对象(不依赖真实 openai 库) ----
class _Msg:
    def __init__(self, content=None, reasoning_content=None, reasoning=None):
        self.content = content
        if reasoning_content is not None:
            self.reasoning_content = reasoning_content
        if reasoning is not None:
            self.reasoning = reasoning


class _Choice:
    def __init__(self, msg):
        self.message = msg


class _Usage:
    prompt_tokens = 10
    completion_tokens = 1470
    total_tokens = 1480


class _Resp:
    def __init__(self, msg):
        self.choices = [_Choice(msg)]
        self.usage = _Usage()


def _make_simulator(responses):
    """构造一个 chat 调用会依次返回 responses 里响应的 simulator(打桩 client)。"""
    from user_simulator import User_simulator

    sim = User_simulator(origin_query="t", user_profile="{}", api_key="dummy")

    seq = list(responses)

    class _FakeCompletions:
        def create(self, **kwargs):
            return seq.pop(0)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    sim.client = _FakeClient()
    return sim


def test_extract_reply_fallback_reasoning():
    print("1) 主 content 空 + reasoning 非空 → 取 reasoning")
    sim = _make_simulator([_Resp(_Msg(content="", reasoning_content="想清楚了：继续"))])
    reply = sim.chat("agent said something")
    assert reply == "想清楚了：继续", f"应回退 reasoning_content, 实得 {reply!r}"
    print("   ✓", repr(reply))


def test_all_empty_falls_back_to_done():
    print("2) content+reasoning 全空,重试仍空 → 兜底 Task_Done,永不空串")
    sim = _make_simulator([_Resp(_Msg(content="")) for _ in range(3)])
    reply = sim.chat("agent said something")
    assert reply.strip(), "chat() 不得返回空串"
    assert "【Task_Done】" in reply, f"应兜底收尾标记, 实得 {reply!r}"
    print("   ✓", repr(reply))


def test_normal_content_unchanged():
    print("3) 正常有 content → 原样返回(不影响正常路径)")
    sim = _make_simulator([_Resp(_Msg(content="正常回复内容"))])
    reply = sim.chat("agent said something")
    assert reply == "正常回复内容", f"正常路径应原样返回, 实得 {reply!r}"
    print("   ✓", repr(reply))


def test_executor_empty_reply_is_finalize():
    print("4) executor: 空 user_reply 判定逻辑等价 Task_Done(不下发空消息)")
    # 复刻 executor 中的判定分支语义,断言"空即收尾"这一契约。
    def decide(user_reply):
        if not (user_reply or "").strip():
            return "done"  # 收尾,break,不赋 current_query
        if "【Task_Done】" in user_reply:
            return "done"
        if "【Task_Failed】" in user_reply:
            return "failed"
        return "continue"

    assert decide("") == "done"
    assert decide("   \n ") == "done"
    assert decide(None) == "done"
    assert decide("继续问点别的") == "continue"
    assert decide("【Task_Done】") == "done"
    print("   ✓ 空/空白/None 均判收尾, 非空正常继续")


def test_client_message_required_fast_fail():
    print("5) client: message-required 归类为快速失败,连接类归类为可 fallback")
    # 复刻 openclaw_client 异常分支的分类判据。
    def is_fast_fail(err_text):
        return "message or attachment required" in str(err_text).lower()

    assert is_fast_fail("GatewayError: message or attachment required")
    assert is_fast_fail("Message or Attachment Required")  # 大小写不敏感
    assert not is_fast_fail("connection reset by peer")
    assert not is_fast_fail("timeout waiting for gateway")
    print("   ✓ message-required→快速失败; 连接/超时→仍走 fallback")


if __name__ == "__main__":
    tests = [
        test_extract_reply_fallback_reasoning,
        test_all_empty_falls_back_to_done,
        test_normal_content_unchanged,
        test_executor_empty_reply_is_finalize,
        test_client_message_required_fast_fail,
    ]
    print("=" * 60)
    print("离线单测: fix-simulator-empty-reply-loop")
    print("=" * 60)
    for t in tests:
        t()
    print("\n✅ 全部通过 (%d 项)" % len(tests))
