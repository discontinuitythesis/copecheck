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


CREATE TABLE IF NOT EXISTS url_submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    figure_id   TEXT NOT NULL REFERENCES figures(id),
    url         TEXT NOT NULL,
    url_type    TEXT DEFAULT 'unknown',
    extracted_text TEXT,
    status      TEXT DEFAULT 'pending',
    error_msg   TEXT,
    submitted_by TEXT DEFAULT 'anonymous',
    ip_hash     TEXT,
    referrer    TEXT DEFAULT '',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_urlsub_status ON url_submissions(status, created_at);
CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_slug TEXT NOT NULL,
    author_name TEXT DEFAULT 'Anonymous',
    body        TEXT NOT NULL,
    ip_hash     TEXT,
    referrer    TEXT DEFAULT '',
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
            cur = c.execute(
                """INSERT INTO articles
                (slug, url, url_hash, title, source, published, snippet, body, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (slug, url, url_hash(url), title, source, published, snippet, body),
            )
            return slug
        except sqlite3.IntegrityError:
            return None


def set_verdict(slug, verdict_md, one_liner, model, price, relevance=None):
    with conn() as c:
        cur = c.execute(
            """UPDATE articles
               SET verdict_md = ?, one_liner = ?, model = ?, price = ?,
                   relevance = ?,
                   status = 'analysed', analysed_at = CURRENT_TIMESTAMP,
                   error = NULL
               WHERE slug = ?""",
            (verdict_md, one_liner, model, price, relevance, slug),
        )


def set_failed(slug, error):
    with conn() as c:
        cur = c.execute(
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


def recent_analysed(limit=60, min_relevance=None):
    with conn() as c:
        if min_relevance is not None:
            cur = c.execute(
                """SELECT * FROM articles
                   WHERE status = 'analysed' AND verdict_md IS NOT NULL
                     AND (relevance IS NULL OR relevance >= ?)
                   ORDER BY analysed_at DESC LIMIT ?""",
                (min_relevance, limit),
            )
        else:
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
        cur = c.execute(
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
        cur = c.execute(
            """INSERT INTO cope_entries
               (figure_id, article_slug, quote, source_url, source_title,
                cope_score, cope_type, analysis_md, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (figure_id, article_slug, quote, source_url, source_title,
             cope_score, cope_type, analysis_md, model),
        )
        cur = c.execute(
            """SELECT cope_score, created_at FROM cope_entries
               WHERE figure_id = ? ORDER BY created_at DESC""",
            (figure_id,),
        )
        entries = cur.fetchall()
        if entries:
            # Recency-weighted scoring with noise filter
            # - Drop entries scoring < 15 (noise / irrelevant mentions)
            # - 14-day half-life: entries lose half their weight every 2 weeks
            import math
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            HALF_LIFE_DAYS = 14.0
            DECAY = math.log(2) / HALF_LIFE_DAYS
            MIN_SCORE = 15  # noise threshold
            total_w = 0.0
            total_s = 0.0
            for e in entries:
                if e["cope_score"] < MIN_SCORE:
                    continue  # skip noise
                try:
                    ts = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age_days = (now - ts).total_seconds() / 86400.0
                except Exception:
                    age_days = 30.0
                w = math.exp(-DECAY * age_days)
                total_w += w
                total_s += e["cope_score"] * w
            if total_w > 0:
                new_avg = round(total_s / total_w, 1)
            else:
                all_scores = [e["cope_score"] for e in entries]
                new_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else cope_score
            cur2 = c.execute("SELECT cope_score FROM figures WHERE id = ?", (figure_id,))
            old = cur2.fetchone()
            prev = old["cope_score"] if old else 50.0

            cur = c.execute(
                """UPDATE figures SET
                       cope_score = ?, prev_score = ?,
                       total_quotes = (SELECT COUNT(*) FROM cope_entries WHERE figure_id = ?),
                       last_quote = ?, last_cope_type = ?,
                       last_scored = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (new_avg, prev, figure_id, quote[:500], cope_type, figure_id),
            )




def add_url_submission(figure_id, url, ip_hash="", submitted_by="anonymous"):
    """Queue a URL for extraction and scoring."""
    with conn() as c:
        # Dedupe: don't resubmit same URL for same figure within 7 days
        cur = c.execute(
            """SELECT 1 FROM url_submissions
               WHERE figure_id = ? AND url = ?
               AND created_at > datetime('now', '-7 days')""",
            (figure_id, url),
        )
        if cur.fetchone():
            return None  # already submitted recently
        # Also check if this URL is already in cope_entries
        cur = c.execute(
            """SELECT 1 FROM cope_entries
               WHERE figure_id = ? AND source_url = ?""",
            (figure_id, url),
        )
        if cur.fetchone():
            return None  # already scored
        cur = c.execute(
            """INSERT INTO url_submissions (figure_id, url, ip_hash, submitted_by)
               VALUES (?, ?, ?, ?)""",
            (figure_id, url, ip_hash, submitted_by),
        )
        return cur.lastrowid


def get_pending_submissions(limit=20):
    """Get pending URL submissions for processing."""
    with conn() as c:
        cur = c.execute(
            """SELECT us.*, f.name as figure_name, f.title as figure_title
               FROM url_submissions us
               JOIN figures f ON us.figure_id = f.id
               WHERE us.status = 'pending'
               ORDER BY us.created_at ASC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def update_submission(sub_id, status, extracted_text=None, url_type=None, error_msg=None):
    """Update a URL submission after processing."""
    with conn() as c:
        cur = c.execute(
            """UPDATE url_submissions SET
                   status = ?,
                   extracted_text = COALESCE(?, extracted_text),
                   url_type = COALESCE(?, url_type),
                   error_msg = ?,
                   processed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, extracted_text, url_type, error_msg, sub_id),
        )


def get_submissions_for_figure(figure_id, limit=10):
    """Get recent submissions for a figure."""
    with conn() as c:
        cur = c.execute(
            """SELECT * FROM url_submissions
               WHERE figure_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (figure_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


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
        cur = c.execute(
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
        cur = c.execute(
            """INSERT INTO submissions (title, source, url, text_preview, body, ip_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, source, url or "", text_preview, body, ip_hash),
        )
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def set_submission_verdict(sub_id, verdict_md, one_liner, model, price):
    with conn() as c:
        cur = c.execute(
            """UPDATE submissions
               SET verdict_md = ?, one_liner = ?, model = ?, price = ?,
                   status = 'analysed'
               WHERE id = ?""",
            (verdict_md, one_liner, model, price, sub_id),
        )


def set_submission_failed(sub_id, error):
    with conn() as c:
        cur = c.execute(
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
        cur = c.execute(
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
    """Return the top cope entry from the past week, cached in cotw_archive."""
    from datetime import datetime, timedelta
    import re as _re
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    week_key = monday.strftime("%Y-%m-%d")

    with conn() as c:
        row = c.execute(
            "SELECT * FROM cotw_archive WHERE week_start = ?", (week_key,)
        ).fetchone()
        if row:
            d = dict(row)
            if not d.get('figure_name'):
                t = d.get('title', '')
                if ' \u2014 ' in t:
                    d['figure_name'] = t.split(' \u2014 ')[0]
            if not d.get('cope_score'):
                t = d.get('title', '')
                m = _re.search(r'(\d+)/100', t)
                if m:
                    d['cope_score'] = float(m.group(1))
            if not d.get('cope_type'):
                d['cope_type'] = d.get('source', 'Maximum Cope')
            return d

        week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        entry = c.execute(
            "SELECT ce.*, f.name as figure_name "
            "FROM cope_entries ce "
            "JOIN figures f ON ce.figure_id = f.id "
            "WHERE ce.created_at >= ? AND ce.cope_score >= 15 "
            "ORDER BY ce.cope_score DESC LIMIT 1",
            (week_ago,)
        ).fetchone()

        if not entry:
            return None

        entry = dict(entry)
        slug = "cope-%s-%s" % (entry['figure_id'], week_key)
        fig = entry['figure_name']
        score = entry['cope_score']
        ctype = entry.get('cope_type', '')
        title = "%s \u2014 %d/100 Cope Score" % (fig, int(score))

        cur = c.execute(
            "INSERT OR REPLACE INTO cotw_archive "
            "(week_start, slug, title, source, one_liner, url, published, analysed_at, figure_name, cope_score, cope_type, analysis_md) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (week_key, slug, title, ctype, entry.get('quote', ''),
             entry.get('source_url', ''), entry.get('created_at', ''),
             entry.get('created_at', ''), fig, score, ctype, entry.get('analysis_md', ''))
        )

        cached = c.execute(
            "SELECT * FROM cotw_archive WHERE week_start = ?", (week_key,)
        ).fetchone()
        if cached:
            d = dict(cached)
            if not d.get('figure_name'):
                d['figure_name'] = fig
            if not d.get('cope_score'):
                d['cope_score'] = score
            if not d.get('cope_type'):
                d['cope_type'] = ctype or 'Maximum Cope'
            return d
        return None

def cotw_archive_list(limit=52):
    """Return past Cope of the Week winners, newest first."""
    with conn() as c:
        cur = c.execute(
            """SELECT ca.*, a.snippet, a.verdict_md
               FROM cotw_archive ca
               LEFT JOIN articles a ON a.slug = ca.slug
               ORDER BY ca.week_start DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


# ─── SEARCH ───────────────────────────────────────────────

def rebuild_fts():
    """Rebuild the FTS5 index from articles table."""
    with conn() as c:
        cur = c.execute("DELETE FROM articles_fts")
        cur = c.execute("""
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


# ─── INSTANT SCORES ──────────────────────────────────────

INSTANT_SCHEMA = """
CREATE TABLE IF NOT EXISTS instant_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    research_text TEXT,
    quotes_json TEXT,
    cope_score  REAL,
    cope_types  TEXT,
    oracle_verdict TEXT,
    ip_hash     TEXT,
    perplexity_model TEXT,
    scoring_model TEXT,
    total_price REAL DEFAULT 0,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_instant_slug ON instant_scores(slug);
CREATE INDEX IF NOT EXISTS idx_instant_name ON instant_scores(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_instant_created ON instant_scores(created_at DESC);
"""


def init_instant():
    with conn() as c:
        c.executescript(INSTANT_SCHEMA)


def get_instant_by_slug(slug):
    with conn() as c:
        cur = c.execute("SELECT * FROM instant_scores WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_cached_instant(name, max_age_hours=24):
    """Return cached instant score if fresh enough."""
    with conn() as c:
        cur = c.execute(
            """SELECT * FROM instant_scores
               WHERE name = ? COLLATE NOCASE
                 AND created_at > datetime('now', ?)
               ORDER BY created_at DESC LIMIT 1""",
            (name.strip(), f"-{max_age_hours} hours"),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def save_instant_score(name, slug, research_text, quotes_json, cope_score,
                       cope_types, oracle_verdict, ip_hash, perplexity_model,
                       scoring_model, total_price):
    with conn() as c:
        try:
            cur = c.execute(
                """INSERT INTO instant_scores
                   (name, slug, research_text, quotes_json, cope_score, cope_types,
                    oracle_verdict, ip_hash, perplexity_model, scoring_model, total_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, slug, research_text, quotes_json, cope_score, cope_types,
                 oracle_verdict, ip_hash, perplexity_model, scoring_model, total_price),
            )
            return c.execute("SELECT last_insert_rowid()").fetchone()[0]
        except sqlite3.IntegrityError:
            return None


def recent_instant_by_ip(ip_hash, minutes=60):
    with conn() as c:
        cur = c.execute(
            """SELECT COUNT(*) AS n FROM instant_scores
               WHERE ip_hash = ? AND created_at > datetime('now', ?)""",
            (ip_hash, f"-{minutes} minutes"),
        )
        return cur.fetchone()["n"]


def recent_instant_scores(limit=20):
    with conn() as c:
        cur = c.execute(
            "SELECT * FROM instant_scores ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


# ─── FEEDBACK ─────────────────────────────────────────────

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    email       TEXT,
    message     TEXT NOT NULL,
    ip_hash     TEXT,
    referrer    TEXT DEFAULT '',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
"""


def init_feedback():
    with conn() as c:
        c.executescript(FEEDBACK_SCHEMA)


def add_feedback(name, email, message, ip_hash, referrer=""):
    with conn() as c:
        cur = c.execute(
            """INSERT INTO feedback (name, email, message, ip_hash, referrer)
               VALUES (?, ?, ?, ?, ?)""",
            ((name or "")[:100], (email or "")[:200], message[:5000], ip_hash, (referrer or "")[:500]),
        )
        return True


def recent_feedback_by_ip(ip_hash, minutes=60):
    with conn() as c:
        cur = c.execute(
            """SELECT COUNT(*) AS n FROM feedback
               WHERE ip_hash = ? AND created_at > datetime('now', ?)""",
            (ip_hash, f"-{minutes} minutes"),
        )
        return cur.fetchone()["n"]


def get_all_feedback(limit=200):
    with conn() as c:
        cur = c.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


# ─── ADMIN HELPERS ────────────────────────────────────────

def get_all_suggestions(status=None):
    with conn() as c:
        if status:
            cur = c.execute(
                "SELECT * FROM suggestions WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cur = c.execute("SELECT * FROM suggestions ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


def get_suggestion(sid):
    with conn() as c:
        cur = c.execute("SELECT * FROM suggestions WHERE id = ?", (sid,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_suggestion_status(sid, status):
    with conn() as c:
        cur = c.execute("UPDATE suggestions SET status = ? WHERE id = ?", (status, sid))


def get_admin_stats():
    with conn() as c:
        stats = {}
        stats["total_articles"] = c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        stats["total_verdicts"] = c.execute("SELECT COUNT(*) FROM articles WHERE status = 'analysed'").fetchone()[0]
        stats["total_comments"] = c.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        stats["total_submissions"] = c.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        stats["total_figures"] = c.execute("SELECT COUNT(*) FROM figures").fetchone()[0]
        stats["total_cope_entries"] = c.execute("SELECT COUNT(*) FROM cope_entries").fetchone()[0]
        stats["suggestions_pending"] = c.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'pending'").fetchone()[0]
        stats["suggestions_approved"] = c.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'approved'").fetchone()[0]
        stats["suggestions_dismissed"] = c.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'dismissed'").fetchone()[0]
        try:
            stats["total_feedback"] = c.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        except Exception:
            stats["total_feedback"] = 0
        return stats
