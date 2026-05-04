#!/usr/bin/env python3
"""Rewrite cope_of_the_week() to use cope_entries (from Brave scans) instead of articles table."""
import re

DB_PY = "/home/ben/infra/copecheck/db.py"

with open(DB_PY, "r") as f:
    code = f.read()

old_pattern = r'def cope_of_the_week\(\):.*?def cotw_archive_list'
new_func = '''def cope_of_the_week():
    """Return the Cope of the Week — highest-scoring cope entry from the past week.
    Locked in on Monday, cached in cotw_archive."""
    from datetime import datetime, timedelta
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    week_key = monday.isoformat()
    prev_monday = (monday - timedelta(days=7)).isoformat()

    with conn() as c:
        # Check cache first
        cached = c.execute(
            "SELECT * FROM cotw_archive WHERE week_start = ?", (week_key,)
        ).fetchone()
        if cached:
            return dict(cached)

        # Pick highest-scoring cope entry from past week with a source URL
        cur = c.execute(
            """SELECT ce.cope_score, ce.cope_type, ce.quote, ce.source_url,
                      ce.created_at, f.name as figure_name, f.photo_url, f.id as figure_id
               FROM cope_entries ce
               JOIN figures f ON f.id = ce.figure_id
               WHERE ce.created_at >= ?
                 AND ce.source_url IS NOT NULL AND ce.source_url != ''
                 AND ce.cope_score >= 15
               ORDER BY ce.cope_score DESC, ce.created_at DESC
               LIMIT 1""",
            (prev_monday,),
        )
        winner = cur.fetchone()

        if not winner:
            # Fallback: highest scoring entry all time
            cur = c.execute(
                """SELECT ce.cope_score, ce.cope_type, ce.quote, ce.source_url,
                          ce.created_at, f.name as figure_name, f.photo_url, f.id as figure_id
                   FROM cope_entries ce
                   JOIN figures f ON f.id = ce.figure_id
                   WHERE ce.source_url IS NOT NULL AND ce.source_url != ''
                     AND ce.cope_score >= 15
                   ORDER BY ce.cope_score DESC
                   LIMIT 1""",
            )
            winner = cur.fetchone()

        if not winner:
            return None

        winner = dict(winner)

        # Cache it
        c.execute(
            """INSERT OR IGNORE INTO cotw_archive
               (week_start, slug, title, source, one_liner, url, published, analysed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (week_key,
             f"cope-{winner['figure_id']}-{week_key}",
             f"{winner['figure_name']} — {int(winner['cope_score'])}/100 Cope Score",
             winner.get('cope_type', ''),
             winner.get('quote', ''),
             winner.get('source_url', ''),
             winner.get('created_at', ''),
             winner.get('created_at', '')),
        )

        # Return in a format the template can use
        return {
            "figure_name": winner["figure_name"],
            "figure_id": winner["figure_id"],
            "photo_url": winner.get("photo_url"),
            "cope_score": winner["cope_score"],
            "cope_type": winner.get("cope_type", ""),
            "quote": winner.get("quote", ""),
            "source_url": winner.get("source_url", ""),
            "created_at": winner.get("created_at", ""),
            # Compatibility fields for archive template
            "title": f"{winner['figure_name']} — {int(winner['cope_score'])}/100 Cope Score",
            "source": winner.get("cope_type", ""),
            "one_liner": winner.get("quote", ""),
            "url": winner.get("source_url", ""),
            "slug": f"cope-{winner['figure_id']}-{week_key}",
        }


def cotw_archive_list'''

code_new = re.sub(old_pattern, new_func, code, flags=re.DOTALL)

if code_new == code:
    print("ERROR: Pattern not found")
else:
    with open(DB_PY, "w") as f:
        f.write(code_new)
    print("OK: cope_of_the_week() rewritten")
