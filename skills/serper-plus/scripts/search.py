#!/usr/bin/env -S python3 -u
"""
Serper-Plus — Google search with full page content extraction (web/news) +
              Google Images search (new).

Three search modes:
  - default:  all-time web search (5 results, enriched with full page text)
  - current:  past-week web + news (3 each, enriched with full page text)
  - image:    Google Images search (10 results by default, metadata only)

Locale via --gl and --hl. Image count via --num (image mode only).
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, List, Dict, Any

from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# trafilatura is only needed for default/current modes (page extraction).
# image mode does not fetch pages, so we lazy-load and tolerate its absence.
trafilatura = None
def _require_trafilatura():
    global trafilatura, _traf_config
    if trafilatura is not None:
        return
    try:
        import trafilatura as _t
    except ImportError:
        print(json.dumps({
            "error": "trafilatura is required for default/current modes but not installed",
            "fix": "pip install trafilatura",
            "note": "image mode does not need trafilatura — use --mode image to skip this dependency",
        }, indent=2), flush=True)
        sys.exit(1)
    trafilatura = _t
    _traf_config = trafilatura.settings.use_config()
    _traf_config.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(FETCH_TIMEOUT))


# =============================================================================
# Auto-load .env from skill directory
# =============================================================================
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


# =============================================================================
# Configuration
# =============================================================================

FETCH_TIMEOUT = 3
USER_AGENT = "Mozilla/5.0 (compatible; SerperPlus/4.0)"

# 经 yibuapi 中转访问 serper(公司网络直连 serper.dev 不通,走中转+系统代理可达)。
# 认证由 X-API-KEY 改为 Authorization: Bearer(见 _serper_post)。
SERP_SEARCH_URL = "https://yibuapi.com/serper/search"
SERP_NEWS_URL   = "https://yibuapi.com/serper/news"
SERP_IMAGES_URL = "https://yibuapi.com/serper/images"
# jina_reader 中转:抓取网页正文(替代 trafilatura,公司网络直连页面不通,走中转+系统代理)
JINA_READER_URL = "https://yibuapi.com/jina_reader/read/"
JINA_TIMEOUT = 8

_traf_config = None  # initialised lazily in _require_trafilatura()


def get_api_key() -> str:
    key = os.environ.get("SERPER_API_KEY") or os.environ.get("SERP_API_KEY")
    if not key:
        # agent 直接跑脚本时环境无此变量,从 skill 根目录 .env 兜底读取(不依赖 python-dotenv)
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line.startswith("SERPER_API_KEY") and "=" in _line:
                        key = _line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not key:
        print(json.dumps({
            "error": "Missing Serper API key",
            "how_to_fix": [
                "1. Get a free key at https://serper.dev (2,500 queries free)",
                '2. Add SERPER_API_KEY="your-key" to .env in the skill directory',
            ],
        }, indent=2), flush=True)
        sys.exit(1)
    if len(key) < 10:
        print(json.dumps({"error": "Serper API key appears invalid (too short)"}), flush=True)
        sys.exit(1)
    return key


# =============================================================================
# Content extraction via trafilatura (web/news only)
# =============================================================================

def _extract_content(url: str) -> Optional[str]:
    # 经 yibuapi 的 jina_reader 中转抓取正文(公司网络直连页面不通,走中转+系统代理)。
    # 返回 data.content(markdown 正文);失败返回 None,default/current 模式据此降级为仅标题+URL。
    try:
        key = get_api_key()
        body = json.dumps({"url": url}).encode("utf-8")
        req = Request(JINA_READER_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        with urlopen(req, timeout=JINA_TIMEOUT) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        return (r.get("data") or {}).get("content") or None
    except Exception:
        return None


# =============================================================================
# 调用次数硬限制(每任务最多 2 次;状态文件落在 cwd = agent workspace,
# 每个任务开始前 workspace 会被清空,因此配额随任务自动重置)
# =============================================================================

MAX_CALLS_PER_TASK = 4
_QUOTA_STATE_FILE = ".serper_call_state.json"


def _check_and_consume_quota(query: str) -> None:
    state_path = Path.cwd() / _QUOTA_STATE_FILE
    count = 0
    if state_path.exists():
        try:
            count = json.loads(state_path.read_text(encoding="utf-8")).get("count", 0)
        except Exception:
            count = 0

    if count >= MAX_CALLS_PER_TASK:
        print(json.dumps({
            "error": "search_quota_exceeded",
            "message": (
                f"本任务的搜索配额已用尽(最多 {MAX_CALLS_PER_TASK} 次)。"
                "禁止再调用 serper-plus，也禁止用其他方式重试搜索。"
                "请立即基于已获取的搜索结果直接给出最终答案。"
            ),
            "calls_used": count,
            "limit": MAX_CALLS_PER_TASK,
        }, ensure_ascii=False), flush=True)
        sys.exit(1)

    count += 1
    try:
        state_path.write_text(
            json.dumps({"count": count, "last_query": query}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# =============================================================================
# Serper API
# =============================================================================

def _serper_post(endpoint: str, api_key: str, payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        msgs = {
            401: "Invalid or expired API key.",
            429: "Rate limit exceeded. Wait and retry.",
        }
        raise Exception(msgs.get(e.code, f"Serper HTTP {e.code}: {body[:300]}"))
    except URLError as e:
        raise Exception(f"Network error: {e.reason}")
    except Exception as e:
        raise Exception(f"Request failed: {e}")


def serper_web_search(query: str, api_key: str, num: int = 5,
                      gl: Optional[str] = None, hl: str = "en",
                      tbs: Optional[str] = None) -> List[Dict[str, Any]]:
    payload: Dict[str, Any] = {"q": query, "num": num, "hl": hl, "autocorrect": True}
    if gl and gl != "world":
        payload["gl"] = gl
    if tbs:
        payload["tbs"] = tbs

    data = _serper_post(SERP_SEARCH_URL, api_key, payload)
    results = []

    kg = data.get("knowledgeGraph")
    if kg and "title" in kg:
        attrs = ""
        if "attributes" in kg:
            attrs = " | ".join(f"{k}: {v}" for k, v in kg["attributes"].items())
        results.append({
            "title": kg["title"],
            "snippet": attrs or kg.get("description", ""),
            "source": "knowledge_graph",
        })

    for item in data.get("organic", [])[:num]:
        r = {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": "web",
        }
        if item.get("date"):
            r["date"] = item["date"]
        results.append(r)

    return results


def serper_news_search(query: str, api_key: str, num: int = 3,
                       gl: Optional[str] = None, hl: str = "en") -> List[Dict[str, Any]]:
    payload: Dict[str, Any] = {"q": query, "num": num, "hl": hl}
    if gl and gl != "world":
        payload["gl"] = gl

    data = _serper_post(SERP_NEWS_URL, api_key, payload)
    results = []
    for item in data.get("news", [])[:num]:
        r = {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": "news",
        }
        if item.get("date"):
            r["date"] = item["date"]
        results.append(r)
    return results


def serper_image_search(query: str, api_key: str, num: int = 10,
                        gl: Optional[str] = None, hl: str = "en") -> List[Dict[str, Any]]:
    """Image search via Serper. Returns list of image-result dicts."""
    payload: Dict[str, Any] = {"q": query, "num": num, "hl": hl, "autocorrect": True}
    if gl and gl != "world":
        payload["gl"] = gl

    data = _serper_post(SERP_IMAGES_URL, api_key, payload)
    results = []
    for item in data.get("images", [])[:num]:
        img_url = item.get("imageUrl") or item.get("imageUrlLarge") or ""
        if not img_url:
            continue
        r = {
            "title":           item.get("title", ""),
            "imageUrl":        img_url,
            "thumbnailUrl":    item.get("thumbnailUrl", ""),
            "width":           item.get("imageWidth"),
            "height":          item.get("imageHeight"),
            "thumbnailWidth":  item.get("thumbnailWidth"),
            "thumbnailHeight": item.get("thumbnailHeight"),
            "domain":          item.get("domain") or item.get("source", ""),
            "sourcePageUrl":   item.get("link", ""),
            "position":        item.get("position"),
            "source":          "image",
        }
        # drop empty / None values for compactness
        r = {k: v for k, v in r.items() if v not in (None, "")}
        r["source"] = "image"
        results.append(r)
    return results


# =============================================================================
# Enrichment — concurrent fetch, streamed as JSON array (web/news only)
# =============================================================================

def enrich_and_stream(results: List[Dict[str, Any]], no_fetch: bool = False):
    futures = {}
    pool = ThreadPoolExecutor(max_workers=max(1, len(results)))
    if not no_fetch:
        for i, r in enumerate(results):
            if r.get("url"):
                futures[i] = pool.submit(_extract_content, r["url"])

    for i, r in enumerate(results):
        out: Dict[str, Any] = {"title": r["title"]}
        if r.get("url"):
            out["url"] = r["url"]
        out["source"] = r["source"]
        if r.get("date"):
            out["date"] = r["date"]

        if r["source"] == "knowledge_graph":
            out["content"] = r["snippet"]
        elif no_fetch:
            # --no-fetch: return only the search snippet, no jina call
            out["snippet"] = r.get("snippet", "")
        else:
            content = None
            if i in futures:
                try:
                    content = futures[i].result(timeout=FETCH_TIMEOUT)
                except Exception:
                    content = None
            MAX_CONTENT_CHARS = 8000
            if content:
                if len(content) > MAX_CONTENT_CHARS:
                    content = content[:MAX_CONTENT_CHARS] + "\n...[truncated]"
                out["content"] = content
            else:
                out["content"] = r["snippet"]

        print("," + json.dumps(out, ensure_ascii=False), flush=True)

    pool.shutdown(wait=False)


def stream_image_results(results: List[Dict[str, Any]]):
    """Image mode has no page fetching — just stream metadata records."""
    for r in results:
        print("," + json.dumps(r, ensure_ascii=False), flush=True)


def search_current(query: str, api_key: str, locale: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
    all_results = []
    seen_urls = set()

    for r in serper_web_search(query, api_key, num=3, gl=locale["gl"], hl=locale["hl"], tbs="qdr:w"):
        if r["source"] == "knowledge_graph":
            all_results.append(r)
        elif r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            all_results.append(r)

    for r in serper_news_search(query, api_key, num=3, gl=locale["gl"], hl=locale["hl"]):
        url = r.get("url", "")
        if url not in seen_urls:
            seen_urls.add(url)
            all_results.append(r)

    return all_results


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Serper-Plus — Google search (web/news/images) with content extraction for web/news",
    )
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument(
        "--mode", "-m",
        default="default",
        choices=["default", "current", "image"],
        help="default (web all-time, 5) | current (past-week web + news, 3 each) | image (Google Images, default 10)",
    )
    parser.add_argument("--num", type=int, default=10,
                        help="Number of results for image mode (1-30). Ignored for default/current.")
    parser.add_argument("--gl", default="world", help="Country code (e.g. cn, de, us, fr). Default: world")
    parser.add_argument("--hl", default="en", help="Language code (e.g. en, zh-cn, de)")
    parser.add_argument("--no-fetch", action="store_true", dest="no_fetch",
                        help="Skip jina reader page fetch — return only title/url/snippet. "
                             "Useful when you want to inspect URLs first before deciding which to fetch.")

    args = parser.parse_args()
    api_key = get_api_key()
    locale = {"gl": args.gl, "hl": args.hl}

    if args.mode == "current":
        results = search_current(args.query, api_key, locale)
        meta_results = [{k: r[k] for k in ("title", "url", "source") if k in r} for r in results]
    elif args.mode == "image":
        n = max(1, min(int(args.num or 10), 30))
        results = serper_image_search(args.query, api_key, num=n, gl=locale["gl"], hl=locale["hl"])
        meta_results = None  # image mode: no preview list (each result already light-weight)
    else:
        results = serper_web_search(args.query, api_key, num=3, gl=locale["gl"], hl=locale["hl"])
        meta_results = [{k: r[k] for k in ("title", "url", "source") if k in r} for r in results]

    if not results:
        print(json.dumps({"error": "No results found", "query": args.query, "mode": args.mode}), flush=True)
        sys.exit(1)

    # JSON array — first element is search metadata
    meta: Dict[str, Any] = {
        "query":  args.query,
        "mode":   args.mode,
        "locale": locale,
    }
    if args.mode == "image":
        meta["results_count"] = len(results)
    else:
        meta["results"] = meta_results

    print("[" + json.dumps(meta, ensure_ascii=False), flush=True)
    if args.mode == "image":
        stream_image_results(results)
    else:
        enrich_and_stream(results, no_fetch=args.no_fetch)
    print("]", flush=True)


if __name__ == "__main__":
    # Windows 控制台默认 gbk,输出含特殊字符(—/emoji 等)会 UnicodeEncodeError;强制 utf-8。
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
