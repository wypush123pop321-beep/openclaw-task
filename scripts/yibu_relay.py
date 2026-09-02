# -*- coding: utf-8 -*-
"""yibuapi 本地反向代理中继:解决 openclaw 网关 undici 代理路径与华为认证代理不兼容的问题。

背景:网关(openclaw gateway,node/undici)的模型调用直连 yibuapi.com 被内网屏蔽,而
openclaw 的 @openclaw/proxyline 代理实现无法对华为 proxysg-spl 代理做认证(curl/Python
requests 可以)。方案:本中继监听本地端口,把网关的 baseUrl 指向这里(localhost 直连绕过
代理),中继再用 Python requests 经认证代理转发到 yibuapi.com。字节级透传,网关无感。

用法:
  python scripts/yibu_relay.py [--port 18888]
  建议用 run_batch/网关重启前先启动本中继,保持常驻。
"""

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

# 加载本机私有凭据(gitignored configs/local.env;净化提交,真值不入库,见 local_env.py)
import local_env
local_env.load()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("yibu_relay")

UPSTREAM = "https://yibuapi.com"
# 认证代理(净化默认占位;真值从 WCX_PROXY env/local.env 注入 —— requests 可处理 %40%40 转义)
PROXY = os.environ.get("WCX_PROXY",
                       "http://<user>:<pwd_urlencoded>@proxysg-spl.huawei.com:8080")
PROXIES = {"http": PROXY, "https": PROXY}

# 透传保留的请求头(网关发的 Authorization 里带 yibuapi key,原样转发)
_KEEP_REQ_HEADERS = {"authorization", "content-type", "accept"}


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _relay(self) -> None:
        method = self.command
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        upstream_url = UPSTREAM + self.path
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() in _KEEP_REQ_HEADERS}

        try:
            up = requests.request(
                method, upstream_url, data=body, headers=headers,
                proxies=PROXIES, stream=True, timeout=(15, 300),
            )
        except requests.exceptions.RequestException as e:
            log.error("[%s] %s 上游转发失败: %s", method, self.path, e)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))
            return

        # 转发状态行与头。Connection: close 让客户端以 EOF 判断响应结束
        # (SSE 流式响应无 Content-Length/chunked,undici 需要明确帧边界)
        self.send_response(up.status_code)
        for k, v in up.headers.items():
            if k.lower() in ("content-length", "transfer-encoding", "connection"):
                continue
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()

        # 流式透传响应体
        try:
            for chunk in up.iter_content(chunk_size=65536):
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            log.warning("[%s] 客户端断开", self.path)
        finally:
            up.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _relay

    def log_message(self, fmt, *args):
        log.info("%s %s", self.command, self.path)


def main() -> None:
    ap = argparse.ArgumentParser(description="yibuapi 本地反向代理中继")
    ap.add_argument("--port", type=int, default=18888)
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), RelayHandler)
    log.info("yibu_relay 监听 http://127.0.0.1:%d → %s (经认证代理)", args.port, UPSTREAM)
    srv.serve_forever()


if __name__ == "__main__":
    main()
