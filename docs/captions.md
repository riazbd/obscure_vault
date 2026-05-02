# `engines/captions.py` — Whisper Transcription + Burn-in

## Purpose
Transcribe the generated voiceover locally with `faster-whisper` and
produce two outputs:
- `.srt` for upload to YouTube as a real caption track
- `.ass` (styled) for FFmpeg burn-in

Burned captions add measurable retention (~5–15 % AVD lift on watch-
without-sound traffic, which is ~50 % of YouTube viewers).

## File
`/home/user/obscure_vault/engines/captions.py`

## Public API

### `is_available()`
Returns `True` if `faster-whisper` is importable. Caller (server.py
and the UI) uses this to decide whether to surface the toggle as
"installed" or "needs install".

### `build(audio_path, workspace, model_name='base.en', style='long', on_log=None)`
End-to-end. Returns:
```python
{
  "ass": Path("workspace/captions.ass"),
  "srt": Path("workspace/captions.srt"),
  "cards": int,
}
```

`style="shorts"` switches to the vertical 1080×1920 ASS template
with 90 px DejaVu Bold centered, narrower 18-char wrap.

### `transcribe(audio_path, model_name='base.en', on_log=None)`
Lazy import of `faster_whisper`. Loads the model with
`device="cpu", compute_type="int8"` (≈3× realtime on the T480).
Returns list of segments with word-level timestamps.

### `chunk_words_into_cards(segments)`
Repacks word stream into 2-line subtitle cards. Rules:
- Max 32 chars/line × 2 lines (long) or 18 × 2 (shorts via wrap below)
- Max 5.5 s per card
- Min 1.0 s per card
- Sentence-aware breaks: word ending with `.`/`!`/`?` after ≥1 s
  triggers an early flush

### `write_srt(cards, path)` / `write_ass(cards, path, style='long')`
Format writers. `_srt_time` and `_ass_time` produce the format-specific
timecode strings.

## ASS templates
Two variants embedded as `ASS_TEMPLATE_LONG` and `ASS_TEMPLATE_SHORTS`.

**Long-form (1920×1080):**
- DejaVu Sans Bold 58 px
- Cream foreground (`&H00F8F0DC`)
- Black 3 px outline + 2 px shadow
- Semi-opaque dark back (`&H8C000000`)
- Bottom-third (Alignment 2, MarginV 90)

**Shorts (1080×1920):**
- DejaVu Sans Bold 90 px
- White foreground
- Black 5 px outline + 2 px shadow
- Heavier dark back (`&HCC000000`)
- Vertically centered (Alignment 5, MarginV 0)

## Configuration
- `cfg.burn_captions` (default False) — toggles cap generation in
  the pipeline
- `cfg.caption_model` — `tiny.en` / `base.en` / `small.en`
- `cfg.tts_voice` — captions transcribe whatever voice produced the
  audio; if you switched to a non-English voice, set
  `model_name="tiny"` (multilingual) by editing `caption_model`

## External dependencies
- **Optional pip dep:** `faster-whisper` (~200 MB with ctranslate2)
- **Model file:** ~75 MB (tiny), ~140 MB (base), ~460 MB (small) —
  downloaded by faster-whisper on first transcription, cached in
  `~/.cache/huggingface/`
- FFmpeg `subtitles` filter (standard)

## Failure modes
- **Not installed** — `is_available()` returns False; pipeline
  detects this and skips caption generation with a log warning;
  video ships without burned-in caps
- **Model download fails on first run** — `WhisperModel` constructor
  raises; pipeline catches, logs, ships uncaptioned
- **Transcription returns 0 segments** — empty card list; `.srt`
  is empty; FFmpeg subtitles filter handles empty `.ass` gracefully
- **Word-level timestamps unavailable** (rare with `int8`) —
  falls back to whole-segment cards

## Path-escaping note
FFmpeg's `subtitles=` filter has cross-platform quirks with absolute
paths (especially on Windows where `C:\` triggers parser issues).
The pipeline sidesteps this by copying the `.ass` into the
workspace and calling FFmpeg with `cwd=str(workspace)` so the
filter sees `subtitles=captions.ass` (relative).

## Used by
- `server.py` `run_pipeline_thread` (long-form, when `cfg.burn_captions`)
- `server.py` `run_short_pipeline_thread` (Shorts, always-on)
