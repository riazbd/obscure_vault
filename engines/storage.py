"""
StorageEngine — disk usage reporting + cleanup tasks.

T480 has ~200 GB usable. After ~50 renders the SSD fills if nothing
prunes. This module exposes:
  - usage(): current footprint of every relevant directory
  - cleanup_workspace(job_name): drop heavy intermediates, keep
    small text artefacts
  - enforce_output_cap(max_gb): roll the output/ directory to a
    hard ceiling, deleting oldest MP4s + their thumbnails + .srt
  - cleanup_all_workspaces(): scan all workspaces, prune anything
    older than N days that's already been uploaded or has no
    matching MP4 in output/
"""

import os
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE_DIR     = Path(__file__).resolve().parent.parent
WORKSPACE    = BASE_DIR / "workspace"
OUTPUT       = BASE_DIR / "output"
DATA_DIR     = BASE_DIR / "data"

# Files inside each workspace/<job>/ that are tiny + useful for review
KEEP_IN_WS = {"script.txt", "metadata.json", "description.txt",
              "outline.json", "captions.srt"}


# ════════════════════════════════════════════════════════
#  Sizing helpers
# ════════════════════════════════════════════════════════

def _du(path: Path) -> int:
    """Recursive byte size using os.scandir (avoids rglob on large trees)."""
    if not path.exists():
        return 0
    total = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat().st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _mb(b: int) -> int:
    return int(b / (1024 * 1024))


def usage() -> dict:
    """Return per-directory MB + free / total disk."""
    workspace_b = _du(WORKSPACE)
    output_b    = _du(OUTPUT)
    cache_b     = _du(DATA_DIR / "cache")
    branding_b  = _du(DATA_DIR / "branding")
    try:
        du = shutil.disk_usage(BASE_DIR)
        free_mb  = _mb(du.free)
        total_mb = _mb(du.total)
    except OSError:
        free_mb = total_mb = 0

    used_by_app = workspace_b + output_b + cache_b + branding_b
    return {
        "workspace_mb": _mb(workspace_b),
        "output_mb":    _mb(output_b),
        "cache_mb":     _mb(cache_b),
        "branding_mb":  _mb(branding_b),
        "app_total_mb": _mb(used_by_app),
        "disk_free_mb": free_mb,
        "disk_total_mb": total_mb,
    }


# ════════════════════════════════════════════════════════
#  Workspace cleanup (called after each successful render)
# ════════════════════════════════════════════════════════

def cleanup_workspace(job_name: str) -> dict:
    """
    Delete every subdirectory inside workspace/<job_name>/ (processed,
    footage, etc.) and any non-keepable file. Returns:
      {ok, freed_mb, kept_files}
    """
    ws = WORKSPACE / job_name
    if not ws.exists() or not ws.is_dir():
        return {"ok": False, "freed_mb": 0, "kept_files": 0}

    freed = 0
    kept  = 0
    for child in ws.iterdir():
        try:
            if child.is_dir():
                size = _du(child)
                shutil.rmtree(child, ignore_errors=True)
                freed += size
            elif child.is_file():
                if child.name in KEEP_IN_WS:
                    kept += 1
                else:
                    sz = child.stat().st_size
                    child.unlink(missing_ok=True)
                    freed += sz
        except OSError:
            continue

    return {"ok": True, "freed_mb": _mb(freed), "kept_files": kept}


def cleanup_all_workspaces(*, older_than_days: int = 7) -> dict:
    """Aggressively prune intermediates from every workspace older than N days."""
    if not WORKSPACE.exists():
        return {"workspaces_cleaned": 0, "freed_mb": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    cleaned, freed_total = 0, 0
    for ws in WORKSPACE.iterdir():
        if not ws.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(ws.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime > cutoff:
            continue
        before = _du(ws)
        cleanup_workspace(ws.name)
        after = _du(ws)
        if before > after:
            cleaned += 1
            freed_total += (before - after)
    return {"workspaces_cleaned": cleaned, "freed_mb": _mb(freed_total)}


# ════════════════════════════════════════════════════════
#  Output cap enforcement
# ════════════════════════════════════════════════════════

def _uploaded_filenames() -> set[str]:
    """Return the set of local filenames that have been uploaded to YouTube."""
    try:
        uploads_path = DATA_DIR / "uploads.json"
        if not uploads_path.exists():
            return set()
        data = json.loads(uploads_path.read_text())
        return {u["local_filename"] for u in data if u.get("local_filename")}
    except Exception:
        return set()


def enforce_output_cap(max_gb: float = 30.0) -> dict:
    """
    Drop oldest MP4s + their sibling thumbnails + .srt + workspace
    folders until total output dir size is under max_gb.
    Skips videos that have not been uploaded to YouTube yet.
    """
    if not OUTPUT.exists():
        return {"kept": 0, "deleted": 0, "freed_mb": 0, "current_mb": 0}

    uploaded = _uploaded_filenames()
    cap = int(max_gb * 1024 * 1024 * 1024)
    items = sorted(OUTPUT.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in items)
    deleted, freed, skipped = 0, 0, 0

    while total > cap and items:
        p = items.pop(0)
        if p.name not in uploaded:
            skipped += 1
            continue  # not yet uploaded — protect it
        siblings = [
            p,
            OUTPUT / p.name.replace(".mp4", "_thumbnail.jpg"),
            OUTPUT / p.name.replace(".mp4", ".srt"),
        ]
        for f in siblings:
            try:
                if f.exists() and f.is_file():
                    sz = f.stat().st_size
                    f.unlink()
                    freed += sz
                    if f.suffix == ".mp4":
                        total -= sz
            except OSError:
                continue
        # Also drop the workspace folder for that job
        ws = WORKSPACE / p.stem
        if ws.exists() and ws.is_dir():
            freed += _du(ws)
            shutil.rmtree(ws, ignore_errors=True)
        deleted += 1

    return {
        "kept":       len(items),
        "deleted":    deleted,
        "skipped":    skipped,
        "freed_mb":   _mb(freed),
        "current_mb": _mb(total),
    }


def estimate_freeable() -> dict:
    """How much you'd reclaim if you ran cleanup_all_workspaces now."""
    if not WORKSPACE.exists():
        return {"freeable_mb": 0, "candidate_workspaces": 0}
    cand, freeable = 0, 0
    for ws in WORKSPACE.iterdir():
        if not ws.is_dir():
            continue
        for sub in ws.iterdir():
            if sub.is_dir():     # processed/, footage/
                cand += 1
                freeable += _du(sub)
                break
    return {"freeable_mb": _mb(freeable), "candidate_workspaces": cand}
