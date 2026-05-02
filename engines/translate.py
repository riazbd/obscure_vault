"""
TranslateEngine — convert a finished English video into another
language, reusing the original footage track. New voice + new
captions + new metadata; same video.

Language coverage: any locale with an Edge TTS voice. The map below
picks a strong masculine documentary voice per locale; all are free,
no signup. Source language is assumed English.
"""

import re
import asyncio
from pathlib import Path

import llm


# locale_code → {name, voice (Edge TTS)}
# Curated for documentary-tone Obscura Vault content; all voices are
# masculine and authoritative. Switch a voice via config.
LANGUAGES: dict[str, dict] = {
    "es":    {"name": "Spanish",         "voice": "es-MX-JorgeNeural"},
    "es-es": {"name": "Spanish (Spain)", "voice": "es-ES-AlvaroNeural"},
    "pt":    {"name": "Portuguese (BR)", "voice": "pt-BR-AntonioNeural"},
    "fr":    {"name": "French",          "voice": "fr-FR-HenriNeural"},
    "de":    {"name": "German",          "voice": "de-DE-ConradNeural"},
    "it":    {"name": "Italian",         "voice": "it-IT-DiegoNeural"},
    "ru":    {"name": "Russian",         "voice": "ru-RU-DmitryNeural"},
    "hi":    {"name": "Hindi",           "voice": "hi-IN-MadhurNeural"},
    "ar":    {"name": "Arabic",          "voice": "ar-SA-HamedNeural"},
    "ja":    {"name": "Japanese",        "voice": "ja-JP-KeitaNeural"},
    "id":    {"name": "Indonesian",      "voice": "id-ID-ArdiNeural"},
    "tr":    {"name": "Turkish",         "voice": "tr-TR-AhmetNeural"},
    "pl":    {"name": "Polish",          "voice": "pl-PL-MarekNeural"},
    "vi":    {"name": "Vietnamese",      "voice": "vi-VN-NamMinhNeural"},
    "ko":    {"name": "Korean",          "voice": "ko-KR-InJoonNeural"},
}


def voice_for(lang_code: str) -> str:
    info = LANGUAGES.get(lang_code) or LANGUAGES.get(lang_code.split("-")[0])
    if not info:
        raise ValueError(f"unsupported language: {lang_code}")
    return info["voice"]


def language_name(lang_code: str) -> str:
    info = LANGUAGES.get(lang_code) or LANGUAGES.get(lang_code.split("-")[0])
    return info["name"] if info else lang_code


# ════════════════════════════════════════════════════════
#  LLM translation
# ════════════════════════════════════════════════════════

def translate_script(api_key: str, script: str, target_lang: str,
                     on_log=None) -> str:
    log = on_log or (lambda m: None)
    name = language_name(target_lang)
    log(f"   📝 translating script to {name}...")

    # Big script → split by paragraph and translate in chunks for context.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", script.strip()) if p.strip()]
    if not paragraphs:
        return script

    out = []
    chunk_size = 6   # paragraphs per LLM call
    for i in range(0, len(paragraphs), chunk_size):
        batch = paragraphs[i:i + chunk_size]
        joined = "\n\n".join(batch)

        msgs = [
            {"role": "system", "content":
                f"You are a professional documentary translator into {name}. "
                "Output ONLY the translation, preserving paragraph breaks. "
                "No commentary, no transliteration, no quotes around the result."},
            {"role": "user", "content":
                f"Translate the following English narration into natural, "
                f"documentary-style {name}. Preserve cinematic register, "
                f"keep sentence pacing similar, do not add or remove "
                f"information. Adapt cultural references where needed.\n\n"
                f"{joined}"},
        ]
        try:
            res = llm.call(api_key, msgs, temperature=0.4, max_tokens=4000)
            out.append(res["text"].strip())
        except Exception as e:
            log(f"   ⚠️  chunk {i//chunk_size + 1} failed: {e}")
            out.append(joined)   # fall back to source so we don't lose chunks

    return "\n\n".join(out)


def translate_metadata(api_key: str, title: str, description: str,
                       target_lang: str, on_log=None) -> dict:
    log = on_log or (lambda m: None)
    name = language_name(target_lang)
    log(f"   🏷️  translating title + description to {name}...")

    msgs = [
        {"role": "system", "content":
            f"You are a YouTube SEO translator for {name}. Output ONLY valid JSON."},
        {"role": "user", "content": f"""
Translate this video title and description into natural, search-optimised
{name}. Preserve emojis. Title length 50-65 chars in the target language.
Keep all hashtags and channel handles intact.

Title (English): {title}

Description (English):
\"\"\"
{description[:3000]}
\"\"\"

Return JSON:
{{
  "title":       "{name} title",
  "description": "{name} description, paragraph breaks preserved",
  "tags":        ["10 short {name} tags"]
}}
""".strip()}]

    try:
        res = llm.call(api_key, msgs, json_mode=True,
                       temperature=0.5, max_tokens=2200)
        d = res["json"] or {}
        return {
            "title":       d.get("title", title),
            "description": d.get("description", description),
            "tags":        [t for t in (d.get("tags") or []) if isinstance(t, str)],
        }
    except Exception as e:
        log(f"   ⚠️  metadata translate failed: {e}")
        return {"title": title, "description": description, "tags": []}


# ════════════════════════════════════════════════════════
#  Edge TTS in target language
# ════════════════════════════════════════════════════════

async def _tts_async(script: str, voice: str, out_path: Path):
    import edge_tts
    comm = edge_tts.Communicate(script, voice)
    await comm.save(str(out_path))


def synthesize_voice(script: str, voice: str, out_path: Path) -> Path:
    asyncio.run(_tts_async(script, voice, out_path))
    return out_path


# ════════════════════════════════════════════════════════
#  Top-level helper
# ════════════════════════════════════════════════════════

def supported_codes() -> list[str]:
    return list(LANGUAGES.keys())
