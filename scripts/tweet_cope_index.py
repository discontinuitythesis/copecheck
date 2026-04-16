#!/usr/bin/env python3
"""Weekly Cope Index leaderboard tweet formatter.

Usage:
    python3 tweet_cope_index.py

Prints a formatted leaderboard tweet to stdout.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

def format_leaderboard_tweet():
    db.init()
    board = db.get_leaderboard()
    if not board:
        print("No figures on leaderboard", file=sys.stderr)
        sys.exit(1)

    lines = ["COPE INDEX — Weekly Leaderboard\n"]
    for i, fig in enumerate(board[:8], 1):
        score = int(fig["cope_score"])
        name = fig["name"]
        # Emoji indicator
        if score >= 76:
            ind = "🔴"
        elif score >= 56:
            ind = "🟠"
        elif score >= 36:
            ind = "🟡"
        elif score >= 16:
            ind = "🟢"
        else:
            ind = "💎"
        lines.append(f"{ind} #{i} {name}: {score}/100")

    lines.append("\nFull leaderboard: https://copecheck.com")

    tweet = "\n".join(lines)
    if len(tweet) > 280:
        # Trim to top 5
        lines = ["COPE INDEX — Weekly Leaderboard\n"]
        for i, fig in enumerate(board[:5], 1):
            score = int(fig["cope_score"])
            lines.append(f"#{i} {fig['name']}: {score}/100")
        lines.append("\nhttps://copecheck.com")
        tweet = "\n".join(lines)

    print(tweet)
    print(f"\n[{len(tweet)} chars]", file=sys.stderr)

if __name__ == "__main__":
    format_leaderboard_tweet()

# Cron entry (uncomment — runs every Monday at 10am):
# 0 10 * * 1 cd /home/ben/infra/copecheck && venv/bin/python3 scripts/tweet_cope_index.py >> logs/tweets.log 2>&1
