# CopeCheck

**The AI Cope Index** — tracking what public figures *really* think about AI replacing jobs, scored by an LLM oracle.

Live at [copecheck.com](https://copecheck.com)

## What it does

CopeCheck monitors 19 high-profile figures (AI lab CEOs, tech leaders, economists, public intellectuals) and scores their public statements on a cope-to-doomer spectrum using an LLM-powered analysis pipeline.

Each figure gets a **Cope Score** (0–10) based on recent quotes about AI and employment, with higher scores indicating more optimistic/dismissive takes on AI disruption.

## Stack

- **Backend**: Python/Flask
- **Database**: SQLite
- **LLM Oracle**: Claude (via Anthropic API) for quote analysis and scoring
- **Image Generation**: Straico API (DALL-E 3) for editorial portraits
- **Hosting**: Hetzner VPS behind Cloudflare tunnel
- **Domain**: copecheck.com

## Architecture

- `app.py` — Flask web app, serves the index and figure pages
- `pipeline.py` — Automated pipeline: search → collect → analyse → score
- `oracle.py` — LLM-powered quote analysis and cope scoring
- `sources.py` — Web search and quote extraction
- `db.py` — SQLite database layer
- `figures.yaml` — Configuration for tracked figures and search queries
- `seed_quotes.py` — Initial data seeding

## License

MIT
