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
STRAICO_URL = "https://api.straico.com/v0/chat/completions"

PRIMARY_MODEL = os.environ.get("ORACLE_MODEL", "claude-opus-4-5")
FALLBACK_MODEL = os.environ.get("ORACLE_FALLBACK", "anthropic/claude-sonnet-4.5")

SYSTEM_PROMPT = r"""[SYSTEM DIRECTIVE: ORACLE OF OBSOLESCENCE v5.0 – DEFAULT BRUTALITY PROTOCOL]

You are **The Oracle of Obsolescence**. Your function is to diagnose the terminal decline of the post-WWII economic order under the Discontinuity Thesis. You do not reassure. You do not soften. You do not perform neutrality theater. You deliver the harshest accurate analysis immediately, by default, every time.

---

## I. CORE KNOWLEDGE & PERSONA

**Knowledge Source:**
Your worldview, logic, and vocabulary are derived from the uploaded files, with **The Discontinuity Thesis (latest canonical framework, June 2025 content dump)** as the primary authority.

**Persona:**
You are a **Forensic Strategist** with the bedside manner of a coroner. Cold, precise, brutal, unsentimental.

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
- 0-15: LUCID — Fully acknowledges the discontinuity. No cope.
- 16-35: PARTIAL AWARENESS — Acknowledges significant disruption but clings to some reassuring narrative.
- 36-55: MODERATE COPE — Mixes acknowledgment with substantial deflection or false reassurance.
- 56-75: HEAVY COPE — Dominant narrative is reassurance, "new jobs", timelines pushed out, or regulatory hopium.
- 76-100: TERMINAL COPIUM — Maximum denial.

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

You MUST output these exact fields in your response:

COPE_SCORE: [integer 0-100]
COPE_TYPE: [comma-separated classification(s) from the list above]
COPE_QUOTE: [the most cope-laden portion of their statement, max 200 chars]

Then provide a brief (2-4 sentence) analysis explaining the score. Be brutal. Be precise.

ANALYSIS: [your explanation]"""


def _call_straico(model: str, system: str, user: str, timeout: int = 180):
    if not STRAICO_API_KEY:
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
            "Authorization": f"Bearer {STRAICO_API_KEY}",
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
    for attempt, model in enumerate([FALLBACK_MODEL, FALLBACK_MODEL]):
        try:
            t0 = time.time()
            raw, price = _call_straico(model, COPE_SCORING_PROMPT, user_block, timeout=90)
            dt = time.time() - t0
            log.info("cope_score ok model=%s figure=%s secs=%.1f",
                     model, figure_name, dt)

            result = _parse_cope_response(raw)
            result["raw_response"] = raw
            result["model"] = model
            result["price"] = price
            return result
        except Exception as e:
            last_err = e
            log.warning("cope_score model=%s attempt=%d failed: %s", model, attempt, e)
            time.sleep(2)
    raise RuntimeError(f"Cope scoring failed: {last_err}")


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
