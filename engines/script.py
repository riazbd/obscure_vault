"""
ScriptEngine — turn an idea into an outline + full narration script.

Two-pass:
  1. Outline (JSON beat sheet)
  2. Draft (long-form narration matching outline)

Quality gates:
  - Word count within ±8 % of target
  - Reading ease threshold (basic heuristic)
  - No banned phrases
On failure: one in-place retry with feedback, then escalate to next model.
"""

import re
import math

import llm


WORDS_PER_MINUTE = 144  # Edge TTS Guy Neural cadence

CHANNEL_BRAND = (
    "Obscura Vault — a YouTube channel for buried, suppressed, and forgotten "
    "history. Tone: calm, grave, authoritative, slightly cinematic. Avoid "
    "sensationalism but keep tension. Address the viewer directly. No "
    "bracketed stage directions, no music cues, no [SOUND] tags — only the "
    "narration the voice will read."
)

BANNED_PATTERNS = [
    r"\b(?:as an ai|as a language model|i cannot|i can'?t|i am unable)\b",
    r"\bdisclaimer\b.{0,40}\bai\b",
    r"\b\[(?:music|sound|sfx|pause|cue)[^\]]*\]",
    r"\bnarrator:\s",
    r"\bact\s+\d+\b",  # leftover outline markers
    r"\bchapter\s+\d+:\s",
]


def target_word_count(minutes: float) -> int:
    return int(round(minutes * WORDS_PER_MINUTE))


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def _violates_banned(text: str) -> str | None:
    low = text.lower()
    for p in BANNED_PATTERNS:
        m = re.search(p, low)
        if m:
            return m.group(0)
    return None


def _outline_prompt(idea: str, minutes: float, target_words: int,
                    research_block: str = "") -> list:
    research_section = ""
    if research_block:
        research_section = (
            f"\n{research_block}\n\n"
            "Use ONLY facts from the RESEARCH PACK above. For every key_fact "
            "you list, reference its [fact_id] in square brackets at the end. "
            "Do not invent additional facts.\n"
        )
    return [
        {"role": "system", "content":
            "You are a senior YouTube documentary writer. Output ONLY valid JSON."},
        {"role": "user", "content": f"""
Channel context:
{CHANNEL_BRAND}

Topic / idea: {idea}
{research_section}
Target video length: {minutes:.1f} minutes (~{target_words} words of narration).

Produce a beat sheet as JSON with this exact shape:

{{
  "working_title": "string",
  "hook": "1-2 sentence opening that creates curiosity in <15 seconds",
  "promise": "what the viewer will learn",
  "acts": [
    {{
      "id": 1,
      "label": "short label e.g. 'Background'",
      "summary": "what this act covers in 1-2 sentences",
      "key_facts": ["concrete fact ending with [f3]", "..."],
      "approx_seconds": 90
    }}
  ],
  "payoff": "the climactic revelation or tension peak",
  "cta": "the closing call to action (subscribe / next video tease)"
}}

Rules:
- 5 to 8 acts.
- Sum of approx_seconds must be within 10% of {int(minutes*60)}.
- Each act must include at least 2 concrete key_facts.
- Use real, plausible historical detail. No invented people unless clearly hypothetical.
- Output JSON ONLY. No prose, no markdown fences.
""".strip()},
    ]


def _draft_prompt(idea: str, outline: dict, target_words: int,
                  research_block: str = "") -> list:
    outline_str = ""
    for act in outline.get("acts", []):
        facts = "\n    - " + "\n    - ".join(act.get("key_facts", []))
        outline_str += (
            f"\nAct {act['id']} — {act.get('label','')}"
            f" (~{act.get('approx_seconds',60)}s):"
            f"\n  {act.get('summary','')}"
            f"\n  Key facts:{facts}\n"
        )

    research_section = (f"\n{research_block}\n\nGround every concrete claim in the research pack. "
                        "Drop the [fX] markers from the prose — they belong only in the outline. "
                        "If the pack doesn't support a claim, omit that claim.\n"
                        if research_block else "")

    return [
        {"role": "system", "content":
            f"You are a senior YouTube documentary writer for {CHANNEL_BRAND}. "
            "Write narration the voice will read aloud — nothing else."},
        {"role": "user", "content": f"""
Topic: {idea}
{research_section}
Working title: {outline.get('working_title','')}
Hook: {outline.get('hook','')}
Promise: {outline.get('promise','')}
Payoff: {outline.get('payoff','')}
CTA: {outline.get('cta','')}

Outline:
{outline_str}

Write the FULL narration as continuous prose. Hard requirements:
- Approximately {target_words} words (±5%).
- Open with the hook in the first 2-3 sentences.
- Cover every act in order, weaving the key facts in naturally.
- Include subtle retention hooks at roughly 25%, 50%, 75% of the way through (mini-cliffhangers like "but that wasn't even the strangest part…").
- Vary sentence length. Median sentence ≤ 22 words. No paragraph longer than 5 sentences.
- Plain prose only. NO act/chapter headings, NO bracketed stage directions, NO speaker labels, NO music cues, NO inline citation tags like [f1].
- No "as an AI" or meta-commentary.
- End with the CTA in the last paragraph.

Output the script and only the script.
""".strip()},
    ]


def _quality_check(text: str, target_words: int) -> tuple[bool, str]:
    wc = _word_count(text)
    lo, hi = int(target_words * 0.92), int(target_words * 1.08)
    if wc < lo:
        return False, f"too short: {wc} words, need {lo}-{hi}"
    if wc > hi:
        return False, f"too long: {wc} words, need {lo}-{hi}"

    bad = _violates_banned(text)
    if bad:
        return False, f"banned pattern present: {bad!r}"

    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) < 20:
        return False, "too few sentences"

    long_sents = sum(1 for s in sentences if len(s.split()) > 35)
    if long_sents / max(len(sentences), 1) > 0.20:
        return False, "too many long sentences (>35 words)"

    return True, "ok"


def generate_outline(api_key: str, idea: str, minutes: float = 10.0,
                     research_block: str = "") -> dict:
    target = target_word_count(minutes)
    res = llm.call(
        api_key,
        _outline_prompt(idea, minutes, target, research_block=research_block),
        json_mode=True,
        temperature=0.6,
        max_tokens=2000,
    )
    outline = res["json"]
    if not isinstance(outline, dict) or "acts" not in outline:
        raise llm.LLMError("outline missing 'acts'")
    return outline


def generate_script(api_key: str, idea: str, minutes: float = 10.0,
                    research_pack: dict | None = None,
                    on_log=None) -> dict:
    """
    Returns: {outline, script, word_count, model, attempts, research_pack}
    """
    log = on_log or (lambda m: None)

    research_block = ""
    if research_pack and research_pack.get("facts"):
        from engines import research as research_engine
        research_block = research_engine.render_pack_for_prompt(research_pack)
        log(f"📚 grounding script in {len(research_pack['facts'])} researched facts")

    log(f"📜 Outlining ({minutes:.1f} min target)...")
    outline = generate_outline(api_key, idea, minutes,
                               research_block=research_block)
    log(f"   ✅ {len(outline.get('acts', []))} acts, working title: {outline.get('working_title','?')}")

    target = target_word_count(minutes)
    attempts, script_text, model_used = 0, None, None

    # Up to 3 attempts: 1 normal, 1 retry with feedback, 1 escalated cascade restart.
    for attempt in range(3):
        attempts += 1
        log(f"✍️  Drafting (attempt {attempts}, target ~{target} words)...")
        msgs = _draft_prompt(idea, outline, target,
                             research_block=research_block)

        if attempt == 1 and script_text:
            wc = _word_count(script_text)
            msgs.append({"role": "assistant", "content": script_text})
            msgs.append({"role": "user", "content":
                f"Your previous draft had {wc} words — I need ~{target} (±5%). "
                "Revise to hit the target. Keep the structure. "
                "Do not add headings or bracketed cues."})

        # On final attempt, restrict to the strongest free model first.
        models = None
        if attempt == 2:
            models = [
                "deepseek/deepseek-chat-v3-0324:free",
                "meta-llama/llama-3.3-70b-instruct:free",
            ]

        res = llm.call(api_key, msgs, models=models, temperature=0.75,
                       max_tokens=8000, use_cache=(attempt == 0))
        script_text = res["text"].strip()
        model_used  = res["model"]

        ok, reason = _quality_check(script_text, target)
        if ok:
            log(f"   ✅ {_word_count(script_text)} words via {model_used}")
            return {
                "outline":    outline,
                "script":     script_text,
                "word_count": _word_count(script_text),
                "model":      model_used,
                "attempts":   attempts,
            }
        log(f"   ⚠️  quality gate failed: {reason}")

    # Last resort: trim/pad won't help — return best we have with a warning.
    log(f"   ⚠️  shipping best-effort draft after {attempts} attempts")
    return {
        "outline":    outline,
        "script":     script_text or "",
        "word_count": _word_count(script_text or ""),
        "model":      model_used,
        "attempts":   attempts,
        "warning":    "did not pass quality gate",
    }
