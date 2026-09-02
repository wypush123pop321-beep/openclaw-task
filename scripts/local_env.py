# -*- coding: utf-8 -*-
"""本机私有凭据加载器(本文件无真值;真值在 gitignored 的 configs/local.env)。

净化约定:仓库内脚本不内置真实凭据(认证代理密码 / gateway token / 模型 key),
统一从环境变量读取(WCX_PROXY / WCX_GATEWAY_TOKEN / SIMULATOR_PROXY / WCX_API_KEY)。
本机运行时把真值写入 gitignored 的 configs/local.env(每行 KEY=VALUE,注释行 # 开头),
由 load() 加载进 os.environ —— 净化提交不泄密,本机照常运行。
新机器 / 无 local.env 时脚本以占位符默认运行(连不上即报错,提示先配 local.env,
模板见 configs/local.env.example)。
"""
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def load() -> None:
    """把 configs/local.env(若存在)读入 os.environ;已存在的 env 不覆盖。"""
    p = _REPO / "configs" / "local.env"
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
