# `engines/review.py` — LLM Performance Scorecard

## Purpose
Self-critique. For any rendered video, gather every artifact the
pipeline left on disk (script, outline, metadata, tags, thumbnail
punchline) plus YouTube metrics if available, send to an LLM with a
6-dimension rubric, and return scores + concrete actionable
improvements. Closes the **creative** feedback loop the same way
`engines/analytics.py` closes the **algorithmic** one.

## File
`/home/user/obscure_vault/engines/review.py`

## Public API

### `review(api_key, video_filename, on_log=None)`
End-to-end scorecard. Returns:
```python
{
  "video_filename": "<job_stem>.mp4",
  "stem":           "<job_stem>",
  "title":          "...",
  "scores": {
    "title":       {"score": 0–10, "reason": "..."},
    "thumbnail":   {"score": 0–10, "reason": "..."},
    "hook":        {"score": 0–10, "reason": "..."},
    "structure":   {"score": 0–10, "reason": "..."},
    "description": {"score": 0–10, "reason": "..."},
    "tags":        {"score": 0–10, "reason": "..."}
  },
  "overall": {"score": 0–10, "verdict": "one short sentence"},
  "actionable_improvements": ["...", "...", "..."],
  "metrics_present": bool,
  "model": "openrouter model name"
}
```

Shape is guaranteed even on partial LLM responses — every dimension
gets a score+reason, defaulting to 0/empty if the LLM omitted them.

## Internal helpers

### `_load_artifacts(video_filename)`
Reads `workspace/<stem>/script.txt`, `metadata.json`, `outline.json`.
Missing files don't error — they return empty / None.

### `_hook(script)`
First 2 sentences (capped at 400 chars).

### `_outline_summary(outline)`
"Act 1: <label> — <summary>" lines for each act.

### `_video_metrics(stem)`
Best-effort lookup in `engines.analytics.list_metrics().by_video`
by lowercased title-substring match. Useful for already-uploaded
videos.

### `_channel_baseline()`
Pulls `analytics.compute_token_signals()['channel_avg']`.

## Prompt structure
The LLM receives:
- The title, thumbnail punchline, hook, act structure summary,
  description first 600 chars, tag list
- Word count of the full script
- YouTube metrics block ("not yet uploaded" if no match)
- Channel baseline ("no baseline yet" for the first video)

And is asked to rate each of 6 dimensions on 0–10 with one short
reason, an overall score + verdict, and 3 highest-impact concrete
improvements for the next video. Output JSON only.

## Configuration
No direct config. Caller passes the OpenRouter key (server.py reads
from `cfg.openrouter_api_key`).

## External dependencies
- `llm.py`
- Optional read of `engines/analytics.py` for metrics enrichment

## Failure modes
- **Workspace folder cleaned up** — script/outline/metadata empty;
  review still works on title + tags + metrics if available; quality
  is degraded but no crash
- **LLM returns malformed JSON** — `_extract_json` in `llm.py`
  surfaces; caller's `try/except` handles
- **No YouTube metrics yet** — `metrics_present: False`; UI shows a
  notice; review still runs purely on artifacts
- **No channel baseline** — same; review runs against absolute
  rubrics rather than relative ones

## Used by
- `server.py` — `_run_review` in a background thread; `/api/review-video`
  and `/api/review-status/<id>` endpoints
- The 🔬 button on every Library card in the UI
