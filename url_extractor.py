"""
URL content extractor for CopeCheck.
Handles articles, YouTube transcripts, and X/Twitter posts.
"""
import re
import logging
import requests
import trafilatura

log = logging.getLogger("url_extractor")

CRAWL4AI_URL = "http://localhost:11235"
YT_TRANSCRIPT_TIMEOUT = 30
ARTICLE_TIMEOUT = 25


def detect_url_type(url: str) -> str:
    """Detect what kind of URL this is."""
    u = url.lower().strip()
    if any(d in u for d in ["youtube.com/watch", "youtu.be/", "youtube.com/shorts"]):
        return "youtube"
    if any(d in u for d in ["twitter.com/", "x.com/"]):
        return "tweet"
    return "article"


def extract_content(url: str, url_type: str = None) -> dict:
    """
    Extract text content from a URL.
    Returns {"text": str, "title": str, "url_type": str, "error": str|None}
    """
    if not url_type:
        url_type = detect_url_type(url)

    try:
        if url_type == "youtube":
            return _extract_youtube(url)
        elif url_type == "tweet":
            return _extract_tweet(url)
        else:
            return _extract_article(url)
    except Exception as e:
        log.error("extract_content failed for %s: %s", url, e)
        return {"text": "", "title": "", "url_type": url_type, "error": str(e)}


def _extract_article(url: str) -> dict:
    """Extract article text using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=False)
        if not downloaded:
            return {"text": "", "title": "", "url_type": "article",
                    "error": "Could not download URL"}
        text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=False,
            favor_recall=True,
        )
        # Try to get title
        title = ""
        try:
            metadata = trafilatura.extract_metadata(downloaded)
            if metadata:
                title = metadata.title or ""
        except Exception:
            pass
        return {"text": (text or "").strip(), "title": title,
                "url_type": "article", "error": None}
    except Exception as e:
        return {"text": "", "title": "", "url_type": "article", "error": str(e)}


def _extract_youtube(url: str) -> dict:
    """Extract YouTube transcript using youtube-transcript-api or fallback."""
    video_id = _parse_youtube_id(url)
    if not video_id:
        return {"text": "", "title": "", "url_type": "youtube",
                "error": "Could not parse YouTube video ID"}

    # Try youtube-transcript-api first
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        text = " ".join([t["text"] for t in transcript_list])
        # Get title via oembed
        title = _get_youtube_title(video_id)
        return {"text": text.strip(), "title": title,
                "url_type": "youtube", "error": None}
    except ImportError:
        log.warning("youtube-transcript-api not installed, trying Crawl4AI")
    except Exception as e:
        log.warning("youtube-transcript-api failed: %s, trying Crawl4AI", e)

    # Fallback: use Crawl4AI
    return _extract_via_crawl4ai(url, "youtube")


def _parse_youtube_id(url: str) -> str:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return ""


def _get_youtube_title(video_id: str) -> str:
    """Get YouTube video title via oembed API."""
    try:
        resp = requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("title", "")
    except Exception:
        pass
    return ""


def _extract_tweet(url: str) -> dict:
    """Extract tweet content using Crawl4AI (X blocks most scrapers)."""
    return _extract_via_crawl4ai(url, "tweet")


def _extract_via_crawl4ai(url: str, url_type: str) -> dict:
    """Use local Crawl4AI instance to extract content from JS-heavy pages."""
    try:
        # Crawl4AI v2 API
        payload = {
            "urls": [url],
            "priority": 5,
            "word_count_threshold": 50,
            "screenshot": False,
            "js_code": None,
            "wait_for": "body",
            "bypass_cache": True,
        }
        resp = requests.post(
            f"{CRAWL4AI_URL}/crawl",
            json=payload,
            timeout=60,
        )
        if resp.ok:
            data = resp.json()
            # Handle both sync and async responses
            if isinstance(data, dict) and "result" in data:
                result = data["result"]
                if isinstance(result, dict):
                    text = result.get("markdown", "") or result.get("extracted_content", "") or result.get("cleaned_html", "")
                    title = result.get("metadata", {}).get("title", "") if isinstance(result.get("metadata"), dict) else ""
                    return {"text": text.strip(), "title": title, "url_type": url_type, "error": None}
            # Try direct task result
            if isinstance(data, dict) and "task_id" in data:
                task_id = data["task_id"]
                # Poll for result
                import time
                for _ in range(30):
                    time.sleep(2)
                    check = requests.get(f"{CRAWL4AI_URL}/task/{task_id}", timeout=10)
                    if check.ok:
                        task_data = check.json()
                        if task_data.get("status") == "completed":
                            result = task_data.get("result", {})
                            text = result.get("markdown", "") or result.get("extracted_content", "")
                            title = result.get("metadata", {}).get("title", "") if isinstance(result.get("metadata"), dict) else ""
                            return {"text": text.strip(), "title": title, "url_type": url_type, "error": None}
                        elif task_data.get("status") == "failed":
                            return {"text": "", "title": "", "url_type": url_type,
                                    "error": f"Crawl4AI task failed: {task_data.get('error', 'unknown')}"}
                return {"text": "", "title": "", "url_type": url_type,
                        "error": "Crawl4AI task timed out"}
            # Unexpected response
            return {"text": "", "title": "", "url_type": url_type,
                    "error": f"Unexpected Crawl4AI response: {str(data)[:200]}"}
        else:
            return {"text": "", "title": "", "url_type": url_type,
                    "error": f"Crawl4AI HTTP {resp.status_code}"}
    except requests.exceptions.ConnectionError:
        log.warning("Crawl4AI not available at %s", CRAWL4AI_URL)
        return {"text": "", "title": "", "url_type": url_type,
                "error": "Crawl4AI not available"}
    except Exception as e:
        return {"text": "", "title": "", "url_type": url_type,
                "error": f"Crawl4AI error: {str(e)}"}


def is_spam(text: str, url: str) -> bool:
    """Basic spam detection for submitted URLs."""
    if not text or len(text.strip()) < 50:
        return True
    t = text.lower()
    # Must mention AI/tech/jobs in some way
    ai_keywords = ["ai", "artificial intelligence", "automation", "robot", "machine learning",
                   "jobs", "employment", "workers", "workforce", "labor", "labour",
                   "technology", "chatgpt", "gpt", "llm", "neural", "algorithm"]
    if not any(kw in t for kw in ai_keywords):
        return True
    return False
