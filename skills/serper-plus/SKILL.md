---
name: serper-plus
description: Google search via Serper API — web (full content extraction), recent news, AND images. Three modes (`default` / `current` / `image`). Also includes fetch.py for standalone URL content extraction. API key via .env.
metadata: {"version": "4.1.0", "tags": ["search", "web-search", "image-search", "serper", "google", "content-extraction", "fetch"]}
---

# Serper-Plus

Extension of the original `serper` skill. Google search via Serper API, **with optional page content extraction** and a standalone `fetch.py` for extracting individual URLs.

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/search.py` | Google search (default: fetches page content via jina reader) |
| `scripts/fetch.py` | Fetch a single URL's content via jina reader |

### How It Works

1. **Serper API call** — fast Google search, returns result URLs / image URLs instantly
2. **For `default` / `current` modes (default behaviour)** — pages are fetched concurrently via jina reader
3. **With `--no-fetch`** — returns only title/url/snippet without any jina reader calls (fast, lets you pick which URLs to fetch)
4. **`fetch.py`** — standalone jina reader for a specific URL; use after `--no-fetch` search to fetch only the URLs that matter
5. **For `image` mode** — no page fetching; results stream as image metadata records
6. **Streamed output** — results print one at a time as each completes

### Two-step pattern for hard-to-extract pages

For pages like financial history tables (Yahoo Finance, etc.) that are JS-rendered, the default fetch often returns incomplete data. Use the two-step approach:

```bash
# Step 1: search without fetching to see which URLs are available
python scripts/search.py -q "2513.HK historical price April May 2026" --no-fetch

# Step 2: fetch the most promising URL directly
python scripts/fetch.py "https://stockanalysis.com/stocks/2513-HK/history/"
```

This lets you choose the best URL rather than fetching all results blindly.

---

## Query Discipline

**Craft focused search queries.** Each call returns multiple results — use `--no-fetch` to quickly scan URLs first, then `fetch.py` to retrieve content from the most promising ones.

Use `search.py` with default mode when you need content extracted automatically. Use `--no-fetch` + `fetch.py` for targeted page extraction (e.g. financial history pages that require specific URL selection).


**Do NOT:**
- Run the same query with different wording to "get more results"
- Run sequential searches to "dig deeper" — full page content is already deep
- Run separate image searches per item when one good image query covers them all

---

## When to Use This Skill

**Use serper-plus when:**
- Any question that needs current factual information from the web (`default` / `current`)
- Research topics that need full article content (`default`)
- News and current events (`current`)
- **Finding real-world images** to embed in a webpage, doc, presentation, or analysis (`image`) — landmark photos, person portraits, product shots, historical photos, scientific diagrams, paintings, satellite/map images, official architecture diagrams, etc.

**Do NOT use this skill for:**
- Questions you can answer from your training data
- Pure math, code execution, creative writing
- Greetings, chitchat
- Generating new images (this skill returns search results, not generated images)

**IMPORTANT: For `default` / `current` modes, this skill already fetches and extracts full page content. Do NOT run web_fetch / WebFetch / curl on the returned URLs. The content is already in the output.**

---

## Three Search Modes

Pick the right one based on the query:

### `default` — General web (all-time)
- All-time Google web search, **5 results**, each enriched with full page content
- For: general questions, research, how-to, evergreen topics, product info, technical docs, comparisons, tutorials, anything NOT time-sensitive

### `current` — Recent news + web
- Past-week Google web (3 results) + Google News (3 results), each enriched with full page content
- For: news, current events, recent developments, breaking news, announcements, anything time-sensitive

### `image` — Image search (NEW)
- Google Images via Serper, **10 results** by default (`--num` to override, up to 30)
- Returns image URL, thumbnail URL, dimensions, source domain, and the source page URL — no page fetching
- For: finding real-world images that exist online — photos of landmarks (Mogao Caves), people (Einstein portraits), products (iPhone evolution), paintings (Mona Lisa), historical events (moon landing), scientific diagrams (DNA helix, atomic structure), maps (1939 Europe), specimens (T-Rex fossil), official architecture diagrams (SLSA, AWS), etc.

#### Mode Selection Guide

| Query signals | Mode |
|---------------|------|
| "how does X work", "what is X", "explain X" | `default` |
| Product research, comparisons, tutorials | `default` |
| Technical documentation, guides | `default` |
| Historical topics, evergreen content | `default` |
| "news", "latest", "today", "this week", "recent" | `current` |
| "what happened", "breaking", "announced", "released" | `current` |
| Current events, politics, sports scores, stock prices | `current` |
| "photo of X", "picture of X", "image of X", "插图", "图片", "照片", "示意图", "结构图", "肖像", "彩色图鉴", "high-resolution image" | `image` |
| Embedding visuals in a webpage / doc / slide | `image` |

---

## Locale (REQUIRED for non-English queries)

**Default is global** — no country filter, English results. Only fine for English queries.

**You MUST ALWAYS set `--gl` and `--hl` when ANY of these are true:**
- The user's message is in a non-English language
- The search query you construct is in a non-English language
- The user mentions a specific country, city, or region
- The user asks for local results in a non-English context

| Scenario | Flags |
|----------|-------|
| English query, no country target | *(omit --gl and --hl)* |
| Chinese query OR user writes in Chinese OR targeting CN | `--gl cn --hl zh-cn` |
| German query OR targeting DE/AT/CH | `--gl de --hl de` |
| French query OR targeting France | `--gl fr --hl fr` |
| Any other non-English language/country | `--gl XX --hl XX` (ISO codes) |

**Rule of thumb:** If the query string contains non-English words, set `--gl` and `--hl` to match.

---

## How to Invoke

```bash
python scripts/search.py -q "QUERY" [--mode MODE] [--num N] [--gl COUNTRY] [--hl LANG]
```

### Examples

```bash
# English, general research
python scripts/search.py -q "how does HTTPS work"

# English, time-sensitive
python scripts/search.py -q "OpenAI latest announcements" --mode current

# German query — set locale + current mode for news/prices
python scripts/search.py -q "aktuelle Preise iPhone" --mode current --gl de --hl de

# Image search — find photos of Dunhuang murals
python scripts/search.py -q "Mogao Caves Dunhuang mural photo" --mode image

# Image search in Chinese — find DNA double helix diagram
python scripts/search.py -q "DNA 双螺旋结构图" --mode image --gl cn --hl zh-cn

# Image search with explicit count
python scripts/search.py -q "Apollo 11 moon landing NASA photo" --mode image --num 20
```

---

## Output Format

The output is a **streamed JSON array** — first element is search metadata, then one element per result.

### `default` / `current` mode

```json
[{"query": "...", "mode": "default", "locale": {"gl": "world", "hl": "en"}, "results": [{"title": "...", "url": "...", "source": "web"}, ...]}
,{"title": "...", "url": "...", "source": "web", "content": "Full extracted page text..."}
,{"title": "...", "url": "...", "source": "news", "date": "2 hours ago", "content": "Full article text..."}
]
```

Result fields:
- `title` — page title
- `url` — source URL
- `source` — `"web"`, `"news"`, or `"knowledge_graph"`
- `content` — full extracted page text (falls back to search snippet if extraction fails)
- `date` — when available

### `image` mode

```json
[{"query": "Mogao Caves Dunhuang mural", "mode": "image", "locale": {"gl": "world", "hl": "en"}, "results_count": 10}
,{"title": "Flying Apsaras, Cave 320", "imageUrl": "https://example.com/apsaras.jpg", "thumbnailUrl": "https://...", "width": 1600, "height": 1067, "domain": "metmuseum.org", "sourcePageUrl": "https://www.metmuseum.org/art/collection/search/123456", "position": 1, "source": "image"}
,{"title": "Bodhisattva, Mogao Cave 57", "imageUrl": "https://...", ...}
]
```

Image result fields:
- `title` — descriptive title (often the alt text or page title)
- `imageUrl` — direct URL to the full-size image (use this for `<img src>` / download)
- `thumbnailUrl` — small thumbnail URL (use for previews / lazy loading)
- `width`, `height` — full image dimensions (pixels)
- `thumbnailWidth`, `thumbnailHeight` — thumbnail dimensions (pixels)
- `domain` — source domain (e.g. `wikipedia.org`)
- `sourcePageUrl` — URL of the page hosting the image (for attribution / context)
- `position` — Google ranking position
- `source` — always `"image"` for this mode

**Note on hotlinking:** Some `imageUrl` values may be CDN-protected and not embeddable directly. When that matters, fall back to `thumbnailUrl` (always Google-hosted and stable) or have the page open `sourcePageUrl` for the user.

---

## CLI Reference

| Flag | Description |
|------|-------------|
| `-q, --query` | Search query (required) |
| `-m, --mode` | `default` (web, 5) / `current` (week + news, 3+3) / `image` (10 image results) |
| `--num` | (image mode) Number of image results, 1-30. Ignored for `default`/`current`. |
| `--gl` | Country code (e.g. `cn`, `de`, `us`, `fr`, `at`, `ch`) |
| `--hl` | Language code (e.g. `en`, `zh-cn`, `de`, `fr`) |

API key: set `SERPER_API_KEY=...` in `.env` in the skill directory (same as the original serper skill).
