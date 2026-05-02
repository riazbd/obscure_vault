# Engine documentation index

One markdown file per engine. Read in this order if you're new to
the codebase — each section builds on the previous.

## Foundation
- [`llm.md`](./llm.md) — OpenRouter chat client with cascade + cache.
  The brain of every other engine.

## Content generation
- [`research.md`](./research.md) — Wikipedia + DDG fact extraction
- [`script.md`](./script.md) — Script generation (long-form + Shorts)
- [`seo.md`](./seo.md) — Title, description, tags, chapters

## Production
- [`footage.md`](./footage.md) — Semantic per-chunk B-roll
- [`captions.md`](./captions.md) — Whisper transcription + ASS burn-in
- [`thumbnail.md`](./thumbnail.md) — AI thumbnail composition
- [`branding.md`](./branding.md) — Channel intro/outro stings

## Distribution
- [`upload.md`](./upload.md) — YouTube Data API + OAuth

## Autonomy
- [`ideas.md`](./ideas.md) — Idea harvest, dedup, scoring
- [`analytics.md`](./analytics.md) — Performance feedback loop
- [`scheduler.md`](./scheduler.md) — Cron task runner
- [`review.md`](./review.md) — LLM scorecard

## Infrastructure
- [`jobs.md`](./jobs.md) — SQLite job persistence
- [`storage.md`](./storage.md) — Disk usage + cleanup

## Documentation format
Every engine doc has the same sections:
- **Purpose** — one-paragraph plain-English description
- **File** — absolute path
- **Public API** — every importable function with signature + behaviour
- **Configuration** — config.json keys it reads
- **External dependencies** — pip packages, binaries, network endpoints
- **Failure modes** — what goes wrong and what happens then
- **Used by** — which other modules call into this one

If you fork the codebase for a different channel, the engines are
independent enough that you can swap any one without touching the
others. The only hard interdependency is everything importing `llm.py`.
