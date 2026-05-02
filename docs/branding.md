# `engines/branding.py` — Channel Intro/Outro Stings

## Purpose
Pre-pend an intro and append an outro to every rendered video, so
your channel branding appears automatically. Designed to be a
**zero-quality-loss, low-render-cost** addition: the heavy main
video is never re-encoded; only the small sting clips are
normalized once on upload, and the final concat uses stream-copy.

## File
`/home/user/obscure_vault/engines/branding.py`

## Public API

### `slot_path(slot)` / `has_slot(slot)` / `list_slots()`
Slot management. Valid slots:
- `long_intro` (1920×1080)
- `long_outro` (1920×1080)
- `short_intro` (1080×1920)
- `short_outro` (1080×1920)

`list_slots()` returns `{slot: {filename, size_kb, duration} | None}`
for the UI.

### `delete_slot(slot)`
Hard-delete the file at `data/branding/<slot>.mp4`.

### `normalize_clip(src_path, slot, *, width=1920, height=1080, fps=30)`
Re-encode the user's uploaded sting to the canonical spec:
- Canvas WxH (long: 1920×1080, short: 1080×1920)
- 30 fps
- libx264 yuv420p, CRF 20, medium preset
- AAC 192 kbps stereo at 44.1 kHz
- letterbox-padded with `pad=W:H:(ow-iw)/2:(oh-ih)/2:black` so any
  aspect ratio fits without distortion
- `+faststart` for streaming

Saves at `data/branding/<slot>.mp4`. Retries without `-af apad` if
the source rejects audio padding (some sources have no audio at all).

### `apply_branding(main_path, out_path, *, intro_path=None, outro_path=None, width=1920, height=1080, on_log=None)`
Concat `[intro?] + main + [outro?]` into `out_path`. Two-step
strategy:

1. **Try concat demuxer with stream-copy first** — fast, lossless.
   Works because the upload normalisation gives every input matching
   codec params.
2. **Fall back to filter-concat with re-encode** if step 1 fails on
   a weird source clip. Slower but bulletproof.

If neither intro nor outro is provided, just copies main → out.

### `apply_for_video_kind(main_path, out_path, *, kind="long", width=1920, height=1080, on_log=None)`
Convenience: looks up the `<kind>_intro` and `<kind>_outro` slots
automatically and calls `apply_branding`.

## Configuration
- `cfg.apply_branding` (default True) — pipeline toggle

## Pipeline integration
After the main FFmpeg assembly writes `output/<job>.mp4`:
1. Move it to `workspace/<job>/main_unbranded.mp4`
2. Call `apply_for_video_kind(main_unbranded, output/<job>.mp4,
   kind="long")` (or `"short"`)
3. Stream-copy concat finishes in seconds; final output replaces
   the unbranded original

Failures are caught — if branding fails, the unbranded MP4 is left
in place so the render still ships. Logged in the job's log.

## External dependencies
- FFmpeg with libx264, AAC encoder, concat demuxer + concat filter
- `ffprobe` for duration introspection in `_probe_duration`

## Failure modes
- **Source has no audio** — second-pass `normalize_clip` retries
  without audio padding
- **Source is corrupted/unreadable** — `normalize_clip` raises
  `RuntimeError` with last 1500 chars of stderr; UI surfaces this
  as the upload status "error"
- **Stream-copy concat fails** — auto-retry with filter-concat
  re-encode (adds ~1 min to render)
- **Filter-concat also fails** — `RuntimeError` propagates;
  pipeline catches and ships the unbranded video

## Used by
- `server.py` `run_pipeline_thread` — long-form post-assembly step
- `server.py` `run_short_pipeline_thread` — Shorts post-assembly step
- `server.py` `/api/branding/list`, `/upload`, `/upload-status/<id>`,
  `/preview/<slot>`, `/api/branding/<slot>` (DELETE)
