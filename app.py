"""CopeCheck v2 — Flask app with Cope Index, News Feed, Comments, RSS, Submit, and OG tags."""
import hashlib
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
                   url_for, Response, jsonify, flash, send_from_directory)
from werkzeug.utils import secure_filename

import db
import oracle

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
CAPTCHA_ANSWER = "artificial intelligence"
RATE_LIMIT_MAX = 3
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds

db.init()

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


app.jinja_env.filters["fmtdate"] = _fmt_date
app.jinja_env.filters["renderverdict"] = _render_markdown
app.jinja_env.filters["copecolor"] = _cope_color
app.jinja_env.filters["copelabel"] = _cope_label
app.jinja_env.filters["trendarrow"] = _trend_arrow
app.jinja_env.filters["first_sentences"] = _first_sentences
app.jinja_env.globals["now"] = datetime.utcnow


# ─── ROUTES ───────────────────────────────────────────────

@app.route("/")
def index():
    leaderboard = db.get_leaderboard()
    items = db.recent_analysed(limit=40)
    total = db.counts().get("analysed", 0)
    cope_of_week = db.cope_of_the_week()
    return render_template("index.html", leaderboard=leaderboard,
                          items=items, total=total, cope_of_week=cope_of_week)


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
    if captcha != CAPTCHA_ANSWER:
        return render_template("submit.html",
                             error="Incorrect answer. What does AI stand for?"), 400

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
    if captcha != CAPTCHA_ANSWER:
        return render_template("suggest.html",
                             error="Incorrect answer. What does AI stand for?"), 400

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


# ─── STANDARD ROUTES ─────────────────────────────────────

@app.route("/healthz")
def healthz():
    c = db.counts()
    return {"ok": True, "counts": c}, 200


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\nSitemap: https://copecheck.com/feed.xml\n",
                    mimetype="text/plain")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("COPECHECK_PORT", "8096"))
    app.run(host="0.0.0.0", port=port, debug=False)
