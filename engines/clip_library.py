"""
Persistent local B-roll clip library.

Avoids re-downloading the same Pexels/Pixabay clips across renders.
Index stored at data/clips/index.json; actual files live in data/clips/.

Public API:
  register(clip_id, url, source, local_path, query, duration, width, height)
  find_cached(clip_id) -> Path | None
  search_similar(query_words, exclude_ids, n) -> list[dict]
  prune(keep_n) -> int  — remove oldest entries beyond keep_n
"""

import json
import threading
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR   = Path(__file__).resolve().parent.parent
CLIPS_DIR  = BASE_DIR / "data" / "clips"
INDEX_PATH = CLIPS_DIR / "index.json"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()


def _load() -> list[dict]:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save(items: list[dict]) -> None:
    INDEX_PATH.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def register(
    clip_id: str,
    url: str,
    source: str,
    local_path: Path,
    query: str,
    duration: float,
    width: int,
    height: int,
) -> None:
    """Add a clip to the library index (idempotent on clip_id)."""
    with _LOCK:
        items = _load()
        if any(c["id"] == clip_id for c in items):
            return
        items.append({
            "id":         clip_id,
            "url":        url,
            "source":     source,
            "path":       str(local_path),
            "query":      query,
            "duration":   duration,
            "width":      width,
            "height":     height,
            "added_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        _save(items)


def find_cached(clip_id: str) -> Path | None:
    """Return the local Path if this clip is cached and the file exists."""
    with _LOCK:
        items = _load()
    for c in items:
        if c["id"] == clip_id:
            p = Path(c["path"])
            if p.exists():
                return p
    return None


def search_similar(
    query_words: list[str],
    exclude_ids: set | None = None,
    n: int = 5,
) -> list[dict]:
    """
    Return up to n cached clips whose stored query overlaps with query_words.
    Clips are only returned if their local file still exists.
    """
    exclude_ids = exclude_ids or set()
    q_set = {w.lower() for w in query_words if len(w) > 2}
    with _LOCK:
        items = _load()

    results = []
    for c in items:
        if c["id"] in exclude_ids:
            continue
        if not Path(c["path"]).exists():
            continue
        c_toks = {w.lower() for w in c["query"].split() if len(w) > 2}
        overlap = len(q_set & c_toks)
        if overlap:
            results.append((overlap, c))

    results.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in results[:n]]


def prune(keep_n: int = 500) -> int:
    """Trim the index to the most recent keep_n entries; delete orphaned files."""
    with _LOCK:
        items = _load()
        # Remove entries whose file has disappeared
        items = [c for c in items if Path(c["path"]).exists()]
        removed = 0
        if len(items) > keep_n:
            to_drop = items[:-keep_n]
            for c in to_drop:
                try:
                    Path(c["path"]).unlink(missing_ok=True)
                except OSError:
                    pass
                removed += 1
            items = items[-keep_n:]
        _save(items)
    return removed
