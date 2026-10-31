"""assistant 系统提示词的统一解析(harness 无关)+ auto-gen 变异。

见 openspec change `auto-gen-assistant-system-prompt`。

两步解析(D2):
  step 1 选 base:agent 的 `system_prompt` 非空 → 用它(source=config);
                  否则 → 内置 DEFAULT_SYSTEM_PROMPT(source=default)。
  step 2 是否变异:`auto_gen_system_prompt=true` → 以 base 为 meta-prompt 调 LLM 改写
                  产出变体(source=auto_gen);变异失败/空 → 回退 base。

解析器只产字符串,不负责下发;下发由各 harness 各自实现(D4)。
变异 LLM 复用 simulator 的模型配置(D3),不新增模型配置块。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger("harness_automation")

# 来源枚举(落盘 trajectory 用)
SOURCE_AUTO_GEN = "auto_gen"
SOURCE_CONFIG = "config"
SOURCE_DEFAULT = "default"

# 7.3:system_prompt 为空时的默认系统提示词。
DEFAULT_SYSTEM_PROMPT = (
    "You are a capable, reliable AI assistant. Understand the user's intent, "
    "ask for clarification when the request is ambiguous, and complete the task "
    "accurately and concisely. Use the available tools when they help, verify your "
    "work before presenting it, and be honest about uncertainty or limitations."
)

# 变异 meta-prompt:以 base 为输入,产出人设/语气/风格明显不同、但任务/工具语义不变的变体。
_META_PROMPT_TEMPLATE = (
    "你是一名提示词工程师,负责为训练数据制造多样性。请把下面这段 assistant 系统提示词"
    "改写成一个明显不同的变体:改变人设、语气、详略程度和措辞,让它读起来与原文有明显区别。"
    "你必须保持原有的任务范围、工具使用方式,以及所有硬性约束/结束条件不变——只允许改动风格与人设。"
    "同时保持与原提示词相同的语言。只输出改写后的系统提示词本身,不要任何前言或说明。\n\n"
    "--- 原系统提示词 ---\n{base}\n--- 原系统提示词结束 ---"
)

# gen_fn 签名:base(str) -> 变体(str) 或 None(失败/不可用)
GenFn = Callable[[str], Optional[str]]


def resolve_system_prompt(
    agent_cfg: Any,
    gen_fn: Optional[GenFn] = None,
) -> Tuple[str, str]:
    """两步解析 assistant 系统提示词,返回 (prompt, source)。

    agent_cfg: 需暴露 `name` / `system_prompt` / `auto_gen_system_prompt` 属性。
    gen_fn: 变异回调(base->变体);auto_gen 开启但未提供或调用失败时回退 base。
    """
    name = getattr(agent_cfg, "name", "?")
    sp = (getattr(agent_cfg, "system_prompt", None) or "").strip()
    if sp:
        base, source = sp, SOURCE_CONFIG
    else:
        base, source = DEFAULT_SYSTEM_PROMPT, SOURCE_DEFAULT

    if not getattr(agent_cfg, "auto_gen_system_prompt", False):
        return base, source

    # auto_gen 分支(7.1)
    if gen_fn is None:
        logger.warning("agent '%s' 开启 auto_gen_system_prompt 但无可用生成器,回退 base(%s)", name, source)
        return base, source
    try:
        variant = gen_fn(base)
    except Exception as e:  # noqa: BLE001
        logger.warning("agent '%s' auto-gen 变异失败,回退 base(%s): %s", name, source, e)
        return base, source
    if variant and variant.strip():
        logger.info("agent '%s' auto-gen 变异成功(base source=%s)", name, source)
        return variant.strip(), SOURCE_AUTO_GEN
    logger.warning("agent '%s' auto-gen 返回空,回退 base(%s)", name, source)
    return base, source


def make_gen_fn(model_cfg: Any, *, temperature: float = 1.0) -> Optional[GenFn]:
    """基于 simulator 模型配置构建 base->变体 回调;无任何模型来源时返回 None。

    model_cfg: AgentModelConfig(model/api_key/base_url) 或 None。缺项回退 SIMULATOR_* 环境变量,
    与 create_simulator 的取值口径一致(D3 复用 simulator 模型)。
    OpenAI client 惰性构建并缓存:构建/调用异常都由 resolve_system_prompt 兜底回退 base。
    """
    cfg_model = getattr(model_cfg, "model", None) if model_cfg else None
    cfg_api_key = getattr(model_cfg, "api_key", None) if model_cfg else None
    cfg_base_url = getattr(model_cfg, "base_url", None) if model_cfg else None

    model = cfg_model or os.environ.get("SIMULATOR_MODEL")
    api_key = cfg_api_key or os.environ.get("SIMULATOR_OPENAI_API_KEY")
    base_url = cfg_base_url or os.environ.get("SIMULATOR_OPENAI_BASE_URL")
    proxy = os.environ.get("SIMULATOR_PROXY")

    if not (model or api_key or base_url):
        # 没有任何 simulator 模型来源 → 无法变异
        return None

    state: dict = {"client": None}

    def gen_fn(base: str) -> Optional[str]:
        if state["client"] is None:
            import httpx
            from openai import OpenAI

            state["client"] = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=httpx.Client(verify=False, proxy=proxy),
            )
        resp = state["client"].chat.completions.create(
            model=model or "gpt-4o",
            messages=[{"role": "user", "content": _META_PROMPT_TEMPLATE.format(base=base)}],
            temperature=temperature,
        )
        return resp.choices[0].message.content

    return gen_fn
