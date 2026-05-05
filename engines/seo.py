"""
SEOEngine — generate YouTube title, description, tags, and chapters.

Strategy:
  - Title: 12 candidates → score on rubric → pick top 3 (1 primary, 2 A/B)
  - Description: hook (first 150 chars) → 2-3 keyword-rich paragraphs →
                 timestamps from outline → CTA → hashtags
  - Tags: primary keyword + entity tags + long-tails (≤500 char total)
  - Chapters: derived from outline act labels with cumulative timestamps
"""

import re

import llm


CHANNEL_TAGLINE = "History They Buried. We Dig It Up."
CHANNEL_NAME    = "Obscura Vault"

DEFAULT_HASHTAGS = ["#ObscuraVault", "#HiddenHistory", "#DarkHistory"]


def _title_score(t: str) -> float:
    """Heuristic 0-1 — favors 50-65 chars, contains a colon or em-dash, no all-caps."""
    L = len(t)
    if L < 30 or L > 80:
        return 0.0
    score = 0.5
    if 50 <= L <= 65:
        score += 0.3
    if ":" in t or "—" in t or "–" in t:
        score += 0.1
    if t.isupper():
        score -= 0.3
    if any(t.lower().startswith(c) for c in
           ("you won't believe", "this is why", "shocking")):
        score -= 0.15  # clickbait clichés
    if any(w[0].isupper() for w in t.split()[:3]):
        score += 0.05
    return max(0.0, min(1.0, score))


def generate_titles(api_key: str, idea: str, outline: dict, n: int = 12) -> list[dict]:
    msgs = [
        {"role": "system", "content":
            "You are a YouTube title strategist. Output ONLY valid JSON."},
        {"role": "user", "content": f"""
Channel: {CHANNEL_NAME} — buried/dark/forgotten history.
Topic: {idea}
Working title: {outline.get('working_title','')}
Hook: {outline.get('hook','')}
Payoff: {outline.get('payoff','')}

Generate {n} candidate YouTube titles. Mix of styles:
  - 4 informational ("The Real Story Behind X")
  - 4 curiosity gap ("X: What [authority] Tried to Bury")
  - 4 number/timestamped ("60 Years Later, X Still Has No Explanation")

Rules:
- 50-65 characters preferred.
- Title case, not ALL CAPS.
- No emoji. No leading numbers like "10 things".
- No clickbait clichés ("you won't believe", "shocking truth").
- Each title must be self-contained — viewer doesn't need to know the channel.

Return JSON: {{"titles": ["title 1", "title 2", ...]}}
""".strip()}]

    res     = llm.call(api_key, msgs, json_mode=True, temperature=0.8, max_tokens=1500)
    titles  = res["json"].get("titles", []) if isinstance(res["json"], dict) else []
    scored  = [{"title": t, "score": _title_score(t)} for t in titles if t]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters_from_outline(outline: dict, total_seconds: float) -> list[tuple[str, str]]:
    acts   = outline.get("acts", []) or []
    if not acts:
        return [("0:00", "Introduction")]

    sum_planned = sum(a.get("approx_seconds", 60) for a in acts) or 1
    scale       = total_seconds / sum_planned
    out, cursor = [], 0.0
    out.append((_format_timestamp(0), "Introduction"))
    for i, a in enumerate(acts):
        if i == 0:
            cursor += a.get("approx_seconds", 60) * scale
            continue
        ts    = _format_timestamp(cursor)
        label = a.get("label") or f"Part {i+1}"
        out.append((ts, label))
        cursor += a.get("approx_seconds", 60) * scale
    return out


def generate_description(api_key: str, idea: str, outline: dict,
                         title: str, total_seconds: float) -> dict:
    chapters = chapters_from_outline(outline, total_seconds)

    msgs = [
        {"role": "system", "content":
            "You are a YouTube SEO writer. Output ONLY valid JSON."},
        {"role": "user", "content": f"""
Channel: {CHANNEL_NAME} ({CHANNEL_TAGLINE}).
Title: {title}
Topic: {idea}
Hook: {outline.get('hook','')}
Promise: {outline.get('promise','')}
Payoff: {outline.get('payoff','')}

Write a YouTube description as JSON:

{{
  "hook_paragraph": "first 150 characters max — appears above the fold; must contain the primary keyword and create curiosity",
  "body_paragraphs": ["paragraph 1", "paragraph 2"],
  "primary_keyword": "the single best 2-4 word keyword",
  "secondary_keywords": ["5 to 8 long-tail variants the description should include"],
  "tags": ["10 to 15 short tags, lowercase, no #, total <= 480 characters when joined with commas"],
  "hashtags": ["3 to 5 hashtags including the # symbol"]
}}

Rules:
- Body paragraphs 2-4 sentences each. Conversational but authoritative.
- Naturally include the primary keyword in hook + body.
- Tags are reusable across niche; not just title words.
- No filler like "in this video we discuss".
- No emoji in body paragraphs (hashtags-only allowed).
""".strip()}]

    res = llm.call(api_key, msgs, json_mode=True, temperature=0.7, max_tokens=1800)
    d   = res["json"] if isinstance(res["json"], dict) else {}

    # Build the final formatted description
    hook   = d.get("hook_paragraph", "").strip()
    body   = [p.strip() for p in d.get("body_paragraphs", []) if p.strip()]
    tags   = [t.strip().lower() for t in d.get("tags", []) if t.strip()]
    hashes = d.get("hashtags") or DEFAULT_HASHTAGS

    # Clamp tags to 480 chars
    cumulative, kept = 0, []
    for t in tags:
        add = len(t) + 2
        if cumulative + add > 480:
            break
        kept.append(t)
        cumulative += add
    tags = kept

    chap_lines = "\n".join(f"{ts} – {lbl}" for ts, lbl in chapters)

    description_text = f"""{hook}

{chr(10).join(body)}

━━━━━━━━━━━━━━━━━━━━━━━━━
CHAPTERS
{chap_lines}
━━━━━━━━━━━━━━━━━━━━━━━━━

🔔 Subscribe to {CHANNEL_NAME} for buried history every week.

{' '.join(hashes)}""".strip()

    return {
        "description":        description_text,
        "primary_keyword":    d.get("primary_keyword", ""),
        "secondary_keywords": d.get("secondary_keywords", []),
        "tags":               tags,
        "hashtags":           hashes,
        "chapters":           chapters,
    }


def build_seo_pack(api_key: str, idea: str, outline: dict,
                   total_seconds: float, on_log=None) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    log = on_log or (lambda m: None)

    # Titles and description are independent LLM calls — run in parallel
    log("🎯 Generating titles + description in parallel...")
    with ThreadPoolExecutor(max_workers=2) as pool:
        titles_fut = pool.submit(generate_titles, api_key, idea, outline)
        # Use a placeholder title for description; swap in real primary after
        desc_fut   = pool.submit(
            generate_description, api_key, idea, outline, idea, total_seconds
        )
        titles = titles_fut.result()
        desc   = desc_fut.result()

    if not titles:
        raise llm.LLMError("no titles generated")
    primary = titles[0]["title"]
    ab      = [t["title"] for t in titles[1:3]]
    log(f"   ✅ primary: {primary!r}")
    log(f"   ✅ {len(desc['tags'])} tags, {len(desc['chapters'])} chapters")

    return {
        "title":              primary,
        "title_alternatives": ab,
        "title_candidates":   titles,
        **desc,
    }
