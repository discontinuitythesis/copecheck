#!/usr/bin/env python3
"""
Upgrade CopeCheck: Monday-locked Cope of the Week with archive.
1. Create cotw_archive table
2. Replace cope_of_the_week() in db.py to lock in on Mondays
3. Add /cope-of-the-week archive route to app.py
4. Create cotw_archive.html template
"""
import sqlite3, os, re

DB_PATH = "/home/ben/infra/copecheck/data/copecheck.db"
DB_PY   = "/home/ben/infra/copecheck/db.py"
APP_PY  = "/home/ben/infra/copecheck/app.py"
TPL_DIR = "/home/ben/infra/copecheck/templates"

# ── 1. Create cotw_archive table ──
conn = sqlite3.connect(DB_PATH)
conn.execute("""
CREATE TABLE IF NOT EXISTS cotw_archive (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start  TEXT NOT NULL UNIQUE,   -- Monday date YYYY-MM-DD
    slug        TEXT NOT NULL,
    title       TEXT,
    source      TEXT,
    one_liner   TEXT,
    url         TEXT,
    published   TEXT,
    analysed_at TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()
conn.close()
print("✓ cotw_archive table created")

# ── 2. Replace cope_of_the_week() in db.py ──
with open(DB_PY, "r") as f:
    db_code = f.read()

# Find the old function and replace it
old_func_pattern = r'def cope_of_the_week\(\):.*?return best if best_score > 0 else \(candidates\[0\] if candidates else None\)'
new_func = '''def cope_of_the_week():
    """Return the locked-in Cope of the Week. Selected each Monday, cached in cotw_archive."""
    from datetime import datetime, timedelta
    today = datetime.utcnow().date()
    # Find this week's Monday
    monday = today - timedelta(days=today.weekday())
    week_key = monday.isoformat()

    with conn() as c:
        # Check if we already have a winner for this week
        cached = c.execute(
            "SELECT * FROM cotw_archive WHERE week_start = ?", (week_key,)
        ).fetchone()
        if cached:
            # Return the full article row
            art = c.execute(
                "SELECT * FROM articles WHERE slug = ?", (cached["slug"],)
            ).fetchone()
            return dict(art) if art else None

        # Pick a winner: highest-cope article analysed since last Monday
        prev_monday = (monday - timedelta(days=7)).isoformat()
        cope_words = ['copium', 'lullaby', 'ideological anesthetic', 'false reassurance',
                      'denial', 'deflection', 'elite self-exoneration', 'techno-optimism',
                      'augmentation fantasy', 'regulatory hopium', 'timeline minimisation',
                      'jobs will be created', 'human creativity cope']
        cur = c.execute(
            """SELECT * FROM articles
               WHERE status = 'analysed' AND verdict_md IS NOT NULL
                 AND analysed_at >= ?
               ORDER BY analysed_at DESC LIMIT 50""",
            (prev_monday,),
        )
        candidates = [dict(r) for r in cur.fetchall()]

        if not candidates:
            # Fallback: most recent 20 articles
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

        winner = best if best_score > 0 else candidates[0]

        # Lock it in
        c.execute(
            """INSERT OR IGNORE INTO cotw_archive
               (week_start, slug, title, source, one_liner, url, published, analysed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (week_key, winner["slug"], winner.get("title"), winner.get("source"),
             winner.get("one_liner"), winner.get("url"), winner.get("published"),
             winner.get("analysed_at")),
        )
        return winner


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
        return [dict(r) for r in cur.fetchall()]'''

db_code_new = re.sub(old_func_pattern, new_func, db_code, flags=re.DOTALL)

if db_code_new == db_code:
    print("⚠ Could not find cope_of_the_week() to replace — check manually")
else:
    with open(DB_PY, "w") as f:
        f.write(db_code_new)
    print("✓ db.py updated with Monday-locked cope_of_the_week() + cotw_archive_list()")

# ── 3. Add archive route to app.py ──
with open(APP_PY, "r") as f:
    app_code = f.read()

archive_route = '''

@app.route("/cope-of-the-week")
def cotw_archive():
    weeks = db.cotw_archive_list()
    return render_template("cotw_archive.html", weeks=weeks)
'''

# Insert after the index route block
if "/cope-of-the-week" not in app_code:
    # Find a good insertion point — after the index route
    insert_after = '@app.route("/v/<slug>")'
    idx = app_code.find(insert_after)
    if idx > 0:
        app_code = app_code[:idx] + archive_route + "\n" + app_code[idx:]
        with open(APP_PY, "w") as f:
            f.write(app_code)
        print("✓ app.py: added /cope-of-the-week route")
    else:
        print("⚠ Could not find insertion point in app.py")
else:
    print("✓ app.py: /cope-of-the-week route already exists")

# ── 4. Create archive template ──
template = '''{% extends "base.html" %}
{% block title %}Cope of the Week Archive — CopeCheck{% endblock %}
{% block content %}
<section class="container" style="max-width:800px;margin:2rem auto;padding:0 1rem">
  <h1 style="font-family:var(--font-display);color:var(--gold);margin-bottom:0.5rem">Cope of the Week Archive</h1>
  <p style="color:#888;margin-bottom:2rem">Every Monday we crown the week's most copium-laden article. Here's the hall of shame.</p>

  {% if weeks %}
  <div class="cotw-archive-list">
    {% for w in weeks %}
    <article class="cotw-card" style="margin-bottom:1.5rem;background:var(--surface);border:1px solid rgba(216,201,163,0.1);border-radius:8px;padding:1.2rem;border-left:3px solid var(--gold)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem">
        <span class="cotw-badge" style="font-size:0.7rem;background:var(--gold);color:#111;padding:2px 8px;border-radius:3px;font-weight:700">WEEK OF {{ w.week_start }}</span>
        {% if w.source %}
        <span style="color:#888;font-size:0.8rem">{{ w.source }}</span>
        {% endif %}
      </div>
      <h3 style="margin:0.3rem 0;font-size:1.05rem">
        <a href="/v/{{ w.slug }}" style="color:var(--text);text-decoration:none">{{ w.title or w.slug }}</a>
      </h3>
      {% if w.one_liner %}
      <p style="color:#999;font-size:0.85rem;margin:0.3rem 0">{{ w.one_liner }}</p>
      {% endif %}
      <footer style="margin-top:0.5rem;font-size:0.8rem">
        <a href="/v/{{ w.slug }}" style="color:var(--gold)">Read the autopsy &rarr;</a>
        {% if w.url %}
        <a href="{{ w.url }}" rel="noopener noreferrer" target="_blank" style="color:#666;margin-left:1rem">Original</a>
        {% endif %}
      </footer>
    </article>
    {% endfor %}
  </div>
  {% else %}
  <p style="color:#888">No winners yet. Check back after Monday!</p>
  {% endif %}
</section>
{% endblock %}
'''

tpl_path = os.path.join(TPL_DIR, "cotw_archive.html")
with open(tpl_path, "w") as f:
    f.write(template)
print("✓ cotw_archive.html template created")

# ── 5. Seed the archive with current COTW ──
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
# Check if any entry already exists
existing = conn.execute("SELECT count(*) as cnt FROM cotw_archive").fetchone()["cnt"]
if existing == 0:
    print("Seeding archive with current week's winner on next page load...")
conn.close()

print("\nDone! Restart copecheck service to apply.")
