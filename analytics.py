"""Lightweight pageview analytics for CopeCheck — SQLite-backed, no cookies, no external services."""
import hashlib
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import db as main_db  # reuse the DB_PATH from main db module

ANALYTICS_DB = str(Path(main_db.DB_PATH).parent / "analytics.db")

# Bot user-agent patterns to skip
BOT_PATTERNS = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|twitterbot|"
    r"linkedinbot|whatsapp|telegrambot|discordbot|googlebot|yandexbot|"
    r"baiduspider|duckduckbot|semrush|ahref|mj12bot|dotbot|petalbot|"
    r"bytespider|gptbot|claudebot|anthropic|ccbot|dataforseo|seznambot|"
    r"ia_archiver|archive\.org",
    re.IGNORECASE,
)

# Paths to skip logging
SKIP_PREFIXES = ("/static/", "/admin", "/healthz", "/robots.txt", "/favicon")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pageviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL,
    referrer    TEXT,
    user_agent  TEXT,
    ip_hash     TEXT,
    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_pv_timestamp ON pageviews(timestamp);
CREATE INDEX IF NOT EXISTS idx_pv_path ON pageviews(path);
CREATE INDEX IF NOT EXISTS idx_pv_ip_hash ON pageviews(ip_hash);
"""


@contextmanager
def aconn():
    """Analytics DB connection."""
    c = sqlite3.connect(ANALYTICS_DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_analytics():
    """Create the pageviews table if it doesn't exist."""
    with aconn() as c:
        c.executescript(SCHEMA)


def _hash_ip(ip_raw: str) -> str:
    """Hash IP for privacy — one-way, no recovery."""
    salted = f"copecheck-salt-2024:{ip_raw}"
    return hashlib.sha256(salted.encode()).hexdigest()[:16]


def _is_bot(user_agent: str) -> bool:
    return bool(BOT_PATTERNS.search(user_agent or ""))


def _should_skip(path: str) -> bool:
    return any(path.startswith(p) for p in SKIP_PREFIXES)


def log_pageview(request):
    """Log a pageview from a Flask request object. Returns immediately, inserts in background."""
    path = request.path
    if _should_skip(path):
        return
    ua = request.headers.get("User-Agent", "")
    if _is_bot(ua):
        return
    if request.method != "GET":
        return

    referrer = request.headers.get("Referer", "")
    ip_raw = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ip_hash = _hash_ip(ip_raw)

    def _insert():
        try:
            with aconn() as c:
                c.execute(
                    "INSERT INTO pageviews (path, referrer, user_agent, ip_hash) VALUES (?, ?, ?, ?)",
                    (path, referrer[:500] if referrer else "", ua[:300] if ua else "", ip_hash),
                )
        except Exception:
            pass

    threading.Thread(target=_insert, daemon=True).start()


def purge_old(days=90):
    """Delete pageviews older than N days."""
    with aconn() as c:
        c.execute(
            "DELETE FROM pageviews WHERE timestamp < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
            (f"-{days} days",),
        )
        deleted = c.execute("SELECT changes()").fetchone()[0]
    return deleted


def _time_filter(period):
    if period == "today":
        return "AND timestamp >= strftime('%Y-%m-%dT00:00:00', 'now')"
    elif period == "7d":
        return "AND timestamp >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')"
    elif period == "30d":
        return "AND timestamp >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-30 days')"
    return ""


def get_overview(period="30d"):
    tf = _time_filter(period)
    with aconn() as c:
        row = c.execute(f"""
            SELECT COUNT(*) as total_views,
                   COUNT(DISTINCT ip_hash) as unique_visitors
            FROM pageviews WHERE 1=1 {tf}
        """).fetchone()
        return {"total_views": row["total_views"], "unique_visitors": row["unique_visitors"]}


def get_top_pages(period="30d", limit=20):
    tf = _time_filter(period)
    with aconn() as c:
        cur = c.execute(f"""
            SELECT path, COUNT(*) as views
            FROM pageviews WHERE 1=1 {tf}
            GROUP BY path ORDER BY views DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_top_referrers(period="30d", limit=20):
    tf = _time_filter(period)
    with aconn() as c:
        cur = c.execute(f"""
            SELECT
                CASE
                    WHEN referrer = '' OR referrer IS NULL THEN '(direct)'
                    WHEN referrer LIKE '%copecheck.com%' THEN '(internal)'
                    ELSE SUBSTR(referrer,
                        INSTR(referrer, '://') + 3,
                        CASE
                            WHEN INSTR(SUBSTR(referrer, INSTR(referrer, '://') + 3), '/') > 0
                            THEN INSTR(SUBSTR(referrer, INSTR(referrer, '://') + 3), '/') - 1
                            ELSE LENGTH(referrer)
                        END
                    )
                END as domain,
                COUNT(*) as views
            FROM pageviews WHERE 1=1 {tf}
            GROUP BY domain ORDER BY views DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_most_viewed_figures(period="30d", limit=20):
    tf = _time_filter(period)
    with aconn() as c:
        cur = c.execute(f"""
            SELECT path,
                   REPLACE(path, '/figure/', '') as figure_id,
                   COUNT(*) as views
            FROM pageviews
            WHERE path LIKE '/figure/%' {tf}
            GROUP BY path ORDER BY views DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_most_viewed_articles(period="30d", limit=20):
    tf = _time_filter(period)
    with aconn() as c:
        cur = c.execute(f"""
            SELECT path,
                   REPLACE(path, '/v/', '') as slug,
                   COUNT(*) as views
            FROM pageviews
            WHERE path LIKE '/v/%' {tf}
            GROUP BY path ORDER BY views DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_most_searched_instant(period="30d", limit=20):
    tf = _time_filter(period)
    with aconn() as c:
        cur = c.execute(f"""
            SELECT path,
                   REPLACE(path, '/instant/', '') as name_slug,
                   COUNT(*) as views
            FROM pageviews
            WHERE path LIKE '/instant/%' AND path != '/instant' {tf}
            GROUP BY path ORDER BY views DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_daily_views(days=30):
    with aconn() as c:
        cur = c.execute("""
            SELECT DATE(timestamp) as day,
                   COUNT(*) as views,
                   COUNT(DISTINCT ip_hash) as visitors
            FROM pageviews
            WHERE timestamp >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
            GROUP BY day ORDER BY day ASC
        """, (f"-{days} days",))
        return [dict(r) for r in cur.fetchall()]
