#!/usr/bin/env python3
"""
CopeCheck — Brave Search News Scanner

Searches for each tracked figure via the Brave Search API,
deduplicates against existing DB entries, fetches articles,
and scores them through the Oracle.

Usage:
  python3 brave_news_scan.py                     # scan all figures
  python3 brave_news_scan.py --figure elon-musk  # scan one figure
  python3 brave_news_scan.py --dry-run           # show what would be fetched
  python3 brave_news_scan.py --max-per-figure 2  # limit per figure
"""
import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import db
import oracle
import pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("brave_scan")

BRAVE_API_KEY = ""
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_PER_FIGURE = 3
SEARCH_FRESHNESS = "pw"  # past week

SKIP_DOMAINS = [
    "twitter.com", "x.com", "youtube.com", "facebook.com",
    "instagram.com", "tiktok.com", "reddit.com", "pinterest.com",
    "linkedin.com",
]


def brave_search(query, count=10):
    if not BRAVE_API_KEY:
        log.error("BRAVE_API_KEY not set")
        return []
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {
        "q": query,
        "count": count,
        "freshness": SEARCH_FRESHNESS,
        "text_decorations": False,
        "search_lang": "en",
    }
    try:
        resp = requests.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "age": item.get("age", ""),
            })
        return results
    except Exception as e:
        log.warning("Brave search failed for %s: %s", query, e)
        return []


def _norm_title(title):
    return re.sub(r"\W+", " ", (title or "").lower()).strip()


def url_already_scored(url, figure_id):
    """Check if this URL is already in cope_entries for this figure."""
    with db.conn() as c:
        row = c.execute(
            "SELECT 1 FROM cope_entries WHERE figure_id = ? AND source_url = ? LIMIT 1",
            (figure_id, url)
        ).fetchone()
        return row is not None


def title_already_scored(title, figure_id):
    """Fuzzy dedup: check if a very similar title exists for this figure."""
    norm = _norm_title(title)
    with db.conn() as c:
        existing = c.execute(
            "SELECT source_title FROM cope_entries WHERE figure_id = ?",
            (figure_id,)
        ).fetchall()
        for row in existing:
            if _norm_title(row[0]) == norm:
                return True
        # Also partial match (first 40 chars normalised)
        short = norm[:40]
        for row in existing:
            if _norm_title(row[0])[:40] == short:
                return True
    return False


def scan_figure(figure, max_new=MAX_PER_FIGURE, dry_run=False):
    name = figure["name"]
    fig_id = figure["id"]
    queries = figure.get("search_queries", [])
    if not queries:
        return 0

    scored = 0
    seen_urls = set()

    for query in queries:
        if scored >= max_new:
            break

        log.info("Brave: %s", query)
        results = brave_search(query)
        time.sleep(1.1)  # 1 req/sec rate limit

        for result in results:
            if scored >= max_new:
                break
            url = result["url"]
            title = result["title"]
            if not url or not title:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Skip social / video
            if any(d in url.lower() for d in SKIP_DOMAINS):
                continue

            # Dedup by URL
            if db.exists(url):
                log.debug("URL in articles table: %s", url[:60])
                continue
            if url_already_scored(url, fig_id):
                log.debug("URL already scored for %s: %s", name, url[:60])
                continue

            # Dedup by title
            if title_already_scored(title, fig_id):
                log.debug("Similar title already scored: %s", title[:60])
                continue

            if dry_run:
                log.info("[DRY RUN] Would fetch: %s — %s", name, title[:70])
                scored += 1
                continue

            # Fetch article body
            log.info("Fetching: %s", title[:70])
            body = pipeline.fetch_article(url)
            if len(body) < 200:
                log.debug("Too short, skipping: %s", url[:60])
                continue

            # Extract context around figure name (now uses word-boundary matching)
            quote_context = pipeline._extract_figure_context(body, name)
            if not quote_context or len(quote_context) < 80:
                log.debug("No relevant context for %s", name)
                continue

            # Verify attribution: confirm the figure is genuinely in this article
            import re as _re
            body_lower = body.lower()
            name_lower = name.lower()
            last_name = name.split()[-1].lower()
            full_count = len(_re.findall(r'\b' + _re.escape(name_lower) + r'\b', body_lower))
            last_count = len(_re.findall(r'\b' + _re.escape(last_name) + r'\b', body_lower)) if len(last_name) >= 4 else 0

            # Require: full name at least once, OR long last name 3+ times
            if full_count == 0 and last_count < 3:
                log.info("SKIP attribution check failed for %s in '%s' (full=%d, last=%d)",
                         name, title[:50], full_count, last_count)
                continue

            # Score through Oracle
            try:
                log.info("Scoring: %s -> %s", name, title[:60])
                cope_result = oracle.score_cope(
                    name, figure.get("title", ""),
                    quote_context,
                    source_context="From: " + title,
                )
                db.add_cope_entry(
                    figure_id=fig_id,
                    article_slug=None,
                    quote=cope_result.get("cope_quote") or quote_context[:300],
                    source_url=url,
                    source_title=title,
                    cope_score=cope_result["cope_score"],
                    cope_type=cope_result.get("cope_type", "unknown"),
                    analysis_md=cope_result.get("analysis", ""),
                    model=cope_result.get("model", ""),
                )
                scored += 1
                log.info("OK: %s score=%s type=%s",
                        name, cope_result["cope_score"],
                        cope_result.get("cope_type", "?"))
                time.sleep(2)
            except Exception as e:
                log.warning("Score failed %s: %s", name, e)

    return scored


def load_figures():
    import yaml
    fig_path = Path(__file__).resolve().parent.parent / "figures.yaml"
    with open(fig_path) as f:
        data = yaml.safe_load(f)
    return data.get("figures", [])


def main():
    parser = argparse.ArgumentParser(description="CopeCheck Brave News Scanner")
    parser.add_argument("--figure", help="Only scan this figure ID")
    parser.add_argument("--max-per-figure", type=int, default=MAX_PER_FIGURE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    global BRAVE_API_KEY
    BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "").strip()

    if not BRAVE_API_KEY:
        log.error("BRAVE_API_KEY not set in .env")
        sys.exit(1)

    db.init()
    figures = load_figures()

    if args.figure:
        figures = [f for f in figures if f["id"] == args.figure]
        if not figures:
            log.error("Figure %s not found", args.figure)
            sys.exit(1)

    total = 0
    for fig in figures:
        n = scan_figure(fig, max_new=args.max_per_figure, dry_run=args.dry_run)
        total += n
        log.info("=== %s: %d new ===", fig["name"], n)

    log.info("Done: %d new entries across %d figures", total, len(figures))


if __name__ == "__main__":
    main()
