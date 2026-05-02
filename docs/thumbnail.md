# `engines/thumbnail.py` — AI Thumbnail Engine

## Purpose
Generate a YouTube thumbnail that's actually attractive and
clickable. Three layers:
1. AI-generated background (Pollinations.ai)
2. Auto-darken + vignette + accent bars
3. Big punchy LLM-written 2–4 word punchline + channel branding

Plus auto-QA so the text is always readable, regardless of the
generated background.

## File
`/home/user/obscure_vault/engines/thumbnail.py`

## Public API

### `generate(api_key, title, out_path, variants=1, vertical=False, on_log=None)`
End-to-end. Returns:
```python
{
  "primary":      str path,
  "variants":     [str paths],
  "punchline":    "2-4 WORD PUNCH",
  "image_prompt": "the full prompt sent to Pollinations",
}
```

`vertical=True` produces 1080×1920 (Shorts thumbnail); default is
1280×720 (long-form).

### `generate_punchline(api_key, title)`
LLM call — JSON output `{"punchline": "..."}`. Strict rules:
- 2–4 words, ≤ 22 chars total
- Must NOT just repeat the full title
- No emoji, quotes, question marks unless essential
- Examples in the prompt: "BURIED ALIVE", "60 YEARS HIDDEN",
  "THEY KNEW", "NEVER FOUND"
- Sanitisation: strips non-alphanumeric chars, falls back to
  title-derived fragment if LLM produces junk

### `generate_image_prompt(api_key, title)`
LLM call — produces a 25–50 word cinematographic image prompt:
- Concrete subject + setting + lighting + mood
- 16:9 framing with negative space for overlay text
- "no faces, no text, no letters" anchors
- Channel-wide cinematic style appended automatically

### `pollinations_image(prompt, *, seed=0, width=1280, height=720, timeout=90)`
Hits `https://image.pollinations.ai/prompt/<urlencoded>?width=…&seed=…&model=flux`.
Returns a PIL `Image`. Caches by `sha256(prompt + seed + size)` at
`data/cache/images/<sha>.png`. 3 retries with exponential backoff
on failure.

### `compose_thumbnail(background, punchline, channel_name, tagline, accent_color, out_path, vertical=False)`
PIL composition:
1. Auto-darken background to ≤ 0.40 mean luminance
2. Vignette
3. Top + bottom 7 px accent-color bars
4. Channel watermark, top-left
5. **Auto-fit** punchline: starts at 180 px (140 / 110 for 2 / 3 lines),
   shrinks 8 px at a time until it fits W − 120
6. Behind-text dark slab for guaranteed contrast
7. Drop shadow + 3 px stroke + cream fill on the punchline
8. Tagline at bottom

### `_avg_luminance(img)` / `_ensure_dark(img, target_max=0.45)`
Histogram-based mean luminance, scale-down to ensure the background
doesn't drown the text. Tested: 0.83-luminance bright background
auto-corrects to 0.40.

## Variants
For A/B testing, generate 2–3 variants per render with different
Pollinations seeds. Files named `<stem>.jpg`, `<stem>_v2.jpg`,
`<stem>_v3.jpg`. The primary uploads to YouTube; you can manually
slot the others into YouTube's native thumbnail-test feature.

## Configuration
- `cfg.use_ai_thumbnail` (default True) — pipeline toggle
- `cfg.thumbnail_variants` (default 1) — number of variants per render
- `cfg.openrouter_api_key` (required for AI thumbnail; falls back to
  legacy frame-based thumbnail if missing)

## External dependencies
- `Pillow` (already required)
- `requests`
- `llm.py`
- HTTP egress to `image.pollinations.ai`

## Failure modes
- **Pollinations 4xx/5xx after 3 retries** — variant 1 falls back
  to a dark card; subsequent variants are skipped
- **LLM returns junk punchline** — regex sanitisation, then
  title-derived fallback
- **LLM image-prompt call fails** — falls back to a generic
  "abandoned historical scene relating to: <title>" prompt
- **Whole AI path errors** — `server.py` catches, falls back to the
  legacy frame-based thumbnail (extracts a frame from the first
  footage clip + adds the same text overlay)

## Used by
- `server.py` `run_pipeline_thread` — primary thumbnail step
- `server.py` `run_short_pipeline_thread` — with `vertical=True`
- `server.py` `_run_thumb_job` — Test Thumbnail preview button
