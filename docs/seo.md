# `engines/seo.py` — Title, Description, Tags, Chapters

## Purpose
Produce a YouTube-optimised SEO pack for a video given its topic and
generated outline.

## File
`/home/user/obscure_vault/engines/seo.py`

## Public API

### `build_seo_pack(api_key, idea, outline, total_seconds, on_log=None)`
Top-level orchestrator. Returns:

```python
{
  "title": "primary title",
  "title_alternatives": ["A/B variant 1", "A/B variant 2"],
  "title_candidates": [{"title": "...", "score": 0.85}, ...],
  "description": "full multi-line description text",
  "primary_keyword": "the lead keyword",
  "secondary_keywords": ["...", "..."],
  "tags": ["tag1", "tag2", ...],
  "hashtags": ["#tag", ...],
  "chapters": [("0:00", "Introduction"), ("1:30", "Background"), ...]
}
```

### `generate_titles(api_key, idea, outline, n=12)`
Generates 12 title candidates with mixed style guidance
(informational / curiosity-gap / number-stamped). Each is scored by
`_title_score()` and returned sorted descending.

### `generate_description(api_key, idea, outline, title, total_seconds)`
LLM JSON call producing:
- A ≤150-char hook paragraph (above-the-fold on YouTube)
- 2 body paragraphs
- Primary keyword + secondary keyword variants
- 10–15 short tags clamped to 480 chars total
- 3–5 hashtags

Then renders these into the final description text with chapter
timestamps and a CTA block.

### `chapters_from_outline(outline, total_seconds)`
Computes scaled chapter timestamps. Sums each act's `approx_seconds`,
scales them so the total matches the actual voiceover duration,
emits `[(timestamp, label), ...]`.

## Title-scoring rubric
`_title_score(t)` returns 0.0–1.0:

- 0 if length outside [30, 80]
- +0.3 bonus if length in [50, 65] (the YouTube sweet spot)
- +0.1 bonus for `:` or em-dash structure
- +0.05 bonus if first 3 words are properly capitalised
- −0.3 penalty if all-caps
- −0.15 penalty for cliché openers ("you won't believe", "this is why",
  "shocking…")

## Configuration
Hardcoded `CHANNEL_TAGLINE` and `CHANNEL_NAME` at the top. Change
for other channels.

`DEFAULT_HASHTAGS` provides a sensible fallback hashtag list.

## External dependencies
Only `llm.py`.

## Failure modes
- **No titles generated** — raises `LLMError("no titles generated")`
- **Description LLM call fails** — caller's `try/except` should
  surface; the SEO pack is critical, so this should fail loud not soft

## Used by
- `server.py` `_run_script_job` (after `script.generate_script`)
- `server.py` `_run_idea_to_video` (full Idea-to-Render chain)
