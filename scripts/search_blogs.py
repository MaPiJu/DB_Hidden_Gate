#!/usr/bin/env python3
"""
Search personal travel blogs via Brave Search API, fetch & clean content with trafilatura.

Dynamic queries — works for any region/country without code changes.
Database-aware — skips blogs already used as sources in spots_database.json.

Usage:
    python3 scripts/search_blogs.py vietnam
    python3 scripts/search_blogs.py morocco --year 2024
    python3 scripts/search_blogs.py "yunnan china" --langs en,fr
    python3 scripts/search_blogs.py patagonia --no-dedup
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

BLOCKED_DOMAINS = [
    # Major commercial platforms
    "tripadvisor", "lonelyplanet", "booking.com", "alltrails", "youtube",
    "reddit.com", "wikipedia", "viator", "getyourguide", "expedia",
    "tiktok", "instagram", "facebook", "pinterest", "hotels.com",
    "agoda", "hostelworld", "klook", "traveloka", "kayak",
    # Travel agencies & tour operators
    "tours.com", "amazingtour", "vietnamamazing", "vietnam-amazing",
    "galatourist", "galat", "originvietnam", "vietnamoriginal",
    "asiaking", "paradisetravel", "vietnamparadise", "adventuregreen",
    "motorbiketour", "motorcycletour", "hikingvietnam", "hiddenlandtravel",
    "hanoivoyage", "autourasia", "tonkin", "indochina", "vietpower",
    "saigonfood", "asiamystika", "vietnamdiscovery", "vietnamevasion",
    "vietnamdragontravel", "izitour", "ecolodge.asia",
    "vietnam.travel", "vietnamtourism", "vietnam.vn",
    "traveltriangle", "rehahnphotographer",
    "paradisevietnam", "snorkeling-report", "getmyboat",
    "travelandleisure", "dulichvtv", "dulich.laichau",
    "airbnb", "homestay.com",
]

ENTHUSIASM_KEYWORDS = [
    "incredible", "breathtaking", "astonishing", "worth the trip",
    "highlight of the trip", "one of the best", "blown away",
    "highly recommend", "unforgettable", "spectacular", "hidden gem",
    "absolutely loved", "must-visit", "jaw-dropping", "don't miss",
    "must visit", "worth every", "blew my mind", "stunned",
]

# Query templates with {region} placeholder — works for any destination.
QUERY_TEMPLATES = {
    "en": [
        "{region} off beaten path personal travel blog",
        "{region} hidden gem trekking blog personal",
        "{region} secret waterfall hike blog",
        "{region} ethnic minority village blog personal",
        "{region} remote village homestay blog",
        "{region} unexplored cave blog personal",
        "{region} secret beach snorkeling blog",
        "{region} motorbike adventure blog personal",
        "{region} backpacker hidden spot blog",
        "{region} wild nature trek blog personal",
    ],
    "fr": [
        "{region} hors sentiers battus blog voyage personnel",
        "{region} randonnée lieu secret blog personnel",
        "{region} village reculé blog voyage",
    ],
    "de": [
        "{region} Geheimtipp Wanderung Reisebericht Blog",
        "{region} abseits Touristenpfade Blog Reisebericht",
    ],
    "es": [
        "{region} senderismo lugar secreto blog personal",
        "{region} mochilero ruta escondida blog",
    ],
}

# Map common country names to ISO codes for DB matching.
COUNTRY_CODES = {
    "vietnam": "VN", "morocco": "MA", "peru": "PE", "chile": "CL",
    "argentina": "AR", "colombia": "CO", "nepal": "NP", "india": "IN",
    "indonesia": "ID", "thailand": "TH", "laos": "LA", "cambodia": "KH",
    "myanmar": "MM", "china": "CN", "japan": "JP", "georgia": "GE",
    "turkey": "TR", "iran": "IR", "ethiopia": "ET", "tanzania": "TZ",
    "kenya": "KE", "madagascar": "MG", "bolivia": "BO", "ecuador": "EC",
    "guatemala": "GT", "mexico": "MX", "philippines": "PH", "malaysia": "MY",
    "sri lanka": "LK", "pakistan": "PK", "kyrgyzstan": "KG", "tajikistan": "TJ",
}


def normalize_url(url: str) -> str:
    """Normalize URL for consistent deduplication."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.rstrip("/")
    return f"{host}{path}".lower()


def load_exclusions(db_path: Path, region_input: str) -> tuple[set[str], list[str]]:
    """Load existing DB and build exclusion sets.

    Returns:
        known_urls: ALL source_urls from DB (skip already-used blogs).
        known_spot_names: Names of spots matching the region (skip redundant results).
    """
    if not db_path.exists():
        print("  No existing DB found — running without dedup", file=sys.stderr)
        return set(), []

    try:
        spots = json.loads(db_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print("  Could not parse DB — running without dedup", file=sys.stderr)
        return set(), []

    # Collect ALL source URLs from the entire database.
    known_urls = set()
    for spot in spots:
        for url in spot.get("source_urls", []):
            known_urls.add(normalize_url(url))

    # Collect spot names that match the target region/country.
    region_lower = region_input.lower()
    country_code = COUNTRY_CODES.get(region_lower, "").upper()
    known_spot_names = []
    for spot in spots:
        spot_region = spot.get("region", "").lower()
        spot_country = spot.get("country", "").upper()
        if (region_lower in spot_region.lower()
                or spot_region.lower() in region_lower
                or (country_code and spot_country == country_code)):
            known_spot_names.append(spot["name"])

    return known_urls, known_spot_names


def generate_queries(region: str, langs: list[str], year: str | None = None) -> list[str]:
    """Generate search queries from templates for the given region."""
    queries = []
    for lang in langs:
        templates = QUERY_TEMPLATES.get(lang, [])
        for template in templates:
            q = template.format(region=region)
            if year:
                q += f" {year}"
            queries.append(q)
    return queries


def is_blocked(url: str) -> bool:
    url_lower = url.lower()
    return any(domain in url_lower for domain in BLOCKED_DOMAINS)


def title_matches_known_spot(title: str, known_spot_names: list[str]) -> str | None:
    """Check if a search result title matches a known spot name.
    Only checks names >= 8 chars to avoid false positives."""
    title_lower = title.lower()
    for name in known_spot_names:
        if len(name) >= 8 and name.lower() in title_lower:
            return name
    return None


def brave_search(query: str, count: int = 10) -> list[dict]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": count}
    try:
        resp = httpx.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return [{"title": r["title"], "url": r["url"], "description": r.get("description", "")}
                for r in results if not is_blocked(r["url"])]
    except Exception as e:
        print(f"  [ERROR] Brave search failed for '{query}': {e}", file=sys.stderr)
        return []


def fetch_and_clean(url: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; TravelBlogResearch/1.0)"})
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
        return text
    except Exception as e:
        print(f"  [ERROR] Fetch failed for {url}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Search personal travel blogs for off-the-beaten-path spots."
    )
    parser.add_argument("region", help="Region or country name (e.g., vietnam, morocco, yunnan)")
    parser.add_argument("--db", type=Path, default=None,
                        help="Path to spots_database.json (default: auto-detect)")
    parser.add_argument("--max-results", type=int, default=10,
                        help="Results per Brave query (default: 10)")
    parser.add_argument("--langs", default="en,fr,de,es",
                        help="Comma-separated language codes (default: en,fr,de,es)")
    parser.add_argument("--year", default=None,
                        help="Append year to queries (e.g., 2024)")
    parser.add_argument("--no-dedup", action="store_true",
                        help="Skip database-aware filtering")
    args = parser.parse_args()

    if not BRAVE_API_KEY:
        print("ERROR: BRAVE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Resolve DB path.
    if args.db:
        db_path = args.db
    else:
        db_path = Path(__file__).resolve().parent.parent / "spots_database.json"

    # Load exclusions from existing database.
    if args.no_dedup:
        known_urls, known_spot_names = set(), []
        print("Dedup disabled — skipping DB check", file=sys.stderr)
    else:
        known_urls, known_spot_names = load_exclusions(db_path, args.region)
        print(f"DB loaded: {len(known_urls)} known URLs, "
              f"{len(known_spot_names)} spot names for '{args.region}'",
              file=sys.stderr)
        if known_spot_names:
            print(f"  Will filter titles matching: {known_spot_names}", file=sys.stderr)

    # Generate queries dynamically.
    langs = [l.strip() for l in args.langs.split(",")]
    queries = generate_queries(args.region, langs, args.year)
    print(f"\nGenerated {len(queries)} queries for '{args.region}'\n", file=sys.stderr)

    # Search phase.
    seen_urls = set()
    results = []
    skipped_known = 0
    skipped_title = 0

    for query in queries:
        print(f"--- Searching: {query} ---", file=sys.stderr)
        hits = brave_search(query, count=args.max_results)
        print(f"  Found {len(hits)} results (after domain filtering)", file=sys.stderr)

        for hit in hits:
            norm = normalize_url(hit["url"])
            if norm in seen_urls:
                continue
            seen_urls.add(norm)

            # Skip URLs already in the database.
            if norm in known_urls:
                print(f"  SKIP (known URL): {hit['url']}", file=sys.stderr)
                skipped_known += 1
                continue

            # Skip titles matching existing spot names.
            matched = title_matches_known_spot(hit["title"], known_spot_names)
            if matched:
                print(f"  SKIP (matches '{matched}'): {hit['title']}", file=sys.stderr)
                skipped_title += 1
                continue

            results.append(hit)
        time.sleep(1)  # rate limit

    print(f"\n=== Search complete: {len(results)} new URLs to fetch "
          f"(skipped {skipped_known} known URLs, {skipped_title} title matches) ===\n",
          file=sys.stderr)

    # Extract region name words for relevance check.
    region_words = [w.lower() for w in args.region.split() if len(w) > 2]
    region_full = args.region.lower()

    # Fetch phase with enthusiasm + region filters.
    output = []
    skipped_no_enthusiasm = 0
    skipped_no_region = 0
    for i, hit in enumerate(results):
        print(f"[{i+1}/{len(results)}] Fetching: {hit['url']}", file=sys.stderr)
        content = fetch_and_clean(hit["url"])
        if not content or len(content) < 300:
            print(f"  SKIP — too short or empty", file=sys.stderr)
            continue

        content_lower = content.lower()

        # Region relevance filter: must mention region name.
        region_mentions = content_lower.count(region_full)
        if region_mentions == 0:
            # Try individual words (e.g. "Lai Chau" → "lai" + "chau")
            if not all(w in content_lower for w in region_words):
                print(f"  SKIP — no region mention", file=sys.stderr)
                skipped_no_region += 1
                continue

        # Enthusiasm pre-filter: must have at least 1 keyword.
        found_enthusiasm = [kw for kw in ENTHUSIASM_KEYWORDS if kw in content_lower]
        if not found_enthusiasm:
            print(f"  SKIP — no enthusiasm keywords", file=sys.stderr)
            skipped_no_enthusiasm += 1
            continue

        output.append({
            "url": hit["url"],
            "title": hit["title"],
            "content": content[:8000],
            "meta": {
                "enthusiasm_keywords": found_enthusiasm,
                "region_mentions": region_mentions,
                "full_length": len(content),
            },
        })
        print(f"  OK — {len(content)} chars, enthusiasm: {found_enthusiasm}", file=sys.stderr)
        time.sleep(0.5)

    # Output JSON to stdout.
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print(f"\n=== Done: {len(output)} blogs kept "
          f"(dropped {skipped_no_region} no-region, {skipped_no_enthusiasm} no-enthusiasm) ===",
          file=sys.stderr)


if __name__ == "__main__":
    main()
