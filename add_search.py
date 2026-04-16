#!/usr/bin/env python3
"""Add FTS5 search to CopeCheck — patches db.py, app.py, and templates."""
import re
from pathlib import Path

BASE = Path(__file__).parent

def patch_db():
    """Add FTS5 table and search functions to db.py"""
    db_path = BASE / "db.py"
    code = db_path.read_text()
    
    # Add FTS5 table creation to SCHEMA
    fts_schema = '''
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    slug, title, source, snippet, one_liner, verdict_md,
    content='articles',
    content_rowid='id'
);
'''
    # Insert before the closing triple-quote of SCHEMA
    if "articles_fts" not in code:
        code = code.replace(
            'CREATE INDEX IF NOT EXISTS idx_comments_slug ON comments(article_slug, created_at ASC);\n"""',
            'CREATE INDEX IF NOT EXISTS idx_comments_slug ON comments(article_slug, created_at ASC);\n' + fts_schema + '"""'
        )
    
    # Add search function and FTS rebuild
    search_funcs = '''

def rebuild_fts():
    """Rebuild the FTS5 index from articles table."""
    with conn() as c:
        c.execute("DELETE FROM articles_fts")
        c.execute("""
            INSERT INTO articles_fts(rowid, slug, title, source, snippet, one_liner, verdict_md)
            SELECT id, slug, title, source, COALESCE(snippet,''), COALESCE(one_liner,''), COALESCE(verdict_md,'')
            FROM articles WHERE status = 'analysed'
        """)


def search_articles(query, limit=30):
    """Full-text search across articles."""
    if not query or len(query.strip()) < 2:
        return []
    # Escape FTS5 special chars and add prefix matching
    safe_q = re.sub(r'[^\\w\\s]', ' ', query).strip()
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
            # Fallback to LIKE search if FTS fails
            like_q = f"%{safe_q}%"
            cur = c.execute("""
                SELECT * FROM articles
                WHERE status = 'analysed' AND (
                    title LIKE ? OR one_liner LIKE ? OR source LIKE ? OR verdict_md LIKE ?
                )
                ORDER BY analysed_at DESC LIMIT ?
            """, (like_q, like_q, like_q, like_q, limit))
            return [dict(r) for r in cur.fetchall()]
'''
    if "def search_articles" not in code:
        code += search_funcs
    
    db_path.write_text(code)
    print("Patched db.py with FTS5 search")

def patch_app():
    """Add search route to app.py"""
    app_path = BASE / "app.py"
    code = app_path.read_text()
    
    search_route = '''

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        results = db.search_articles(q, limit=40)
    return render_template("search.html", query=q, results=results)
'''
    if '/search' not in code:
        # Insert before the healthz route
        code = code.replace('@app.route("/healthz")', search_route + '\n@app.route("/healthz")')
    
    app_path.write_text(code)
    print("Patched app.py with search route")

def create_search_template():
    """Create search results template."""
    tmpl = BASE / "templates" / "search.html"
    tmpl.write_text('''{% extends "base.html" %}
{% block title %}Search{% if query %}: {{ query }}{% endif %} — CopeCheck{% endblock %}
{% block content %}
<section class="search-page">
  <h1>Search the Autopsy Archive</h1>
  <form class="search-form" action="/search" method="get">
    <input type="text" name="q" value="{{ query }}" placeholder="Search headlines, sources, verdicts…" autofocus />
    <button type="submit">Search</button>
  </form>

  {% if query %}
    <p class="search-meta">{{ results|length }} result{{ 's' if results|length != 1 }} for &ldquo;{{ query }}&rdquo;</p>
  {% endif %}

  {% if results %}
  <div class="feed">
    {% for a in results %}
    <article class="card">
      <header class="card-head">
        <span class="card-source">{{ a.source }}</span>
        <span class="card-dot">&middot;</span>
        <span class="card-date">{{ a.published | fmtdate or a.analysed_at | fmtdate }}</span>
      </header>
      <h3 class="card-title">
        <a href="/v/{{ a.slug }}">{{ a.title }}</a>
      </h3>
      {% if a.one_liner %}
      <p class="card-verdict">{{ a.one_liner }}</p>
      {% endif %}
      <footer class="card-foot">
        <a class="card-link" href="/v/{{ a.slug }}">Read the autopsy &rarr;</a>
        <a class="card-link faded" href="{{ a.url }}" rel="noopener" target="_blank">Original</a>
      </footer>
    </article>
    {% endfor %}
  </div>
  {% elif query %}
    <p class="empty">No results. The Oracle has not yet autopsied anything matching &ldquo;{{ query }}&rdquo;.</p>
  {% endif %}
</section>
{% endblock %}
''')
    print("Created search.html template")

def patch_index_template():
    """Add search bar to the homepage."""
    tmpl = BASE / "templates" / "index.html"
    code = tmpl.read_text()
    
    search_bar = '''  <form class="search-form" action="/search" method="get">
    <input type="text" name="q" placeholder="Search headlines, sources, verdicts…" />
    <button type="submit">Search</button>
  </form>
'''
    if 'search-form' not in code:
        # Insert after the meter paragraph
        code = code.replace(
            '</section>\n\n<!-- COPE INDEX LEADERBOARD -->',
            search_bar + '</section>\n\n<!-- COPE INDEX LEADERBOARD -->'
        )
    
    tmpl.write_text(code)
    print("Patched index.html with search bar")

def patch_base_template():
    """Add search link to nav if there's a nav element."""
    tmpl = BASE / "templates" / "base.html"
    code = tmpl.read_text()
    
    # Add search to nav if not already there
    if '/search' not in code and '<nav' in code:
        code = code.replace('</nav>', '<a href="/search">Search</a></nav>')
        tmpl.write_text(code)
        print("Patched base.html nav with search link")
    elif '/search' not in code:
        # If no nav, just note it
        print("No nav element in base.html — search accessible via homepage bar and /search URL")

def patch_css():
    """Add search form styles to style.css"""
    css_path = BASE / "static" / "style.css"
    code = css_path.read_text()
    
    search_css = '''
/* Search */
.search-form { display:flex; gap:0.5rem; margin:1.5rem 0; max-width:600px; }
.search-form input {
  flex:1; padding:0.75rem 1rem; font-size:1rem;
  border:2px solid #30363d; border-radius:8px;
  background:#0d1117; color:#c9d1d9;
  font-family:inherit;
}
.search-form input:focus { border-color:#ff3333; outline:none; }
.search-form input::placeholder { color:#484f58; }
.search-form button {
  padding:0.75rem 1.5rem; font-size:1rem; font-weight:700;
  border:none; border-radius:8px; cursor:pointer;
  background:#ff3333; color:#0d1117;
  font-family:inherit; text-transform:uppercase; letter-spacing:0.05em;
}
.search-form button:hover { background:#ff5555; }
.search-page { max-width:800px; margin:0 auto; }
.search-page h1 { margin-bottom:0.5rem; }
.search-meta { color:#8b949e; margin-bottom:1.5rem; }
'''
    if '.search-form' not in code:
        code += search_css
        css_path.write_text(code)
        print("Patched style.css with search styles")

if __name__ == "__main__":
    patch_db()
    patch_app()
    create_search_template()
    patch_index_template()
    patch_base_template()
    patch_css()
    print("\nAll search patches applied. Restart the service to activate.")
