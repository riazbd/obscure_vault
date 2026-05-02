# `engines/footage.py` — Semantic B-roll Engine

## Purpose
Replace the legacy "if 'war' in title, search 'battlefield aerial'"
keyword map with per-chunk semantic search. The script is split into
sentence-grouped chunks, each chunk gets its own LLM-written
cinematographic search query, candidate clips are scored, and one
clip per chunk is downloaded, colour-graded, Ken-Burns-panned, and
concatenated in script order so the visuals follow what the
narrator is saying.

## File
`/home/user/obscure_vault/engines/footage.py`

## Public API

### `build(*, script, duration, workspace, openrouter_key, pexels_key, pixabay_key='', width=1920, height=1080, target_chunk_secs=10.0, motion='pan', on_log=None)`
End-to-end build. Returns:
```python
{
  "track":  Path("workspace/processed/footage_track.mp4"),
  "plan":   [{"chunk": ..., "clip": ..., "query": ...}, ...],
  "chunks": [{"id", "text", "start", "end", "duration"}, ...],
}
```

### `chunk_script_by_time(script, total_seconds, target_chunk_secs=10.0)`
Sentence-grouped chunking, then duration-scaled so the sum of chunk
durations equals `total_seconds` exactly. Each chunk has start/end
timestamps aligned to the eventual voiceover.

### `generate_visual_queries(api_key, chunks, channel_style=None)`
**One batched LLM call** sends all chunks together, receives 2
search queries per chunk back. Prompt forbids generic queries
("history", "war", "mystery") and demands cinematographic specificity
("abandoned soviet bunker dim corridor", "fog over still mountain
lake dawn").

### `search_pexels(query, key, n=4)` / `search_pixabay(query, key, n=4)`
Provider-specific search. Both return a list of:
```python
{"id", "url", "duration", "width", "height", "query", "source"}
```
Pexels: `https://api.pexels.com/videos/search` with Authorization header.
Pixabay: `https://pixabay.com/api/videos/` with `key=` query param.

### `pick_clips_for_chunks(chunks, queries_per_chunk, pexels_key, pixabay_key, on_log=None)`
For each chunk:
1. Try every query in order; collect candidates from both providers
2. Score with `_score(clip, chunk_dur, used_ids, query_idx)`:
   - +0.25 × `min(width / 1920, 1.0)` (resolution)
   - +0.35 if duration ≥ chunk_dur, else proportional
   - +0.20 / +0.10 / +0.00 by query rank
   - −0.50 if clip already used
3. Pick the highest-scored
4. Mark used; move on

Returns the per-chunk plan.

### `build_footage_track(plan, workspace, width, height, motion='pan', on_log=None)`
For each chunk in the plan:
1. Download the chosen clip → `workspace/footage/<id>.mp4`
2. Process with `_process_clip_segment(src, out, duration, W, H, motion)`:
   - Stream-loop the source for the chunk duration
   - Scale + crop to W×H
   - Apply colour grade (warm shadows, lifted blacks, slight desaturation)
   - Apply motion effect:
     - `pan` (default) — sinusoidal x-offset across a 12 % up-scaled canvas
     - `zoom` — `zoompan` with steady 1.00 → 1.10× zoom (best for stills)
     - `off` — flat scale + crop
   - libx264 fast, CRF 23, 30 fps
3. Concat all segments via concat demuxer with stream-copy

Returns the path to `processed/footage_track.mp4`.

## Caching
Per-query result cache lives in memory for the duration of one build
call (so chunks sharing a query reuse downloads). Downloaded clips
persist in `workspace/<job>/footage/<clip_id>.mp4` until the post-render
storage cleanup deletes them.

## Configuration
- `cfg.smart_broll` (default True) — toggles the engine on/off in
  the pipeline; off falls back to legacy substring keyword map
- `cfg.chunk_seconds` (default 10) — `target_chunk_secs` parameter
- `cfg.motion_effect` (default `pan`) — passed to `motion=` arg
- `cfg.pexels_api_key` (required)
- `cfg.pixabay_api_key` (optional, second source)

## External dependencies
- `requests`
- `llm.py`
- FFmpeg on PATH (libx264, scale, crop, zoompan, colorchannelmixer,
  curves, eq, setsar)
- HTTP egress to `api.pexels.com` and `pixabay.com`

## Failure modes
- **LLM query generation fails entirely** — `RuntimeError`,
  `server.py` falls back to legacy keyword search
- **No clips found for a chunk** — dark card placeholder (FFmpeg
  `color=c=0x0a0a0a` source); pipeline continues
- **Clip download fails** — same dark-card fallback for that chunk
- **`_process_clip_segment` fails with motion effect** — auto-retry
  with `motion="off"` (flat scale + crop)
- **No segments produce at all** — total dark card spanning the full
  duration; video still ships

## Used by
- `server.py` `run_pipeline_thread` (long-form)
- `server.py` `run_short_pipeline_thread` (Shorts, with width=1080
  height=1920)
