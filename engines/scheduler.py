"""
SchedulerEngine — single-process tick loop that fires recurring tasks.

Tasks (all optional, configured in config.json under `scheduler.<name>`):
  - harvest_ideas        — run the idea harvester every N hours
  - produce_top_idea     — pick the highest-ranked pending idea and run
                            the full script + render + upload pipeline,
                            but only when no other pipeline is running
  - refresh_analytics    — daily YouTube metrics pull

State (last_run, next_run) persisted to data/scheduler.json so restarts
don't double-fire or skip work.

Single thread, ticks every 60 seconds. Tasks themselves run in their own
threads (the scheduler doesn't block on them).
"""

import json
import time
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH  = DATA_DIR / "scheduler.json"

_LOCK   = threading.Lock()
_THREAD = None
_STOP   = threading.Event()
_LOG    = []   # ring buffer for the UI

DEFAULT_TASKS = {
    "harvest_ideas":     {"enabled": False, "interval_hours": 6},
    "produce_top_idea":  {"enabled": False, "interval_hours": 12},
    "refresh_analytics": {"enabled": False, "interval_hours": 24},
    "storage_cleanup":   {"enabled": False, "interval_hours": 24},
}


# ════════════════════════════════════════════════════════
#  State
# ════════════════════════════════════════════════════════

def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"tasks": {}, "log": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"tasks": {}, "log": []}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def get_state(cfg_tasks: dict | None = None) -> dict:
    """Merge persisted state with current config to expose to UI."""
    state = _load_state()
    cfg_tasks = cfg_tasks or {}
    out = {"tasks": {}, "log": _LOG[-50:], "running": _THREAD is not None and _THREAD.is_alive()}
    for name, default in DEFAULT_TASKS.items():
        cfg = {**default, **cfg_tasks.get(name, {})}
        st  = state.get("tasks", {}).get(name, {})
        out["tasks"][name] = {
            "enabled":         bool(cfg.get("enabled", False)),
            "interval_hours":  float(cfg.get("interval_hours", default["interval_hours"])),
            "last_run":        st.get("last_run"),
            "last_status":     st.get("last_status"),
            "last_error":      st.get("last_error"),
            "next_run":        _compute_next_run(
                st.get("last_run"),
                cfg.get("interval_hours", default["interval_hours"]),
                cfg.get("enabled", False),
            ),
        }
    return out


def _compute_next_run(last_run: str | None, interval_hours: float,
                      enabled: bool) -> str | None:
    if not enabled:
        return None
    interval = timedelta(hours=float(interval_hours))
    if not last_run:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        prev = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (prev + interval).isoformat(timespec="seconds")


def _record_run(name: str, status: str, error: str | None = None):
    with _LOCK:
        state = _load_state()
        tasks = state.setdefault("tasks", {})
        tasks[name] = {
            "last_run":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_status":  status,
            "last_error":   error,
        }
        _save_state(state)
    _log(f"{name}: {status}" + (f" — {error}" if error else ""))


def _log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    _LOG.append(line)
    if len(_LOG) > 200:
        del _LOG[:100]
    print(f"[scheduler] {msg}")


# ════════════════════════════════════════════════════════
#  Task implementations
# ════════════════════════════════════════════════════════

def task_harvest_ideas(get_cfg, runtime):
    from engines import ideas as I
    cfg = get_cfg()
    or_key = cfg.get("openrouter_api_key", "").strip()
    seeds  = cfg.get("scheduler_yt_seeds")  or None
    subs   = cfg.get("scheduler_subs")      or None
    niche  = cfg.get("scheduler_niche")     or None
    res = I.run_harvest(
        yt_seeds=seeds, subreddits=subs,
        score_with_openrouter_key=or_key, niche=niche or I.DEFAULT_NICHE,
        on_log=_log,
    )
    return f"+{res.get('added', 0)} ideas (total {res.get('total', 0)})"


def task_produce_top_idea(get_cfg, runtime):
    """Pick the best pending idea and start the full pipeline."""
    import random
    from engines import ideas as I
    cfg = get_cfg()
    or_key = cfg.get("openrouter_api_key", "").strip()
    if not or_key:
        return "skip: no OpenRouter key"

    # Don't queue a new render if one is already running.
    pipeline_jobs = runtime["pipeline_jobs"]()
    for j in pipeline_jobs.values():
        if j.get("status") == "running" and j.get("kind") in ["pipeline", "short_pipeline"]:
            return "skip: pipeline already running"

    # Check daily limits
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _load_state()
    daily_stats = state.get("daily_stats", {})
    today_stats = daily_stats.get(today_str, {"long": 0, "short": 0})
    
    limit_long = int(cfg.get("daily_limit_long", 2))
    limit_short = int(cfg.get("daily_limit_short", 2))

    can_do_long = limit_long > 0 and today_stats.get("long", 0) < limit_long
    can_do_short = limit_short > 0 and today_stats.get("short", 0) < limit_short

    if not can_do_long and not can_do_short:
        return f"skip: daily limits reached (Long: {today_stats.get('long', 0)}/{limit_long}, Short: {today_stats.get('short', 0)}/{limit_short})"

    # Pick format
    chosen_format = None
    if can_do_long and can_do_short:
        chosen_format = random.choice(["long", "short"])
    elif can_do_long:
        chosen_format = "long"
    else:
        chosen_format = "short"

    pending = [it for it in I.list_all() if it.get("status") == "pending"]
    if not pending:
        return "skip: no pending ideas"
    pending.sort(
        key=lambda it: (it.get("ranked_score") or it.get("niche_fit") or 0),
        reverse=True,
    )
    top = pending[0]
    minutes = float(cfg.get("scheduler_minutes", 10))

    # Hand off to the existing produce flow via the runtime callback.
    runtime["produce_idea"](top, minutes, video_format=chosen_format)

    # Update state
    today_stats[chosen_format] = today_stats.get(chosen_format, 0) + 1
    daily_stats[today_str] = today_stats
    state["daily_stats"] = daily_stats
    _save_state(state)

    return f"produced: {chosen_format} '{top['title'][:80]}'"


def task_refresh_analytics(get_cfg, runtime):
    from engines import analytics as A
    res = A.refresh_metrics(on_log=_log)
    return f"refreshed {res.get('refreshed',0)}/{res.get('total',0)}"


def task_storage_cleanup(get_cfg, runtime):
    from engines import storage as S
    cfg = get_cfg()
    older = int(cfg.get("scheduler_cleanup_days", 7))
    cap   = float(cfg.get("output_cap_gb", 30.0))
    ws = S.cleanup_all_workspaces(older_than_days=older)
    op = S.enforce_output_cap(cap)
    return (f"cleaned {ws.get('workspaces_cleaned', 0)} workspaces "
            f"({ws.get('freed_mb', 0)} MB), "
            f"deleted {op.get('deleted', 0)} old MP4s")


TASKS = {
    "harvest_ideas":     task_harvest_ideas,
    "produce_top_idea":  task_produce_top_idea,
    "refresh_analytics": task_refresh_analytics,
    "storage_cleanup":   task_storage_cleanup,
}


# ════════════════════════════════════════════════════════
#  Tick loop
# ════════════════════════════════════════════════════════

def _is_due(name: str, interval_hours: float) -> bool:
    state = _load_state()
    last  = state.get("tasks", {}).get(name, {}).get("last_run")
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except Exception:
        return True
    return datetime.now(timezone.utc) - prev >= timedelta(hours=float(interval_hours))


def _run_task_async(name: str, fn, get_cfg, runtime):
    def _wrap():
        try:
            msg = fn(get_cfg, runtime) or "ok"
            _record_run(name, "ok: " + msg, None)
        except Exception as e:
            import traceback
            _record_run(name, "error", str(e))
            _log(traceback.format_exc().splitlines()[-1])
    threading.Thread(target=_wrap, daemon=True).start()


def _tick(get_cfg, runtime):
    cfg = get_cfg()
    sched_cfg = cfg.get("scheduler", {}) or {}
    for name, fn in TASKS.items():
        task_cfg = {**DEFAULT_TASKS[name], **sched_cfg.get(name, {})}
        if not task_cfg.get("enabled"):
            continue
        if _is_due(name, task_cfg["interval_hours"]):
            _log(f"firing: {name}")
            _run_task_async(name, fn, get_cfg, runtime)


def start(get_cfg, runtime, tick_seconds: int = 60):
    """
    Start the scheduler thread.
      get_cfg() -> dict   — current config snapshot
      runtime: {
        "pipeline_jobs": callable() -> dict (the live jobs map),
        "produce_idea":  callable(idea, minutes) -> None,
      }
    """
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _log("scheduler starting")

    def _loop():
        # Stagger the first tick so tasks don't all fire at boot.
        time.sleep(2)
        while not _STOP.is_set():
            try:
                _tick(get_cfg, runtime)
            except Exception as e:
                _log(f"tick error: {e}")
            _STOP.wait(timeout=tick_seconds)
        _log("scheduler stopped")

    _THREAD = threading.Thread(target=_loop, daemon=True)
    _THREAD.start()


def stop():
    _STOP.set()


def trigger_now(name: str, get_cfg, runtime) -> dict:
    """Manually fire a task (button in UI). Returns the run record."""
    if name not in TASKS:
        return {"error": "unknown task"}
    _log(f"manual trigger: {name}")
    _run_task_async(name, TASKS[name], get_cfg, runtime)
    return {"ok": True}
