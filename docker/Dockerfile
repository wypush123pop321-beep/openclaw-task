# openclaw 沙箱镜像：每个容器自带一个 openclaw 网关 + 跑一个 dailyclawbench 任务。
# 构建上下文 = 仓库根目录：  docker build -f docker/Dockerfile -t openclaw-task:latest .
FROM python:3.12-slim

# 允许用内网 PyPI 源（openclaw-sdk 若不在公网 PyPI 上）：
#   docker build --build-arg PIP_INDEX_URL=http://your-index/simple ...
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""

# 构建时代理（供 apt / npm / pip 走公网用）。compose 会自动从宿主机 shell 透传
# HTTP_PROXY/HTTPS_PROXY/NO_PROXY（BuildKit 预定义代理 ARG 会自动注入到 RUN 环境）。
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""

# openclaw CLI 版本：落在 openclaw-sdk 2.1.0 兼容区间 2026.2.0~2026.2.28 内，
# 取已发布的最高版 2026.2.26（也正是宿主机 openclaw.json 的 wizard.lastRunVersion）。
ARG OPENCLAW_VERSION="2026.2.26"
# Node 官方二进制版本（openclaw 要求 node>=22.19.0；与宿主机一致）
ARG NODE_DIST="v22.22.1"

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PUPPETEER_SKIP_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/corp-ca-bundle.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

# 企业代理若对 HTTPS 做拦截（用自签 CA 重签），需先把该企业 CA 装进系统信任库，
# 否则 curl/npm/pip 及运行时 Node 的 TLS 全部校验失败。
# 把你环境的 CA 放到 docker/certs/corp-ca-bundle.crt（该目录已 gitignore，不入库）。
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates
COPY docker/certs/corp-ca-bundle.crt /usr/local/share/ca-certificates/corp-ca-bundle.crt
RUN update-ca-certificates

# Node 22（官方二进制，避开发行版/nodesource 适配问题）+ openclaw CLI
# 这层最重、最稳，放最前面利用缓存。curl/npm 走 build-arg 透传的代理。
# git：2026.2.x 的 openclaw 有 git 形式的依赖，npm install 需要它
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl xz-utils procps git \
    && curl -fsSL "https://nodejs.org/dist/${NODE_DIST}/node-${NODE_DIST}-linux-x64.tar.xz" -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz \
    && node --version && npm --version \
    && npm install -g "openclaw@${OPENCLAW_VERSION}" \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && openclaw --version

# Python 依赖（含 cryptography：SDK 握手 Ed25519 签名必需）
COPY docker/requirements-openclaw.txt /app/docker/requirements-openclaw.txt
RUN pip install --no-cache-dir -r docker/requirements-openclaw.txt

# ── Kit 资产（repo 无关，烧进 /opt/kit）────────────────────────────────
# 只烧「环境层」：entrypoint 逻辑、网关配置+identity、serper skill、模型 key。
# 目标 workspace 的 harness repo 在运行时挂载到 /app（不同版本随便换，无需重建）。
RUN mkdir -p /opt/kit
COPY docker/entrypoint.sh            /opt/kit/entrypoint.sh
COPY docker/entrypoint.py           /opt/kit/entrypoint.py
COPY docker/gateway/openclaw.json   /opt/kit/openclaw.json
COPY docker/gateway/identity/       /opt/kit/identity/
COPY skills/serper-plus/            /opt/kit/serper-plus/
COPY configs/user_proxy_model.json  /opt/kit/user_proxy_model.json
RUN chmod +x /opt/kit/entrypoint.sh

# /app = 运行时挂载目标 repo 的位置
WORKDIR /app
ENTRYPOINT ["/opt/kit/entrypoint.sh"]
