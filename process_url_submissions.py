#!/usr/bin/env python3
"""
Process queued URL submissions: extract content, filter spam, score cope.
Run daily or on-demand: python3 process_url_submissions.py
"""
import logging
import os
import sys
import time
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k] = v

sys.path.insert(0, str(Path(__file__).parent))
import db
import oracle
import url_extractor

log = logging.getLogger("url_submissions")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

db.init()

MAX_PROCESS = int(os.environ.get("MAX_URL_PROCESS", "20"))


def process_pending():
    """Process all pending URL submissions."""
    pending = db.get_pending_submissions(limit=MAX_PROCESS)
    if not pending:
        log.info("No pending URL submissions")
        return 0

    log.info("Processing %d pending URL submissions", len(pending))
    scored = 0

    for sub in pending:
        sub_id = sub["id"]
        url = sub["url"]
        figure_id = sub["figure_id"]
        figure_name = sub.get("figure_name", "unknown")
        figure_title = sub.get("figure_title", "")

        log.info("[%d] Extracting: %s for %s", sub_id, url[:80], figure_name)

        # 1. Detect URL type and extract content
        url_type = url_extractor.detect_url_type(url)
        result = url_extractor.extract_content(url, url_type)

        if result.get("error"):
            log.warning("[%d] Extraction failed: %s", sub_id, result["error"])
            db.update_submission(sub_id, "failed", url_type=url_type,
                               error_msg=result["error"])
            continue

        text = result.get("text", "").strip()
        title = result.get("title", "")

        if not text or len(text) < 50:
            log.warning("[%d] Too little text extracted (%d chars)", sub_id, len(text))
            db.update_submission(sub_id, "failed", extracted_text=text[:500],
                               url_type=url_type, error_msg="Insufficient text extracted")
            continue

        # 2. Spam check
        if url_extractor.is_spam(text, url):
            log.info("[%d] Flagged as spam/irrelevant", sub_id)
            db.update_submission(sub_id, "rejected", extracted_text=text[:500],
                               url_type=url_type, error_msg="Not relevant to AI/jobs")
            continue

        # 3. Extract figure context (look for their name in the content)
        from pipeline import _extract_figure_context
        quote_context = _extract_figure_context(text, figure_name)
        if not quote_context or len(quote_context) < 80:
            # For tweets, use the whole text since it's short
            if url_type == "tweet" and len(text) < 2000:
                quote_context = text
            else:
                log.warning("[%d] Could not find %s context in extracted text", sub_id, figure_name)
                db.update_submission(sub_id, "failed", extracted_text=text[:500],
                                   url_type=url_type,
                                   error_msg=f"Could not find mentions of {figure_name}")
                continue

        # 4. Score cope
        try:
            log.info("[%d] Scoring cope for %s...", sub_id, figure_name)
            cope_result = oracle.score_cope(
                figure_name, figure_title,
                quote_context,
                source_context=f"From {url_type}: {title or url}",
            )

            db.add_cope_entry(
                figure_id=figure_id,
                article_slug=None,
                quote=cope_result.get("cope_quote") or quote_context[:300],
                source_url=url,
                source_title=title or url,
                cope_score=cope_result["cope_score"],
                cope_type=cope_result.get("cope_type", "unknown"),
                analysis_md=cope_result.get("analysis", ""),
                model=cope_result.get("model", ""),
            )

            db.update_submission(sub_id, "scored", extracted_text=text[:2000],
                               url_type=url_type)
            scored += 1
            log.info("[%d] Scored: %s = %.0f/100 (%s)",
                     sub_id, figure_name,
                     cope_result["cope_score"],
                     cope_result.get("cope_type", ""))
            time.sleep(2)  # be nice to APIs

        except Exception as e:
            log.error("[%d] Scoring failed: %s", sub_id, e)
            db.update_submission(sub_id, "failed", extracted_text=text[:500],
                               url_type=url_type, error_msg=str(e)[:500])

    log.info("Done: %d/%d scored", scored, len(pending))
    return scored


if __name__ == "__main__":
    process_pending()
