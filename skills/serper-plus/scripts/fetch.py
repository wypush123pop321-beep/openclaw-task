#!/usr/bin/env -S python3 -u
"""
fetch.py — 独立的 jina reader 页面正文抓取工具。

与 search.py 分离，让 agent 自己决定哪些 URL 值得抓取正文。

用法：
    python scripts/fetch.py <URL>

输出：JSON，字段：
  - url: 请求的 URL
  - content: 页面正文（markdown，最多 MAX_CONTENT_CHARS 字符）
  - error: 若抓取失败，包含错误描述

示例：
    python skills/serper-plus/scripts/fetch.py "https://hk.finance.yahoo.com/quote/2513.HK/history/"
"""

import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

MAX_CONTENT_CHARS = 8000
JINA_TIMEOUT = 15  # 比 search.py 里长一点，给单个页面更多时间

sys.stdout = __import__('io').TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _load_env_file():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    if line.startswith("export "):
                        line = line[7:]
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value

_load_env_file()


def get_api_key() -> str:
    key = os.environ.get("SERPER_API_KEY") or os.environ.get("SERP_API_KEY")
    if not key:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SERPER_API_KEY") and "=" in line:
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    return key or ""


JINA_READER_URL = "https://yibuapi.com/jina_reader/read/"
USER_AGENT = "Mozilla/5.0 (compatible; SerperPlus/4.0)"


def fetch_url(url: str) -> dict:
    key = get_api_key()
    if not key:
        return {"url": url, "error": "Missing API key"}
    try:
        body = json.dumps({"url": url}).encode("utf-8")
        req = Request(JINA_READER_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        with urlopen(req, timeout=JINA_TIMEOUT) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        content = (r.get("data") or {}).get("content") or ""
        if not content:
            return {"url": url, "error": "jina reader returned empty content"}
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + f"\n...[truncated, total {len(content)} chars]"
        return {"url": url, "content": content}
    except Exception as e:
        return {"url": url, "error": str(e)}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "Usage: python fetch.py <URL>",
            "example": 'python skills/serper-plus/scripts/fetch.py "https://hk.finance.yahoo.com/quote/2513.HK/history/"'
        }, ensure_ascii=False))
        sys.exit(1)

    url = sys.argv[1]
    result = fetch_url(url)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
