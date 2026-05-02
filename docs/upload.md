# `engines/upload.py` — YouTube Data API Upload

## Purpose
Publish a finished video to YouTube via the Data API v3, with
thumbnail, captions, and AI-disclosure flag set per current YouTube
policy.

## File
`/home/user/obscure_vault/engines/upload.py`

## Public API

### `is_installed()` / `has_secrets()` / `has_token()`
Status checks for the Settings UI status panel.

### `channel_info()`
Returns `{id, title, subscribers}` for the authorized channel, or
None. Surfaced in the YouTube Settings card so the user knows
which channel they're authenticated against.

### `authorize(open_browser=True)`
Runs the InstalledAppFlow loopback OAuth flow. **Blocks** until the
user clicks "Allow" in their browser, then writes
`data/youtube/token.json`. Always called from a background thread
in `server.py`.

### `upload_video(video_path, *, title, description, tags=None, category_id="27", privacy_status="private", publish_at=None, made_for_kids=False, contains_synthetic_media=True, on_progress=None, on_log=None)`
Resumable upload via `MediaFileUpload(chunksize=4MB, resumable=True)`.
Retries on 5xx and 429 with 5 s backoff per chunk. Returns the new
videoId.

`category_id="27"` is YouTube's "Education" category. Most history
content fits here.

### `set_thumbnail(video_id, thumbnail_path, on_log=None)`
Hits `thumbnails().set()`. Requires the channel to be verified
(account-level YouTube setting, not API setting).

### `upload_caption(video_id, srt_path, language="en", name="English", on_log=None)`
Hits `captions().insert()` with the SRT as media body. Also
verified-account-only.

### `publish(video_path, *, title, description, tags, thumbnail_path, caption_srt_path, privacy_status, publish_at, contains_synthetic_media, idea_id, on_progress, on_log)`
Convenience wrapper: calls `upload_video` → `set_thumbnail` →
`upload_caption`. Records the upload via `analytics.record_upload`
for performance tracking. Returns
`{video_id, url, studio}`.

### `revoke_token()`
Deletes `data/youtube/token.json`. UI's "Revoke token" button.

## OAuth setup (one-time)
Walked through in the README §5. In summary:
1. Google Cloud Console → create project → enable YouTube Data API v3
2. OAuth consent screen → External; add yourself as Test user
3. Credentials → OAuth client ID → **Desktop app** type
4. Download the JSON
5. UI: Settings → YouTube Upload → "Upload client_secrets.json"
6. UI: "Authorize" → browser opens → consent → token saved

## Quotas
- **YouTube Data API:** 10 000 units/day
- **Upload:** 1 600 units/upload → ~6 uploads/day per project
- **Thumbnail set:** 50 units
- **Caption insert:** 400 units
- **videos.list (analytics):** 1 unit per call

To scale beyond 6 uploads/day, create a second Google Cloud project
with its own OAuth credentials.

## SCOPES
- `youtube.upload`
- `youtube.readonly` (for channel_info + analytics)
- `youtube.force-ssl` (for caption upload)

## Configuration
- `cfg.auto_upload` (default False) — auto-publish after each render
- `cfg.default_privacy` (default "private")
- `cfg.contains_synthetic_media` (default True) — recommended

## External dependencies
- **Optional pip deps:** `google-api-python-client`,
  `google-auth-oauthlib`, `google-auth-httplib2` (~50 MB combined,
  installed via UI button)
- HTTP egress to `oauth2.googleapis.com`, `www.googleapis.com`,
  `accounts.google.com`

## Failure modes
- **Not installed** — `is_installed()` returns False; UI surfaces
  "Install libs" button; pipeline auto-upload silently skips
- **client_secrets.json missing** — `RuntimeError`
- **Token expired/refresh failed** — Credentials raises; user must
  re-Authorize
- **Quota exceeded mid-upload** — HttpError 403; not currently
  retried (would just hit again); user sees the error in the
  Jobs tab log
- **Resumable upload chunk fails 5×** — raises; pipeline catches,
  ships the video locally, logs the failure

## Used by
- `server.py` — `/api/youtube/*` endpoints, pipeline auto-upload
  hooks in both `run_pipeline_thread` and `run_short_pipeline_thread`
- `engines/analytics.py` — uses `_load_creds` and `_build_youtube_data`
  / `_build_youtube_analytics` helpers from this module
