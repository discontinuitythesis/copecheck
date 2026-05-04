#!/usr/bin/env python3
"""
Brave Search scorer for CopeCheck main site figures.
Uses Brave Search API -> trafilatura -> oracle.score_cope() pipeline.
"""
import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests
import trafilatura
import yaml

sys.path.insert(0, os.path.dirname(__file__))
import db
import oracle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            str(Path(__file__).parent / "logs" / "brave_scorer.log"),
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("brave_scorer")

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "").strip()
FIGURES_PATH = Path(__file__).parent / "figures.yaml"
MIN_BODY = 300
MAX_PER_FIGURE = 3
FETCH_TIMEOUT = 25

# Skip domains unlikely to have scorable content
SKIP_DOMAINS = {
    "wikipedia.org", "britannica.com", "linkedin.com", "twitter.com",
    "x.com", "facebook.com", "instagram.com", "youtube.com",
    "imdb.com", "amazon.com", "reddit.com", "tiktok.com",
}


def load_figures():
    """Load figures from figures.yaml."""
    if not FIGURES_PATH.exists():
        log.warning("figures.yaml not found at %s", FIGURES_PATH)
        return []
    with open(FIGURES_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("figures", [])


def brave_search(query, count=8):
    """Search using Brave Search API. Returns list of {url, title, description}."""
    if not BRAVE_API_KEY:
        raise RuntimeError("BRAVE_API_KEY not set")
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": count, "search_lang": "en", "freshness": "pm"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("web", {}).get("results", []):
            results.append({
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "description": r.get("description", ""),
            })
        return results
    except Exception as e:
        log.warning("Brave search error for '%s': %s", query, e)
        return []


def fetch_article(url):
    """Fetch article text via trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return "", ""
        text = trafilatura.extract(downloaded, include_comments=False) or ""
        # Try to get title
        metadata = trafilatura.extract(downloaded, output_format="json",
                                        include_comments=False)
        title = ""
        if metadata:
            import json
            try:
                meta = json.loads(metadata)
                title = meta.get("title", "")
            except Exception:
                pass
        return text, title
    except Exception as e:
        log.debug("trafilatura failed for %s: %s", url[:60], e)
        return "", ""


def should_skip_url(url):
    """Skip reference/social URLs that won't have scorable articles."""
    for d in SKIP_DOMAINS:
        if d in url.lower():
            return True
    return False


def extract_figure_context(text, name, window=800):
    """Extract text around mentions of a figure. Requires strong name match."""
    lower = text.lower()
    name_lower = name.lower()
    last_name = name.split()[-1].lower()

    def _word_boundary_find(haystack, needle):
        positions = []
        pattern = re.compile(r'\b' + re.escape(needle) + r'\b')
        for m in pattern.finditer(haystack):
            positions.append(m.start())
        return positions

    full_positions = _word_boundary_find(lower, name_lower)
    last_positions = []
    if len(last_name) >= 4:
        last_positions = _word_boundary_find(lower, last_name)

    if full_positions:
        positions = sorted(set(full_positions + last_positions))
    elif len(last_positions) >= 2:
        positions = last_positions
    else:
        return ""

    if not positions:
        return ""

    chunks = []
    for pos in positions[:3]:
        s = max(0, pos - window // 2)
        e = min(len(text), pos + window // 2)
        chunks.append(text[s:e])

    return "\n...\n".join(chunks)


def main():
    log.info("=== CopeCheck Brave Search Scorer ===")
    db.init()

    if not BRAVE_API_KEY:
        log.error("BRAVE_API_KEY not set in environment — aborting")
        sys.exit(1)

    figures = load_figures()
    if not figures:
        log.error("No figures loaded from figures.yaml")
        sys.exit(1)

    log.info("Loaded %d figures", len(figures))
    seen_urls = set()
    total_scored = 0

    for fig in figures:
        queries = fig.get("search_queries", [])
        if not queries:
            continue

        fig_id = fig["id"]
        fig_name = fig["name"]
        fig_title = fig.get("title", "")
        log.info("--- Processing: %s (%s) ---", fig_name, fig_id)
        scored_this_fig = 0

        for query in queries:
            if scored_this_fig >= MAX_PER_FIGURE:
                break

            log.info("Brave search: '%s'", query)
            results = brave_search(query)
            log.info("  got %d results", len(results))

            for r in results:
                if scored_this_fig >= MAX_PER_FIGURE:
                    break

                url = r["url"]
                title = r["title"]

                if url in seen_urls or should_skip_url(url):
                    continue
                seen_urls.add(url)

                # Check if already scored for this figure
                if db.exists(url):
                    log.info("  already in DB: %s", url[:60])
                    continue


                log.info("  trying: %s", url[:80])
                body, fetched_title = fetch_article(url)
                if not fetched_title:
                    fetched_title = title

                if len(body) < MIN_BODY:
                    log.info("    body too short (%d chars)", len(body))
                    continue

                quote_context = extract_figure_context(body, fig_name)
                if not quote_context or len(quote_context) < 80:
                    log.info("    no/short context for %s", fig_name)
                    continue

                if db.cope_entry_exists(fig_id, quote_context[:200]):
                    log.info("    cope entry already exists")
                    continue

                try:
                    log.info("    name found, scoring via oracle...")
                    cope_result = oracle.score_cope(
                        fig_name, fig_title,
                        quote_context,
                        source_context=f"From: {fetched_title}",
                    )
                    db.add_cope_entry(
                        figure_id=fig_id,
                        article_slug=None,
                        quote=cope_result.get("cope_quote") or quote_context[:300],
                        source_url=url,
                        source_title=fetched_title,
                        cope_score=cope_result["cope_score"],
                        cope_type=cope_result.get("cope_type", "unknown"),
                        analysis_md=cope_result.get("analysis", ""),
                        model=cope_result.get("model", ""),
                    )
                    scored_this_fig += 1
                    total_scored += 1
                    log.info("    SCORED %s: score=%s type=%s",
                             fig_name, cope_result.get("cope_score"),
                             cope_result.get("cope_type"))
                except Exception as e:
                    log.warning("    scoring error for %s: %s", fig_name, e)

                time.sleep(1.5)  # Rate limit between articles

            time.sleep(1)  # Rate limit between queries

        log.info("  %s: %d new scores", fig_name, scored_this_fig)

    log.info("=== DONE === Total new scored: %d", total_scored)
    counts = db.counts()
    log.info("DB counts: %s", counts)


if __name__ == "__main__":
    main()
