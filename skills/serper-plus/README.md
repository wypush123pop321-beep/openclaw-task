# Serper-Plus

Google search via Serper API with full page content extraction, **extended with Google Images search**.

This is a drop-in superset of the original `serper` skill: it keeps the same `default` (all-time web) and `current` (past-week web + news) modes — both still fetch and extract full page text — and adds a new `image` mode that returns Google Images results (image URL, thumbnail URL, dimensions, source page).

Version `4.0.0`.

---

## How It Works

1. **Serper API call** — fast Google search, returns result URLs (or image URLs) instantly
2. **For `default` / `current`** — pages fetched concurrently and full text extracted via trafilatura (3s per page)
3. **For `image`** — no page fetching; results stream as image metadata records
4. **Streamed output** — results print one at a time as each completes

One query returns 5 (default) / 6 (current) / 10 by default (image) results.

---

## Install

### 1. Drop the skill in place

```bash
# Copy or symlink the whole serper-plus folder into your skills dir, e.g.:
cp -r serper-plus ~/.openclaw/skills/serper-plus
```

### 2. Install trafilatura (needed for default/current modes)

```bash
pip install trafilatura
```

### 3. Add your Serper API key

Create `.env` in the skill root (same folder as `SKILL.md`):

```
SERPER_API_KEY="your-key-from-serper.dev"
```

Get a free key at <https://serper.dev> (2,500 free queries).

---

## Quick examples

```bash
# General web research (5 results, full page text)
python scripts/search.py -q "how does HTTPS work"

# Recent news (past week web + news)
python scripts/search.py -q "OpenAI latest announcements" --mode current

# Image search — 10 image results with imageUrl / thumbnailUrl / sourcePageUrl
python scripts/search.py -q "Mogao Caves Dunhuang mural photo" --mode image

# Image search in Chinese
python scripts/search.py -q "DNA 双螺旋结构图" --mode image --gl cn --hl zh-cn

# Image search, larger result set
python scripts/search.py -q "Apollo 11 moon landing NASA photo" --mode image --num 20
```

See [SKILL.md](SKILL.md) for full documentation (mode selection, locale rules, output format, query discipline).

---

## Output schema differences from the original `serper`

| Field | default / current | image |
|---|---|---|
| `title` | ✓ page title | ✓ image alt/title |
| `url` | ✓ source page URL | — |
| `imageUrl` | — | ✓ direct full-image URL |
| `thumbnailUrl` | — | ✓ Google-hosted thumbnail |
| `width` / `height` | — | ✓ pixels |
| `domain` | — | ✓ source domain |
| `sourcePageUrl` | — | ✓ page hosting the image |
| `content` | ✓ extracted full page text | — |
| `source` | `"web"` / `"news"` / `"knowledge_graph"` | `"image"` |
| `date` | when available | — |
| `position` | — | ✓ Google ranking position |

---

## Compatibility

- All existing CLI flags from `serper` 3.x still work the same way
- The only new flags are `--mode image` and `--num` (image mode only)
- `.env` lookup is identical (`SERPER_API_KEY` or legacy `SERP_API_KEY`)
