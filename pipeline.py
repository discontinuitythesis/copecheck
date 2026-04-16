"""CopeCheck v2 ingestion pipeline.

Two modes:
  --news    : Pull RSS feeds, filter, fetch articles, run through Oracle
  --cope    : Scan for tracked figure quotes, score cope levels
  (no args) : Run both sequentially
"""
import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import trafilatura
import yaml
from dateutil import parser as dateparser

import db
import oracle
import sources

log = logging.getLogger("pipeline")

MAX_NEW_PER_RUN = int(os.environ.get("COPECHECK_MAX_NEW", "30"))
MAX_ANALYSE_PER_RUN = int(os.environ.get("COPECHECK_MAX_ANALYSE", "12"))
MAX_COPE_SCAN_PER_FIGURE = int(os.environ.get("COPECHECK_MAX_COPE_SCAN", "3"))
MIN_BODY_CHARS = 350
FETCH_TIMEOUT = 25

FIGURES_PATH = Path(__file__).parent / "figures.yaml"


def _hash_title(title: str) -> str:
    norm = re.sub(r"\W+", " ", (title or "").lower()).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _matches_topic(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in sources.TOPIC_KEYWORDS)


def _clean_url(u: str) -> str:
    if not u:
        return u
    return u


def _parse_date(entry) -> str | None:
    for key in ("published", "updated", "created"):
        v = entry.get(key)
        if v:
            try:
                return dateparser.parse(v).astimezone(timezone.utc).isoformat()
            except Exception:
                continue
    return None


def _entry_snippet(entry) -> str:
    raw = entry.get("summary", "") or entry.get("description", "")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def fetch_article(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=False)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=False, favor_recall=True,
        )
        return (text or "").strip()
    except Exception as e:
        log.warning("fetch_article failed for %s: %s", url, e)
        return ""


def ingest_feeds() -> int:
    seen_title_hashes: set[str] = set()
    inserted = 0
    for source_name, feed_url in sources.ALL_FEEDS:
        if inserted >= MAX_NEW_PER_RUN:
            break
        log.info("feed scan: %s", source_name)
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            log.warning("feed parse failed %s: %s", source_name, e)
            continue
        if parsed.bozo and not parsed.entries:
            continue

        narrow = source_name in sources.TRUSTED_NARROW_FEEDS

        for entry in parsed.entries[:25]:
            if inserted >= MAX_NEW_PER_RUN:
                break
            url = _clean_url(entry.get("link", ""))
            title = (entry.get("title") or "").strip()
            if not url or not title:
                continue
            if db.exists(url):
                continue
            th = _hash_title(title)
            if th in seen_title_hashes:
                continue
            seen_title_hashes.add(th)

            snippet = _entry_snippet(entry)
            search_blob = f"{title}\n{snippet}"
            if not narrow and not _matches_topic(search_blob):
                continue

            body = fetch_article(url)
            if len(body) < MIN_BODY_CHARS:
                if len(snippet) > MIN_BODY_CHARS:
                    body = snippet
                else:
                    continue

            if not narrow and not _matches_topic(body[:4000]):
                continue

            pub = _parse_date(entry)
            slug = db.insert_pending(url, title, source_name, pub, snippet, body)
            if slug:
                inserted += 1
                log.info("queued [%s] %s", source_name, title[:90])
    log.info("ingestion done: %d new pending", inserted)
    return inserted


def analyse_pending() -> int:
    pending = db.pending_for_analysis(limit=MAX_ANALYSE_PER_RUN)
    if not pending:
        log.info("no pending articles")
        return 0
    done = 0
    for row in pending:
        slug = row["slug"]
        try:
            log.info("oracle -> [%s] %s", row["source"], row["title"][:90])
            result = oracle.consult(
                title=row["title"], url=row["url"],
                source=row["source"],
                article_text=row["body"] or row["snippet"] or "",
            )
            one_liner = oracle.extract_one_liner(result["verdict_md"])
            db.set_verdict(slug, result["verdict_md"], one_liner,
                          result["model"], result["price"])
            done += 1
            _crosslink_figures(row, result)
            time.sleep(2)
        except Exception as e:
            log.exception("oracle failed for slug=%s", slug)
            db.set_failed(slug, str(e))
    log.info("oracle pass done: %d analysed", done)
    return done


def _crosslink_figures(article_row, oracle_result):
    figures = _load_figures()
    if not figures:
        return
    text = (article_row.get("body") or article_row.get("snippet") or "").lower()
    title = (article_row.get("title") or "").lower()

    for fig in figures:
        name_parts = fig["name"].lower().split()
        last_name = name_parts[-1] if name_parts else ""
        if last_name in text or last_name in title or fig["name"].lower() in text:
            quote_context = _extract_figure_context(
                article_row.get("body") or article_row.get("snippet") or "",
                fig["name"]
            )
            if quote_context and len(quote_context) > 50:
                try:
                    log.info("cope cross-link: %s in article %s",
                             fig["name"], article_row["slug"][:40])
                    cope_result = oracle.score_cope(
                        fig["name"], fig.get("title", ""),
                        quote_context,
                        source_context=f"From article: {article_row['title']}"
                    )
                    db.add_cope_entry(
                        figure_id=fig["id"],
                        article_slug=article_row["slug"],
                        quote=cope_result.get("cope_quote") or quote_context[:300],
                        source_url=article_row["url"],
                        source_title=article_row["title"],
                        cope_score=cope_result["cope_score"],
                        cope_type=cope_result.get("cope_type", "unknown"),
                        analysis_md=cope_result.get("analysis", ""),
                        model=cope_result.get("model", ""),
                    )
                    time.sleep(1)
                except Exception as e:
                    log.warning("cope cross-link failed for %s: %s", fig["name"], e)


def _extract_figure_context(text: str, name: str, window=800) -> str:
    lower = text.lower()
    name_lower = name.lower()
    last_name = name.split()[-1].lower()

    positions = []
    for search_term in [name_lower, last_name]:
        start = 0
        while True:
            idx = lower.find(search_term, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + len(search_term)

    if not positions:
        return ""

    chunks = []
    for pos in positions[:3]:
        s = max(0, pos - window // 2)
        e = min(len(text), pos + window // 2)
        chunks.append(text[s:e])

    return "\n...\n".join(chunks)


def _load_figures() -> list[dict]:
    if not FIGURES_PATH.exists():
        log.warning("figures.yaml not found at %s", FIGURES_PATH)
        return []
    with open(FIGURES_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("figures", [])


def sync_figures():
    figures = _load_figures()
    for fig in figures:
        db.upsert_figure(
            fig["id"], fig["name"], fig.get("title"),
            fig.get("category"), fig.get("photo_url"),
            fig.get("cope_bias"),
        )
    log.info("synced %d figures to DB", len(figures))
    return figures


def scan_figure_news() -> int:
    figures = _load_figures()
    if not figures:
        return 0

    total_scored = 0
    for fig in figures:
        queries = fig.get("search_queries", [])
        if not queries:
            continue

        scored_this_figure = 0
        for query in queries:
            if scored_this_figure >= MAX_COPE_SCAN_PER_FIGURE:
                break

            feed_url = sources.google_news_url(query)
            try:
                parsed = feedparser.parse(feed_url)
            except Exception:
                continue

            for entry in parsed.entries[:5]:
                if scored_this_figure >= MAX_COPE_SCAN_PER_FIGURE:
                    break
                url = entry.get("link", "")
                title = (entry.get("title") or "").strip()
                if not url or not title:
                    continue

                body = fetch_article(url)
                if len(body) < 200:
                    continue

                quote_context = _extract_figure_context(body, fig["name"])
                if not quote_context or len(quote_context) < 80:
                    continue

                if db.cope_entry_exists(fig["id"], quote_context[:200]):
                    continue

                try:
                    log.info("cope scan: %s -> %s", fig["name"], title[:60])
                    cope_result = oracle.score_cope(
                        fig["name"], fig.get("title", ""),
                        quote_context,
                        source_context=f"From: {title}",
                    )
                    db.add_cope_entry(
                        figure_id=fig["id"],
                        article_slug=None,
                        quote=cope_result.get("cope_quote") or quote_context[:300],
                        source_url=url,
                        source_title=title,
                        cope_score=cope_result["cope_score"],
                        cope_type=cope_result.get("cope_type", "unknown"),
                        analysis_md=cope_result.get("analysis", ""),
                        model=cope_result.get("model", ""),
                    )
                    scored_this_figure += 1
                    total_scored += 1
                    time.sleep(2)
                except Exception as e:
                    log.warning("cope score failed for %s: %s", fig["name"], e)

    log.info("cope scan done: %d new scores", total_scored)
    return total_scored


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                str(Path(__file__).parent / "logs" / "pipeline.log"),
                encoding="utf-8",
            ),
        ],
    )
    db.init()

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    started = datetime.now(timezone.utc).isoformat()
    log.info("=== copecheck v2 pipeline start mode=%s %s ===", mode, started)

    sync_figures()

    if mode in ("all", "news"):
        n_new = ingest_feeds()
        n_done = analyse_pending()
        log.info("news pipeline: ingested=%d analysed=%d", n_new, n_done)

    if mode in ("all", "cope"):
        n_cope = scan_figure_news()
        log.info("cope pipeline: scored=%d", n_cope)

    snapshot = db.counts()
    log.info("counts: %s", snapshot)
    log.info("=== copecheck v2 pipeline done ===")


if __name__ == "__main__":
    main()
