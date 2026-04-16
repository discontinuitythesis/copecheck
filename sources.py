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

TRUSTED_NARROW_FEEDS = set(q for q, _ in GOOGLE_NEWS_FEEDS)
