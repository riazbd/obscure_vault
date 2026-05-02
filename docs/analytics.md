# `engines/analytics.py` — Performance Tracking + Feedback Loop

## Purpose
Pull YouTube performance for every uploaded video, compute per-token
performance multipliers from the channel's actual data, and feed
those signals back into the idea ranker so winning topic patterns
get amplified and losing patterns suppressed automatically.

## File
`/home/user/obscure_vault/engines/analytics.py`

## Public API

### `record_upload(video_id, title, tags, idea_id=None)`
Append to `data/uploads.json`. Idempotent (skip if `video_id`
already present). Called by `engines/upload.py` `publish()` after
every successful upload.

### `list_uploads()` / `list_metrics()`
Read accessors. Used by `/api/dashboard` and the analytics token-signal
computation.

### `refresh_metrics(on_log=None)`
For every recorded upload, hits both:
- **YouTube Data API** (videos.list, batched 50 ids/call) → views,
  likes, comments, publishedAt, duration
- **YouTube Analytics API** (per-video reports.query) →
  estimatedMinutesWatched, averageViewDuration, averageViewPercentage,
  subscribersGained, impressions, impressionClickThroughRate (CTR)

Stores the merged dict at `data/metrics.json`. Returns
`{refreshed, total, errors}`.

### `compute_token_signals()`
Returns:
```python
{
  "channel_avg": {"views_per_day", "ctr", "avg_view_percent"},
  "tokens": {
    "<token>": {"samples": int, "multiplier": 0.5–1.6},
    ...
  }
}
```

Algorithm:
1. For each uploaded video, compute (views_per_day, ctr, avp)
   relative to the channel mean
2. Aggregate per-token (every token from titles + tags appearing
   anywhere)
3. Per-token raw signal = `0.45 * v_ratio + 0.35 * c_ratio + 0.20 * a_ratio`
4. Confidence shrinkage: with 1 sample, 25 % confidence; saturates
   at 4 samples
5. `multiplier = 1.0 + (raw - 1.0) * confidence`, clamped to [0.5, 1.6]

### `predict_score_for_idea(title, tags, signals=None)`
Returns a multiplier in [0.5, 1.6] for a hypothetical new idea
based on token overlap with the signal map. 1.0 means "no signal"
(no overlapping tokens have any channel data yet).

Uses sample-count-weighted average of overlapping tokens'
multipliers.

## Persistence
- `data/uploads.json` — append-only. Each entry:
  ```python
  {"video_id", "title", "tags", "idea_id", "uploaded_at"}
  ```
- `data/metrics.json` — `{by_video: {video_id: stats}, refreshed_at}`

## Configuration
No direct config; reads OAuth credentials via `engines.upload._load_creds()`.

## External dependencies
- `engines/upload.py` for the OAuth token (and lazy-imported
  `googleapiclient`)
- HTTP egress to `youtube.googleapis.com`, `youtubeanalytics.googleapis.com`

## Failure modes
- **Not authorized** — `refresh_metrics` raises
  `RuntimeError("YouTube not authorized…")`; UI surfaces as error
- **Per-video Analytics call fails** — that video gets data-API stats
  only; `errors` counter increments, others continue
- **No uploads recorded yet** — returns
  `{refreshed: 0, total: 0, errors: 0}`
- **First-week-post-upload** — Analytics API may return empty rows;
  metrics fields default to 0, no crash

## Used by
- `server.py` — `/api/analytics/refresh`, `/api/analytics/list`,
  `/api/analytics/signals`, `/api/dashboard`
- `engines/scheduler.py` — `task_refresh_analytics`
- `engines/upload.py` — `publish()` calls `record_upload()`
- `engines/ideas.py` — `run_harvest()` calls `compute_token_signals()`
  and `predict_score_for_idea()` to compute `ranked_score`
- `engines/review.py` — pulls per-video metrics + channel baseline
  for the LLM scorecard
