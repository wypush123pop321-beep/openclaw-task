#!/usr/bin/env python3
"""
从宿主机现有的 openclaw.json 生成一份「容器网关专用」最小配置。

只保留网关路由模型 / 联网工具 / 网关监听所必需的部分，去掉 Windows 专属路径与
预置 agents 列表（让 harness 在容器内现建），并把 gateway.auth 关成 none，
方便同容器内的 harness 免 token 连接本地网关。

用法：
    python docker/gateway/make_config.py [源openclaw.json] [目标]
源默认取环境变量 OPENCLAW_SRC，否则 ~/.openclaw/openclaw.json。
（WSL 场景网关配置在 Windows 侧时，把该路径作为第一个参数或 OPENCLAW_SRC 传入，
 例如 /mnt/c/Users/<你>/.openclaw/openclaw.json）
默认目标 = docker/gateway/openclaw.json

注意：生成文件含真实 apiKey，已在 .gitignore / .dockerignore 中排除出 git，
但会被 COPY 进镜像（用户已确认「拷贝现有配置」）。不要把该镜像推到公共 registry。
"""
import json
import os
import sys
from pathlib import Path

DEFAULT_SRC = os.environ.get("OPENCLAW_SRC", str(Path.home() / ".openclaw" / "openclaw.json"))
DEFAULT_DST = str(Path(__file__).parent / "openclaw.json")

CONTAINER_WORKSPACE = "/root/.openclaw/workspace"


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC)
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DST)

    if not src.is_file():
        print(f"[make_config] 源配置不存在: {src}", file=sys.stderr)
        return 1

    full = json.loads(src.read_text(encoding="utf-8"))

    # 网关鉴权（token 模式）。关键：SDK 客户端握手时出示的是 device-auth.json 里
    # tokens.operator.token，网关拿它与 gateway.auth.token 比对。因此必须把
    # gateway.auth.token 强制设为该 operator token，两边才一致（否则 token_mismatch）。
    # 强制 bind=loopback / port=18789（容器内本地网关），其余保留。
    gateway = dict(full.get("gateway", {}))
    gateway["port"] = 18789
    gateway["bind"] = "loopback"
    gateway["mode"] = gateway.get("mode", "local")

    op_token = ""
    dauth_path = src.parent / "identity" / "device-auth.json"
    if dauth_path.is_file():
        dauth = json.loads(dauth_path.read_text(encoding="utf-8"))
        op_token = dauth.get("tokens", {}).get("operator", {}).get("token", "")
    if op_token:
        gateway.setdefault("auth", {})
        gateway["auth"] = {**gateway.get("auth", {}), "mode": "token", "token": op_token}
        print("[make_config] gateway.auth.token 已对齐 device-auth operator token")
    else:
        print("[make_config] 警告: 未找到 device-auth operator token，沿用原 gateway.auth")

    # meta.lastTouchedVersion 对齐容器内 CLI 版本，消掉 "written by a newer OpenClaw" 警告
    meta = dict(full.get("meta", {}))
    meta["lastTouchedVersion"] = "2026.2.26"

    minimal = {
        "meta": meta,
        # 模型 provider（含 baseUrl/apiKey/models）—— 网关给主 agent 路由模型用，原样保留
        "models": full.get("models", {}),
        # 联网工具（web_search / web_fetch）—— task03 需要，原样保留（含 search apiKey）
        "tools": full.get("tools", {}),
        "gateway": gateway,
        # agents：保留默认模型映射，但 workspace 指向 Linux 路径、清空预置列表
        "agents": {
            "defaults": {
                **full.get("agents", {}).get("defaults", {}),
                "workspace": CONTAINER_WORKSPACE,
            },
            "list": [],
        },
        "commands": full.get("commands", {}),
        "session": full.get("session", {}),
    }
    # defaults 里可能残留 Windows agentDir/workspace，逐一清掉
    minimal["agents"]["defaults"].pop("agentDir", None)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(minimal, ensure_ascii=False, indent=2), encoding="utf-8")

    # 一并拷贝 device identity（device.json / device-auth.json）到 identity/ 子目录，
    # 供 SDK 客户端签名握手用。含私钥/令牌，同样 gitignore。
    src_id = src.parent / "identity"
    dst_id = dst.parent / "identity"
    if src_id.is_dir():
        dst_id.mkdir(parents=True, exist_ok=True)
        for fn in ("device.json", "device-auth.json"):
            fp = src_id / fn
            if fp.is_file():
                (dst_id / fn).write_text(fp.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[make_config] 已拷贝 identity -> {dst_id}")

    # 只打印结构性摘要，不打印任何 key 值
    provs = list(minimal.get("models", {}).get("providers", {}).keys())
    models = [
        m.get("id")
        for p in minimal.get("models", {}).get("providers", {}).values()
        for m in p.get("models", [])
    ]
    print(f"[make_config] 已写出: {dst}")
    print(f"[make_config] providers={provs}")
    print(f"[make_config] models={models}")
    print(f"[make_config] gateway.auth.mode={gateway.get('auth',{}).get('mode')} port=18789 bind=loopback")
    print(f"[make_config] web tools: {list(minimal.get('tools', {}).get('web', {}).keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
