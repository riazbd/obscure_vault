# `engines/ideas.py` — Idea Engine

## Purpose
Mine fresh video topics from free public sources, dedup against what
you already have, score for niche fit, weight by past channel
performance, and persist a ranked queue ready to be turned into videos.

## File
`/home/user/obscure_vault/engines/ideas.py`

## Public API

### `run_harvest(*, yt_seeds=None, subreddits=None, include_wikipedia=True, score_with_openrouter_key="", niche=DEFAULT_NICHE, novelty_threshold=0.55, keep_top=60, on_log=None)`
End-to-end harvest. Returns `{added, total, top_sample}`.

### `list_all()`
Returns the full persisted list (sorted: pending first, then by
ranked_score desc).

### `update_status(idea_id, status, **patch)`
Move an idea through its lifecycle:
- `pending` (default after harvest)
- `approved` (when "Generate" clicked, before pipeline finishes)
- `produced` (when pipeline completes successfully)
- `rejected` (manual user action)

### `delete(idea_id)`
Hard delete from `data/ideas.json`.

## Sources

### YouTube Suggest (`harvest_youtube_suggest`)
Hits `https://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q=<seed>`.
For every seed term, queries the seed itself plus the seed +
each letter `a`–`j`. Letter-expansion gives long-tail variants real
searchers actually type.

No API key required.

### Reddit (`harvest_reddit`)
Each configured subreddit's `/hot.json` endpoint with a
`User-Agent` header. Default subs:
`AskHistorians, UnresolvedMysteries, ColdWar, HistoryAnecdotes,
MilitaryHistory, Mysterious_Earth`.

No API key required.

### Wikipedia (`harvest_wikipedia`)
`https://en.wikipedia.org/api/rest_v1/feed/onthisday/all/<MM>/<DD>` —
returns events, deaths, and selected entries for today's date. Good
for anniversary-driven topics.

No API key required.

## Filtering & dedup

### `_filter_obviously_bad(items)`
Drops:
- Title length < 14 or > 220
- Regex: `porn|nsfw|trailer|reaction|tier list|ranking|reddit thread|original poster|aita`

### Token-Jaccard dedup
`_tokens(title)` returns lowercased non-stopword tokens with len > 2.
`_jaccard(a, b)` = |a ∩ b| / |a ∪ b|. New ideas with Jaccard ≥ 0.55
to any existing idea are dropped. Conservative threshold preserves
near-duplicate angles.

## Scoring

### LLM niche fit
`score_with_llm(api_key, items, niche, on_log)` batches items in
groups of 25 and asks the LLM to score each on 0.0–1.0 with a
one-sentence rationale. Hard-rejects news-like / current-affairs
content (lasts < 1 month relevance), generic listicles, and
self-promotional / AI-tooling / tech-review topics.

Items below 0.35 niche_fit are culled before persisting.

### Analytics performance signal
After LLM scoring, `analytics.compute_token_signals()` is called
(if available). For each idea, `predict_score_for_idea()` returns a
multiplier in [0.5, 1.6] based on token overlap with past channel
videos.

`ranked_score = niche_fit × perf_multiplier`

This is the value the scheduler's "Produce top idea" task picks by.

## Persistence
`data/ideas.json` — list of dicts:
```python
{
  "id":            "16-char sha256 of normalized title",
  "title":         "raw harvest title",
  "source":        "yt_suggest" | "reddit" | "wikipedia_events" | ...,
  "source_url":    "...",
  "harvested_at":  "ISO 8601 UTC",
  "status":        "pending" | "approved" | "produced" | "rejected",
  "niche_fit":     0.0–1.0 or null,
  "rationale":     "LLM one-liner",
  "perf_multiplier": 0.5–1.6,
  "ranked_score":  niche_fit × perf_multiplier,
  "scripted_title": "...",   # set when produced
  "pipeline_job":  "20260502_…",  # set when produced
  "video_id":      "YouTube id",  # set after upload
}
```

Hard cap: 500 ideas total (oldest dropped on overflow).

## Configuration
No direct config keys; the scheduler task reads
`scheduler_yt_seeds`, `scheduler_subs`, `scheduler_niche`, and the
`openrouter_api_key` from cfg.

## External dependencies
- `requests`
- `llm.py`
- HTTP egress to `suggestqueries.google.com`, `www.reddit.com`,
  `en.wikipedia.org`

## Failure modes
- **A source returns nothing** — silent; the others contribute
- **All sources empty** — `run_harvest` reports `added=0`, `top_sample=[]`
- **LLM scoring fails entirely** — falls through with `niche_fit=null`
  on each item; survival cull is skipped (everything stays)
- **Reddit User-Agent blocked** — that subreddit returns 403; logged,
  others continue

## Used by
- `server.py` — `_run_harvest`, `_run_idea_to_video`,
  `/api/ideas/list`, `/api/ideas/<id>/status`,
  `/api/ideas/<id>/produce`, `/api/ideas/<id>` (DELETE)
- `engines/scheduler.py` — `task_harvest_ideas`, `task_produce_top_idea`
