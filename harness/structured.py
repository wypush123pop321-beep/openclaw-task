"""中立结构化解析兜底(能力: harness-adapter)。

当 adapter 不具备 `Capability.STRUCTURED_OUTPUT` 时,核心走解析兜底:从模型自由文本中
抽取 JSON 并按目标 pydantic schema 校验。逻辑对标 harness 原生结构化解析,但**不依赖任何
harness SDK**,使核心层保持中立。
"""

from __future__ import annotations

import json
import re
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredParseError(ValueError):
    """自由文本中未找到可校验为目标 schema 的 JSON。"""


def parse_structured_text(response: str, model: Type[T]) -> T:
    """从 `response` 抽取首个 JSON 块并校验为 `model`。

    搜索顺序:
    1. 围栏 ```json ... ``` 代码块;
    2. 裸 `{...}` JSON 对象。
    """
    match = re.search(r"```json\s*([\s\S]*?)```", response)
    if match:
        json_str = match.group(1).strip()
    else:
        bare_match = re.search(r"\{[\s\S]*\}", response)
        if bare_match:
            json_str = bare_match.group(0)
        else:
            raise StructuredParseError(f"No JSON found in response: {response[:200]}")

    try:
        data = json.loads(json_str)
        return model.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise StructuredParseError(
            f"Failed to parse response as {model.__name__}: {exc}"
        ) from exc
