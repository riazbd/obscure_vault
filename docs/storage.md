# `engines/storage.py` — Disk Usage + Cleanup

## Purpose
The T480 has ~200 GB usable. Each render writes ~3–5 GB of intermediates
to `workspace/<job>/` and a 700 MB–1.5 GB final to `output/`. Without
management the SSD fills in ~50 renders. This engine:
- Reports current per-directory usage to the dashboard
- Cleans up intermediate files post-render (auto)
- Enforces a hard cap on the `output/` directory (auto)
- Provides a manual "Run cleanup now" button + a scheduler task

## File
`/home/user/obscure_vault/engines/storage.py`

## Public API

### `usage()`
Returns:
```python
{
  "workspace_mb":   int,
  "output_mb":      int,
  "cache_mb":       int,
  "branding_mb":    int,
  "app_total_mb":   int,
  "disk_free_mb":   int,
  "disk_total_mb":  int,
}
```

### `cleanup_workspace(job_name)`
Drop heavy intermediates from `workspace/<job_name>/`. Specifically:
- Recursively delete every subdirectory (e.g. `processed/`, `footage/`)
- Delete files NOT in `KEEP_IN_WS = {script.txt, metadata.json,
  description.txt, outline.json, captions.srt}`

The kept files are tiny (<10 KB each) and useful for the Performance
Review engine. Returns `{ok, freed_mb, kept_files}`.

Called automatically by both pipeline threads right before
`progress(100)` when `cfg.auto_cleanup_workspace=True` (default).

### `cleanup_all_workspaces(*, older_than_days=7)`
Iterate every subdirectory of `workspace/`, check mtime, run
`cleanup_workspace` if older than `older_than_days`. Returns
`{workspaces_cleaned, freed_mb}`.

### `enforce_output_cap(max_gb=30.0)`
Sort `output/*.mp4` by mtime ascending (oldest first). Until total
size is under `max_gb`, drop:
- The MP4 itself
- Its sibling `_thumbnail.jpg`
- Its sibling `.srt`
- The whole `workspace/<stem>/` directory

Returns `{kept, deleted, freed_mb, current_mb}`.

Called automatically by both pipeline threads right before
`progress(100)`.

### `estimate_freeable()`
"How much would `cleanup_all_workspaces` reclaim if I ran it now?"
Returns `{freeable_mb, candidate_workspaces}`. Surfaced in the
dashboard's Storage card.

## Configuration
- `cfg.auto_cleanup_workspace` (default True) — pipeline post-render
  hook
- `cfg.output_cap_gb` (default 30) — hard ceiling
- `cfg.scheduler_cleanup_days` (default 7) — passed to
  `cleanup_all_workspaces` from the scheduler task

## External dependencies
Stdlib only (`shutil`, `pathlib`, `datetime`).

## Failure modes
- **Permission denied when deleting** (rare on Linux/Mac, possible
  on Windows if a video is open in a player) — `shutil.rmtree(...,
  ignore_errors=True)` skips silently; the file gets cleaned next
  time
- **`disk_usage` raises OSError** (e.g. on weird filesystem) —
  returns 0 for free / total in `usage()`
- **All workspaces freshly cleaned but cap still exceeded** —
  `enforce_output_cap` deletes oldest MP4s; if the cap is set
  smaller than a single MP4, will delete every MP4 and leave the
  user with nothing. UI clamps cap input to ≥ 5 GB.

## Smoke-tested
- 17 MB synthetic workspace → 0 MB after cleanup, 2 small files preserved
- 60 MB output dir + 20 MB cap → 20 MB after enforcement, 5 oldest deleted

## Used by
- `server.py` — both pipeline threads call `cleanup_workspace` +
  `enforce_output_cap` post-render; `/api/storage/usage` and
  `/api/storage/cleanup` endpoints; `/api/dashboard` returns
  `usage()` + `estimate_freeable()`
- `engines/scheduler.py` — `task_storage_cleanup`
- The Dashboard tab's Storage card (UI)
