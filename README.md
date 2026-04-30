# DB Hidden Gate

A curated database of off-the-beaten-path travel spots discovered from personal travel blogs — no tour operators, no TripAdvisor, just places real travellers genuinely loved.

## How it works

The pipeline runs in two steps:

1. **Fetch** — `scripts/search_blogs.py` queries Brave Search for personal travel blogs by region, fetches and cleans each page with trafilatura, and filters by enthusiasm keywords and region relevance. Output is raw blog JSON saved to `blogs/<country>/<region>.json`.
2. **Analyze** — Claude Code reads the fetched blogs, extracts qualifying spots (personal blog, genuine enthusiasm, crowd level ≤ 3), looks up GPS coordinates, and merges them into `spots_database.json`.

Progress is tracked in `search_progress.json` so work can resume across sessions without re-fetching.

## Quick start

### Requirements

```
pip install httpx trafilatura lxml_html_clean
```

A `BRAVE_API_KEY` is required for blog fetching. Set it as an environment variable locally, or as a GitHub secret for the Action.

### Fetch + analyze locally

```bash
export BRAVE_API_KEY=your_key_here

# Fetch blogs for a country (saves to blogs/vietnam/)
python3 scripts/run_pipeline.py --country vietnam

# Then analyze in Claude Code
# (open Claude Code and say: analyze vietnam)
```

### Mobile / cloud workflow

1. Go to the repo's **Actions** tab → **Search Travel Spots** → **Run workflow**
2. Enter the country name and number of regions to search
3. The Action fetches blogs and pushes raw JSON to `blogs/`
4. Open Claude Code and say `analyze vietnam` to extract spots

## Scripts

### `scripts/search_blogs.py`

Searches Brave for personal travel blogs and outputs cleaned blog content as JSON.

```
python3 scripts/search_blogs.py "ha giang vietnam"
python3 scripts/search_blogs.py morocco --year 2024
python3 scripts/search_blogs.py "yunnan china" --langs en,fr
python3 scripts/search_blogs.py patagonia --no-dedup
```

- Skips commercial sites (TripAdvisor, Lonely Planet, booking platforms, tour operators)
- Requires at least one enthusiasm keyword in the content
- Skips URLs already used as sources in the database (dedup)

### `scripts/run_pipeline.py`

Orchestrates region-by-region fetching for a country and updates `search_progress.json`.

```
python3 scripts/run_pipeline.py --country vietnam
python3 scripts/run_pipeline.py --country vietnam --max-regions 3
```

## File structure

```
spots_database.json      # The spot database (array of spot objects)
search_progress.json     # Per-country region fetch/analyze status
blogs/                   # Raw fetched blog JSON, organised by country/region
scripts/
  search_blogs.py        # Brave Search + trafilatura fetch script
  run_pipeline.py        # Pipeline orchestrator (fetch only)
.github/workflows/
  search.yml             # GitHub Action for remote fetching
```

## Spot schema

Each entry in `spots_database.json` follows this structure:

| Field | Type | Description |
|---|---|---|
| `id` | string | Kebab-case unique identifier |
| `name` | string | Canonical English name |
| `name_local` | string\|null | Name in local language/script |
| `country` | string | ISO 3166-1 alpha-2 code |
| `region` | string | Province / state / department |
| `lat` / `lng` | number | WGS-84 coordinates, 5 decimal places |
| `category` | string | `waterfall`, `cave`, `trek`, `viewpoint`, `village`, `ruins`, `beach`, `lake`, `hot_spring`, `forest`, `mountain`, `other` |
| `description_short` | string | 1-2 sentence hook, max 200 chars |
| `description_context` | string | 2-4 sentences on access, terrain, best season |
| `crowd_level` | integer 1-5 | 1 = almost nobody → 5 = tourist hotspot |
| `best_months` | string[] | Month names |
| `access_difficulty` | string | `easy`, `moderate`, `hard`, `expert` |
| `source_urls` | string[] | Blog post URLs used as sources |
| `source_type` | string | `personal_blog`, `travel_forum`, `local_guide` |
| `discovered_at` | string | ISO 8601 date added |
| `tags` | string[] | Freeform tags |

## Quality rules

- **Personal blogs only** — no commercial platforms, travel agencies, or aggregators
- **Genuine enthusiasm required** — blogger must have loved the place (not just mentioned it)
- **crowd_level ≤ 3** — off the beaten path only
- **GPS required** — every spot has coordinates
- **No hallucination** — only details explicitly stated or clearly implied in the source

## Current coverage

Vietnam: 30 spots across Ha Giang, Cao Bang, Lang Son, Yen Bai, Son La, Lai Chau, Thanh Hoa, Quang Binh, Da Nang, Binh Dinh, Kon Tum, Gia Lai, Dak Lak, Lam Dong, Ba Ria-Vung Tau, Hai Phong, Lao Cai, Hoa Binh, Ninh Binh, Quang Nam, Phu Yen, Dak Nong, Nghe An.
