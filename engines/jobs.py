"""
JobsEngine — SQLite-backed persistence for pipeline jobs.

Stdlib sqlite3, no external deps. Single file at data/jobs.db.

Schema is deliberately small: one row per job, log lines stored
newline-joined inside the row (we don't need indexed log search).
"""

import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = BASE_DIR / "data" / "jobs.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()
_INIT_DONE = False


def _conn():
    c = sqlite3.connect(str(DB_PATH), timeout=10, isolation_level=None)
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA synchronous = NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema():
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _LOCK:
        if _INIT_DONE:
            return
        with _conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id          TEXT PRIMARY KEY,
                    kind        TEXT,
                    title       TEXT,
                    status      TEXT,
                    progress    INTEGER,
                    stage       TEXT,
                    started_at  TEXT,
                    finished_at TEXT,
                    result      TEXT,
                    error       TEXT,
                    log         TEXT,
                    duration_s  INTEGER
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS jobs_started_idx "
                      "ON jobs(started_at DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS jobs_status_idx "
                      "ON jobs(status, started_at DESC)")
        _INIT_DONE = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ════════════════════════════════════════════════════════
#  Public API
# ════════════════════════════════════════════════════════

def upsert_job(
    job_id: str,
    *,
    kind: str | None = None,
    title: str | None = None,
    status: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    result: dict | None = None,
    error: str | None = None,
    duration_s: int | None = None,
) -> None:
    _ensure_schema()
    fields, values = [], []

    def add(name, value):
        if value is None:
            return
        fields.append(name)
        values.append(value)

    add("kind",        kind)
    add("title",       title)
    add("status",      status)
    add("progress",    progress)
    add("stage",       stage)
    add("started_at",  started_at)
    add("finished_at", finished_at)
    add("error",       error)
    add("duration_s",  duration_s)
    if result is not None:
        fields.append("result")
        values.append(json.dumps(result, ensure_ascii=False))

    with _LOCK, _conn() as c:
        # Try update; if no row, insert
        if fields:
            sets = ", ".join(f"{f} = ?" for f in fields)
            row  = c.execute(
                f"UPDATE jobs SET {sets} WHERE id = ?",
                (*values, job_id),
            )
            if row.rowcount == 0:
                cols = ["id"] + fields
                vals = [job_id] + values
                placeholders = ", ".join("?" for _ in cols)
                c.execute(
                    f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
        else:
            c.execute("INSERT OR IGNORE INTO jobs (id) VALUES (?)", (job_id,))


def append_log(job_id: str, line: str) -> None:
    _ensure_schema()
    with _LOCK, _conn() as c:
        row = c.execute("SELECT log FROM jobs WHERE id = ?", (job_id,)).fetchone()
        cur = (row["log"] if row and row["log"] else "")
        # Cap the log to a sane size in DB (last 2000 lines)
        joined = (cur + "\n" + line).lstrip("\n")
        if joined.count("\n") > 2000:
            lines = joined.split("\n")[-2000:]
            joined = "\n".join(lines)
        if row is None:
            c.execute(
                "INSERT INTO jobs (id, log, started_at) VALUES (?, ?, ?)",
                (job_id, joined, _now()),
            )
        else:
            c.execute("UPDATE jobs SET log = ? WHERE id = ?", (joined, job_id))


def get_job(job_id: str) -> dict | None:
    _ensure_schema()
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    out = dict(row)
    if out.get("result"):
        try:
            out["result"] = json.loads(out["result"])
        except Exception:
            pass
    return out


def list_jobs(*, status: str | None = None, kind: str | None = None,
              limit: int = 100) -> list[dict]:
    _ensure_schema()
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    sql = "SELECT id, kind, title, status, progress, stage, started_at, " \
          "finished_at, error, duration_s FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    with _LOCK, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def delete_old(*, keep_recent: int = 200) -> int:
    """Trim the DB to the most recent `keep_recent` jobs."""
    _ensure_schema()
    with _LOCK, _conn() as c:
        c.execute("""
            DELETE FROM jobs WHERE id NOT IN (
                SELECT id FROM jobs ORDER BY started_at DESC LIMIT ?
            )
        """, (keep_recent,))
        return c.execute("SELECT changes()").fetchone()[0]


def mark_orphans_failed():
    """
    On server boot, any job left in 'running' state is from a prior run
    that crashed / was killed. Mark them errored so the UI doesn't show
    stale spinners.
    """
    _ensure_schema()
    with _LOCK, _conn() as c:
        c.execute("""
            UPDATE jobs
               SET status      = 'error',
                   error       = COALESCE(error, 'orphaned by server restart'),
                   finished_at = COALESCE(finished_at, ?)
             WHERE status = 'running'
        """, (_now(),))
