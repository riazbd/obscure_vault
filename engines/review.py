"""
ReviewEngine — LLM-driven performance scorecard for finished videos.

Pulls every artifact already on disk (script, outline, metadata, thumbnail
punchline, tags) plus YouTube metrics if available, then asks the LLM to
rate each component against a channel-aware rubric and return concrete,
actionable suggestions.

Output is structured JSON so the UI can render the scores as bars and the
suggestions as a checklist.
"""

import re
import json
from pathlib import Path

import llm


BASE_DIR  = Path(__file__).resolve().parent.parent
WORKSPACE = BASE_DIR / "workspace"
OUTPUT    = BASE_DIR / "output"


# ════════════════════════════════════════════════════════
#  Data gathering
# ════════════════════════════════════════════════════════

def _load_artifacts(video_filename: str) -> dict:
    """Pull every artefact a finished render leaves behind."""
    src_stem  = Path(video_filename).stem
    workspace = WORKSPACE / src_stem
    script    = ""
    outline   = None
    meta      = {}

    sp = workspace / "script.txt"
    if sp.exists():
        script = sp.read_text(encoding="utf-8", errors="ignore")

    mp = workspace / "metadata.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text())
        except Exception:
            meta = {}

    op = workspace / "outline.json"
    if op.exists():
        try:
            outline = json.loads(op.read_text())
        except Exception:
            outline = None

    return {
        "stem":      src_stem,
        "workspace": str(workspace),
        "script":    script,
        "outline":   outline,
        "metadata":  meta,
    }


def _hook(script: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (script or "").strip())
    return " ".join(parts[:2])[:400] if parts else ""


def _outline_summary(outline: dict | None) -> str:
    if not outline or not isinstance(outline, dict):
        return "(no outline available)"
    acts = outline.get("acts", []) or []
    parts = []
    for a in acts:
        parts.append(f"Act {a.get('id','?')}: {a.get('label','')} "
                     f"— {a.get('summary','')[:140]}")
    return "\n".join(parts) or "(no acts)"


def _video_metrics(stem: str) -> dict | None:
    """Find this video in the analytics store by title match."""
    try:
        from engines import analytics
    except Exception:
        return None
    uploads = analytics.list_uploads()
    metrics = analytics.list_metrics().get("by_video", {})
    for u in uploads:
        # Workspace stems are timestamp-prefixed slugs; the YouTube title
        # is the human title we tagged at upload. Best-effort match by
        # lowercased substring on the slug.
        title = (u.get("title") or "").lower()
        if title and (title in stem.lower() or stem.lower() in title):
            return metrics.get(u["video_id"])
    return None


def _channel_baseline() -> dict | None:
    try:
        from engines import analytics
    except Exception:
        return None
    sigs = analytics.compute_token_signals()
    return sigs.get("channel_avg")


# ════════════════════════════════════════════════════════
#  LLM scorecard
# ════════════════════════════════════════════════════════

def review(api_key: str, video_filename: str, on_log=None) -> dict:
    log = on_log or (lambda m: None)
    log(f"🔬 reviewing {video_filename}")

    a       = _load_artifacts(video_filename)
    metrics = _video_metrics(a["stem"])
    base    = _channel_baseline()

    title       = (a["metadata"].get("title") or "").strip() or a["stem"]
    description = a["metadata"].get("description", "")
    tags        = a["metadata"].get("tags", []) or []
    punchline   = a["metadata"].get("thumbnail_punchline", "")
    word_count  = len((a["script"] or "").split())
    hook        = _hook(a["script"])
    outline_sum = _outline_summary(a["outline"])

    metrics_block = "(not yet uploaded or metrics not refreshed)"
    if metrics:
        metrics_block = (
            f"views: {metrics.get('views', 0):,}\n"
            f"impressions: {metrics.get('impressions', 0):,}\n"
            f"CTR: {metrics.get('ctr', 0):.2f}%\n"
            f"avg view percent (AVD): {metrics.get('avg_view_percent', 0):.1f}%\n"
            f"subs gained: {metrics.get('subs_gained', 0)}"
        )

    baseline_block = "(no channel baseline yet)"
    if base:
        baseline_block = (
            f"channel avg CTR: {base.get('ctr', 0):.2f}%\n"
            f"channel avg AVD: {base.get('avg_view_percent', 0):.1f}%\n"
            f"channel avg views/day: {base.get('views_per_day', 0):.1f}"
        )

    prompt = f"""
You are a senior YouTube content strategist reviewing one video for the
Obscura Vault channel (buried/dark/forgotten history).

VIDEO TITLE: {title}

THUMBNAIL PUNCHLINE: {punchline or '(none)'}

OPENING HOOK (first 2 sentences):
\"\"\"
{hook or '(missing)'}
\"\"\"

ACT STRUCTURE:
{outline_sum}

DESCRIPTION (first 600 chars):
\"\"\"
{description[:600]}
\"\"\"

TAGS ({len(tags)}): {", ".join(tags[:15])}

SCRIPT WORD COUNT: {word_count}

YOUTUBE METRICS:
{metrics_block}

CHANNEL BASELINE:
{baseline_block}

Rate each dimension 0-10 (0 = bad, 10 = excellent) and give one short reason.
Then list the 3 highest-impact concrete improvements for the next video.

Return JSON ONLY:
{{
  "scores": {{
    "title":        {{"score": 0, "reason": "..."}},
    "thumbnail":    {{"score": 0, "reason": "..."}},
    "hook":         {{"score": 0, "reason": "..."}},
    "structure":    {{"score": 0, "reason": "..."}},
    "description":  {{"score": 0, "reason": "..."}},
    "tags":         {{"score": 0, "reason": "..."}}
  }},
  "overall": {{"score": 0, "verdict": "one short sentence"}},
  "actionable_improvements": [
    "specific, concrete change to try in the next video",
    "...",
    "..."
  ]
}}
""".strip()

    msgs = [
        {"role": "system", "content":
            "You are a YouTube content strategist. Output ONLY valid JSON."},
        {"role": "user", "content": prompt},
    ]
    res = llm.call(api_key, msgs, json_mode=True,
                   temperature=0.3, max_tokens=2000)
    data = res["json"] or {}

    # Guarantee shape so the UI doesn't blow up on partial responses.
    scores  = data.get("scores", {}) or {}
    for dim in ("title", "thumbnail", "hook", "structure",
                "description", "tags"):
        s = scores.get(dim) or {}
        scores[dim] = {
            "score":  int(s.get("score", 0) or 0),
            "reason": str(s.get("reason", ""))[:280],
        }
    overall = data.get("overall") or {}
    overall = {
        "score":   int(overall.get("score", 0) or 0),
        "verdict": str(overall.get("verdict", ""))[:280],
    }
    improvements = [
        str(x)[:300] for x in (data.get("actionable_improvements") or [])
        if isinstance(x, str)
    ][:5]

    log(f"   ✅ overall {overall['score']}/10 via {res['model']}")

    return {
        "video_filename": video_filename,
        "stem":           a["stem"],
        "title":          title,
        "scores":         scores,
        "overall":        overall,
        "actionable_improvements": improvements,
        "metrics_present": metrics is not None,
        "model":           res["model"],
    }
