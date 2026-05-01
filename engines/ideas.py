"""
IdeaEngine — harvest, dedup, score, and persist video ideas.

Sources (all free, no keys):
  - YouTube search-suggest (https://suggestqueries.google.com)
  - Reddit JSON listings (no auth, just User-Agent)
  - Wikipedia random / on-this-day (REST API)

Persistence: data/ideas.json (single-channel for now).
Dedup: token Jaccard similarity vs. all existing ideas.
Scoring: LLM rubric (one batched call) for niche fit + novelty heuristic.
"""

import re
import json
import time
import hashlib
import threading
from pathlib import Path
from datetime import datetime, timezone

import requests

import llm


BASE_DIR  = Path(__file__).resolve().parent.parent
DATA_DIR  = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
IDEAS_PATH = DATA_DIR / "ideas.json"

UA = ("Mozilla/5.0 (compatible; ObscuraVault/1.0; "
      "+https://github.com/riazbd/obscure_vault)")

DEFAULT_NICHE = (
    "Obscura Vault — buried, suppressed, and forgotten history. "
    "Cold war, ancient mysteries, declassified events, mysterious "
    "disappearances, lost civilizations, dark documentaries."
)

DEFAULT_YT_SEEDS = [
    "lost history", "declassified", "soviet mystery",
    "buried truth", "untold history", "ancient mystery",
    "cold war secret", "unsolved disappearance",
]

DEFAULT_SUBREDDITS = [
    "AskHistorians", "UnresolvedMysteries", "ColdWar",
    "HistoryAnecdotes", "MilitaryHistory", "Mysterious_Earth",
]

_LOCK = threading.Lock()   # guard concurrent reads/writes of ideas.json


# ════════════════════════════════════════════════════════
#  Persistence
# ════════════════════════════════════════════════════════

def _load() -> list[dict]:
    if not IDEAS_PATH.exists():
        return []
    try:
        return json.loads(IDEAS_PATH.read_text())
    except Exception:
        return []


def _save(ideas: list[dict]):
    IDEAS_PATH.write_text(json.dumps(ideas, indent=2, ensure_ascii=False))


def list_all() -> list[dict]:
    with _LOCK:
        return _load()


def update_status(idea_id: str, status: str, **patch) -> dict | None:
    with _LOCK:
        ideas = _load()
        for it in ideas:
            if it["id"] == idea_id:
                it["status"] = status
                it.update(patch)
                _save(ideas)
                return it
    return None


def delete(idea_id: str) -> bool:
    with _LOCK:
        ideas = _load()
        kept  = [it for it in ideas if it["id"] != idea_id]
        if len(kept) == len(ideas):
            return False
        _save(kept)
        return True


# ════════════════════════════════════════════════════════
#  Normalization + dedup
# ════════════════════════════════════════════════════════

def _normalize(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _tokens(title: str) -> set[str]:
    stop = {"the","a","an","of","and","in","on","at","to","for","with",
            "is","was","were","what","why","how","that","this","these",
            "those","but","or","by","from","be","been","being"}
    return {w for w in _normalize(title).split() if len(w) > 2 and w not in stop}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _id_for(title: str) -> str:
    return hashlib.sha256(_normalize(title).encode()).hexdigest()[:16]


def _is_duplicate(title: str, existing_token_sets: list[tuple[str, set]],
                  threshold: float = 0.55) -> bool:
    new_tokens = _tokens(title)
    if len(new_tokens) < 2:
        return True   # too generic
    for tid, toks in existing_token_sets:
        if _jaccard(new_tokens, toks) >= threshold:
            return True
    return False


# ════════════════════════════════════════════════════════
#  Harvesters
# ════════════════════════════════════════════════════════

def harvest_youtube_suggest(seeds: list[str], on_log=None) -> list[dict]:
    """Hit youtube search-suggest, then expand each term by appending letters."""
    log = on_log or (lambda m: None)
    out = []

    def fetch(q: str) -> list[str]:
        try:
            r = requests.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "youtube", "ds": "yt", "q": q},
                headers={"User-Agent": UA},
                timeout=10,
            )
            if r.status_code != 200:
                return []
            # Response is JSONP-ish: window.google.ac.h(["q",[["sugg1",..],..]])
            text = r.text.strip()
            # Extract the array
            m = re.search(r"\[(.+)\]\s*\)?\s*$", text, re.S)
            if not m:
                return []
            try:
                data = json.loads("[" + m.group(1) + "]")
            except Exception:
                return []
            # data shape: [query, [[sugg, ...], [sugg, ...], ...], {...}]
            sugg_list = data[1] if len(data) > 1 else []
            return [s[0] for s in sugg_list if isinstance(s, list) and s]
        except requests.RequestException:
            return []

    for seed in seeds:
        suggestions = fetch(seed)
        log(f"   yt-suggest '{seed}' → {len(suggestions)}")
        for s in suggestions:
            out.append({"title": s, "source": "yt_suggest", "source_url": ""})

        # Expand: " a" .. " z" — gives us long-tails
        for letter in "abcdefghij":
            for s in fetch(f"{seed} {letter}"):
                out.append({"title": s, "source": "yt_suggest", "source_url": ""})

    return out


def harvest_reddit(subs: list[str], on_log=None) -> list[dict]:
    log = on_log or (lambda m: None)
    out = []
    for sub in subs:
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/hot.json",
                params={"limit": 30},
                headers={"User-Agent": UA},
                timeout=12,
            )
            if r.status_code != 200:
                log(f"   reddit r/{sub} HTTP {r.status_code}")
                continue
            posts = r.json().get("data", {}).get("children", [])
            log(f"   reddit r/{sub} → {len(posts)}")
            for p in posts:
                d = p.get("data", {})
                title = d.get("title", "").strip()
                if not title or len(title) < 12:
                    continue
                out.append({
                    "title":      title,
                    "source":     "reddit",
                    "source_url": f"https://reddit.com{d.get('permalink','')}",
                })
        except requests.RequestException as e:
            log(f"   reddit r/{sub} error: {e}")
    return out


def harvest_wikipedia(n: int = 12, on_log=None) -> list[dict]:
    log = on_log or (lambda m: None)
    out = []

    # On-this-day: events, deaths, selected
    today = datetime.utcnow()
    try:
        r = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/all/"
            f"{today.month:02d}/{today.day:02d}",
            headers={"User-Agent": UA},
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            for bucket in ("events", "selected", "deaths"):
                for item in data.get(bucket, [])[:8]:
                    text = item.get("text", "").strip()
                    if not text or len(text) < 30:
                        continue
                    pages = item.get("pages", [])
                    url = pages[0].get("content_urls", {}).get("desktop", {}).get("page", "") if pages else ""
                    out.append({
                        "title":      f"{text[:140]}",
                        "source":     f"wikipedia_{bucket}",
                        "source_url": url,
                    })
        log(f"   wikipedia on-this-day → {len(out)}")
    except requests.RequestException as e:
        log(f"   wikipedia error: {e}")

    return out


# ════════════════════════════════════════════════════════
#  Filtering + scoring
# ════════════════════════════════════════════════════════

def _filter_obviously_bad(items: list[dict]) -> list[dict]:
    bad = re.compile(
        r"\b(porn|nsfw|trailer|reaction|tier list|ranking|reddit "
        r"thread|original poster|aita|am i the asshole|amitheasshole)\b",
        re.I,
    )
    out = []
    for it in items:
        title = it["title"]
        if len(title) < 14 or len(title) > 220:
            continue
        if bad.search(title):
            continue
        out.append(it)
    return out


def score_with_llm(api_key: str, items: list[dict],
                   niche: str = DEFAULT_NICHE,
                   on_log=None) -> dict[str, dict]:
    """
    One batched LLM call. Scores each id on niche_fit and gives one-line
    rationale. Returns: {idea_id: {niche_fit, rationale}}.
    """
    log = on_log or (lambda m: None)
    if not items:
        return {}

    # Cap batch size to keep prompts in reasonable bounds.
    batch_size = 25
    out = {}

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        log(f"   scoring batch {i//batch_size + 1} ({len(batch)} items)...")
        msgs = [
            {"role": "system", "content":
                "You score video ideas for niche fit. Output ONLY valid JSON."},
            {"role": "user", "content": f"""
Channel niche:
{niche}

Score each idea on:
  - niche_fit: 0.0 to 1.0 (1.0 = perfect for this channel; 0.0 = totally off)

Reject hard if:
  - News-like / current-affairs (lasts < 1 month relevance)
  - Generic top-N listicle without a clear story angle
  - Self-promotional, AI tooling, or technology reviews

Ideas:
{json.dumps([{"id": it["id"], "title": it["title"]} for it in batch], indent=2, ensure_ascii=False)}

Return JSON:
{{
  "scores": [
    {{"id": "abc...", "niche_fit": 0.78, "rationale": "one short sentence"}}
  ]
}}
""".strip()}]

        try:
            res = llm.call(api_key, msgs, json_mode=True,
                           temperature=0.4, max_tokens=2500)
            for s in (res["json"] or {}).get("scores", []):
                if "id" in s:
                    out[s["id"]] = {
                        "niche_fit": float(s.get("niche_fit", 0) or 0),
                        "rationale": s.get("rationale", "").strip(),
                    }
        except Exception as e:
            log(f"   ⚠️  scoring batch failed: {e}")

    return out


# ════════════════════════════════════════════════════════
#  Top-level: harvest + score + persist
# ════════════════════════════════════════════════════════

def run_harvest(
    *,
    yt_seeds: list[str] = None,
    subreddits: list[str] = None,
    include_wikipedia: bool = True,
    score_with_openrouter_key: str = "",
    niche: str = DEFAULT_NICHE,
    novelty_threshold: float = 0.55,
    keep_top: int = 60,
    on_log=None,
) -> dict:
    log = on_log or (lambda m: None)

    yt_seeds   = yt_seeds   or DEFAULT_YT_SEEDS
    subreddits = subreddits or DEFAULT_SUBREDDITS

    log("🌾 harvesting...")
    raw = []
    raw += harvest_youtube_suggest(yt_seeds, on_log=log)
    raw += harvest_reddit(subreddits, on_log=log)
    if include_wikipedia:
        raw += harvest_wikipedia(on_log=log)

    log(f"   harvested {len(raw)} raw")
    raw = _filter_obviously_bad(raw)
    log(f"   {len(raw)} after junk filter")

    # Build existing token sets for dedup
    with _LOCK:
        existing = _load()
    existing_tok = [(it["id"], _tokens(it["title"])) for it in existing]

    # Dedup against existing AND against this batch
    seen_ids = set(it["id"] for it in existing)
    fresh = []
    seen_tok: list[tuple[str, set]] = list(existing_tok)
    for it in raw:
        title = it["title"].strip()
        idea_id = _id_for(title)
        if idea_id in seen_ids:
            continue
        if _is_duplicate(title, seen_tok, threshold=novelty_threshold):
            continue
        seen_ids.add(idea_id)
        new_tok = _tokens(title)
        seen_tok.append((idea_id, new_tok))
        fresh.append({
            "id":           idea_id,
            "title":        title,
            "source":       it["source"],
            "source_url":   it.get("source_url", ""),
            "harvested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status":       "pending",
            "niche_fit":    None,
            "rationale":    "",
        })

    log(f"   {len(fresh)} fresh ideas after dedup")

    # Score with LLM if key provided
    if score_with_openrouter_key and fresh:
        log("🎯 scoring with LLM...")
        scored = score_with_llm(score_with_openrouter_key, fresh, niche=niche,
                                on_log=log)
        for it in fresh:
            s = scored.get(it["id"])
            if s:
                it["niche_fit"] = s["niche_fit"]
                it["rationale"] = s["rationale"]
        # Cull obvious off-niche ideas (< 0.35 fit) before persisting,
        # but only when the LLM actually produced a score.
        fresh = [it for it in fresh
                 if it["niche_fit"] is None or it["niche_fit"] >= 0.35]
        log(f"   {len(fresh)} survived niche-fit cull")

    # Apply analytics-derived performance signals (zero-effect if no
    # uploads have been tracked yet).
    try:
        from engines import analytics as _an
        signals = _an.compute_token_signals()
        if signals.get("tokens"):
            log(f"📊 applying signals from {len(signals['tokens'])} tokens...")
            for it in fresh:
                mult = _an.predict_score_for_idea(
                    it["title"], [], signals=signals)
                it["perf_multiplier"] = mult
                if it.get("niche_fit") is not None:
                    it["ranked_score"] = round(it["niche_fit"] * mult, 3)
                else:
                    it["ranked_score"] = mult
    except Exception as e:
        log(f"   ⚠️  signal apply skipped: {e}")

    # Sort by ranked_score (or niche_fit if no signals) desc; cap at keep_top
    def _rank(it):
        return it.get("ranked_score") or it.get("niche_fit") or 0
    fresh.sort(key=_rank, reverse=True)
    fresh = fresh[:keep_top]

    with _LOCK:
        all_ideas = _load()
        all_ideas.extend(fresh)
        # Sort the merged list by status (pending first), then niche_fit desc
        order_status = {"pending": 0, "approved": 1, "produced": 2,
                        "rejected": 3}
        all_ideas.sort(key=lambda it: (
            order_status.get(it.get("status", "pending"), 9),
            -(it.get("niche_fit") or 0),
        ))
        # Hard cap total stored ideas to avoid unbounded growth
        if len(all_ideas) > 500:
            all_ideas = all_ideas[:500]
        _save(all_ideas)

    return {
        "added":      len(fresh),
        "total":      len(all_ideas),
        "top_sample": fresh[:5],
    }
