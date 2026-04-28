#!/usr/bin/env python3
"""CopeCheck Weekly Digest — HTML email summary, sent via n8n webhook."""

import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "copecheck.db")
SITE = "https://copecheck.com"
RECIPIENT = "btl101@gmail.com"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [digest] %(message)s")
log = logging.getLogger(__name__)

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def q(sql, params=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]

def q1(sql, params=()):
    rows = q(sql, params)
    return rows[0] if rows else None

def cope_of_the_week():
    return q1("""
        SELECT a.slug, a.title, a.source, a.verdict_md, a.one_liner,
               a.created_at, COUNT(ce.id) AS cope_count
        FROM articles a
        JOIN cope_entries ce ON ce.article_slug = a.slug
        WHERE a.status = 'done'
          AND a.created_at > datetime('now', '-7 days')
          AND a.verdict_md IS NOT NULL
        GROUP BY a.slug
        ORDER BY cope_count DESC, a.created_at DESC
        LIMIT 1
    """)

def leaderboard_movers():
    return q("""
        SELECT f.name, f.cope_score, f.prev_score, f.last_quote,
               f.last_cope_type, f.last_scored, f.id
        FROM figures f
        WHERE f.cope_score != f.prev_score
          AND f.prev_score IS NOT NULL
          AND f.last_scored > datetime('now', '-7 days')
        ORDER BY ABS(f.cope_score - f.prev_score) DESC
    """)

def weekly_stats():
    stats = {}
    stats["new_articles"] = q1("SELECT COUNT(*) AS n FROM articles WHERE created_at > datetime('now', '-7 days')")["n"]
    stats["analysed"] = q1("SELECT COUNT(*) AS n FROM articles WHERE status = 'done' AND analysed_at > datetime('now', '-7 days')")["n"]
    stats["new_submissions"] = q1("SELECT COUNT(*) AS n FROM submissions WHERE created_at > datetime('now', '-7 days')")["n"]
    stats["new_suggestions"] = q1("SELECT COUNT(*) AS n FROM suggestions WHERE created_at > datetime('now', '-7 days')")["n"]
    stats["pageviews"] = None
    stats["unique_visitors"] = None
    stats["top_pages"] = []
    stats["top_referrers"] = []
    try:
        tables = [r["name"] for r in q("SELECT name FROM sqlite_master WHERE type='table'")]
        if "pageviews" in tables:
            stats["pageviews"] = q1("SELECT COUNT(*) AS n FROM pageviews WHERE created_at > datetime('now', '-7 days')")["n"]
            stats["unique_visitors"] = q1("SELECT COUNT(DISTINCT ip_hash) AS n FROM pageviews WHERE created_at > datetime('now', '-7 days')")["n"]
            stats["top_pages"] = q("SELECT path, COUNT(*) AS views FROM pageviews WHERE created_at > datetime('now', '-7 days') GROUP BY path ORDER BY views DESC LIMIT 5")
            stats["top_referrers"] = q("SELECT referrer, COUNT(*) AS views FROM pageviews WHERE created_at > datetime('now', '-7 days') AND referrer IS NOT NULL AND referrer != '' GROUP BY referrer ORDER BY views DESC LIMIT 5")
    except Exception:
        pass
    return stats

def instant_scores_this_week():
    try:
        tables = [r["name"] for r in q("SELECT name FROM sqlite_master WHERE type='table'")]
        if "instant_scores" not in tables:
            return []
        return q("""
            SELECT name, slug, cope_score, cope_types, oracle_verdict, created_at
            FROM instant_scores
            WHERE created_at > datetime('now', '-7 days')
            ORDER BY created_at DESC
        """)
    except Exception:
        return []

def md_to_html(text):
    if not text:
        return ""
    lines = text.strip().split("\n")
    html_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            html_parts.append("")
            continue
        if line.startswith("### "):
            html_parts.append(f'<h4 style="color:#f0c040;margin:12px 0 4px;">{line[4:]}</h4>')
        elif line.startswith("## "):
            html_parts.append(f'<h3 style="color:#f0c040;margin:14px 0 4px;">{line[3:]}</h3>')
        elif line.startswith("# "):
            html_parts.append(f'<h3 style="color:#f0c040;margin:14px 0 4px;">{line[2:]}</h3>')
        else:
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
            html_parts.append(f"<p style='margin:6px 0;line-height:1.5;'>{line}</p>")
    return "\n".join(html_parts)

def cope_color(score):
    if score is None: return "#888"
    if score >= 70: return "#ff4444"
    if score >= 50: return "#ff8c00"
    if score >= 30: return "#f0c040"
    return "#44cc44"

def arrow(old, new):
    if new > old: return "&#9650;"
    if new < old: return "&#9660;"
    return "&#9472;"

def arrow_color(old, new):
    return "#ff4444" if new > old else "#44cc44" if new < old else "#888"

def build_email():
    cotw = cope_of_the_week()
    movers = leaderboard_movers()
    stats = weekly_stats()
    instants = instant_scores_this_week()
    now = datetime.now(timezone.utc)
    subject = f"CopeCheck Weekly Digest \u2014 {now.strftime('%d %b %Y')}"

    if cotw:
        verdict_html = md_to_html(cotw["verdict_md"])
        oneliner_html = f'<p style="color:#f0c040;font-style:italic;margin:0 0 16px;">&ldquo;{cotw["one_liner"]}&rdquo;</p>' if cotw.get("one_liner") else ""
        cotw_section = f'''
        <div style="background:#1a1a2e;border:1px solid #f0c040;border-radius:8px;padding:20px;margin:20px 0;">
            <h2 style="color:#f0c040;margin:0 0 4px;">&#127942; COPE OF THE WEEK</h2>
            <p style="color:#888;margin:0 0 12px;font-size:13px;">Highest cope density from the past 7 days</p>
            <h3 style="color:#fff;margin:0 0 6px;"><a href="{SITE}/article/{cotw["slug"]}" style="color:#fff;text-decoration:underline;">{cotw["title"]}</a></h3>
            <p style="color:#aaa;margin:0 0 12px;font-size:13px;">{cotw["source"]} &middot; {cotw["cope_count"]} cope classifications detected</p>
            {oneliner_html}
            <div style="border-top:1px solid #333;padding-top:14px;color:#ccc;font-size:14px;">
                <h4 style="color:#f0c040;margin:0 0 8px;">The Oracle&#39;s Verdict</h4>
                {verdict_html}
            </div>
            <p style="margin:14px 0 0;"><a href="{SITE}/article/{cotw["slug"]}" style="color:#f0c040;">Read the full verdict &rarr;</a></p>
        </div>'''
    else:
        cotw_section = '''
        <div style="background:#1a1a2e;border:1px solid #333;border-radius:8px;padding:20px;margin:20px 0;">
            <h2 style="color:#f0c040;margin:0 0 8px;">&#127942; COPE OF THE WEEK</h2>
            <p style="color:#888;">No articles analysed this week. The Oracle rests.</p>
        </div>'''

    if movers:
        mover_rows = ""
        for m in movers:
            old, new = m["prev_score"], m["cope_score"]
            arr, ac = arrow(old, new), arrow_color(old, new)
            qs = (m["last_quote"] or "")[:120]
            if len(m.get("last_quote") or "") > 120: qs += "..."
            mover_rows += f'''
            <tr>
                <td style="padding:8px;border-bottom:1px solid #333;"><a href="{SITE}/figure/{m["id"]}" style="color:#fff;text-decoration:underline;">{m["name"]}</a></td>
                <td style="padding:8px;border-bottom:1px solid #333;text-align:center;color:#888;">{old:.1f}</td>
                <td style="padding:8px;border-bottom:1px solid #333;text-align:center;color:{ac};font-size:18px;">{arr}</td>
                <td style="padding:8px;border-bottom:1px solid #333;text-align:center;color:{cope_color(new)};font-weight:bold;">{new:.1f}</td>
                <td style="padding:8px;border-bottom:1px solid #333;color:#999;font-size:12px;font-style:italic;">&ldquo;{qs}&rdquo;</td>
            </tr>'''
        movers_section = f'''
        <div style="margin:20px 0;">
            <h2 style="color:#f0c040;margin:0 0 12px;">&#128202; LEADERBOARD MOVERS</h2>
            <table style="width:100%;border-collapse:collapse;color:#ccc;font-size:14px;">
                <tr style="border-bottom:2px solid #f0c040;">
                    <th style="padding:8px;text-align:left;color:#f0c040;">Figure</th>
                    <th style="padding:8px;text-align:center;color:#888;">Old</th>
                    <th style="padding:8px;text-align:center;color:#888;"></th>
                    <th style="padding:8px;text-align:center;color:#888;">New</th>
                    <th style="padding:8px;text-align:left;color:#888;">Triggering Quote</th>
                </tr>{mover_rows}
            </table>
        </div>'''
    else:
        movers_section = '''
        <div style="margin:20px 0;">
            <h2 style="color:#f0c040;margin:0 0 8px;">&#128202; LEADERBOARD MOVERS</h2>
            <p style="color:#888;">No movement &mdash; they&#39;re all still coping at the same rate.</p>
        </div>'''

    stat_items = f'''
        <tr><td style="padding:6px 12px;color:#aaa;">Articles ingested</td><td style="padding:6px 12px;color:#fff;font-weight:bold;">{stats["new_articles"]}</td></tr>
        <tr><td style="padding:6px 12px;color:#aaa;">Articles analysed</td><td style="padding:6px 12px;color:#fff;font-weight:bold;">{stats["analysed"]}</td></tr>
        <tr><td style="padding:6px 12px;color:#aaa;">User submissions</td><td style="padding:6px 12px;color:#fff;font-weight:bold;">{stats["new_submissions"]}</td></tr>
        <tr><td style="padding:6px 12px;color:#aaa;">Figure suggestions</td><td style="padding:6px 12px;color:#fff;font-weight:bold;">{stats["new_suggestions"]}</td></tr>'''
    if stats["pageviews"] is not None:
        stat_items += f'''
        <tr><td style="padding:6px 12px;color:#aaa;">Pageviews</td><td style="padding:6px 12px;color:#fff;font-weight:bold;">{stats["pageviews"]:,}</td></tr>
        <tr><td style="padding:6px 12px;color:#aaa;">Unique visitors</td><td style="padding:6px 12px;color:#fff;font-weight:bold;">{stats["unique_visitors"]:,}</td></tr>'''
        if stats["top_pages"]:
            pl = "".join(f'<li style="margin:2px 0;color:#ccc;">{p["path"]} <span style="color:#888;">({p["views"]})</span></li>' for p in stats["top_pages"])
            stat_items += f'''
            <tr><td colspan="2" style="padding:10px 12px 2px;color:#f0c040;font-weight:bold;">Top Pages</td></tr>
            <tr><td colspan="2" style="padding:0 12px;"><ul style="margin:4px 0;padding-left:18px;">{pl}</ul></td></tr>'''
        if stats["top_referrers"]:
            rl = "".join(f'<li style="margin:2px 0;color:#ccc;">{r["referrer"][:60]} <span style="color:#888;">({r["views"]})</span></li>' for r in stats["top_referrers"])
            stat_items += f'''
            <tr><td colspan="2" style="padding:10px 12px 2px;color:#f0c040;font-weight:bold;">Top Referrers</td></tr>
            <tr><td colspan="2" style="padding:0 12px;"><ul style="margin:4px 0;padding-left:18px;">{rl}</ul></td></tr>'''
    else:
        stat_items += '<tr><td colspan="2" style="padding:6px 12px;color:#555;font-style:italic;">Analytics not yet live</td></tr>'
    stats_section = f'''
    <div style="background:#1a1a2e;border-radius:8px;padding:16px;margin:20px 0;">
        <h2 style="color:#f0c040;margin:0 0 12px;">&#128200; WEEKLY STATS</h2>
        <table style="border-collapse:collapse;font-size:14px;">{stat_items}</table>
    </div>'''

    if instants:
        irows = ""
        for ins in instants:
            sc = ins["cope_score"] or 0
            ol = ins["oracle_verdict"].strip().split("\n")[0][:120] if ins.get("oracle_verdict") else ""
            irows += f'''
            <tr>
                <td style="padding:6px 8px;border-bottom:1px solid #333;"><a href="{SITE}/instant/{ins["slug"]}" style="color:#fff;text-decoration:underline;">{ins["name"]}</a></td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;text-align:center;color:{cope_color(sc)};font-weight:bold;">{sc:.1f}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#999;font-size:12px;">{ol}</td>
            </tr>'''
        instant_section = f'''
        <div style="margin:20px 0;">
            <h2 style="color:#f0c040;margin:0 0 12px;">&#9889; NEW INSTANT SCORES</h2>
            <table style="width:100%;border-collapse:collapse;color:#ccc;font-size:14px;">
                <tr style="border-bottom:2px solid #f0c040;">
                    <th style="padding:6px 8px;text-align:left;color:#f0c040;">Name</th>
                    <th style="padding:6px 8px;text-align:center;color:#888;">Score</th>
                    <th style="padding:6px 8px;text-align:left;color:#888;">Verdict</th>
                </tr>{irows}
            </table>
        </div>'''
    else:
        instant_section = ""

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0d0d1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:20px;">
    <div style="text-align:center;padding:24px 0;border-bottom:2px solid #f0c040;">
        <h1 style="margin:0;color:#f0c040;font-size:28px;letter-spacing:1px;"><a href="{SITE}" style="color:#f0c040;text-decoration:none;">CopeCheck</a></h1>
        <p style="color:#888;margin:6px 0 0;font-size:14px;">Weekly Digest &middot; {now.strftime("%d %B %Y")}</p>
    </div>
    {cotw_section}
    {movers_section}
    {stats_section}
    {instant_section}
    <div style="border-top:1px solid #333;padding:20px 0;margin-top:20px;text-align:center;">
        <p style="color:#555;font-size:12px;margin:0;">You&#39;re receiving this because you&#39;re the admin of <a href="{SITE}" style="color:#f0c040;">CopeCheck</a>. The Oracle sees all.</p>
    </div>
</div>
</body>
</html>'''
    return subject, html

def send_digest():
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    subject, html = build_email()

    msg = MIMEMultipart("alternative")
    msg["From"] = "CopeCheck <hello@copperchunk.com>"
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("mail-eu.smtp2go.com", 587) as server:
            server.starttls()
            server.login("vps_btl101", "EQPmg2US8HOqruEC")
            server.sendmail("hello@copperchunk.com", [RECIPIENT], msg.as_string())
        log.info("Digest sent via SMTP2GO to %s", RECIPIENT)
        return True
    except Exception as e:
        log.error("Failed to send digest: %s", e)
        return False


if __name__ == "__main__":
    log.info("Building CopeCheck weekly digest...")
    ok = send_digest()
    sys.exit(0 if ok else 1)
