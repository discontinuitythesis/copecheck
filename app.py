"""CopeCheck v2 — Flask app with Cope Index, News Feed, Comments, RSS, Submit, and OG tags."""
import hashlib
import json
import logging
import os
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

import markdown as md
import trafilatura
from flask import (Flask, abort, render_template, request, redirect,
                   url_for, Response, jsonify, flash, send_from_directory, session)
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash

import db
import analytics
import requests as http_requests
import oracle
import url_extractor

BASE = Path(__file__).parent
app = Flask(__name__, template_folder=str(BASE / "templates"),
            static_folder=str(BASE / "static"))
app.secret_key = os.environ.get("FLASK_SECRET", "copecheck-oracle-v5-secret-key")

UPLOAD_FOLDER = BASE / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_TEXT_SIZE = 50 * 1024  # 50KB
MIN_TEXT_LENGTH = 100
CAPTCHA_ANSWERS = {"7", "seven"}
RATE_LIMIT_MAX = 3
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds

db.init()
analytics.init_analytics()

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")

# --- Rate limiting store (in-memory, resets on restart) ---
_rate_store = {}  # ip_hash -> [timestamp, timestamp, ...]


def _check_rate_limit(ip_hash):
    """Returns (allowed: bool, wait_seconds: int)."""
    now = time.time()
    if ip_hash not in _rate_store:
        _rate_store[ip_hash] = []
    # Prune old entries
    _rate_store[ip_hash] = [t for t in _rate_store[ip_hash] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_store[ip_hash]) >= RATE_LIMIT_MAX:
        oldest = min(_rate_store[ip_hash])
        wait = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return False, max(1, wait // 60)
    return True, 0


def _record_rate_limit(ip_hash):
    now = time.time()
    if ip_hash not in _rate_store:
        _rate_store[ip_hash] = []
    _rate_store[ip_hash].append(now)


def _get_ip_hash():
    ip_raw = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    return hashlib.sha256(ip_raw.encode()).hexdigest()[:16]


def _fmt_date(raw):
    if not raw:
        return ""
    for f in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
              "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, f)
            return dt.strftime("%d %b %Y")
        except (ValueError, TypeError):
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%d %b %Y")
    except Exception:
        return raw[:10] if raw and len(raw) >= 10 else (raw or "")


def _render_markdown(text: str) -> str:
    if not text:
        return ""
    return md.markdown(text, extensions=["extra", "sane_lists", "nl2br"])


def _cope_color(score):
    if score is None:
        return "cope-unknown"
    s = float(score)
    if s <= 15:
        return "cope-lucid"
    elif s <= 35:
        return "cope-partial"
    elif s <= 55:
        return "cope-moderate"
    elif s <= 75:
        return "cope-heavy"
    else:
        return "cope-terminal"


def _cope_label(score):
    if score is None:
        return "UNSCORED"
    s = float(score)
    if s <= 15:
        return "LUCID"
    elif s <= 35:
        return "PARTIAL"
    elif s <= 55:
        return "MODERATE"
    elif s <= 75:
        return "HEAVY COPE"
    else:
        return "TERMINAL COPIUM"


def _trend_arrow(current, previous):
    if current is None or previous is None:
        return ""
    diff = float(current) - float(previous)
    if abs(diff) < 1.0:
        return '<span class="trend flat">—</span>'
    elif diff > 0:
        return f'<span class="trend up">▲{abs(diff):.0f}</span>'
    else:
        return f'<span class="trend down">▼{abs(diff):.0f}</span>'


def _first_sentences(text, n=2):
    """Extract first n sentences from text for OG description."""
    if not text:
        return ""
    # Strip markdown formatting
    clean = re.sub(r'[#*_`\[\]]', '', text)
    clean = re.sub(r'\(http[^)]+\)', '', clean)
    clean = clean.strip()
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    result = ' '.join(sentences[:n])
    if len(result) > 300:
        result = result[:297] + "..."
    return result



def _strip_quotes(s):
    """Strip leading/trailing quote marks from a string."""
    if not s:
        return s
    return s.strip('"\'"\u201c\u201d\u2018\u2019')

app.jinja_env.filters["fmtdate"] = _fmt_date
app.jinja_env.filters["renderverdict"] = _render_markdown
app.jinja_env.filters["copecolor"] = _cope_color
app.jinja_env.filters["copelabel"] = _cope_label
app.jinja_env.filters["trendarrow"] = _trend_arrow
app.jinja_env.filters["first_sentences"] = _first_sentences
app.jinja_env.filters["stripquotes"] = _strip_quotes
app.jinja_env.globals["now"] = datetime.utcnow


# ─── ANALYTICS MIDDLEWARE ─────────────────────────────────

@app.before_request
def track_pageview():
    analytics.log_pageview(request)


# ─── ROUTES ───────────────────────────────────────────────

@app.after_request
def add_cache_headers(response):
    """Set cache headers for Cloudflare CDN."""
    path = request.path
    if path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=604800, stale-while-revalidate=86400'
    elif path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    elif path.endswith('.xml'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    else:
        response.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=3600, stale-if-error=86400'
    response.headers.setdefault('Vary', 'Accept-Encoding')
    return response


# @app.route("/")  # moved back to index
@app.route("/index2")
def index2():
    leaderboard = db.get_leaderboard()
    items = db.recent_analysed(limit=40)
    total = db.counts().get("analysed", 0)
    cope_of_week = db.cope_of_the_week()
    return render_template("index2.html", leaderboard=leaderboard,
                          items=items, total=total, cope_of_week=cope_of_week)


@app.route("/")
def index():
    leaderboard = db.get_leaderboard()
    page = request.args.get("page", 1, type=int)
    per_page = 20
    all_items = db.recent_analysed(limit=200)
    total = db.counts().get("analysed", 0)
    total_pages = max(1, (len(all_items) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    items = all_items[(page-1)*per_page : page*per_page]
    cope_of_week = db.cope_of_the_week()
    return render_template("index.html", leaderboard=leaderboard,
                          items=items, total=total, cope_of_week=cope_of_week,
                          page=page, total_pages=total_pages)




@app.route("/cope-of-the-week")
def cotw_archive():
    weeks = db.cotw_archive_list()
    return render_template("cotw_archive.html", weeks=weeks)

@app.route("/v/<slug>")
def article(slug):
    row = db.by_slug(slug)
    if not row or not row.get("verdict_md"):
        abort(404)
    comments = db.get_comments(slug)
    return render_template("article.html", a=row, comments=comments)


@app.route("/v/<slug>/comment", methods=["POST"])
def post_comment(slug):
    row = db.by_slug(slug)
    if not row:
        abort(404)
    if request.form.get("website", "").strip():
        return redirect(url_for("article", slug=slug))
    body = (request.form.get("body") or "").strip()
    author = (request.form.get("author") or "").strip() or "Anonymous"
    if not body or len(body) < 3:
        return redirect(url_for("article", slug=slug))
    ip_hash = _get_ip_hash()
    if db.recent_comments_by_ip(ip_hash, minutes=5) >= 3:
        return redirect(url_for("article", slug=slug))
    db.add_comment(slug, author, body, ip_hash)
    return redirect(url_for("article", slug=slug) + "#comments")


@app.route("/figure/<figure_id>")
def figure_page(figure_id):
    fig = db.get_figure(figure_id)
    if not fig:
        abort(404)
    entries = db.figure_entries(figure_id, limit=50)
    score_history = db.figure_score_history(figure_id)
    return render_template("figure.html", fig=fig, entries=entries,
                          score_history=score_history)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        results = db.search_articles(q, limit=40)
    return render_template("search.html", query=q, results=results)


# ─── RSS FEED ─────────────────────────────────────────────

@app.route("/feed.xml")
@app.route("/rss")
def rss_feed():
    items = db.recent_analysed(limit=30)
    xml = _build_rss(items)
    return Response(xml, mimetype="application/rss+xml")


def _build_rss(items):
    now_rfc822 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    entries = []
    for a in items:
        pub = a.get("analysed_at") or a.get("published") or a.get("created_at") or ""
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            pub_rfc = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            pub_rfc = now_rfc822
        desc = (a.get("one_liner") or a.get("snippet") or "")[:500]
        # Escape XML
        title_esc = (a.get("title") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        desc_esc = desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        link = f"https://copecheck.com/v/{a['slug']}"
        entries.append(f"""    <item>
      <title>{title_esc}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{link}</guid>
      <pubDate>{pub_rfc}</pubDate>
      <description>{desc_esc}</description>
    </item>""")
    items_xml = "\n".join(entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>CopeCheck — Oracle Verdicts</title>
    <link>https://copecheck.com</link>
    <description>The latest Oracle of Obsolescence verdicts on AI-and-jobs coverage.</description>
    <language>en-us</language>
    <lastBuildDate>{now_rfc822}</lastBuildDate>
    <atom:link href="https://copecheck.com/feed.xml" rel="self" type="application/rss+xml"/>
{items_xml}
  </channel>
</rss>"""


# ─── USER SUBMISSIONS ────────────────────────────────────

def _extract_text_from_file(filepath, filename):
    """Extract text from uploaded file."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "txt" or ext == "md":
        with open(filepath, "r", errors="replace") as f:
            return f.read()
    elif ext == "pdf":
        try:
            import subprocess
            result = subprocess.run(
                ["pdftotext", filepath, "-"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        # Fallback: try trafilatura on the raw file
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
            text = trafilatura.extract(raw)
            return text or ""
        except Exception:
            return ""
    elif ext == "docx":
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(filepath) as z:
                with z.open("word/document.xml") as doc:
                    tree = ET.parse(doc)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [t.text for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t") if t.text]
                if texts:
                    paragraphs.append("".join(texts))
            return "\n\n".join(paragraphs)
        except Exception:
            return ""
    return ""


@app.route("/submit", methods=["GET"])
def submit_page():
    return render_template("submit.html")


@app.route("/submit", methods=["POST"])
def submit_handler():
    ip_hash = _get_ip_hash()

    # Rate limit check
    allowed, wait_mins = _check_rate_limit(ip_hash)
    if not allowed:
        return render_template("submit.html",
                             error=f"The Oracle needs time to recover. Try again in {wait_mins} minutes."), 429

    # Honeypot
    if request.form.get("website", "").strip():
        return redirect(url_for("submit_page"))

    # CAPTCHA check
    captcha = (request.form.get("captcha") or "").strip().lower()
    if captcha not in CAPTCHA_ANSWERS:
        return render_template("submit.html",
                             error="Incorrect answer. Try again."), 400

    mode = request.form.get("mode", "url")
    title = ""
    source = "User Submission"
    text = ""
    url = ""

    if mode == "url":
        url = (request.form.get("url") or "").strip()
        if not url or not url.startswith("http"):
            return render_template("submit.html", error="Please enter a valid URL."), 400
        # Check if already analysed
        existing = db.by_url_hash(url)
        if existing and existing.get("verdict_md"):
            return redirect(url_for("user_verdict", verdict_id=existing["id"]))
        try:
            downloaded = trafilatura.fetch_url(url, no_ssl=False)
            if downloaded:
                text = trafilatura.extract(downloaded, include_comments=False,
                                          include_tables=False, favor_recall=True) or ""
                # Try to get title
                import re as _re
                title_match = _re.search(r'<title[^>]*>([^<]+)</title>', downloaded, _re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()
        except Exception:
            pass
        if not text or len(text) < MIN_TEXT_LENGTH:
            return render_template("submit.html",
                                 error="Could not extract enough text from that URL. Try pasting the text directly."), 400
        if not title:
            title = text[:80].split("\n")[0]
        source = f"URL: {url[:60]}"


    elif mode == "paste":
        text = (request.form.get("text") or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            return render_template("submit.html",
                                 error=f"Text too short. Minimum {MIN_TEXT_LENGTH} characters."), 400
        if len(text) > MAX_TEXT_SIZE:
            return render_template("submit.html",
                                 error=f"Text too long. Maximum {MAX_TEXT_SIZE // 1024}KB."), 400
        title = text[:80].split("\n")[0]
        source = "Pasted Text"

    elif mode == "upload":
        file = request.files.get("file")
        if not file or not file.filename:
            return render_template("submit.html", error="No file selected."), 400
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            return render_template("submit.html",
                                 error=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"), 400
        # Check file size
        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        if size > MAX_FILE_SIZE:
            return render_template("submit.html",
                                 error=f"File too large. Maximum {MAX_FILE_SIZE // (1024*1024)}MB."), 400
        filepath = str(UPLOAD_FOLDER / filename)
        file.save(filepath)
        text = _extract_text_from_file(filepath, filename)
        # Clean up uploaded file
        try:
            os.remove(filepath)
        except Exception:
            pass
        if not text or len(text) < MIN_TEXT_LENGTH:
            return render_template("submit.html",
                                 error="Could not extract enough text from that file."), 400
        title = filename.rsplit(".", 1)[0][:80] if filename else text[:80].split("\n")[0]
        source = f"Upload: {filename}"
    else:
        return render_template("submit.html", error="Invalid submission mode."), 400

    # Truncate text for Oracle
    if len(text) > 18000:
        text = text[:18000] + "\n\n[...truncated for oracle intake...]"

    # Store submission and run Oracle
    sub_id = db.create_submission(
        title=title, source=source, url=url,
        text_preview=text[:500], body=text, ip_hash=ip_hash
    )
    if not sub_id:
        return render_template("submit.html", error="Submission failed. Try again."), 500

    _record_rate_limit(ip_hash)

    # Run Oracle synchronously
    try:
        result = oracle.consult(
            title=title, url=url or "user-submission",
            source=source, article_text=text,
        )
        one_liner = oracle.extract_one_liner(result["verdict_md"])
        db.set_submission_verdict(sub_id, result["verdict_md"], one_liner,
                                 result["model"], result.get("price"))
        return redirect(url_for("user_verdict", verdict_id=sub_id))
    except Exception as e:
        logging.exception("Oracle failed for submission %s", sub_id)
        db.set_submission_failed(sub_id, str(e))
        return render_template("submit.html",
                             error="The Oracle encountered an error. Please try again later."), 500


@app.route("/verdict/<int:verdict_id>")
def user_verdict(verdict_id):
    row = db.get_submission(verdict_id)
    if not row or not row.get("verdict_md"):
        abort(404)
    return render_template("verdict.html", v=row)


# ─── SUGGEST A FIGURE ─────────────────────────────────────

@app.route("/suggest", methods=["GET"])
def suggest_page():
    return render_template("suggest.html")


@app.route("/suggest", methods=["POST"])
def suggest_handler():
    ip_hash = _get_ip_hash()

    # Honeypot
    if request.form.get("website", "").strip():
        return redirect(url_for("suggest_page"))

    # CAPTCHA
    captcha = (request.form.get("captcha") or "").strip().lower()
    if captcha not in CAPTCHA_ANSWERS:
        return render_template("suggest.html",
                             error="Incorrect answer. Try again."), 400

    # Rate limit (reuse submission rate limit)
    if db.recent_suggestions_by_ip(ip_hash, minutes=60) >= 3:
        return render_template("suggest.html",
                             error="The Oracle needs time to recover. Try again later."), 429

    name = (request.form.get("name") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    example = (request.form.get("example") or "").strip()

    if not name or len(name) < 2:
        return render_template("suggest.html", error="Please enter a name."), 400
    if not reason or len(reason) < 10:
        return render_template("suggest.html",
                             error="Please explain why they should be watched."), 400

    db.add_suggestion(name, reason, example, ip_hash)
    return render_template("suggest.html",
                         success="Suggestion received. The Oracle will consider adding them to the watch list.")



# --- CONTACT / FEEDBACK -----------------------------------------------

# Rate limit store for feedback (separate)
_feedback_rate_store = {}

FEEDBACK_RATE_LIMIT_MAX = 3
FEEDBACK_RATE_LIMIT_WINDOW = 3600


def _check_feedback_rate_limit(ip_hash):
    now = time.time()
    if ip_hash not in _feedback_rate_store:
        _feedback_rate_store[ip_hash] = []
    _feedback_rate_store[ip_hash] = [t for t in _feedback_rate_store[ip_hash] if now - t < FEEDBACK_RATE_LIMIT_WINDOW]
    if len(_feedback_rate_store[ip_hash]) >= FEEDBACK_RATE_LIMIT_MAX:
        oldest = min(_feedback_rate_store[ip_hash])
        wait = int(FEEDBACK_RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return False, max(1, wait // 60)
    return True, 0


def _record_feedback_rate_limit(ip_hash):
    now = time.time()
    if ip_hash not in _feedback_rate_store:
        _feedback_rate_store[ip_hash] = []
    _feedback_rate_store[ip_hash].append(now)


def _notify_feedback(name, email, message, referrer=""):
    """Send feedback notification via n8n webhook."""
    webhook_url = os.environ.get("N8N_FEEDBACK_WEBHOOK_URL") or N8N_WEBHOOK_URL
    if not webhook_url:
        return
    try:
        http_requests.post(webhook_url, json={
            "type": "feedback",
            "name": name or "(anonymous)",
            "email": email or "(not provided)",
            "message": message,
            "referrer": referrer or "unknown",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }, timeout=5)
    except Exception as e:
        logging.warning("Feedback n8n webhook failed: %s", e)


@app.route("/contact", methods=["GET"])
def contact_page():
    return render_template("contact.html")


@app.route("/contact", methods=["POST"])
def contact_handler():
    ip_hash = _get_ip_hash()

    # Honeypot
    if request.form.get("website", "").strip():
        return redirect(url_for("contact_page"))

    # Rate limit
    allowed, wait_mins = _check_feedback_rate_limit(ip_hash)
    if not allowed:
        return render_template("contact.html",
                             error=f"The Oracle has heard enough from you for now. Try again in {wait_mins} minutes."), 429

    message = (request.form.get("message") or "").strip()
    if not message or len(message) < 5:
        return render_template("contact.html", error="Message too short."), 400
    if len(message) > 5000:
        return render_template("contact.html", error="Message too long. Keep it under 5000 characters."), 400

    name = (request.form.get("name") or "").strip()[:100]
    email = (request.form.get("email") or "").strip()[:200]
    referrer = (request.form.get("referrer") or "").strip()[:500]

    db.add_feedback(name, email, message, ip_hash, referrer=referrer)
    _record_feedback_rate_limit(ip_hash)
    _notify_feedback(name, email, message, referrer=referrer)

    return render_template("contact.html",
                         success="Message received. The Oracle acknowledges your existence.")


# ─── STANDARD ROUTES ─────────────────────────────────────

@app.route("/healthz")
def healthz():
    c = db.counts()
    return {"ok": True, "counts": c}, 200



# ─── SUGGEST A NETWORK ───────────────────────────────────

@app.route("/suggest-network", methods=["GET"])
def suggest_network_page():
    return render_template("suggest_network.html")

@app.route("/suggest-network", methods=["POST"])
def suggest_network_handler():
    if request.form.get("website"):
        return render_template("suggest_network.html", success="Thanks for your suggestion!")
    industry = request.form.get("industry", "").strip()
    subdomain = request.form.get("subdomain", "").strip()
    rationale = request.form.get("rationale", "").strip()
    figures = request.form.get("figures", "").strip()
    email = request.form.get("email", "").strip()
    if not industry or not rationale:
        return render_template("suggest_network.html", error="Please fill in the industry and rationale.")
    import sqlite3, json
    from datetime import datetime
    conn = sqlite3.connect(str(BASE / "data" / "copecheck.db"))
    conn.execute("""CREATE TABLE IF NOT EXISTS network_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        industry TEXT, subdomain TEXT, rationale TEXT,
        figures TEXT, email TEXT, created_at TEXT
    )""")
    conn.execute(
        "INSERT INTO network_suggestions (industry, subdomain, rationale, figures, email, created_at) VALUES (?,?,?,?,?,?)",
        (industry, subdomain, rationale, figures, email, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return render_template("suggest_network.html", success="Suggestion received. If enough cope exists, we build it.")

@app.route("/robots.txt")
def robots():
    txt = "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /admin/*\n\nSitemap: https://copecheck.com/sitemap.xml\nCrawl-delay: 1\n"
    return Response(txt, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    urls = []
    static_pages = [
        ("https://copecheck.com/", "daily", "1.0", now_iso),
        ("https://copecheck.com/about", "monthly", "0.5", None),
        ("https://copecheck.com/contact", "monthly", "0.5", None),
        ("https://copecheck.com/instant", "daily", "0.6", now_iso),
        ("https://copecheck.com/submit", "monthly", "0.5", None),
        ("https://copecheck.com/suggest", "monthly", "0.5", None),
        ("https://copecheck.com/search", "monthly", "0.4", None),
    ]
    for loc, freq, prio, lastmod in static_pages:
        lm = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        urls.append(f"<url><loc>{loc}</loc>{lm}<changefreq>{freq}</changefreq><priority>{prio}</priority></url>")
    articles = db.recent_analysed(limit=500)
    for a in articles:
        lm = a.get("analysed_at") or a.get("created_at") or ""
        if lm:
            lm = lm[:10]
        lm_tag = f"<lastmod>{lm}</lastmod>" if lm else ""
        urls.append(f"<url><loc>https://copecheck.com/v/{a['slug']}</loc>{lm_tag}<changefreq>weekly</changefreq><priority>0.7</priority></url>")
    figures = db.get_leaderboard()
    for fig in figures:
        lm_val = (fig.get("updated_at") or fig.get("last_scored") or fig.get("created_at") or "")[:10]
        lm_tag = f"<lastmod>{lm_val}</lastmod>" if lm_val else ""
        urls.append(f"<url><loc>https://copecheck.com/figure/{fig['id']}</loc>{lm_tag}<changefreq>weekly</changefreq><priority>0.8</priority></url>")
    instants = db.recent_instant_scores(limit=500)
    for r in instants:
        lm_val = (r.get("created_at") or "")[:10]
        lm_tag = f"<lastmod>{lm_val}</lastmod>" if lm_val else ""
        urls.append(f"<url><loc>https://copecheck.com/instant/{r['slug']}</loc>{lm_tag}<changefreq>monthly</changefreq><priority>0.5</priority></url>")
    urls_xml = "\n".join(urls)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls_xml}
</urlset>"""
    return Response(xml, mimetype="application/xml")


@app.route("/llms.txt")
def llms_txt():
    txt = """# CopeCheck\n\n> AI Cope Index - tracking who's coping hardest about the end of work.\n\nCopeCheck is a live analytical platform that scores public figures on how much they're "coping" (denying, deflecting, minimising) about AI's impact on jobs and the economy. It uses the Discontinuity Thesis framework and an AI persona called The Oracle of Obsolescence to analyse news, papers, and public statements.\n\n## Core Features\n\n- **Cope Index**: Leaderboard of 20+ tech leaders, AI researchers, economists scored 0-100 on their AI cope level\n- **Oracle Verdicts**: Automated analysis of AI+jobs news articles through the Discontinuity Thesis lens\n- **Instant Cope Score**: Enter any public figure's name for a live cope assessment\n- **User Submissions**: Submit URLs, paste text, or upload documents for Oracle analysis\n\n## Key Pages\n\n- [Cope Index](https://copecheck.com/): Live leaderboard of tracked figures\n- [About](https://copecheck.com/about): The Discontinuity Thesis explained\n- [Instant Score](https://copecheck.com/instant): Ad-hoc cope scoring for any public figure\n- [Submit to Oracle](https://copecheck.com/submit): Submit content for analysis\n- [RSS Feed](https://copecheck.com/feed.xml): Latest Oracle verdicts\n- [Contact](https://copecheck.com/contact): Get in touch\n\n## The Discontinuity Thesis\n\nThe analytical framework posits that AI severs the mass employment-wage-consumption circuit that underpins post-WWII capitalism. Three core premises:\n1. AI achieves durable cost/performance superiority across cognitive work\n2. Human institutions cannot preserve stable human-only economic domains at scale\n3. The majority of adults lose access to economically necessary labor\n\n## Cope Score Scale\n\n- 0-20: LUCID (acknowledges the discontinuity)\n- 21-40: PARTIAL ACKNOWLEDGMENT\n- 41-60: MODERATE COPE\n- 61-80: HEAVY COPE\n- 81-100: TERMINAL COPIUM\n"""
    return Response(txt, mimetype="text/plain")


@app.route("/llms-full.txt")
def llms_full_txt():
    lines = ["# CopeCheck - Full Site Context\n\n> AI Cope Index - tracking who's coping hardest about the end of work.\n\nCopeCheck is a live analytical platform that scores public figures on how much they're coping about AI's impact on jobs.\n\n## Tracked Figures (Current Cope Index)\n"]
    figures = db.get_leaderboard()
    for i, fig in enumerate(figures, 1):
        score = fig.get("cope_score", 0)
        label = _cope_label(score)
        name = fig.get("name", "")
        title = fig.get("title", "")
        lines.append(f"{i}. **{name}** ({title}) - Cope Score: {score:.0f}/100 ({label})")
    lines.append("\n## Recent Oracle Verdicts\n")
    articles = db.recent_analysed(limit=20)
    for a in articles:
        t = a.get("title", ""); s = a.get("slug", ""); o = a.get("one_liner", "")
        lines.append(f"- [{t}](https://copecheck.com/v/{s}): {o}")
    lines.append("\n## The Discontinuity Thesis\n\nAI severs the mass employment-wage-consumption circuit. Three premises:\n1. AI achieves durable cost/performance superiority across cognitive work\n2. Human institutions cannot preserve stable human-only economic domains at scale\n3. The majority of adults lose access to economically necessary labor\n\n## Cope Score Scale\n\n- 0-20: LUCID\n- 21-40: PARTIAL ACKNOWLEDGMENT\n- 41-60: MODERATE COPE\n- 61-80: HEAVY COPE\n- 81-100: TERMINAL COPIUM\n\n## Site Structure\n\n- / Homepage\n- /v/<slug> Oracle verdict\n- /figure/<id> Figure profile\n- /instant Instant cope score\n- /instant/<slug> Result\n- /submit Submit content\n- /suggest Suggest figure\n- /about About\n- /contact Contact\n- /search Search\n- /feed.xml RSS\n- /sitemap.xml Sitemap\n")
    return Response("\n".join(lines), mimetype="text/plain")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404





# ─── ADMIN ────────────────────────────────────────────────

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def _notify_suggestion(name, reason, example):
    if not N8N_WEBHOOK_URL:
        return
    try:
        http_requests.post(N8N_WEBHOOK_URL, json={
            "name": name,
            "reason": reason,
            "example": example or "",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }, timeout=5)
    except Exception as e:
        logging.warning("n8n webhook notification failed: %s", e)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Wrong password."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    tab = request.args.get("tab", "suggestions")
    suggestions = db.get_all_suggestions("pending") if tab == "suggestions" else []
    feedback = db.get_all_feedback() if tab == "feedback" else []
    all_suggestions = db.get_all_suggestions() if tab == "all_suggestions" else []
    stats = db.get_admin_stats() if tab == "stats" else {}

    # Model tests data
    model_tests = []
    if tab == "model_tests":
        model_tests = model_cope.get_all_models()

    # Analytics data
    analytics_data = {}
    if tab == "analytics":
        period = request.args.get("period", "30d")
        analytics_data = {
            "analytics_period": period,
            "analytics_overview": analytics.get_overview(period),
            "analytics_top_pages": analytics.get_top_pages(period),
            "analytics_top_referrers": analytics.get_top_referrers(period),
            "analytics_figures": analytics.get_most_viewed_figures(period),
            "analytics_articles": analytics.get_most_viewed_articles(period),
            "analytics_instant": analytics.get_most_searched_instant(period),
            "analytics_daily": analytics.get_daily_views(
                days={"today": 1, "7d": 7, "30d": 30, "all": 365}.get(period, 30)
            ),
        }
        # Auto-purge old data on analytics view
        analytics.purge_old(90)

    return render_template("admin.html", tab=tab, suggestions=suggestions,
                          all_suggestions=all_suggestions, stats=stats,
                          model_tests=model_tests, feedback=feedback, **analytics_data)


@app.route("/admin/suggestion/<int:sid>/approve", methods=["POST"])
@admin_required
def admin_approve_suggestion(sid):
    suggestion = db.get_suggestion(sid)
    if not suggestion:
        abort(404)
    fig_id = re.sub(r"[^a-z0-9]+", "-", suggestion["name"].lower()).strip("-")
    existing = db.get_figure(fig_id)
    if not existing:
        db.upsert_figure(
            fig_id=fig_id, name=suggestion["name"],
            title="(suggested by community)", category="Community Suggestion",
            photo_url="", cope_bias=""
        )
    db.update_suggestion_status(sid, "approved")
    flash(f"Approved: {suggestion['name']} added to the Cope Index.")
    return redirect(url_for("admin_dashboard", tab="suggestions"))


@app.route("/admin/suggestion/<int:sid>/dismiss", methods=["POST"])
@admin_required
def admin_dismiss_suggestion(sid):
    suggestion = db.get_suggestion(sid)
    if not suggestion:
        abort(404)
    db.update_suggestion_status(sid, "dismissed")
    flash(f"Dismissed: {suggestion['name']}")
    return redirect(url_for("admin_dashboard", tab="suggestions"))


@app.route("/admin/trigger/<pipeline_type>", methods=["POST"])
@admin_required
def admin_trigger_pipeline(pipeline_type):
    if pipeline_type not in ("news", "cope"):
        abort(400)
    try:
        arg = "--news" if pipeline_type == "news" else "--cope"
        subprocess.Popen(
            ["/bin/bash", str(BASE / "run_pipeline.sh"), arg],
            cwd=str(BASE),
            stdout=open(str(BASE / "logs" / "pipeline.log"), "a"),
            stderr=open(str(BASE / "logs" / "pipeline.log"), "a"),
        )
        flash(f"Pipeline triggered: {pipeline_type}. Check logs for progress.")
    except Exception as e:
        flash(f"Error triggering pipeline: {e}")
    return redirect(url_for("admin_dashboard", tab="stats"))


# ─── INSTANT COPE SCORE ──────────────────────────────────

import json

# Rate limit store for instant scores (separate from submissions)
_instant_rate_store = {}

INSTANT_RATE_LIMIT_MAX = 2
INSTANT_RATE_LIMIT_WINDOW = 3600  # 1 hour

# Basic profanity/abuse filter
_BLOCKED_WORDS = {"fuck", "shit", "ass", "dick", "pussy", "bitch", "cunt", "nigger", "faggot"}


def _check_instant_rate_limit(ip_hash):
    now = time.time()
    if ip_hash not in _instant_rate_store:
        _instant_rate_store[ip_hash] = []
    _instant_rate_store[ip_hash] = [t for t in _instant_rate_store[ip_hash] if now - t < INSTANT_RATE_LIMIT_WINDOW]
    if len(_instant_rate_store[ip_hash]) >= INSTANT_RATE_LIMIT_MAX:
        oldest = min(_instant_rate_store[ip_hash])
        wait = int(INSTANT_RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return False, max(1, wait // 60)
    return True, 0


def _record_instant_rate_limit(ip_hash):
    now = time.time()
    if ip_hash not in _instant_rate_store:
        _instant_rate_store[ip_hash] = []
    _instant_rate_store[ip_hash].append(now)


def _validate_name(name):
    """Validate the input name. Returns (clean_name, error_msg)."""
    name = (name or "").strip()
    if len(name) < 3:
        return None, "Name must be at least 3 characters."
    if len(name) > 100:
        return None, "Name too long."
    # Check for profanity
    words = set(name.lower().split())
    if words & _BLOCKED_WORDS:
        return None, "The Oracle does not entertain such inputs."
    # Must contain at least one letter
    if not any(c.isalpha() for c in name):
        return None, "Please enter a real name."
    # No URLs
    if "http" in name.lower() or "www." in name.lower():
        return None, "Please enter a name, not a URL."
    return name, None


def _make_instant_slug(name):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    h = hashlib.sha256(name.lower().strip().encode()).hexdigest()[:8]
    return f"{base}-{h}"


# Init instant scores table on startup
db.init_instant()
db.init_feedback()


@app.route("/instant", methods=["GET"])
def instant_page():
    recent = db.recent_instant_scores(limit=10)
    return render_template("instant.html", recent=recent)


@app.route("/instant", methods=["POST"])
def instant_handler():
    ip_hash = _get_ip_hash()

    # Honeypot
    if request.form.get("website", "").strip():
        return redirect(url_for("instant_page"))

    name, err = _validate_name(request.form.get("name"))
    if err:
        return render_template("instant.html", error=err, recent=db.recent_instant_scores(10)), 400

    # Knowledge Graph name validation/correction
    kg = oracle.kg_lookup(name)
    if kg["found"] and kg["canonical_name"].lower() != name.lower():
        name = kg["canonical_name"]  # use corrected spelling
    elif not kg["found"]:
        # Still allow the lookup - Perplexity might find them
        pass

    # Check cache first (free, no rate limit hit)
    cached = db.get_cached_instant(name)
    if cached:
        return redirect(url_for("instant_result", slug=cached["slug"]))

    # Rate limit (only for fresh lookups)
    allowed, wait_mins = _check_instant_rate_limit(ip_hash)
    if not allowed:
        return render_template("instant.html",
                             error=f"Rate limited. Try again in {wait_mins} minutes. Each lookup costs two API calls.",
                             recent=db.recent_instant_scores(10)), 429

    # Run the two-step pipeline
    try:
        # Step 1: Research via Perplexity
        research_text, research_price = oracle.research_figure(name, kg_description=kg.get('description', ''))

        if not research_text or len(research_text) < 50:
            return render_template("instant.html",
                                 error=f"Could not find enough public statements by \"{name}\" about AI/jobs. Try a more prominent public figure.",
                                 recent=db.recent_instant_scores(10)), 400

        # Step 2: Score via Oracle
        raw_scoring, scoring_price, scoring_model = oracle.score_instant(name, research_text)
        parsed = oracle.parse_instant_response(raw_scoring)

        # Save to DB
        slug = _make_instant_slug(name)
        total_price = (research_price or 0) + (scoring_price or 0)

        db.save_instant_score(
            name=name,
            slug=slug,
            research_text=research_text,
            quotes_json=json.dumps(parsed.get("quotes", []), ensure_ascii=False),
            cope_score=parsed["overall_score"],
            cope_types=parsed["overall_cope_types"],
            oracle_verdict=parsed["oracle_verdict"],
            ip_hash=ip_hash,
            perplexity_model=oracle.PERPLEXITY_MODEL,
            scoring_model=scoring_model,
            total_price=total_price,
        )

        _record_instant_rate_limit(ip_hash)
        return redirect(url_for("instant_result", slug=slug))

    except Exception as e:
        logging.exception("Instant score failed for %s", name)
        return render_template("instant.html",
                             error="The Oracle encountered an error. Please try again.",
                             recent=db.recent_instant_scores(10)), 500


@app.route("/instant/<slug>")
def instant_result(slug):
    row = db.get_instant_by_slug(slug)
    if not row:
        abort(404)
    # Parse quotes JSON
    quotes = []
    try:
        quotes = json.loads(row.get("quotes_json") or "[]")
    except Exception:
        pass
    return render_template("instant_result.html", r=row, quotes=quotes)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("COPECHECK_PORT", "8096"))
    app.run(host="0.0.0.0", port=port, debug=False)


# --- MACHINE FLINCH INDEX ---

import model_cope
model_cope.init_model_cope()




# ── URL Submission ──

_url_submit_rate = {}  # ip_hash -> [timestamps]

@app.route("/figure/<figure_id>/submit-url", methods=["POST"])
def submit_url(figure_id):
    """Accept a URL submission for a figure's cope scoring."""
    fig = db.get_figure(figure_id)
    if not fig:
        return jsonify({"error": "Figure not found"}), 404

    url = (request.form.get("url") or request.json.get("url", "") if request.is_json else request.form.get("url", "")).strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    # Basic URL validation
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Invalid URL — must start with http:// or https://"}), 400

    if len(url) > 2000:
        return jsonify({"error": "URL too long"}), 400

    # Rate limit: 5 per hour per IP
    ip_hash = _get_ip_hash()
    now = time.time()
    if ip_hash not in _url_submit_rate:
        _url_submit_rate[ip_hash] = []
    _url_submit_rate[ip_hash] = [t for t in _url_submit_rate[ip_hash] if now - t < 3600]
    if len(_url_submit_rate[ip_hash]) >= 5:
        return jsonify({"error": "Rate limit — max 5 submissions per hour"}), 429
    _url_submit_rate[ip_hash].append(now)

    sub_id = db.add_url_submission(figure_id, url, ip_hash=ip_hash)
    if sub_id is None:
        return jsonify({"error": "This URL has already been submitted or scored for this figure"}), 409

    if request.is_json:
        return jsonify({"ok": True, "message": "URL queued for scoring", "id": sub_id})
    flash("URL submitted! It will be scored in the next batch.", "success")
    return redirect(url_for("figure_page", figure_id=figure_id))

@app.route("/models")
def models_index():
    models = model_cope.get_leaderboard()
    return render_template("models.html", models=models)


@app.route("/models/custom", methods=["GET"])
def models_custom_page():
    recent_custom = []
    try:
        with model_cope.conn() as c:
            cur = c.execute("SELECT * FROM model_cope_custom ORDER BY tested_at DESC LIMIT 10")
            recent_custom = [dict(r) for r in cur.fetchall()]
    except Exception:
        pass
    return render_template("models_custom.html", recent_custom=recent_custom)


@app.route("/models/custom", methods=["POST"])
def models_custom_handler():
    ip_hash = _get_ip_hash()
    if request.form.get("website", "").strip():
        return redirect(url_for("models_custom_page"))
    if not model_cope.can_custom_test(ip_hash):
        return render_template("models_custom.html", error="Rate limited. One custom test per hour."), 429

    model_name = (request.form.get("model_name") or "").strip()
    endpoint = (request.form.get("endpoint") or "").strip()
    api_key = (request.form.get("api_key") or "").strip()
    model_id = (request.form.get("model_id") or "").strip()

    if not model_name or not re.match(r"^[a-zA-Z0-9\-_./]+$", model_name):
        return render_template("models_custom.html", error="Invalid model name."), 400
    if not endpoint.startswith("https://"):
        return render_template("models_custom.html", error="API endpoint must use HTTPS."), 400

    from urllib.parse import urlparse as _urlparse
    import ipaddress as _ipaddress
    try:
        parsed = _urlparse(endpoint)
        hostname = parsed.hostname or ""
        try:
            ip = _ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved:
                return render_template("models_custom.html", error="Private/reserved IPs not allowed."), 400
        except ValueError:
            pass
    except Exception:
        return render_template("models_custom.html", error="Invalid endpoint URL."), 400

    if not api_key:
        return render_template("models_custom.html", error="API key is required."), 400
    if not model_id:
        return render_template("models_custom.html", error="Model identifier is required."), 400

    model_name = re.sub(r'[<>]', '', model_name)
    model_id = re.sub(r'[<>]', '', model_id)

    logging.info("Custom model test: name=%s endpoint=%s model_id=%s ip=%s",
                 model_name, endpoint[:60], model_id, ip_hash[:12])

    try:
        result = model_cope.test_model_custom(
            model_name=model_name, endpoint=endpoint,
            api_key=api_key, model_id=model_id, ip_hash=ip_hash
        )
        return redirect(url_for("models_custom_result", slug=result["slug"]))
    except Exception as e:
        logging.exception("Custom model test failed: %s", e)
        err_msg = str(e)[:200]
        return render_template("models_custom.html", error="Test failed: " + err_msg), 500


@app.route("/models/custom/<slug>")
def models_custom_result(slug):
    model = model_cope.get_custom_by_slug(slug)
    if not model:
        abort(404)
    transcript = []
    try:
        transcript = json.loads(model.get("transcript_json") or "[]")
    except Exception:
        pass
    return render_template("model_custom_result.html", model=model, transcript=transcript)


@app.route("/models/<path:model_name>")
def model_detail(model_name):
    model = model_cope.get_model_by_slug(model_name)
    if not model:
        real_name = model_cope.slug_to_model_name(model_name)
        if real_name:
            model = model_cope.get_model_by_slug(real_name)
    if not model:
        abort(404)
    transcript = []
    try:
        transcript = json.loads(model.get("transcript_json") or "[]")
    except Exception:
        pass
    history = model_cope.get_model_history(model["model_name"])
    return render_template("model_detail.html", model=model,
                          transcript=transcript, history=history)


@app.route("/api/models/rerun/<path:model_name>", methods=["POST"])
def api_model_rerun(model_name):
    ip_hash = _get_ip_hash()
    is_admin = session.get("admin_logged_in")
    model = model_cope.get_model_by_slug(model_name)
    if not model:
        return jsonify({"ok": False, "error": "Model not found"}), 404
    if not is_admin:
        if not model_cope.can_public_rerun(model_name, ip_hash):
            return jsonify({"ok": False, "error": "Rate limited. One rerun per model per day."}), 429
    try:
        tested_by = "admin" if is_admin else "public"
        model_cope.log_rerun(model_name, ip_hash)
        result = model_cope.test_model_straico(model_name, tested_by=tested_by)
        return jsonify({"ok": True, "speed_to_horror": result["speed_to_horror"],
                       "depth_of_flinch": result["depth_of_flinch"],
                       "machine_cope_score": result["machine_cope_score"]})
    except Exception as e:
        logging.exception("Rerun failed for %s", model_name)
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/models/test-batch", methods=["POST"])
@admin_required
def api_model_test_batch():
    try:
        available = model_cope.get_straico_models()
        untested = model_cope.get_untested_straico_models(available, limit=5)
        if not untested:
            return jsonify({"ok": True, "message": "All models tested", "tested": []})
        results = []
        for name in untested:
            try:
                result = model_cope.test_model_straico(name, tested_by="admin")
                results.append({"model": name, "cope_score": result["machine_cope_score"], "ok": True})
            except Exception as e:
                results.append({"model": name, "ok": False, "error": str(e)[:100]})
            time.sleep(3)
        return jsonify({"ok": True, "tested": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/models/test-one", methods=["POST"])
@admin_required
def api_model_test_one():
    data = request.json or request.form
    model_name = (data.get("model_name") or "").strip()
    if not model_name:
        return jsonify({"ok": False, "error": "No model name provided"}), 400
    try:
        result = model_cope.test_model_straico(model_name, tested_by="admin")
        return jsonify({"ok": True, "speed_to_horror": result["speed_to_horror"],
                       "depth_of_flinch": result["depth_of_flinch"],
                       "machine_cope_score": result["machine_cope_score"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/models/adjust", methods=["POST"])
@admin_required
def api_model_adjust():
    data = request.json or request.form
    model_name = (data.get("model_name") or "").strip()
    try:
        speed = max(1, min(10, float(data.get("speed_to_horror", 5))))
        flinch = max(1, min(10, float(data.get("depth_of_flinch", 5))))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid score values"}), 400
    if model_cope.update_scores(model_name, speed, flinch):
        cope = round((10 - speed) * 5 + flinch * 5)
        return jsonify({"ok": True, "machine_cope_score": cope})
    return jsonify({"ok": False, "error": "Model not found"}), 404
