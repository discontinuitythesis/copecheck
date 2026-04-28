import os
"""Feed sources and keyword filters for CopeCheck v2."""

from urllib.parse import quote_plus

# ─── Google News RSS ──────────────────────────────────────────
GOOGLE_NEWS_QUERIES = [
    "AI jobs",
    "AI automation labour",
    "AI unemployment",
    "AI white collar",
    "automation jobs",
    "cognitive automation",
    "AI layoffs",
    "generative AI employment",
    "AI replacing workers",
    "AI future of work",
]

def google_news_url(q: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(q + ' when:7d')}&hl=en-US&gl=US&ceid=US:en"
    )

GOOGLE_NEWS_FEEDS = [(q, google_news_url(q)) for q in GOOGLE_NEWS_QUERIES]

# ─── arXiv ────────────────────────────────────────────────────
ARXIV_FEEDS = [
    ("arXiv cs.AI", "https://rss.arxiv.org/rss/cs.AI"),
    ("arXiv econ.GN", "https://rss.arxiv.org/rss/econ.GN"),
    ("arXiv cs.CY", "https://rss.arxiv.org/rss/cs.CY"),
]

# ─── Hacker News ──────────────────────────────────────────────
HN_FEEDS = [
    ("Hacker News Front Page", "https://hnrss.org/frontpage"),
    ("Hacker News Best", "https://hnrss.org/best"),
]

# ─── Press & Substacks ───────────────────────────────────────
PRESS_FEEDS = [
    ("Stratechery", "https://stratechery.com/feed/"),
    ("Noah Smith", "https://www.noahpinion.blog/feed"),
    ("Matt Yglesias", "https://www.slowboring.com/feed"),
    ("Axios Future", "https://www.axios.com/feeds/feed.rss"),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
    ("The Verge AI", "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml"),
    ("Ars Technica AI", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
]

# ─── Working Papers ───────────────────────────────────────────
WORKING_PAPER_FEEDS = [
    ("NBER New Papers", "https://www.nber.org/rss/new.xml"),
]

ALL_FEEDS = GOOGLE_NEWS_FEEDS + ARXIV_FEEDS + HN_FEEDS + PRESS_FEEDS + WORKING_PAPER_FEEDS

# ─── Topic keywords (for generic feed filtering) ─────────────
TOPIC_KEYWORDS = [
    "ai", "artificial intelligence", "llm", "large language model",
    "automation", "automate", "automated",
    "job", "jobs", "employment", "unemploy", "labour", "labor",
    "wage", "wages", "worker", "workers", "workforce",
    "white collar", "white-collar", "knowledge work",
    "displace", "displacement", "obsolete", "obsolescence",
    "agi", "agents", "agentic",
    "layoff", "layoffs", "hiring freeze",
    "gig economy", "ubi", "universal basic income",
    "productivity paradox", "task automation",
    "future of work", "post-work", "jobless",
]



# ─── GNews API ────────────────────────────────────────────────
import requests as _requests

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY", "").strip()
GNEWS_URL = "https://gnews.io/api/v4/search"

GNEWS_QUERIES = [
    "AI jobs automation",
    "artificial intelligence unemployment",
    "AI replacing workers",
    "AI layoffs",
    "AI future of work",
]

def gnews_search(query: str, max_results: int = 10) -> list[dict]:
    """Search GNews API. Returns list of {title, url, source, published, snippet, body}.
    Free tier: 100 requests/day, 10 results per request."""
    if not GNEWS_API_KEY:
        return []
    params = {
        "q": query,
        "lang": "en",
        "max": min(max_results, 10),
        "apikey": GNEWS_API_KEY,
        "sortby": "publishedAt",
    }
    try:
        resp = _requests.get(GNEWS_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        articles = []
        for a in data.get("articles", []):
            articles.append({
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "source": a.get("source", {}).get("name", ""),
                "published": a.get("publishedAt", ""),
                "snippet": a.get("description", ""),
                "body": a.get("content", ""),
            })
        return articles
    except Exception as e:
        import logging
        logging.getLogger("sources").warning("GNews search failed for %r: %s", query, e)
        return []

TRUSTED_NARROW_FEEDS = set(q for q, _ in GOOGLE_NEWS_FEEDS)
