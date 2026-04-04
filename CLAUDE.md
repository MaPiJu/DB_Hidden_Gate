# DB Hidden Gate

A curated database of off-the-beaten-path travel spots discovered from personal travel blogs.

## Quick Commands

### `analyze <country>` (e.g. "analyze vietnam")

Analyze fetched blogs and extract spots. Do the following automatically:

1. Read `search_progress.json` to find regions with status `"fetched"` (not yet `"analyzed"`).
2. For each fetched region:
   a. Read the blog JSON from `blogs/<country>/<region-slug>.json`.
   b. For each blog, check: is it a personal blog (not a travel agency)? Does the blogger show genuine enthusiasm? Is the spot off-the-beaten-path (crowd_level ≤ 3)?
   c. For qualifying spots, look up GPS coordinates via web search.
   d. Add new spots to `spots_database.json` following the schema below.
   e. Update `search_progress.json`: set status to `"analyzed"` and add `spots_added` count.
3. After modifying any files, **commit and push to GitHub**:
   ```
   git add spots_database.json search_progress.json
   git commit -m "Add <N> spots from <Region>, <Country>"
   git push
   ```
4. Continue to the next fetched region. Stop after each region and report what was found before continuing.

### `search <country>` (e.g. "search vietnam")

If `BRAVE_API_KEY` is available, run the full pipeline locally:

1. Read `search_progress.json` to find unsearched regions for that country.
2. If the country has no entry yet, generate a list of travel-relevant regions and save to `search_progress.json`.
3. For each unsearched region, one at a time:
   a. Run: `python3 scripts/search_blogs.py "<Region> <country>"`
   b. Save output to `blogs/<country>/<region-slug>.json`.
   c. Analyze the blogs (same as `analyze` command above).
   d. Update `search_progress.json` with status `"analyzed"`.
4. Commit and push after each region.

If `BRAVE_API_KEY` is NOT available (e.g. cloud environment), tell the user:
> "Blog fetching requires BRAVE_API_KEY. Trigger the GitHub Action from the Actions tab to fetch blogs first, then say `analyze <country>` to extract spots."

## Environment Setup

- **BRAVE_API_KEY** — needed for blog search. Set as env var locally, or as a GitHub secret for the Action.
- **GitHub Action** — go to the repo's Actions tab → "Search Travel Spots" → "Run workflow" to fetch blogs from any device.
- Python dependencies: `pip install httpx trafilatura lxml_html_clean`

## Two-Step Workflow (for mobile/cloud)

1. **Fetch** — trigger the GitHub Action "Search Travel Spots" from the Actions tab (works from phone). It runs `search_blogs.py` for each region, saves raw blog JSON to `blogs/`, and pushes.
2. **Analyze** — open Claude Code and say `analyze <country>`. Claude reads the fetched blogs, extracts qualifying spots, and pushes results.

## Spot JSON Schema

Each spot in `spots_database.json` follows this schema:

```json
{
  "id": "string — kebab-case unique identifier, e.g. 'ban-gioc-waterfall'",
  "name": "string — canonical English name",
  "name_local": "string | null — name in local language/script",
  "country": "string — ISO 3166-1 alpha-2 code, e.g. 'VN'",
  "region": "string — province/state/department",
  "lat": "number — WGS-84 latitude, 5 decimal places",
  "lng": "number — WGS-84 longitude, 5 decimal places",
  "category": "string — one of: waterfall, cave, trek, viewpoint, village, ruins, beach, lake, hot_spring, forest, mountain, other",
  "description_short": "string — 1-2 sentence hook, original English, max 200 chars",
  "description_context": "string — 2-4 sentences providing practical context (access, terrain, best season), original English",
  "crowd_level": "integer 1-5 — 1=almost nobody, 2=few travelers, 3=moderate, 4=popular but manageable, 5=tourist hotspot",
  "best_months": ["string — month names, e.g. 'October', 'November'"],
  "access_difficulty": "string — one of: easy, moderate, hard, expert",
  "source_urls": ["string — URLs of the blog posts used as sources"],
  "source_type": "string — one of: personal_blog, travel_forum, local_guide",
  "discovered_at": "string — ISO 8601 date when added to DB, e.g. '2026-03-31'",
  "tags": ["string — freeform tags, e.g. 'motorbike', 'waterfall', 'ethnic-minority'"]
}
```

## Quality Rules

1. **Personal blogs only** — reject commercial sites (TripAdvisor, Lonely Planet, Booking, GetYourGuide, AllTrails, Viator, YouTube, Reddit, Wikipedia).
2. **Blogger enthusiasm required** — only extract spots the blogger genuinely enjoyed or recommended. Look for positive sentiment signals in the text such as: "incredible", "breathtaking", "astonishing", "worth the trip", "highlight of the trip", "one of the best", "blown away", "highly recommend", "don't miss", "unforgettable", "spectacular", "hidden gem", "absolutely loved", "must-visit", "jaw-dropping". Reject spots the blogger found disappointing, overhyped, or merely mentioned in passing without personal enthusiasm.
4. **Factual extraction** — only record details explicitly stated or clearly implied in the source. Do not hallucinate distances, times, or features.
5. **Original descriptions** — description_short and description_context must be original English text, not copied from blogs.
6. **GPS required** — every spot must have lat/lng. Look up coordinates via web search if the blog doesn't provide them.
7. **Deduplication** — before adding, check if a spot with the same id or within 5 km and similar name already exists.
8. **Non-destructive merge** — when updating an existing spot, never overwrite a non-null field with null.

## Search Workflow

The pipeline searches **region by region** within a country for thorough coverage.

1. **Country selection** — user provides a country name.
2. **Region listing** — generate a list of relevant travel regions (not all administrative divisions — only those likely to contain off-the-beaten-path spots). Save to `search_progress.json`.
3. **Region-by-region search** — for each region, run `scripts/search_blogs.py "<region> <country>"`, analyze blog content, extract qualifying spots, and merge into `spots_database.json`.
4. **Progress tracking** — mark each region as searched in `search_progress.json` with date and results count. This prevents re-searching and lets work resume across sessions.

## File Structure

- `CLAUDE.md` — this file
- `spots_database.json` — the spot database (array of spot objects)
- `search_progress.json` — tracks which regions have been searched per country
- `scripts/search_blogs.py` — Brave Search + trafilatura fetch script (dynamic, DB-aware)
