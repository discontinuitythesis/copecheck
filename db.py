"""SQLite storage for CopeCheck v2 — articles, figures, cope scores, comments, submissions."""
import os
import re
import sqlite3
import hashlib
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get(
    "COPECHECK_DB",
    str(Path(__file__).parent / "data" / "copecheck.db"),
)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT UNIQUE NOT NULL,
    url         TEXT NOT NULL,
    url_hash    TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    source      TEXT NOT NULL,
    published   TEXT,
    snippet     TEXT,
    body        TEXT,
    verdict_md  TEXT,
    one_liner   TEXT,
    model       TEXT,
    price       REAL,
    status      TEXT DEFAULT 'pending',
    error       TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    analysed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_analysed ON articles(analysed_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);

CREATE TABLE IF NOT EXISTS figures (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    title       TEXT,
    category    TEXT,
    photo_url   TEXT,
    cope_bias   TEXT,
    cope_score  REAL DEFAULT 50.0,
    prev_score  REAL DEFAULT 50.0,
    total_quotes INTEGER DEFAULT 0,
    last_quote  TEXT,
    last_cope_type TEXT,
    last_scored TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cope_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    figure_id   TEXT NOT NULL REFERENCES figures(id),
    article_slug TEXT REFERENCES articles(slug),
    quote       TEXT NOT NULL,
    source_url  TEXT,
    source_title TEXT,
    cope_score  REAL NOT NULL,
    cope_type   TEXT,
    analysis_md TEXT,
    model       TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cope_figure ON cope_entries(figure_id, created_at DESC);

CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_slug TEXT NOT NULL,
    author_name TEXT DEFAULT 'Anonymous',
    body        TEXT NOT NULL,
    ip_hash     TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_comments_slug ON comments(article_slug, created_at ASC);

CREATE TABLE IF NOT EXISTS submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT,
    source      TEXT,
    url         TEXT,
    text_preview TEXT,
    body        TEXT,
    verdict_md  TEXT,
    one_liner   TEXT,
    model       TEXT,
    price       REAL,
    ip_hash     TEXT,
    status      TEXT DEFAULT 'pending',
    error       TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_submissions_created ON submissions(created_at DESC);

CREATE TABLE IF NOT EXISTS suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    reason      TEXT,
    example     TEXT,
    ip_hash     TEXT,
    status      TEXT DEFAULT 'pending',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    slug UNINDEXED, title, source, snippet, one_liner, verdict_md
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def make_slug(title: str, url: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:60]
    if not base:
        base = "article"
    return f"{base}-{url_hash(url)[:8]}"


def exists(url: str) -> bool:
    with conn() as c:
        cur = c.execute("SELECT 1 FROM articles WHERE url_hash = ? LIMIT 1", (url_hash(url),))
        return cur.fetchone() is not None


def by_url_hash(url: str):
    """Look up article by URL hash."""
    with conn() as c:
        cur = c.execute("SELECT * FROM articles WHERE url_hash = ?", (url_hash(url),))
        row = cur.fetchone()
        return dict(row) if row else None


def insert_pending(url, title, source, published, snippet, body):
    slug = make_slug(title, url)
    with conn() as c:
        try:
            c.execute(
                """INSERT INTO articles
                (slug, url, url_hash, title, source, published, snippet, body, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (slug, url, url_hash(url), title, source, published, snippet, body),
            )
            return slug
        except sqlite3.IntegrityError:
            return None


def set_verdict(slug, verdict_md, one_liner, model, price):
    with conn() as c:
        c.execute(
            """UPDATE articles
               SET verdict_md = ?, one_liner = ?, model = ?, price = ?,
                   status = 'analysed', analysed_at = CURRENT_TIMESTAMP,
                   error = NULL
               WHERE slug = ?""",
            (verdict_md, one_liner, model, price, slug),
        )


def set_failed(slug, error):
    with conn() as c:
        c.execute(
            "UPDATE articles SET status = 'failed', error = ? WHERE slug = ?",
            (error[:1000], slug),
        )


def pending_for_analysis(limit=25):
    with conn() as c:
        cur = c.execute(
            "SELECT * FROM articles WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def recent_analysed(limit=60):
    with conn() as c:
        cur = c.execute(
            """SELECT * FROM articles
               WHERE status = 'analysed' AND verdict_md IS NOT NULL
               ORDER BY analysed_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def by_slug(slug):
    with conn() as c:
        cur = c.execute("SELECT * FROM articles WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None


def counts():
    with conn() as c:
        cur = c.execute("SELECT status, COUNT(*) AS n FROM articles GROUP BY status")
        return {r["status"]: r["n"] for r in cur.fetchall()}


def upsert_figure(fig_id, name, title, category, photo_url, cope_bias):
    with conn() as c:
        c.execute(
            """INSERT INTO figures (id, name, title, category, photo_url, cope_bias)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name, title=excluded.title,
                   category=excluded.category, photo_url=excluded.photo_url,
                   cope_bias=excluded.cope_bias, updated_at=CURRENT_TIMESTAMP""",
            (fig_id, name, title, category, photo_url, cope_bias),
        )


def get_figure(fig_id):
    with conn() as c:
        cur = c.execute("SELECT * FROM figures WHERE id = ?", (fig_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_leaderboard():
    with conn() as c:
        cur = c.execute(
            """SELECT * FROM figures ORDER BY cope_score DESC, name ASC"""
        )
        return [dict(r) for r in cur.fetchall()]


def add_cope_entry(figure_id, article_slug, quote, source_url, source_title,
                   cope_score, cope_type, analysis_md, model):
    with conn() as c:
        c.execute(
            """INSERT INTO cope_entries
               (figure_id, article_slug, quote, source_url, source_title,
                cope_score, cope_type, analysis_md, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (figure_id, article_slug, quote, source_url, source_title,
             cope_score, cope_type, analysis_md, model),
        )
        cur = c.execute(
            """SELECT cope_score, created_at FROM cope_entries
               WHERE figure_id = ? ORDER BY created_at DESC LIMIT 20""",
            (figure_id,),
        )
        entries = cur.fetchall()
        if entries:
            total_w = 0.0
            total_s = 0.0
            for i, e in enumerate(entries):
                w = 0.85 ** i
                total_w += w
                total_s += e["cope_score"] * w
            new_avg = round(total_s / total_w, 1) if total_w > 0 else cope_score
            cur2 = c.execute("SELECT cope_score FROM figures WHERE id = ?", (figure_id,))
            old = cur2.fetchone()
            prev = old["cope_score"] if old else 50.0

            c.execute(
                """UPDATE figures SET
                       cope_score = ?, prev_score = ?,
                       total_quotes = (SELECT COUNT(*) FROM cope_entries WHERE figure_id = ?),
                       last_quote = ?, last_cope_type = ?,
                       last_scored = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (new_avg, prev, figure_id, quote[:500], cope_type, figure_id),
            )


def figure_entries(figure_id, limit=50):
    with conn() as c:
        cur = c.execute(
            """SELECT * FROM cope_entries
               WHERE figure_id = ? ORDER BY created_at DESC LIMIT ?""",
            (figure_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def figure_score_history(figure_id):
    """Get cope score history for chart data."""
    with conn() as c:
        cur = c.execute(
            """SELECT cope_score, created_at FROM cope_entries
               WHERE figure_id = ? ORDER BY created_at ASC""",
            (figure_id,),
        )
        return [{"score": r["cope_score"], "date": r["created_at"]} for r in cur.fetchall()]


def cope_entry_exists(figure_id, quote_hash):
    with conn() as c:
        cur = c.execute(
            """SELECT 1 FROM cope_entries
               WHERE figure_id = ? AND substr(quote, 1, 200) = ? LIMIT 1""",
            (figure_id, quote_hash[:200]),
        )
        return cur.fetchone() is not None


def add_comment(article_slug, author_name, body, ip_hash=None):
    with conn() as c:
        c.execute(
            """INSERT INTO comments (article_slug, author_name, body, ip_hash)
               VALUES (?, ?, ?, ?)""",
            (article_slug, (author_name or "Anonymous").strip()[:50],
             body.strip()[:2000], ip_hash),
        )


def get_comments(article_slug):
    with conn() as c:
        cur = c.execute(
            """SELECT id, author_name, body, created_at FROM comments
               WHERE article_slug = ? ORDER BY created_at ASC""",
            (article_slug,),
        )
        return [dict(r) for r in cur.fetchall()]


def comment_count(article_slug):
    with conn() as c:
        cur = c.execute(
            "SELECT COUNT(*) AS n FROM comments WHERE article_slug = ?",
            (article_slug,),
        )
        return cur.fetchone()["n"]


def recent_comments_by_ip(ip_hash, minutes=5):
    with conn() as c:
        cur = c.execute(
            """SELECT COUNT(*) AS n FROM comments
               WHERE ip_hash = ? AND created_at > datetime('now', ?)""",
            (ip_hash, f"-{minutes} minutes"),
        )
        return cur.fetchone()["n"]


# ─── SUBMISSIONS ──────────────────────────────────────────

def create_submission(title, source, url, text_preview, body, ip_hash):
    with conn() as c:
        c.execute(
            """INSERT INTO submissions (title, source, url, text_preview, body, ip_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, source, url or "", text_preview, body, ip_hash),
        )
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def set_submission_verdict(sub_id, verdict_md, one_liner, model, price):
    with conn() as c:
        c.execute(
            """UPDATE submissions
               SET verdict_md = ?, one_liner = ?, model = ?, price = ?,
                   status = 'analysed'
               WHERE id = ?""",
            (verdict_md, one_liner, model, price, sub_id),
        )


def set_submission_failed(sub_id, error):
    with conn() as c:
        c.execute(
            "UPDATE submissions SET status = 'failed', error = ? WHERE id = ?",
            (error[:1000], sub_id),
        )


def get_submission(sub_id):
    with conn() as c:
        cur = c.execute(
            "SELECT * FROM submissions WHERE id = ? AND status = 'analysed'",
            (sub_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ─── SUGGESTIONS ──────────────────────────────────────────

def add_suggestion(name, reason, example, ip_hash):
    with conn() as c:
        c.execute(
            """INSERT INTO suggestions (name, reason, example, ip_hash)
               VALUES (?, ?, ?, ?)""",
            (name[:100], (reason or "")[:1000], (example or "")[:1000], ip_hash),
        )
        return True


def recent_suggestions_by_ip(ip_hash, minutes=60):
    with conn() as c:
        cur = c.execute(
            """SELECT COUNT(*) AS n FROM suggestions
               WHERE ip_hash = ? AND created_at > datetime('now', ?)""",
            (ip_hash, f"-{minutes} minutes"),
        )
        return cur.fetchone()["n"]


# ─── COPE OF THE WEEK ────────────────────────────────────

def cope_of_the_week():
    """Find the article from the past 7 days with highest cope density."""
    cope_words = ['copium', 'lullaby', 'ideological anesthetic', 'false reassurance',
                  'denial', 'deflection', 'elite self-exoneration', 'techno-optimism',
                  'augmentation fantasy', 'regulatory hopium', 'timeline minimisation',
                  'jobs will be created', 'human creativity cope']
    with conn() as c:
        cur = c.execute(
            """SELECT * FROM articles
               WHERE status = 'analysed' AND verdict_md IS NOT NULL
                 AND analysed_at > datetime('now', '-7 days')
               ORDER BY analysed_at DESC LIMIT 50""",
        )
        candidates = [dict(r) for r in cur.fetchall()]

    if not candidates:
        # Fallback to all time if no recent articles
        with conn() as c:
            cur = c.execute(
                """SELECT * FROM articles
                   WHERE status = 'analysed' AND verdict_md IS NOT NULL
                   ORDER BY analysed_at DESC LIMIT 20""",
            )
            candidates = [dict(r) for r in cur.fetchall()]

    if not candidates:
        return None

    best = None
    best_score = -1
    for art in candidates:
        verdict = (art.get("verdict_md") or "").lower()
        score = sum(verdict.count(w) for w in cope_words)
        if score > best_score:
            best_score = score
            best = art

    return best if best_score > 0 else (candidates[0] if candidates else None)


# ─── SEARCH ───────────────────────────────────────────────

def rebuild_fts():
    """Rebuild the FTS5 index from articles table."""
    with conn() as c:
        c.execute("DELETE FROM articles_fts")
        c.execute("""
            INSERT INTO articles_fts(slug, title, source, snippet, one_liner, verdict_md)
            SELECT slug, title, source, COALESCE(snippet,''), COALESCE(one_liner,''), COALESCE(verdict_md,'')
            FROM articles WHERE status = 'analysed'
        """)


def search_articles(query, limit=30):
    """Full-text search across articles."""
    if not query or len(query.strip()) < 2:
        return []
    safe_q = re.sub(r'[^\w\s]', ' ', query).strip()
    terms = safe_q.split()
    if not terms:
        return []
    fts_query = ' OR '.join(f'"{t}"*' for t in terms[:5])
    with conn() as c:
        try:
            cur = c.execute("""
                SELECT a.* FROM articles a
                JOIN articles_fts f ON a.slug = f.slug
                WHERE articles_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, limit))
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            like_q = f"%{safe_q}%"
            cur = c.execute("""
                SELECT * FROM articles
                WHERE status = 'analysed' AND (
                    title LIKE ? OR one_liner LIKE ? OR source LIKE ? OR verdict_md LIKE ?
                )
                ORDER BY analysed_at DESC LIMIT ?
            """, (like_q, like_q, like_q, like_q, limit))
            return [dict(r) for r in cur.fetchall()]
