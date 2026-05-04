# CopeCheck API & Infrastructure Reference

Last updated: 2026-04-22

## SSH Access
```
ssh ben@100.127.164.64    # via Tailscale (only way in — port 22 blocked externally)
```

## Service Management
```bash
sudo systemctl restart copecheck    # restart web app
sudo systemctl status copecheck     # check status
tail -f ~/infra/copecheck/logs/gunicorn-error.log   # live errors
tail -f ~/infra/copecheck/logs/pipeline.log          # pipeline log
```

## Environment Variables (~/infra/copecheck/.env)

| Key | Purpose | Free? |
|-----|---------|-------|
| GEMINI_API_KEY | Google AI Studio — Gemma 4 primary scorer | Yes (free tier) |
| STRAICO_API_KEY | Straico API (Perplexity research for instant cope) | Lifetime deal, has limits |
| OPENROUTER_API_KEY | OpenRouter fallback (MiniMax M2.5, Gemma 4 free) | Yes (free tier) |
| NVIDIA_NIM_API_KEY | NVIDIA NIM — currently unreliable, not in scoring chain | Yes but unstable |
| GOOGLE_KG_API_KEY | Google Knowledge Graph + YouTube Data API | Yes (free tier) |
| GNEWS_API_KEY | GNews news search (article discovery) | Yes (100 req/day) |
| BRAVE_API_KEY | Brave Search (daily scheduled scan via Cowork) | Yes (free tier) |
| ORACLE_MODEL | Primary Straico model (last-resort fallback) | — |
| ORACLE_FALLBACK | Secondary Straico model (last-resort fallback) | — |

## Model Routing (oracle.py)

### Article Verdicts — consult()
1. Gemini AI Studio Gemma 4 31B (free) ← primary
2. OpenRouter MiniMax M2.5 free (fallback)
3. OpenRouter Gemma 4 free (fallback)
4. Straico Claude Opus 4.5 (paid fallback)
5. Straico Claude Sonnet 4.5 (paid fallback)

### Cope Scoring — score_cope()
1. Gemini AI Studio Gemma 4 31B (free) ← primary
2. OpenRouter MiniMax M2.5 free (fallback)
3. OpenRouter Gemma 4 free (fallback)
4. Straico Claude Sonnet 4.5 (paid fallback)
5. OpenRouter Gemini Flash (paid fallback)

### Instant Cope Score — 4-stage
1. Google Knowledge Graph — validate/correct the name (free)
2. YouTube Data API — find relevant videos for context (free, 10k units/day)
3. Perplexity via Straico — research figure statements with YT context (~11 coins)
4. Gemini AI Studio Gemma 4 — score the research (free)

### News Ingestion — pipeline.py news
1. RSS feeds (Google News, arXiv, HN, press) — free
2. GNews API — 5 search queries, 10 results each (free, 100 req/day)
3. Full article fetch via trafilatura
4. Oracle verdict via Gemma 4 (free)
5. Cross-link figures + cope scoring via Gemma 4 (free)

## Running the Pipeline
```bash
cd ~/infra/copecheck
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# Full pipeline (news + cope scanning)
python3 pipeline.py

# News only (ingest + analyse)
python3 pipeline.py news

# Cope scanning only (figure quotes)
python3 pipeline.py cope
```

## Cron Schedule (already active)
- News pipeline: hourly at :07
- Cope index scan: every 4 hours at :22
- Weekly digest: Monday 8am
- URL submissions: daily 6am

## Pipeline Limits
- MAX_NEW: 50 articles per run
- MAX_ANALYSE: 30 articles per run
- MAX_COPE_SCAN: 3 per figure per run

## Gemini AI Studio API
- Endpoint: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
- Model: gemma-4-31b-it (configurable via GEMINI_MODEL env var)
- Free tier, supports system instructions and reasoning/thought

## OpenRouter Free Models
- MiniMax M2.5: minimax/minimax-m2.5:free
- Gemma 4 31B: google/gemma-4-31b-it:free
- Endpoint: https://openrouter.ai/api/v1/chat/completions (OpenAI-compatible)

## NVIDIA NIM API (currently offline — kept as reference)
- Endpoint: https://integrate.api.nvidia.com/v1/chat/completions
- Model: deepseek-ai/deepseek-v3.2
- Rate limit: 40 requests/minute
- Status: unreliable as of 2026-04-22, removed from scoring chain

## GNews API
- Endpoint: https://gnews.io/api/v4/search
- Free tier: 100 requests/day
- Queries: AI jobs automation, artificial intelligence unemployment, AI replacing workers, AI layoffs, AI future of work

## YouTube Data API v3
- Uses same Google API key as Knowledge Graph
- 10,000 free units/day (search = 100 units, so ~100 searches/day)
- Used to enrich instant cope research with video context

## Gunicorn Config
- Workers: 4
- Timeout: 300 seconds (needed for research+scoring chain)
- Port: 8096 (behind Cloudflare tunnel)

## Cost Summary
- Instant cope score: ~11 Straico coins (Perplexity research only)
- Article verdicts: FREE (Gemma 4)
- Cope scoring: FREE (Gemma 4)
- News scanning: FREE (RSS + GNews)
- Name validation: FREE (Google KG)
- YouTube enrichment: FREE (Google API)
