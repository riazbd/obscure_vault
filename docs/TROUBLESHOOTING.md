# Troubleshooting

Indexed by error message. If you don't find your error here, check
the Jobs tab → click the failed job → expand the log; that has the
full stack tail.

---

## Installation & startup

### `python: command not found` (Windows)
Reinstall Python from `python.org` with the **"Add Python to PATH"**
checkbox ticked during the installer. Restart your terminal.

### `ffmpeg: command not found`
FFmpeg isn't on your system PATH. See README §4.2. Quick check:
`ffmpeg -version` should print version info.

### `python start.py` exits immediately with no error
Probably a virtualenv issue. Try:
```bash
python -m pip install --upgrade pip
python -m pip install pillow edge-tts requests flask
python server.py
```

### Browser doesn't auto-open
Just visit `http://localhost:5050` manually. The launcher's auto-open
is best-effort.

---

## API keys & credentials

### Pexels validation says "Invalid"
You either copied a partial key or signed up but didn't activate.
Visit `pexels.com/api`, log in, copy the full key on the dashboard.
Test directly with:
```bash
curl -H "Authorization: <KEY>" \
  "https://api.pexels.com/videos/search?query=test&per_page=1"
```
Should return JSON with a `videos` array.

### OpenRouter validation says "Invalid key or no free models available"
Common causes:
- Key has a typo (paste again)
- You're on OpenRouter's paid plan with no free credits routed
- All 5 cascade free models are temporarily down (rare; retry in 1 h)

### "OpenRouter: all models failed; last=… HTTP 429"
Daily free-tier quota exhausted across all 5 cascaded models. Wait
~24 h or upgrade your OpenRouter account (paid models still cheap).

### YouTube Authorize button does nothing
Browser tab probably opened but you missed it. Look for a tab that
says "Choose an account" or "Sign in to continue". If still nothing,
firewall might be blocking the OAuth loopback port; try disabling
your firewall briefly.

### "client_secrets.json: Doesn't look like an OAuth client_secrets file"
You uploaded the wrong JSON. From Google Cloud Console it should be
the file you got after creating an **OAuth client ID of type
"Desktop app"** under APIs & Services → Credentials.

---

## Rendering failures

### "FFmpeg assembly failed: subtitles filter not found"
Your FFmpeg is built without the `subtitles` filter. Either upgrade
to a full FFmpeg build (4.4+) or turn off **Burn-in Captions** in
Settings. On Windows, prefer gyan.dev's "full" build.

### "FFmpeg assembly failed: sidechaincompress filter not found"
Older FFmpeg without sidechain support. Upgrade FFmpeg. Workaround:
turn **Audio polish** off in Settings (the simpler `amix` graph
doesn't need this filter).

### Pipeline runs to ~70 % then "FFmpeg failed"
Always look at the log in the Jobs tab. The last 1500 chars of
FFmpeg stderr are captured. Most common causes:
- Temp disk full (run **🧹 Run cleanup now** on the Dashboard)
- Filter graph error from a corrupted clip download (the next
  render usually picks different clips)

### Render runs but the video is just a dark screen
Pexels footage download failed (network blip or rate-limit). The
pipeline falls back to dark cards intentionally so the video still
ships. Check the Jobs log for "download fail" or "Pexels HTTP" lines.
Run again later.

### "smart B-roll failed: no clips found"
LLM produced search queries but neither Pexels nor Pixabay returned
any results. Falls back to the legacy keyword-substring map
automatically. Improve by providing a more concrete topic.

### Captions toggle is on but no captions appear
`faster-whisper` isn't installed. Settings → Burn-in Captions →
**Install caption deps**. First transcription downloads the model
(~140 MB to `~/.cache/huggingface/`).

### "WhisperModel: failed to load model"
First-time model download failed. Causes:
- No internet
- HuggingFace down (rare)
- Disk full

Re-run; if it persists, try a smaller model in Settings (`tiny.en`).

---

## Thumbnails

### `pollinations failed: HTTP 429`
Pollinations is throttling. Engine retries 3× with backoff; if it
still fails, the pipeline falls back to the **legacy frame-based
thumbnail** (extracts a frame from the first footage clip + adds
the same text overlay). Logged.

### `pollinations failed: connection refused`
Their service is down. Wait or set `cfg.use_ai_thumbnail=False` to
skip the AI path entirely.

### Thumbnail text is barely readable
Auto-darkening should prevent this; if it doesn't, the background
was already very bright. Open Settings → AI Thumbnail → bump
**Variants per video** to 3 and pick a different seed (delete the
current thumbnail and re-render).

---

## Upload

### "YouTube quota exceeded"
You've hit YouTube Data API's 10 000 units/day. Each upload costs
~1 600 units → ~6 uploads/day per Google Cloud project. Wait until
UTC midnight or create a second project for fresh quota.

### Upload completes but thumbnail / captions don't attach
You need a **verified YouTube account** for both. Search "verify
YouTube account" → enter your phone number. Re-run upload won't help
once the video is up; manually upload the thumbnail / SRT in
YouTube Studio.

### "OAuth token has been expired or revoked"
Settings → YouTube Upload → click **Revoke token** → re-Authorize.
Sometimes Google forces re-consent; this is normal.

---

## Scheduler

### Enabled tasks aren't firing
Check `data/scheduler.json` for `last_run` and `next_run`. If
`next_run` is in the future, it's just waiting. If `last_status`
says "error", click **Run now** to see the error in the log.

### "skip: no pending ideas"
The Produce-top-idea task ran but found nothing in `pending` status.
Run Harvest first, or approve some ideas manually in the Ideas tab.

### "skip: pipeline already running"
A previous render is still going. The scheduler waits politely.

---

## Storage

### Output directory keeps growing past 30 GB
- Confirm `auto_cleanup_workspace=True` in Settings → Audio card
- Confirm `output_cap_gb` is 30 (or your value) in Settings
- Check the Storage card on the Dashboard; click **🧹 Run cleanup now**
- If still growing, individual final MP4s are larger than your cap
  divided by some sensible count. Lower video resolution or
  shorten target minutes.

### "Storage 0 MB free"
Stop the server immediately. Manually `rm -rf workspace/*` and
`rm -rf data/cache/*`. Restart. Lower `output_cap_gb` to 10 GB.

---

## Database

### `data/jobs.db is locked`
Two pipelines tried to run concurrently. Boot orphan-recovery should
fix this on next restart; otherwise stop the server, delete
`data/jobs.db`, restart. You lose history but no other state.

### `jobs.json is corrupted`
Stop the server, back up the file, delete `data/ideas.json` (or
`uploads.json` etc — whichever is failing). Re-harvest will repopulate.

---

## Performance

### Renders are taking 90+ minutes (vs the documented 25–40 min)
Likely causes:
- Other heavy apps running (Chrome with many tabs uses 4 GB+ RAM
  on the T480; close it)
- AI Thumbnail with `variants=3` adds ~3 min per variant; reduce
  to 1
- Captions with `small.en` is 3× slower than `base.en`; switch
- Smart B-roll with low `chunk_seconds` (e.g. 5 s) doubles the
  number of clips processed; raise to 12 s

### "OOM killed" / pipeline thread dies silently mid-render
8 GB RAM is tight. Close Chrome, close any other heavy app. The
budget docs in PLAN.md §2.1 assume nothing else is running on the
machine.
