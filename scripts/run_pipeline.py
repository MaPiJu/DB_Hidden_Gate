#!/usr/bin/env python3
"""
Search pipeline orchestrator: search blogs for each unsearched region and save results.

Runs search_blogs.py for each unsearched region, saves raw blog JSON to blogs/<country>/<region>.json,
and updates search_progress.json with status "fetched".

Analysis is done separately by Claude Code (not this script).

Usage:
    python3 scripts/run_pipeline.py --country vietnam
    python3 scripts/run_pipeline.py --country vietnam --max-regions 3
"""

from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


def get_unsearched_regions(progress_path: Path, country: str) -> list[str]:
    """Get list of regions not yet fetched for a country."""
    if not progress_path.exists():
        return []

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    country_data = progress.get(country.lower(), {})
    all_regions = country_data.get("regions", [])
    searched = country_data.get("searched", {})

    return [r for r in all_regions if r not in searched]


def run_search(region: str, country: str, project_root: Path, blogs_dir: Path) -> tuple[Path | None, int]:
    """Run search_blogs.py and save output to blogs/<country>/<region>.json.

    Returns (output_path, blog_count) or (None, 0) on failure.
    """
    # Slugify region name for filename
    region_slug = region.lower().replace(" ", "-").replace("'", "")
    output_file = blogs_dir / f"{region_slug}.json"

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
            return None, 0

        data = json.loads(output_file.read_text())
        blog_count = len(data)
        print(f"  Saved {blog_count} blogs to {output_file}", file=sys.stderr)

        if blog_count == 0:
            output_file.unlink(missing_ok=True)
            return None, 0

        return output_file, blog_count

    except Exception as e:
        print(f"  [ERROR] Search failed: {e}", file=sys.stderr)
        return None, 0


def update_progress(progress_path: Path, country: str, region: str, blogs_found: int, status: str):
    """Update search_progress.json with fetch status."""
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
        "status": status,
    }

    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run blog search pipeline (fetch only).")
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

    if args.max_regions > 0:
        unsearched = unsearched[:args.max_regions]

    print(f"Will search {len(unsearched)} regions: {unsearched}", file=sys.stderr)

    # Create blogs output directory
    blogs_dir = project_root / "blogs" / args.country.lower()
    blogs_dir.mkdir(parents=True, exist_ok=True)

    total_blogs = 0
    for region in unsearched:
        output_path, blog_count = run_search(region, args.country, project_root, blogs_dir)
        total_blogs += blog_count

        status = "fetched" if blog_count > 0 else "fetched_empty"
        update_progress(progress_path, args.country, region, blog_count, status)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"FETCH COMPLETE: {total_blogs} total blogs from {len(unsearched)} regions", file=sys.stderr)
    print(f"Saved to: {blogs_dir}/", file=sys.stderr)
    print(f"Next step: open Claude Code and say 'analyze {args.country}'", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)


if __name__ == "__main__":
    main()
