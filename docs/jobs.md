# `engines/jobs.py` — Persistent Job History (SQLite)

## Purpose
Until this engine, `jobs` was an in-memory dict that grew without
bound and lost everything on restart. Now every long-form and Shorts
render writes through to `data/jobs.db` (single-file SQLite, WAL
journal mode), so:
- Render history survives restarts
- The Jobs tab can show what happened last week
- The scheduler can mark orphaned-by-crash jobs as failed on boot

## File
`/home/user/obscure_vault/engines/jobs.py`

## Public API

### `upsert_job(job_id, **fields)`
Insert if missing, update otherwise. Allowed fields:
`kind`, `title`, `status`, `progress`, `stage`, `started_at`,
`finished_at`, `error`, `duration_s`, `result` (auto-JSON-serialised).

Called by both pipeline threads on every `progress()` and on every
status change.

### `append_log(job_id, line)`
Append one line to the job's `log` text column. The column is
hard-capped at 2 000 lines (older lines are dropped) so a runaway
log doesn't bloat the DB.

### `get_job(job_id)`
Return the full row including `log` (newline-joined) and
`result` (deserialised dict).

### `list_jobs(*, status=None, kind=None, limit=100)`
Filterable list. Status: `running`, `done`, `error`. Kind: `long`,
`short`, `translate` (legacy — engine reverted but DB column still
exists). Returns `[{id, kind, title, status, progress, stage,
started_at, finished_at, error, duration_s}]` (no log/result for
performance — the Jobs tab fetches detail per row on click).

### `delete_old(*, keep_recent=200)`
Trim the table to the most recent N rows. Returns deletion count.
Called by the UI's Cleanup button.

### `mark_orphans_failed()`
Flips any `status='running'` rows to `status='error'` with
`error='orphaned by server restart'`. Called once on `__main__`
boot.

## Schema
```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT,
    title       TEXT,
    status      TEXT,           -- 'running' | 'done' | 'error'
    progress    INTEGER,        -- 0–100
    stage       TEXT,           -- human-readable current stage
    started_at  TEXT,           -- ISO 8601 UTC
    finished_at TEXT,
    result      TEXT,           -- JSON
    error       TEXT,
    log         TEXT,           -- newline-joined, capped at 2000 lines
    duration_s  INTEGER         -- final voice/render seconds
);
CREATE INDEX jobs_started_idx ON jobs(started_at DESC);
CREATE INDEX jobs_status_idx  ON jobs(status, started_at DESC);
```

## Concurrency
- Module-level `threading.Lock` (`_LOCK`) wraps every DB transaction
- WAL journal mode allows concurrent reads while a writer holds the
  lock
- `synchronous = NORMAL` for reasonable durability without per-op
  fsync

## Configuration
None.

## External dependencies
Stdlib `sqlite3` only. No new pip deps.

## Failure modes
- **DB file locked** (rare; only if Windows AV scans `data/jobs.db`
  during a write) — `sqlite3.connect` retries for 10 s before
  raising `OperationalError`; pipeline catches with a `try/except`
  per call so the render itself isn't blocked
- **DB corruption** — delete `data/jobs.db`; schema is auto-recreated
  next call. Loses history.
- **Disk full while writing log** — caught silently per-call; render
  log in the in-memory dict is still complete

## Used by
- `server.py` — pipeline threads call `upsert_job`/`append_log`;
  `/api/jobs/list`, `/api/jobs/<id>`, `/api/jobs/cleanup` endpoints;
  `mark_orphans_failed()` in `__main__`
- The Jobs tab UI consumes the endpoints
