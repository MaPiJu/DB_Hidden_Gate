#!/usr/bin/env python3
"""
Full pipeline orchestrator: search blogs → analyze with Claude → merge into DB.

Designed to run in GitHub Actions but works locally too.

Usage:
    python3 scripts/run_pipeline.py --country vietnam
    python3 scripts/run_pipeline.py --country vietnam --max-regions 3
"""

from __future__ import annotations
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def get_unsearched_regions(progress_path: Path, country: str) -> list[str]:
    """Get list of regions not yet searched for a country."""
    if not progress_path.exists():
        return []

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    country_data = progress.get(country.lower(), {})
    all_regions = country_data.get("regions", [])
    searched = set(country_data.get("searched", {}).keys())

    return [r for r in all_regions if r not in searched]


def run_search(region: str, country: str, project_root: Path) -> Path | None:
    """Run search_blogs.py and return path to output JSON."""
    output_file = Path(tempfile.mktemp(suffix=".json"))

    query = f"{region} {country}"
    cmd = [
        sys.executable, str(project_root / "scripts" / "search_blogs.py"),
        query,
        "--db", str(project_root / "spots_database.json"),
    ]

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SEARCHING: {region}, {country}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    try:
        with open(output_file, "w") as f:
            result = subprocess.run(cmd, stdout=f, stderr=sys.stderr, timeout=300)
        if result.returncode != 0:
            print(f"  [ERROR] search_blogs.py returned {result.returncode}", file=sys.stderr)
            return None

        # Verify valid JSON
        data = json.loads(output_file.read_text())
        print(f"  Search returned {len(data)} qualifying blogs", file=sys.stderr)
        return output_file if data else None

    except Exception as e:
        print(f"  [ERROR] Search failed: {e}", file=sys.stderr)
        return None


def run_analysis(region: str, country: str, blogs_path: Path, project_root: Path):
    """Run analyze_and_merge.py to process blogs with Claude."""
    cmd = [
        sys.executable, str(project_root / "scripts" / "analyze_and_merge.py"),
        "--region", region,
        "--country", country,
        "--blogs", str(blogs_path),
        "--db", str(project_root / "spots_database.json"),
        "--progress", str(project_root / "search_progress.json"),
    ]

    print(f"\nANALYZING: {region} blogs with Claude...", file=sys.stderr)

    try:
        result = subprocess.run(cmd, stderr=sys.stderr, timeout=180)
        if result.returncode != 0:
            print(f"  [ERROR] analyze_and_merge.py returned {result.returncode}", file=sys.stderr)
    except Exception as e:
        print(f"  [ERROR] Analysis failed: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Run full search pipeline.")
    parser.add_argument("--country", required=True, help="Country to search")
    parser.add_argument("--max-regions", type=int, default=0,
                        help="Max regions to search (0 = all remaining)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    progress_path = project_root / "search_progress.json"

    # Get unsearched regions
    unsearched = get_unsearched_regions(progress_path, args.country)

    if not unsearched:
        print(f"All regions for {args.country} have been searched!", file=sys.stderr)
        return

    # Limit regions if requested
    if args.max_regions > 0:
        unsearched = unsearched[:args.max_regions]

    print(f"Will search {len(unsearched)} regions: {unsearched}", file=sys.stderr)

    total_spots = 0
    for region in unsearched:
        # Step 1: Search blogs
        blogs_path = run_search(region, args.country, project_root)

        if blogs_path:
            # Step 2: Analyze and merge
            # Count spots before
            db_path = project_root / "spots_database.json"
            before = len(json.loads(db_path.read_text())) if db_path.exists() else 0

            run_analysis(region, args.country, blogs_path, project_root)

            after = len(json.loads(db_path.read_text())) if db_path.exists() else 0
            added = after - before
            total_spots += added
            print(f"\n  {region}: +{added} spots (DB now has {after} total)", file=sys.stderr)

            # Clean up temp file
            blogs_path.unlink(missing_ok=True)
        else:
            # No blogs found — still mark as searched
            from scripts.analyze_and_merge import update_progress
            update_progress(progress_path, args.country, region, 0, 0)
            print(f"\n  {region}: no qualifying blogs found", file=sys.stderr)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"PIPELINE COMPLETE: {total_spots} total spots added from {len(unsearched)} regions", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)


if __name__ == "__main__":
    main()
