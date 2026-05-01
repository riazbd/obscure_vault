"""
AnalyticsEngine — pull YouTube performance, learn token-level signals,
feed them back into idea scoring.

Two data sources (both free, both via the existing OAuth token):
  - YouTube Data API   → viewCount, likeCount, commentCount
  - YouTube Analytics  → estimatedMinutesWatched, averageViewDuration,
                          averageViewPercentage, subscribersGained,
                          impressions, impressionClickThroughRate (CTR)

Persistence:
  data/uploads.json   — append-only record of every video this system
                        publishes (video_id, title, tags, idea_id)
  data/metrics.json   — last-refreshed metrics keyed by video_id

Heavy deps (google-api-python-client, google-auth) are lazy-imported so
this module can be imported without them.
"""

import re
import json
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE_DIR     = Path(__file__).resolve().parent.parent
DATA_DIR     = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_PATH = DATA_DIR / "uploads.json"
METRICS_PATH = DATA_DIR / "metrics.json"

_LOCK = threading.Lock()


# ════════════════════════════════════════════════════════
#  Upload registry
# ════════════════════════════════════════════════════════

def _load_uploads() -> list[dict]:
    if not UPLOADS_PATH.exists():
        return []
    try:
        return json.loads(UPLOADS_PATH.read_text())
    except Exception:
        return []


def _save_uploads(items: list[dict]):
    UPLOADS_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False))


def record_upload(video_id: str, title: str, tags: list[str] | None,
                  idea_id: str | None = None) -> None:
    """Idempotently log a new upload."""
    if not video_id:
        return
    with _LOCK:
        items = _load_uploads()
        if any(it.get("video_id") == video_id for it in items):
            return
        items.append({
            "video_id":    video_id,
            "title":       title,
            "tags":        tags or [],
            "idea_id":     idea_id,
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        _save_uploads(items)


def list_uploads() -> list[dict]:
    with _LOCK:
        return _load_uploads()


# ════════════════════════════════════════════════════════
#  Metrics persistence + freshness
# ════════════════════════════════════════════════════════

def _load_metrics() -> dict:
    if not METRICS_PATH.exists():
        return {"by_video": {}, "refreshed_at": None}
    try:
        return json.loads(METRICS_PATH.read_text())
    except Exception:
        return {"by_video": {}, "refreshed_at": None}


def _save_metrics(blob: dict):
    METRICS_PATH.write_text(json.dumps(blob, indent=2, ensure_ascii=False))


def list_metrics() -> dict:
    with _LOCK:
        return _load_metrics()


# ════════════════════════════════════════════════════════
#  YouTube fetch (lazy imports — only when refreshing)
# ════════════════════════════════════════════════════════

def _build_youtube_data():
    from googleapiclient.discovery import build
    from engines import upload as up
    return build("youtube", "v3", credentials=up._load_creds(),
                 cache_discovery=False)


def _build_youtube_analytics():
    from googleapiclient.discovery import build
    from engines import upload as up
    return build("youtubeAnalytics", "v2", credentials=up._load_creds(),
                 cache_discovery=False)


def _fetch_data_stats(video_ids: list[str]) -> dict[str, dict]:
    """Batched videos.list — 50 ids per call."""
    yt = _build_youtube_data()
    out = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = yt.videos().list(
            id=",".join(batch),
            part="snippet,statistics,contentDetails",
        ).execute()
        for it in resp.get("items", []):
            stats = it.get("statistics", {})
            out[it["id"]] = {
                "title":          it["snippet"].get("title"),
                "published_at":   it["snippet"].get("publishedAt"),
                "duration_iso":   it.get("contentDetails", {}).get("duration"),
                "views":          int(stats.get("viewCount", 0)),
                "likes":          int(stats.get("likeCount", 0)),
                "comments":       int(stats.get("commentCount", 0)),
            }
    return out


def _fetch_analytics(video_id: str, published_at: str | None) -> dict:
    """Per-video Analytics report. Returns metrics dict (zeros if N/A)."""
    ya = _build_youtube_analytics()
    end = datetime.now(timezone.utc).date().isoformat()
    if published_at:
        try:
            start = datetime.fromisoformat(published_at.replace("Z", "+00:00")).date().isoformat()
        except Exception:
            start = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
    else:
        start = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()

    try:
        r = ya.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics=("views,estimatedMinutesWatched,averageViewDuration,"
                     "averageViewPercentage,subscribersGained,"
                     "impressions,impressionClickThroughRate"),
            filters=f"video=={video_id}",
        ).execute()
    except Exception as e:
        return {"error": str(e)}

    headers = [c["name"] for c in r.get("columnHeaders", [])]
    rows    = r.get("rows", [])
    if not rows:
        return {"views": 0, "minutes_watched": 0, "avg_view_seconds": 0,
                "avg_view_percent": 0, "subs_gained": 0,
                "impressions": 0, "ctr": 0}
    row = rows[0]
    pick = lambda k: (row[headers.index(k)] if k in headers else 0) or 0
    return {
        "views":            int(pick("views")),
        "minutes_watched":  float(pick("estimatedMinutesWatched")),
        "avg_view_seconds": float(pick("averageViewDuration")),
        "avg_view_percent": float(pick("averageViewPercentage")),
        "subs_gained":      int(pick("subscribersGained")),
        "impressions":      int(pick("impressions")),
        "ctr":              float(pick("impressionClickThroughRate")),  # already a percentage
    }


def refresh_metrics(on_log=None) -> dict:
    """
    Pull fresh metrics for every recorded upload. Returns:
      {refreshed: int, total: int, errors: int}
    """
    log = on_log or (lambda m: None)
    from engines import upload as up

    if not (up.is_installed() and up.has_token()):
        raise RuntimeError("YouTube not authorized — connect in Settings first.")

    uploads = list_uploads()
    if not uploads:
        log("no recorded uploads — nothing to refresh")
        return {"refreshed": 0, "total": 0, "errors": 0}

    ids   = [u["video_id"] for u in uploads if u.get("video_id")]
    log(f"📊 fetching basic stats for {len(ids)} videos...")
    data_stats = _fetch_data_stats(ids)

    out      = {"by_video": {}, "refreshed_at":
                datetime.now(timezone.utc).isoformat(timespec="seconds")}
    errors   = 0

    for vid in ids:
        d = data_stats.get(vid, {})
        log(f"   📈 analytics for {vid} ({d.get('title','?')[:50]})...")
        a = _fetch_analytics(vid, d.get("published_at"))
        if "error" in a:
            errors += 1
            log(f"      ⚠️  {a['error']}")
        out["by_video"][vid] = {**d, **{k: v for k, v in a.items() if k != "error"}}

    with _LOCK:
        _save_metrics(out)

    log(f"   ✅ refreshed {len(ids) - errors}/{len(ids)} (errors={errors})")
    return {"refreshed": len(ids) - errors, "total": len(ids), "errors": errors}


# ════════════════════════════════════════════════════════
#  Token-level performance signals
# ════════════════════════════════════════════════════════

_STOPWORDS = {"the","a","an","of","and","in","on","at","to","for","with",
              "is","was","were","what","why","how","that","this","these",
              "those","but","or","by","from","be","been","being",
              "their","they","them","its","not","no","yes"}


def _tokens(s: str) -> set[str]:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return {w for w in s.split() if len(w) > 2 and w not in _STOPWORDS}


def compute_token_signals() -> dict:
    """
    For every token that ever appeared in a produced video, compute the
    average view-velocity and CTR. Then derive a per-token multiplier
    relative to the channel mean. Returns:
      {
        "channel_avg": {views_per_day, ctr, avg_view_percent},
        "tokens": {tok: {samples, multiplier}}  # multiplier in roughly [0.5, 1.6]
      }
    """
    blob    = list_metrics()
    by_vid  = blob.get("by_video", {})
    uploads = list_uploads()
    if not by_vid:
        return {"channel_avg": None, "tokens": {}}

    # Collect (tokens, views_per_day, ctr, avg_view_percent) per video
    samples = []
    for u in uploads:
        m = by_vid.get(u["video_id"])
        if not m:
            continue
        try:
            published = datetime.fromisoformat(
                m.get("published_at", "").replace("Z", "+00:00"))
            age_days = max(1.0, (datetime.now(timezone.utc) - published).total_seconds() / 86400)
        except Exception:
            age_days = 30.0
        views_pd = (m.get("views", 0) or 0) / age_days
        ctr      = m.get("ctr", 0) or 0       # already a percentage 0-100
        avp      = m.get("avg_view_percent", 0) or 0
        toks     = _tokens(u.get("title", "")) | _tokens(" ".join(u.get("tags", [])))
        samples.append({
            "tokens":   toks,
            "views_pd": views_pd,
            "ctr":      ctr,
            "avp":      avp,
        })

    if not samples:
        return {"channel_avg": None, "tokens": {}}

    chan_views_pd = sum(s["views_pd"] for s in samples) / len(samples)
    chan_ctr      = sum(s["ctr"]      for s in samples) / len(samples)
    chan_avp      = sum(s["avp"]      for s in samples) / len(samples)

    # Per-token aggregates
    bucket = {}
    for s in samples:
        for t in s["tokens"]:
            b = bucket.setdefault(t, {"v": [], "c": [], "a": []})
            b["v"].append(s["views_pd"])
            b["c"].append(s["ctr"])
            b["a"].append(s["avp"])

    tokens = {}
    for t, b in bucket.items():
        n = len(b["v"])
        if n < 1:
            continue
        v_ratio = (sum(b["v"]) / n) / max(chan_views_pd, 0.001)
        c_ratio = (sum(b["c"]) / n) / max(chan_ctr,      0.001)
        a_ratio = (sum(b["a"]) / n) / max(chan_avp,      0.001)
        # Weighted blend: views, CTR, retention all matter
        raw = 0.45 * v_ratio + 0.35 * c_ratio + 0.20 * a_ratio
        # Confidence shrinkage: with 1 sample, pull 60 % toward 1.0
        confidence = min(1.0, n / 4.0)
        multiplier = 1.0 + (raw - 1.0) * confidence
        # Clamp to reasonable band
        multiplier = max(0.5, min(1.6, multiplier))
        tokens[t] = {"samples": n, "multiplier": round(multiplier, 3)}

    return {
        "channel_avg": {
            "views_per_day":    round(chan_views_pd, 2),
            "ctr":              round(chan_ctr, 2),
            "avg_view_percent": round(chan_avp, 2),
        },
        "tokens": tokens,
    }


def predict_score_for_idea(title: str, tags: list[str] | None,
                           signals: dict | None = None) -> float:
    """
    Returns a multiplier in [0.5, 1.6] reflecting predicted performance
    based on token overlap with past channel data. 1.0 = no signal.
    """
    if signals is None:
        signals = compute_token_signals()
    tok_signals = signals.get("tokens", {})
    if not tok_signals:
        return 1.0

    toks = _tokens(title) | _tokens(" ".join(tags or []))
    matches = [tok_signals[t] for t in toks if t in tok_signals]
    if not matches:
        return 1.0

    # Confidence-weighted average of token multipliers
    total_w = sum(m["samples"] for m in matches)
    blend   = sum(m["multiplier"] * m["samples"] for m in matches) / max(total_w, 1)
    return round(max(0.5, min(1.6, blend)), 3)
