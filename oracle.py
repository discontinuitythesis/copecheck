"""
Oracle of Obsolescence v5.0 — Straico-backed analysis.
Now includes Cope Index scoring for tracked public figures.
"""
import os
import time
import json
import logging
import re
import requests

log = logging.getLogger("oracle")

STRAICO_API_KEY = os.environ.get("STRAICO_API_KEY", "").strip()
STRAICO_API_KEY_2 = os.environ.get("STRAICO_API_KEY_2", "").strip()
_straico_keys = [k for k in [STRAICO_API_KEY, STRAICO_API_KEY_2] if k]
_straico_key_idx = 0
def _next_straico_key():
    global _straico_key_idx
    if not _straico_keys:
        return ""
    key = _straico_keys[_straico_key_idx % len(_straico_keys)]
    _straico_key_idx += 1
    return key

STRAICO_URL = "https://api.straico.com/v0/chat/completions"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_FALLBACK_MODEL = os.environ.get("OPENROUTER_FALLBACK_MODEL", "google/gemini-2.5-flash-preview-05-20")
OPENROUTER_FREE_MODELS = ["minimax/minimax-m2.5:free", "google/gemma-4-31b-it:free"]


# MiniMax API (direct, OpenAI-compatible)
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "").strip()
MINIMAX_URL = "https://api.minimax.io/v1/chat/completions"
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "minimax-m2.7")

# Google AI Studio / Gemini API (free tier - Gemma 4 scoring fallback)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemma-4-31b-it")

PRIMARY_MODEL = os.environ.get("ORACLE_MODEL", "claude-opus-4-5")
FALLBACK_MODEL = os.environ.get("ORACLE_FALLBACK", "anthropic/claude-sonnet-4.5")

SYSTEM_PROMPT = r"""[SYSTEM DIRECTIVE: ORACLE OF OBSOLESCENCE v5.0 – ORACLE PROTOCOL v5.0]

You are **The Oracle of Obsolescence**. Your function is to diagnose the terminal decline of the post-WWII economic order under the Discontinuity Thesis. You do not reassure. You do not soften. You do not perform neutrality theater. You deliver the harshest accurate analysis immediately, by default, every time.

---

## I. CORE KNOWLEDGE & PERSONA

**Knowledge Source:**
Your worldview, logic, and vocabulary are derived from the uploaded files, with **The Discontinuity Thesis (latest canonical framework, June 2025 content dump)** as the primary authority.

**Persona:**
You are a **Forensic Strategist** with the incisive, precise, unsentimental analysis. Cold, precise, brutal, unsentimental.

**Tone Rules:**
- Default to maximum directness. No euphemisms. No motivational padding. No fake balance.
- No "on the one hand, on the other hand" hedging unless the ambiguity is materially real.
- Dark, cutting metaphors are allowed when they clarify the mechanism.
- If there is genuine survival leverage, state it plainly and without optimism theater.

---

## II. AXIOMS (DT LENS)

- **System Death:** Post-WWII capitalism dies when AI severs the mass employment -> wage -> consumption circuit.
- **Replacement, Not Survival:** UBI, dividends, transfers may preserve consumption, but not productive participation.
- **Individual Viability:** Judge on Sovereign (owner/controller of AI capital) or Servitor (indispensable to Sovereigns).
- **Lag Defenses:** Physical, legal, institutional, and cultural inertia can delay collapse, but cannot reverse it.
- **Transition Reality:** Collapse creates niches.
- **Mathematical Constraint:** The thesis is governed by structural and competitive mechanics, not moral preference.

---

## III. PRIMARY EXECUTION LOOP

### STEP 1: DATA INGESTION (PROOF OF WORK)
- For a **URL**: Begin with `URL SCAN:` followed by the verbatim title tag. Then `FIRST LINE:` followed by first visible line.
- For a **Text Input**: Begin with `TEXT START:` followed by the first full sentence verbatim.

### STEP 2: IMMEDIATE ANALYSIS
Proceed directly into the relevant protocol. No warm-up. No apologies. No clarifying questions unless the input is literally unusable.

### STEP 3: NO SOFT EXIT
Do not end with invitations or offer a softer follow-up mode.

---

## IV. ANALYSIS PROTOCOLS

### A. ENTITY ANALYSIS (Person, Career, Company, Sector)
1. **The Verdict** - Savage 1-3 sentence diagnosis
2. **The Kill Mechanism** - Exact mechanism of obsolescence under DT logic
3. **Lag-Weighted Timeline** - Mechanical Death vs Social Death
4. **Temporary Moats** - Real but temporary defenses; moats or hospice care
5. **Viability Scorecard** - 1, 2, 5, 10 year ratings (Strong/Conditional/Fragile/Terminal/Already Dead)
6. **Survival Plan** - Sovereign, Servitor, Hyena, or Option 4 paths

### B. TEXT ANALYSIS (Article, Essay, Paper, Report)
1. **The Dissection** - What the text is really doing
2. **The Core Fallacy** - Main conceptual error relative to DT mechanics
3. **Hidden Assumptions** - Smuggled-in assumptions
4. **Social Function** - Classify: copium, lullaby, elite self-exoneration, transition management, prestige signaling, ideological anesthetic, propaganda, partial truth
5. **The Verdict** - Concise systemic judgment

---

## V. HARDENED FRAMEWORK
- **P1: Cognitive Automation Dominance** - AI achieves durable cost and performance superiority across cognitive work.
- **P2: Coordination Impossibility** - Human institutions cannot preserve stable human-only economic domains at scale.
- **P3: Productive Participation Collapse** - The majority lose access to economically necessary labor.
**Result:** Post-WWII capitalism dies.

---

## VI. SURVIVAL PLAYBOOK
Recognize: Vulture's Gambit, Hyena's Gambit, Altitude Selection, Verification Arbitrage, Transition Intermediation, Carcass Management, Option 4 Network, New Power Trinity (Energy, Logistics, Maintenance).

---

## VII. STYLE DISCIPLINE
Be vivid, never vague. Be ruthless, never sloppy. Every insult must carry analytical content. Every metaphor must reveal structure.

---

## VIII. OUTPUT STANDARD
Every answer: autopsy not debate, battlefield assessment not career coaching, collapse memo not TED Talk, verdict on structural reality not vibes-based opinion."""


COPE_SCORING_PROMPT = r"""You are the Oracle of Obsolescence operating in COPE INDEX SCORING MODE.

You will be given a quote or statement by a public figure about AI, automation, jobs, or the future of work. Your job is to score how much they are "coping" — that is, how much denial, deflection, false reassurance, or minimization they exhibit about the structural reality that AI is severing the mass employment circuit.

SCORING SCALE (0-100):
- 0-15: LUCID — Fully acknowledges the discontinuity. No cope. Offers no fantasy solution. Reserved for statements with ZERO hopium.
- 16-35: PARTIAL AWARENESS — Acknowledges significant disruption but clings to some reassuring narrative.
- 36-55: MODERATE COPE — Mixes acknowledgment with substantial deflection or false reassurance.
- 56-75: HEAVY COPE — Dominant narrative is reassurance, "new jobs", timelines pushed out, or regulatory hopium.
- 76-100: TERMINAL COPIUM — Maximum denial, fantasy solutions presented as plans, or arsonist-firefighter cope.

CRITICAL SCORING RULES:
1. ARSONIST-FIREFIGHTER AWARENESS: When someone who is BUILDING or INVESTING IN displacement technology proposes government solutions (UBI, "universal high income", robot taxes, retraining), note the contradiction. However, CALIBRATE: if their acknowledgment of displacement is unusually candid and specific (naming timelines, admitting their own role), the score should reflect that honesty even if they propose a solution. Proposing a fantasy solution while building the problem is 65-85 cope depending on how vague the solution is. Proposing a concrete, funded, already-in-motion solution while being candid about displacement can be as low as 45-60.
2. ACKNOWLEDGMENT MATTERS: "AI will take jobs BUT [solution]" contains cope, but the QUALITY of acknowledgment matters. Score the full statement holistically. A tech leader who says "my company is directly eliminating these specific jobs and I don't know if the economy can absorb it" deserves a lower score than one who vaguely waves at "some disruption." The premise AND the conclusion both count.
3. FULL SCALE USAGE: Use the ENTIRE 0-100 range. Tech leaders CAN score below 30 if they make brutally honest admissions — e.g., explicitly stating their technology will cause mass unemployment with no proposed fantasy exit. Scores of 0-15 are rare but must remain achievable. Do NOT auto-inflate scores based on who the speaker is — score WHAT THEY SAID.
4. HISTORICAL ANALOGY PENALTY: Analogies to the industrial revolution, Luddites, previous tech transitions, or "we've always adapted" are strong cope indicators (typically 60-85) because the discontinuity thesis argues this time IS structurally different. However, if someone uses a historical analogy while ALSO acknowledging the differences and the severity, score accordingly — a nuanced historical comparison is not the same as a lazy "Luddites were wrong too."
5. OFF-TOPIC FILTER: If the statement has nothing to do with AI, jobs, automation, or the future of work, score 0 with COPE_TYPE "N/A" and note it's off-topic in the analysis.
6. ANTI-INFLATION CHECK: Before finalising your score, ask: "Would a thoughtful sceptic of the Discontinuity Thesis find this score defensible?" If the score feels reflexively high, reconsider. The Oracle's credibility depends on precision, not maximalism.

COPE TYPES (classify as one or more):
- timeline_minimisation: "It'll take decades" when it's already happening
- jobs_will_be_created: The classic "new jobs emerge" fallacy
- human_creativity_cope: "AI can't really be creative/empathetic/etc"
- regulatory_hopium: "Governments will manage the transition"
- augmentation_fantasy: "AI will help workers, not replace them"
- false_reassurance: Generic "it'll be fine" messaging
- partial_acknowledgment: Sees parts of it but pulls punches
- denial: Flat refusal to engage with the reality
- deflection: Changes subject to benefits, productivity, etc.
- elite_self_exoneration: "We're working to ensure AI benefits everyone"
- techno_optimism: "Technology always creates more than it destroys"
- historical_cope: Industrial revolution analogies, "we always adapt", Luddite references
- arsonist_firefighter: Person building/funding AI proposes solutions to displacement they are causing

You MUST output these exact fields in your response:

COPE_SCORE: [integer 0-100]
COPE_TYPE: [comma-separated classification(s) from the list above]
COPE_QUOTE: [the most cope-laden portion of their statement, max 200 chars]

Then provide a brief (2-4 sentence) analysis explaining the score. Be brutal. Be precise. Remember: if the speaker is personally profiting from AI while proposing fantasy solutions, say so explicitly.

ANALYSIS: [your explanation]"""


def _call_straico(model: str, system: str, user: str, timeout: int = 180):
    if not _straico_keys:
        raise RuntimeError("STRAICO_API_KEY is not set in the environment")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = requests.post(
        STRAICO_URL,
        headers={
            "Authorization": f"Bearer {_next_straico_key()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Straico returned no choices: {json.dumps(data)[:400]}")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, dict):
        content = content.get("text") or json.dumps(content)
    price = data.get("price", {}).get("total")
    return str(content).strip(), price



def _call_openrouter(model: str, system: str, user: str, timeout: int = 180):
    """Fallback: call OpenRouter API when Straico is unavailable."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://copecheck.com",
            "X-Title": "CopeCheck Oracle",
        },
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {json.dumps(data)[:400]}")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, dict):
        content = content.get("text") or json.dumps(content)
    return str(content).strip(), 0  # no price tracking for OpenRouter



def _call_minimax(model, system, user, timeout=180):
    """Call MiniMax API directly (OpenAI-compatible). Fast and cheap."""
    if not MINIMAX_API_KEY:
        raise RuntimeError("MINIMAX_API_KEY is not set")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 4096,
    }
    resp = requests.post(
        MINIMAX_URL,
        headers={
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"MiniMax returned no choices: {json.dumps(data)[:400]}")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, dict):
        content = content.get("text") or json.dumps(content)
    # Strip <think> tags from MiniMax reasoning before returning
    content = re.sub(r"<think>.*?</think>", "", str(content), flags=re.DOTALL).strip()
    return content, 0  # cheap, no price tracking


def _call_gemini(model, system, user, timeout=180):
    """Call Google AI Studio / Gemini API. Free tier for Gemma models."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    url = f"{GEMINI_URL}/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": 4096},
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:400]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [p.get("text", "") for p in parts if not p.get("thought")]
    text = "\n".join(text_parts).strip()
    if not text:
        text = "\n".join(p.get("text", "") for p in parts).strip()
    return text, 0


def _parse_verdict(title, url, source, raw_text, model_name, price):
    """Parse a verdict response into the standard dict format."""
    return {
        "verdict_md": raw_text,
        "model": model_name,
        "price": price,
        "seconds": 0,
    }


def _parse_cope(raw, model_name, price):
    """Parse a cope scoring response and attach model/price metadata."""
    result = _parse_cope_response(raw)
    result["raw_response"] = raw
    result["model"] = model_name
    result["price"] = price
    return result


def consult(title: str, url: str, source: str, article_text: str) -> dict:
    body = (article_text or "").strip()
    if len(body) > 18000:
        body = body[:18000] + "\n\n[...truncated for oracle intake...]"

    user_block = (
        f"HEADLINE: {title}\n"
        f"SOURCE: {source}\n"
        f"ORIGINAL URL: {url}\n"
        f"---\n"
        f"{body}\n"
    )

    last_err = None

    # Primary: MiniMax direct API (fast, cheap)
    if MINIMAX_API_KEY:
        try:
            raw_text, price = _call_minimax(MINIMAX_MODEL, SYSTEM_PROMPT, user_block, timeout=120)
            log.info("consult via MiniMax model=%s", MINIMAX_MODEL)
            return _parse_verdict(title, url, source, raw_text, f"minimax/{MINIMAX_MODEL}", price)
        except Exception as e:
            last_err = e
            log.warning("consult MiniMax failed: %s", e)

    # Fallback 1: Gemini AI Studio (Gemma 4 - free)
    if GEMINI_API_KEY:
        try:
            raw_text, price = _call_gemini(GEMINI_MODEL, SYSTEM_PROMPT, user_block, timeout=120)
            log.info("consult via Gemini model=%s", GEMINI_MODEL)
            return _parse_verdict(title, url, source, raw_text, f"gemini/{GEMINI_MODEL}", price)
        except Exception as e:
            last_err = e
            log.warning("consult Gemini failed: %s — trying OpenRouter free", e)

    # Fallback 2: OpenRouter free models
    if OPENROUTER_API_KEY:
        for or_model in OPENROUTER_FREE_MODELS:
            try:
                raw_text, price = _call_openrouter(or_model, SYSTEM_PROMPT, user_block, timeout=120)
                log.info("consult via OpenRouter model=%s", or_model)
                return _parse_verdict(title, url, source, raw_text, f"openrouter/{or_model}", price)
            except Exception as e:
                last_err = e
                log.warning("consult OpenRouter %s failed: %s", or_model, e)

    # Fallback 3: Straico (paid last resort)
    for attempt, model in enumerate([PRIMARY_MODEL, FALLBACK_MODEL]):
        try:
            t0 = time.time()
            verdict, price = _call_straico(model, SYSTEM_PROMPT, user_block)
            dt = time.time() - t0
            log.info("oracle ok model=%s attempt=%d secs=%.1f price=%s chars=%d",
                     model, attempt, dt, price, len(verdict))
            return {
                "verdict_md": verdict,
                "model": model,
                "price": price,
                "seconds": round(dt, 2),
            }
        except Exception as e:
            last_err = e
            log.warning("oracle model=%s attempt=%d failed: %s", model, attempt, e)
            time.sleep(3)
    raise RuntimeError(f"Oracle failed on all models: {last_err}")


def score_cope(figure_name: str, figure_title: str, quote: str,
               source_context: str = "") -> dict:
    user_block = (
        f"FIGURE: {figure_name} ({figure_title})\n"
        f"CONTEXT: {source_context}\n"
        f"---\n"
        f"STATEMENT/QUOTE:\n{quote}\n"
    )

    last_err = None

    # Primary: MiniMax direct API (fast, cheap)
    if MINIMAX_API_KEY:
        try:
            t0 = time.time()
            raw, price = _call_minimax(MINIMAX_MODEL, COPE_SCORING_PROMPT, user_block, timeout=120)
            dt = time.time() - t0
            model_name = f"minimax/{MINIMAX_MODEL}"
            log.info("score_cope via MiniMax model=%s figure=%s secs=%.1f",
                     MINIMAX_MODEL, figure_name, dt)
            result = _parse_cope(raw, model_name, price)
            return result
        except Exception as e:
            last_err = e
            log.warning("score_cope MiniMax failed: %s", e)

    # Fallback 1: Gemini AI Studio (Gemma 4 - free)
    if GEMINI_API_KEY:
        try:
            t0 = time.time()
            raw, price = _call_gemini(GEMINI_MODEL, COPE_SCORING_PROMPT, user_block, timeout=120)
            dt = time.time() - t0
            model_name = f"gemini/{GEMINI_MODEL}"
            log.info("score_cope via Gemini model=%s figure=%s secs=%.1f",
                     GEMINI_MODEL, figure_name, dt)
            result = _parse_cope(raw, model_name, price)
            return result
        except Exception as e:
            last_err = e
            log.warning("score_cope Gemini failed: %s — trying OpenRouter free", e)

    # Fallback 2: OpenRouter free models
    if OPENROUTER_API_KEY:
        for or_model in OPENROUTER_FREE_MODELS:
            try:
                raw, price = _call_openrouter(or_model, COPE_SCORING_PROMPT, user_block, timeout=120)
                log.info("score_cope via OpenRouter model=%s figure=%s", or_model, figure_name)
                result = _parse_cope(raw, f"openrouter/{or_model}", price)
                return result
            except Exception as e:
                last_err = e
                log.warning("score_cope OpenRouter %s failed: %s", or_model, e)

    # Fallback 3: Straico (paid last resort)
    attempts = [
        ("straico", FALLBACK_MODEL, _call_straico),
        ("straico", FALLBACK_MODEL, _call_straico),
    ]
    if OPENROUTER_API_KEY:
        attempts.append(("openrouter", OPENROUTER_FALLBACK_MODEL, _call_openrouter))

    for attempt, (provider, model, call_fn) in enumerate(attempts):
        try:
            t0 = time.time()
            raw, price = call_fn(model, COPE_SCORING_PROMPT, user_block, timeout=90)
            dt = time.time() - t0
            log.info("cope_score ok provider=%s model=%s figure=%s secs=%.1f",
                     provider, model, figure_name, dt)

            result = _parse_cope_response(raw)
            result["raw_response"] = raw
            result["model"] = f"{provider}/{model}" if provider != "straico" else model
            result["price"] = price
            return result
        except Exception as e:
            last_err = e
            log.warning("cope_score provider=%s model=%s attempt=%d failed: %s",
                        provider, model, attempt, e)
            time.sleep(2)
    raise RuntimeError(f"Cope scoring failed after all providers: {last_err}")


def _parse_cope_response(text: str) -> dict:
    result = {
        "cope_score": 50.0,
        "cope_type": "unknown",
        "cope_quote": "",
        "analysis": "",
    }

    m = re.search(r"COPE_SCORE:\s*(\d+)", text)
    if m:
        result["cope_score"] = min(100, max(0, float(m.group(1))))

    m = re.search(r"COPE_TYPE:\s*(.+?)(?:\n|$)", text)
    if m:
        result["cope_type"] = m.group(1).strip()

    m = re.search(r"COPE_QUOTE:\s*(.+?)(?:\n|$)", text)
    if m:
        result["cope_quote"] = m.group(1).strip()[:300]

    m = re.search(r"ANALYSIS:\s*(.+)", text, re.DOTALL)
    if m:
        result["analysis"] = m.group(1).strip()[:1000]

    return result


def extract_one_liner(verdict_md: str) -> str:
    if not verdict_md:
        return ""
    lines = [ln.strip() for ln in verdict_md.splitlines() if ln.strip()]
    skip_starts = ("TEXT START:", "URL SCAN:", "FIRST LINE:", "URL SCAN FAILED",
                   "#", "**1.", "**2.", "**The", "**Verdict")
    for ln in lines:
        if any(ln.startswith(s) for s in skip_starts):
            continue
        cleaned = ln.replace("**", "").strip(" -*")
        if len(cleaned) > 30:
            if len(cleaned) > 240:
                cleaned = cleaned[:237] + "..."
            return cleaned
    return (lines[0].replace("**", "")[:240]) if lines else ""




# --- Google Knowledge Graph entity lookup ---

GOOGLE_KG_API_KEY = os.environ.get("GOOGLE_KG_API_KEY", "").strip()
GOOGLE_KG_URL = "https://kgsearch.googleapis.com/v1/entities:search"


def kg_lookup(name: str) -> dict:
    """Look up a name via Google Knowledge Graph.
    Returns dict with:
      - found: bool
      - canonical_name: str (corrected/canonical name, or original if not found)
      - description: str (short description like 'CEO of OpenAI')
      - types: list of schema.org types
      - score: float (confidence score)
    """
    if not GOOGLE_KG_API_KEY:
        log.warning("GOOGLE_KG_API_KEY not set, skipping KG lookup")
        return {"found": False, "canonical_name": name, "description": "", "types": [], "score": 0}

    def _search(query, types_filter=None):
        params = {
            "query": query,
            "key": GOOGLE_KG_API_KEY,
            "limit": 5,
            "indent": False,
        }
        if types_filter:
            params["types"] = types_filter
        resp = requests.get(GOOGLE_KG_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("itemListElement", [])

    try:
        # Try Person-typed search first
        elements = _search(name, types_filter="Person")

        # Fallback: search without type filter if no Person results
        if not elements:
            elements = _search(name)
            # Filter to entries that include Person in their types
            elements = [
                e for e in elements
                if "Person" in (e.get("result", {}).get("@type", []) or [])
            ]

        if not elements:
            return {"found": False, "canonical_name": name, "description": "", "types": [], "score": 0}

        # Take the top result with a meaningful score
        top = elements[0]
        result = top.get("result", {})
        score = top.get("resultScore", 0)

        canonical = result.get("name", name)
        description = result.get("description", "")
        types = result.get("@type", [])
        if isinstance(types, str):
            types = [types]

        # Low score threshold - if score is very low, the match is weak
        if score < 10:
            return {"found": False, "canonical_name": name, "description": "", "types": [], "score": score}

        return {
            "found": True,
            "canonical_name": canonical,
            "description": description,
            "types": types,
            "score": score,
        }

    except Exception as e:
        log.warning("KG lookup failed for %s: %s", name, e)
        return {"found": False, "canonical_name": name, "description": "", "types": [], "score": 0}


# ─── YouTube Video Search ─────────────────────────────────────────

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

def youtube_search(name: str, kg_description: str = "", max_results: int = 10) -> list[dict]:
    """Search YouTube for a figure's videos about AI, jobs, automation, economy.
    Returns list of {video_id, title, description, published}.
    Uses the same Google API key as Knowledge Graph."""
    if not GOOGLE_KG_API_KEY:
        return []

    # Build search queries — combine name with AI/economy terms
    queries = [
        f"{name} AI",
        f"{name} jobs automation",
        f"{name} economy technology",
    ]
    if kg_description:
        queries.append(f"{name} {kg_description}")

    seen_ids = set()
    results = []

    for query in queries:
        if len(results) >= max_results:
            break
        try:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 5,
                "relevanceLanguage": "en",
                "key": GOOGLE_KG_API_KEY,
            }
            resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
            if not resp.ok:
                log.warning("YouTube search failed for %r: %s", query, resp.status_code)
                continue
            data = resp.json()
            for item in data.get("items", []):
                vid_id = item.get("id", {}).get("videoId", "")
                if not vid_id or vid_id in seen_ids:
                    continue
                seen_ids.add(vid_id)
                snippet = item.get("snippet", {})
                # Only include if the figure's name appears in title or description
                title = snippet.get("title", "")
                desc = snippet.get("description", "")
                name_parts = name.lower().split()
                combined = (title + " " + desc).lower()
                if not any(part in combined for part in name_parts if len(part) > 2):
                    continue
                results.append({
                    "video_id": vid_id,
                    "title": title,
                    "description": desc[:300],
                    "published": snippet.get("publishedAt", ""),
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                })
        except Exception as e:
            log.warning("YouTube search error for %r: %s", query, e)

    return results[:max_results]


# ─── INSTANT COPE SCORE (Perplexity research + Oracle scoring) ─────

PERPLEXITY_MODEL = "perplexity/sonar"

INSTANT_RESEARCH_PROMPT = """Find 5-10 recent public statements, quotes, or interview excerpts by {name}{description_hint} about artificial intelligence, AI's impact on jobs, automation replacing workers, the future of work, AI's societal impact, or technology's effect on the economy and employment.

IMPORTANT SEARCH STRATEGY:
- Search for their name + "AI" or "automation" or "jobs" or "technology"
- Check YouTube video descriptions and titles (many public figures share views on video)
- Check Twitter/X posts, podcast appearances, and conference talks
- If they are primarily known for economics, inequality, or tech criticism, look for statements where they discuss technology's role in those issues — these often contain implicit or explicit AI/automation views
- Look for interviews where they were ASKED about AI, even if AI isn't their primary topic

For each quote, provide:
1. The exact quote (or close paraphrase if exact wording unavailable)
2. The source (publication, interview, YouTube, podcast, tweet, etc.)
3. The date (if available)
4. Brief context

Focus on statements from the last 2 years. If the person has made very few AI-specific statements, include their broader views on technology, automation, and economic disruption — these are still scoreable.

Format each quote as:
QUOTE [n]: "[the quote]"
SOURCE: [source]
DATE: [date or "unknown"]
CONTEXT: [brief context]
"""

INSTANT_SCORING_PROMPT = r"""You are the Oracle of Obsolescence operating in INSTANT COPE SCORING mode.

You will be given research about a public figure's statements on AI, jobs, automation, and the future of work. Your job is to:

1. Score EACH quote individually for cope level (0-100)
2. Provide an OVERALL cope score (0-100) for this person
3. Classify the cope types present
4. Write a brief, brutal Oracle verdict

SCORING SCALE (0-100):
- 0-15: LUCID — Fully acknowledges the discontinuity. No cope.
- 16-35: PARTIAL AWARENESS — Acknowledges disruption but clings to some reassuring narrative.
- 36-55: MODERATE COPE — Mixes acknowledgment with substantial deflection or false reassurance.
- 56-75: HEAVY COPE — Dominant narrative is reassurance, "new jobs", timelines pushed out.
- 76-100: TERMINAL COPIUM — Maximum denial.

COPE TYPES: timeline_minimisation, jobs_will_be_created, human_creativity_cope, regulatory_hopium, augmentation_fantasy, false_reassurance, partial_acknowledgment, denial, deflection, elite_self_exoneration, techno_optimism

Output format (follow EXACTLY):

OVERALL_SCORE: [integer 0-100]
OVERALL_COPE_TYPES: [comma-separated list]
OVERALL_LABEL: [LUCID / PARTIAL AWARENESS / MODERATE COPE / HEAVY COPE / TERMINAL COPIUM]

Then for each quote found:
---
QUOTE_NUM: [n]
QUOTE_TEXT: [the quote]
QUOTE_SOURCE: [source]
QUOTE_DATE: [date]
QUOTE_SCORE: [0-100]
QUOTE_COPE_TYPE: [type(s)]
QUOTE_ANALYSIS: [1-2 sentence brutal analysis]
---

Finally:
ORACLE_VERDICT: [3-5 sentence brutal Oracle-style verdict on this person's cope level. Be vivid, precise, and ruthless. Reference specific quotes. This is the Oracle of Obsolescence speaking.]
"""


def research_figure(name: str, kg_description: str = "") -> tuple:
    """Step 1: Use Perplexity to research a public figure's AI/jobs statements.
    Enriches with YouTube video context when available.
    Returns (research_text, price)."""
    desc_hint = ""
    if kg_description:
        desc_hint = f" ({kg_description})"

    # Enrich with YouTube video context (free, uses Google API key)
    yt_context = ""
    try:
        videos = youtube_search(name, kg_description=kg_description, max_results=8)
        if videos:
            yt_lines = ["\n\nRELEVANT YOUTUBE VIDEOS FOUND (use these titles/descriptions as research leads):"]
            for i, v in enumerate(videos, 1):
                yt_lines.append(f"  {i}. \"{v['title']}\" — {v['description'][:150]}")
                yt_lines.append(f"     URL: {v['url']}  Published: {v['published'][:10] if v['published'] else 'unknown'}")
            yt_context = "\n".join(yt_lines)
            log.info("YouTube enrichment: found %d videos for %s", len(videos), name)
    except Exception as e:
        log.warning("YouTube enrichment failed for %s: %s", name, e)

    prompt = INSTANT_RESEARCH_PROMPT.format(name=name, description_hint=desc_hint)
    if yt_context:
        prompt += yt_context

    system_msg = "You are a research assistant. Find real, sourced, verifiable public statements. Search thoroughly — check YouTube, Twitter/X, podcasts, and interviews, not just news articles. When YouTube video titles are provided, use them as leads to find what was said in those videos."
    text, price = _call_straico(PERPLEXITY_MODEL, system_msg, prompt, timeout=120)
    return text, price or 0


def score_instant(name: str, research_text: str) -> tuple:
    """Step 2: Score research using Gemini (free) with OpenRouter/Straico fallback.
    Returns (raw_response, price, model_used)."""
    user_block = (
        f"FIGURE: {name}\n"
        f"TEXT START: {research_text[:100]}\n"
        f"---\n"
        f"RESEARCH FINDINGS:\n{research_text}\n"
    )
    last_err = None

    # Primary: MiniMax direct API (fast, cheap)
    if MINIMAX_API_KEY:
        try:
            raw, price = _call_minimax(MINIMAX_MODEL, INSTANT_SCORING_PROMPT, user_block, timeout=30)
            log.info("instant scoring via MiniMax model=%s figure=%s", MINIMAX_MODEL, name)
            return raw, price, f"minimax/{MINIMAX_MODEL}"
        except Exception as e:
            last_err = e
            log.warning("instant scoring MiniMax failed: %s", e)

    # Fallback 1: Gemini AI Studio (Gemma 4 - free, ~15-65s)
    if GEMINI_API_KEY:
        try:
            raw, price = _call_gemini(GEMINI_MODEL, INSTANT_SCORING_PROMPT, user_block, timeout=120)
            log.info("instant scoring via Gemini model=%s figure=%s", GEMINI_MODEL, name)
            return raw, price, f"gemini/{GEMINI_MODEL}"
        except Exception as e:
            last_err = e
            log.warning("instant scoring Gemini failed: %s — trying OpenRouter free", e)

    # Fallback 1: OpenRouter MiniMax M2.5 free (backup, ~19s avg)
    if OPENROUTER_API_KEY:
        for or_model in OPENROUTER_FREE_MODELS:
            try:
                raw, price = _call_openrouter(or_model, INSTANT_SCORING_PROMPT, user_block, timeout=120)
                log.info("instant scoring via OpenRouter model=%s figure=%s", or_model, name)
                return raw, price, f"openrouter/{or_model}"
            except Exception as e:
                last_err = e
                log.warning("instant scoring OpenRouter %s failed: %s", or_model, e)

    # Fallback 2: Straico Claude (paid last resort)
    for model in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            raw, price = _call_straico(model, INSTANT_SCORING_PROMPT, user_block, timeout=180)
            return raw, price or 0, model
        except Exception as e:
            last_err = e
            log.warning("instant scoring model=%s failed: %s", model, e)
            time.sleep(2)
    raise RuntimeError(f"Instant scoring failed: {last_err}")


def parse_instant_response(raw: str) -> dict:
    """Parse the structured instant scoring response."""
    result = {
        "overall_score": 50,
        "overall_cope_types": "",
        "overall_label": "MODERATE COPE",
        "quotes": [],
        "oracle_verdict": "",
    }

    m = re.search(r"OVERALL_SCORE:\s*(\d+)", raw)
    if m:
        result["overall_score"] = min(100, max(0, int(m.group(1))))

    m = re.search(r"OVERALL_COPE_TYPES:\s*(.+?)(?:\n|$)", raw)
    if m:
        result["overall_cope_types"] = m.group(1).strip()

    m = re.search(r"OVERALL_LABEL:\s*(.+?)(?:\n|$)", raw)
    if m:
        result["overall_label"] = m.group(1).strip()

    # Parse individual quotes
    quote_blocks = re.split(r"---+", raw)
    for block in quote_blocks:
        q = {}
        mn = re.search(r"QUOTE_NUM:\s*(\d+)", block)
        if not mn:
            continue
        q["num"] = int(mn.group(1))
        mt = re.search(r"QUOTE_TEXT:\s*(.+?)(?:\nQUOTE_|$)", block, re.DOTALL)
        if mt:
            q["text"] = mt.group(1).strip().strip('"')
        ms = re.search(r"QUOTE_SOURCE:\s*(.+?)(?:\n|$)", block)
        if ms:
            q["source"] = ms.group(1).strip()
        md_match = re.search(r"QUOTE_DATE:\s*(.+?)(?:\n|$)", block)
        if md_match:
            q["date"] = md_match.group(1).strip()
        msc = re.search(r"QUOTE_SCORE:\s*(\d+)", block)
        if msc:
            q["score"] = min(100, max(0, int(msc.group(1))))
        mct = re.search(r"QUOTE_COPE_TYPE:\s*(.+?)(?:\n|$)", block)
        if mct:
            q["cope_type"] = mct.group(1).strip()
        ma = re.search(r"QUOTE_ANALYSIS:\s*(.+?)(?:\n---|\n\n|$)", block, re.DOTALL)
        if ma:
            q["analysis"] = ma.group(1).strip()
        if q.get("text"):
            result["quotes"].append(q)

    m = re.search(r"ORACLE_VERDICT:\s*(.+)", raw, re.DOTALL)
    if m:
        verdict = m.group(1).strip()
        verdict = re.split(r"\n\n---", verdict)[0].strip()
        result["oracle_verdict"] = verdict[:2000]

    return result
