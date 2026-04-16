#!/usr/bin/env python3
"""Tweet formatter for Oracle verdicts.

Usage:
    python3 tweet_verdict.py <article_id>

Prints a formatted tweet to stdout. Wire up Twitter API creds later.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

def format_tweet(article_id):
    db.init()
    with db.conn() as c:
        cur = c.execute("SELECT * FROM articles WHERE id = ? AND status = 'analysed'",
                        (article_id,))
        row = cur.fetchone()
        if not row:
            print(f"No analysed article with id={article_id}", file=sys.stderr)
            sys.exit(1)
        row = dict(row)

    title = row["title"]
    one_liner = row.get("one_liner") or ""
    slug = row["slug"]
    url = f"https://copecheck.com/v/{slug}"

    # Trim to fit ~280 chars
    # Format: "{title} — Oracle verdict: {one_liner}. Full dissection: {url}"
    base = f"Full dissection: {url}"
    max_verdict = 280 - len(title) - len(" — Oracle verdict: ") - len(f". {base}") - 5

    if one_liner and len(one_liner) > max_verdict:
        one_liner = one_liner[:max_verdict-3] + "..."

    if one_liner:
        tweet = f"{title} — Oracle verdict: {one_liner}. {base}"
    else:
        tweet = f"{title} — {base}"

    # Final trim
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."

    print(tweet)
    print(f"\n[{len(tweet)} chars]", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 tweet_verdict.py <article_id>", file=sys.stderr)
        sys.exit(1)
    format_tweet(int(sys.argv[1]))

# Cron entry (uncomment and add to crontab):
# 0 9 * * * cd /home/ben/infra/copecheck && venv/bin/python3 scripts/tweet_verdict.py $(sqlite3 data/copecheck.db "SELECT id FROM articles WHERE status='analysed' ORDER BY analysed_at DESC LIMIT 1") >> logs/tweets.log 2>&1
