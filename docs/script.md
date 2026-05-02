# `engines/script.py` — Script Generation

## Purpose
Turn a topic (string) into a long-form narration script suitable for
TTS, optionally grounded in a research_pack. Also handles short-form
hook-only scripts for the Shorts pipeline.

## File
`/home/user/obscure_vault/engines/script.py`

## Public API

### `generate_script(api_key, idea, minutes=10.0, research_pack=None, on_log=None)`
Two-pass generation:

1. **Outline pass** — LLM returns a JSON beat sheet:
   ```json
   {
     "working_title": "...",
     "hook": "...",
     "promise": "...",
     "acts": [{"id": 1, "label": "...", "summary": "...",
               "key_facts": ["...", "..."], "approx_seconds": 90}],
     "payoff": "...",
     "cta": "..."
   }
   ```
2. **Draft pass** — LLM expands to continuous narration prose, no
   headings or stage cues, hits target word count ±5 %.

Returns `{outline, script, word_count, model, attempts, warning?}`.

When a `research_pack` is supplied, the outline prompt is augmented
to require every `key_fact` reference its `[fX]` source id, and the
draft prompt instructs the LLM to drop those markers in the final
prose.

### `generate_short_script(api_key, idea, target_words=110, on_log=None)`
One-shot script for a 30–55 second YouTube Short. No outline, no
acts. Hook-only structure. Returns
`{script, word_count, model, working_title}`.

### `generate_outline(api_key, idea, minutes=10.0, research_block="")`
Lower-level outline-only call. Useful when you want to inspect or
edit the outline before committing to a draft.

### `target_word_count(minutes)` / `WORDS_PER_MINUTE = 144`
Edge TTS Guy Neural's sustained cadence. 1440 words ≈ 10 min.

## Quality gates
After every draft attempt, `_quality_check(text, target_words)`
checks:

- Word count within `[0.92, 1.08] × target`
- No banned regex pattern (`as an ai`, `\\[music\\]`, `narrator:`,
  `act \\d+`, `chapter \\d+:`, etc.)
- ≥ 20 sentences
- < 20 % sentences exceeding 35 words

Fail → retry once with feedback in the next message. Fail twice →
escalate to a curated stronger model list. Fail thrice → ship the
best draft with a `warning` field set.

## Configuration
Reads `OPENROUTER_API_KEY` from caller; doesn't touch config.json directly.

`CHANNEL_BRAND` is a hardcoded string at the top of the module
describing tone for prompt injection. Edit if you fork for a
different channel.

`BANNED_PATTERNS` is a list of regex strings; extend if your tests
catch more LLM tics.

## External dependencies
Only `llm.py` (which itself depends on `requests` and OpenRouter).

## Failure modes
- **LLM returns malformed JSON for outline** — `LLMError` propagates;
  caller's `try/except` should handle (see `_run_script_job` in
  `server.py`)
- **Quality gate fails 3×** — script ships with `warning`, caller
  should still proceed (script is usable, just imperfect)
- **Research pack present but LLM ignores `[fX]` markers** — silent;
  no enforcement at gate level (could be added)

## Used by
- `server.py` — both `_run_script_job` and `_run_idea_to_video`
- `engines/upload.py` — `engines/review.py` (which reads the produced
  `script.txt`)
