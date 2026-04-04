#!/usr/bin/env python3
"""
Analyze blog content using Claude API and merge qualifying spots into the database.

Reads blog JSON from search_blogs.py output, sends to Claude for analysis,
and merges extracted spots into spots_database.json.

Usage:
    python3 scripts/analyze_and_merge.py --region "Lai Chau" --country vietnam --blogs /tmp/blogs.json
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import httpx

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

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

SYSTEM_PROMPT = """You are an expert travel database curator. You analyze blog posts to extract off-the-beaten-path travel spots.

RULES:
1. Only extract spots from PERSONAL blogs (not travel agencies, commercial sites).
2. Only extract spots the blogger genuinely enjoyed — look for enthusiasm signals like "incredible", "breathtaking", "worth the trip", "highly recommend", "hidden gem", "unforgettable", "spectacular", "must-visit", "jaw-dropping".
3. Only extract spots with crowd_level <= 3 (1=almost nobody, 2=few travelers, 3=moderate). Reject tourist hotspots.
4. Only record details explicitly stated or implied in the source. Do not invent facts.
5. Write ORIGINAL descriptions — do not copy text from blogs.
6. Every spot needs lat/lng coordinates. If the blog doesn't provide them, estimate based on the location described (village name, district, province). Use 5 decimal places.

OUTPUT FORMAT: Return a JSON array of spot objects. If no spots qualify, return an empty array [].
Each spot object must have exactly these fields:
{
  "id": "kebab-case-unique-id",
  "name": "English name",
  "name_local": "local script name or null",
  "country": "ISO 2-letter code",
  "region": "province/state",
  "lat": 12.34567,
  "lng": 103.45678,
  "category": "one of: waterfall, cave, trek, viewpoint, village, ruins, beach, lake, hot_spring, forest, mountain, other",
  "description_short": "1-2 sentence hook, max 200 chars",
  "description_context": "2-4 sentences with practical context (access, terrain, best season)",
  "crowd_level": 1-3,
  "best_months": ["Month", "Month"],
  "access_difficulty": "easy|moderate|hard|expert",
  "source_urls": ["url1"],
  "source_type": "personal_blog",
  "discovered_at": "YYYY-MM-DD",
  "tags": ["tag1", "tag2"]
}

Return ONLY the JSON array, no other text."""


def call_claude(blogs_content: str, region: str, country: str, existing_spots: list[dict]) -> list[dict]:
    """Send blog content to Claude API for analysis."""

    existing_names = [s["name"] for s in existing_spots]
    existing_ids = [s["id"] for s in existing_spots]

    user_prompt = f"""Analyze these blog posts about {region}, {country} and extract qualifying off-the-beaten-path spots.

EXISTING SPOTS (do not duplicate these): {json.dumps(existing_names)}

Today's date: {date.today().isoformat()}
Country code: {COUNTRY_CODES.get(country.lower(), country.upper())}
Region: {region}

BLOG CONTENT:
{blogs_content}"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    try:
        resp = httpx.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"]

        # Parse JSON from response (handle markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]

        spots = json.loads(text)

        # Filter out any spots that duplicate existing ones
        new_spots = []
        for spot in spots:
            if spot["id"] in existing_ids:
                print(f"  SKIP duplicate id: {spot['id']}", file=sys.stderr)
                continue
            if spot["name"] in existing_names:
                print(f"  SKIP duplicate name: {spot['name']}", file=sys.stderr)
                continue
            new_spots.append(spot)

        return new_spots

    except Exception as e:
        print(f"  [ERROR] Claude API call failed: {e}", file=sys.stderr)
        if hasattr(e, 'response'):
            print(f"  Response: {e.response.text[:500]}", file=sys.stderr)
        return []


def merge_spots(db_path: Path, new_spots: list[dict]) -> int:
    """Merge new spots into the database, respecting dedup rules."""
    if db_path.exists():
        existing = json.loads(db_path.read_text(encoding="utf-8"))
    else:
        existing = []

    existing_ids = {s["id"] for s in existing}
    added = 0

    for spot in new_spots:
        if spot["id"] in existing_ids:
            print(f"  SKIP (already in DB): {spot['id']}", file=sys.stderr)
            continue
        existing.append(spot)
        existing_ids.add(spot["id"])
        added += 1
        print(f"  ADDED: {spot['name']} ({spot['id']})", file=sys.stderr)

    db_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return added


def update_progress(progress_path: Path, country: str, region: str, blogs_found: int, spots_added: int):
    """Update search_progress.json."""
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    else:
        progress = {}

    country_lower = country.lower()
    if country_lower not in progress:
        progress[country_lower] = {"regions": [], "searched": {}}

    progress[country_lower]["searched"][region] = {
        "date": date.today().isoformat(),
        "blogs_found": blogs_found,
        "spots_added": spots_added,
    }

    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Analyze blogs and merge spots into DB.")
    parser.add_argument("--region", required=True, help="Region name (e.g., 'Lai Chau')")
    parser.add_argument("--country", required=True, help="Country name (e.g., 'vietnam')")
    parser.add_argument("--blogs", required=True, type=Path, help="Path to blog JSON from search_blogs.py")
    parser.add_argument("--db", type=Path, default=None, help="Path to spots_database.json")
    parser.add_argument("--progress", type=Path, default=None, help="Path to search_progress.json")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Resolve paths
    project_root = Path(__file__).resolve().parent.parent
    db_path = args.db or project_root / "spots_database.json"
    progress_path = args.progress or project_root / "search_progress.json"

    # Load blogs
    blogs = json.loads(args.blogs.read_text(encoding="utf-8"))
    print(f"Loaded {len(blogs)} blogs for {args.region}, {args.country}", file=sys.stderr)

    if not blogs:
        print("No blogs to analyze", file=sys.stderr)
        update_progress(progress_path, args.country, args.region, 0, 0)
        return

    # Load existing spots for dedup
    existing_spots = []
    if db_path.exists():
        existing_spots = json.loads(db_path.read_text(encoding="utf-8"))

    # Build blog content string for Claude (truncate to fit context)
    blog_texts = []
    for b in blogs:
        blog_texts.append(f"=== {b['title']} ===\nURL: {b['url']}\n"
                         f"Enthusiasm: {b.get('meta', {}).get('enthusiasm_keywords', [])}\n"
                         f"{b['content']}\n")

    blogs_content = "\n".join(blog_texts)
    # Truncate if too long (keep under ~100k chars for Claude context)
    if len(blogs_content) > 100000:
        blogs_content = blogs_content[:100000]
        print("  Warning: truncated blog content to 100k chars", file=sys.stderr)

    # Call Claude to analyze
    print(f"Sending {len(blogs)} blogs to Claude for analysis...", file=sys.stderr)
    new_spots = call_claude(blogs_content, args.region, args.country, existing_spots)
    print(f"Claude extracted {len(new_spots)} qualifying spots", file=sys.stderr)

    # Merge into DB
    spots_added = merge_spots(db_path, new_spots)

    # Update progress
    update_progress(progress_path, args.country, args.region, len(blogs), spots_added)

    print(f"\n=== Done: {spots_added} spots added from {args.region} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
