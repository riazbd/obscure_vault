# `engines/scheduler.py` — Cron Task Runner

## Purpose
Single daemon thread that ticks every 60 seconds and fires recurring
tasks. The "autopilot heart" — turn it on and the system runs itself.

## File
`/home/user/obscure_vault/engines/scheduler.py`

## Public API

### `start(get_cfg, runtime, tick_seconds=60)`
Boot the scheduler thread. Called from `server.py`'s `__main__`.

- `get_cfg()` — callable returning current config dict (called every
  tick so config changes apply on next tick)
- `runtime` — dict the tasks need:
  - `pipeline_jobs`: callable returning the live `jobs` map (so
    `task_produce_top_idea` can check if a render is already running)
  - `produce_idea`: callable that takes an idea + minutes and starts
    the full Idea-to-Video chain

### `stop()`
Set the stop event; the thread exits within 60 s.

### `get_state(cfg_tasks=None)`
Returns the snapshot the UI consumes:
```python
{
  "tasks": {
    "<task_name>": {
      "enabled": bool,
      "interval_hours": float,
      "last_run": ISO ts | null,
      "last_status": "ok: ..." | "error" | "skip: ..." | null,
      "last_error": str | null,
      "next_run": ISO ts | null,
    },
    ...
  },
  "log": [last 50 log lines],
  "running": bool,
}
```

### `trigger_now(name, get_cfg, runtime)`
Fire one task immediately, regardless of interval. Used by the
"Run now" button per task.

## Tasks

### `task_harvest_ideas` (default off, every 6 h)
Calls `engines.ideas.run_harvest(...)` with config-driven seeds and
the OpenRouter key for niche scoring.

### `task_produce_top_idea` (default off, every 12 h)
1. Skip if no OpenRouter key
2. Skip if any pipeline job is in `running` state
3. Pick the highest `ranked_score` `pending` idea
4. Call `runtime["produce_idea"](top_idea, minutes)` which kicks off
   the full Idea-to-Video chain in a separate thread
5. Returns immediately — does not wait for the render to finish

### `task_refresh_analytics` (default off, every 24 h)
Calls `engines.analytics.refresh_metrics()`.

### `task_storage_cleanup` (default off, every 24 h)
Reads `cfg.scheduler_cleanup_days` (default 7) and `cfg.output_cap_gb`
(default 30). Calls
`engines.storage.cleanup_all_workspaces(older_than_days=…)` plus
`engines.storage.enforce_output_cap(gb=…)`.

## Persistence
`data/scheduler.json`:
```python
{
  "tasks": {
    "<name>": {
      "last_run": "2026-05-02T12:00:00+00:00",
      "last_status": "ok: +5 ideas (total 47)",
      "last_error": null
    }, ...
  }
}
```

`_LOG` is an in-memory ring buffer (last 200 lines); not persisted.

## Tick logic
For each task in `TASKS`:
1. Read merged config (defaults + cfg overrides)
2. Skip if `enabled=False`
3. `_is_due(name, interval_hours)` — return True if no `last_run` in
   state, else True if `now - last_run >= interval`
4. If due, spawn a new thread to run the task; record start
5. Each task wraps in try/except, persists `last_status` and
   `last_error` on completion or failure

## Configuration
Everything is in `cfg.scheduler` (a nested dict):
```json
{
  "scheduler": {
    "harvest_ideas":     {"enabled": true, "interval_hours": 6},
    "produce_top_idea":  {"enabled": true, "interval_hours": 12},
    "refresh_analytics": {"enabled": true, "interval_hours": 24},
    "storage_cleanup":   {"enabled": false, "interval_hours": 24}
  }
}
```

Plus task-specific top-level keys:
- `scheduler_yt_seeds`, `scheduler_subs`, `scheduler_niche` — for
  harvest task (override the defaults from `engines/ideas.py`)
- `scheduler_minutes` (default 10) — target minutes for produce task
- `scheduler_cleanup_days` (default 7) — for cleanup task

## External dependencies
None directly. Imports `engines.ideas`, `engines.analytics`,
`engines.storage` lazily inside each task.

## Failure modes
- **Scheduler thread dies** — won't restart automatically; user must
  restart `python start.py`
- **Task throws** — caught, status becomes "error", logged; subsequent
  ticks still run other tasks
- **Two ticks of the same task overlap** — guarded only by `_is_due`
  using `last_run`; since `_run_task_async` records `last_run` only
  after the task completes, a long-running task can't double-fire
  in the same ≤60 s window between ticks (next tick checks again)

## Used by
- `server.py` — `__main__` calls `sched.start()`;
  `/api/scheduler/state` and `/api/scheduler/trigger/<task>` endpoints
- The Settings → Scheduler card in the UI calls these endpoints
