# `engines/research.py` — Citation-Grounded Fact Extraction

## Purpose
Pull facts about a topic from free public sources, extract atomic
claims with source URLs, and produce a **research_pack** that the
script engine can cite. Reduces hallucinations by forcing the LLM
to ground its claims in real, traceable data.

## File
`/home/user/obscure_vault/engines/research.py`

## Public API

### `build_research_pack(api_key, topic, *, wikipedia_articles=3, ddg_results=4, on_log=None)`
End-to-end harvest. Returns:
```python
{
  "topic": "...",
  "facts": [{"id": "f1", "claim": "...", "source": "url",
             "source_title": "..."}, ...],
  "sources": [{"title": "...", "url": "..."}, ...],
  "_persisted_at": "data/research_packs/<slug>_<ts>.json"
}
```

### `render_pack_for_prompt(pack, max_facts=60)`
Format pack as a compact text block that fits in an LLM prompt.
Emits:
```
RESEARCH PACK for topic: <topic>

FACTS (use only these — every concrete claim in the script must be backed by one of these):
- [f1] Nine hikers vanished in the Ural mountains in February 1959.
- [f2] The tent was found cut from inside.
...

SOURCES:
- Dyatlov Pass incident: https://en.wikipedia.org/wiki/...
```

Used by `engines/script.py`.

## Sources used

### Wikipedia
- `wikipedia_search(query, limit)` — opensearch API → top N article titles
- `wikipedia_extract(title)` — query API with `prop=extracts&explaintext=1`
  → plain-text article body (capped at 8 000 chars)

### DuckDuckGo HTML
- `ddg_search(query, limit)` — scrapes `html.duckduckgo.com/html/`
  with regex; cleans DDG redirect URLs; filters out social-media
  and reddit/youtube domains
- `fetch_url_text(url)` — GETs the URL, runs through `html_to_text`,
  caches at `data/cache/research/<sha>.txt`

### `html_to_text(html)`
Stdlib `html.parser.HTMLParser` subclass `_TextExtractor`. Skips
`<script>`, `<style>`, `<nav>`, `<footer>`, `<aside>`, `<noscript>`,
`<form>`, `<button>`, `<svg>`. Returns whitespace-collapsed plain
text. No BeautifulSoup dependency.

## Fact extraction
`extract_facts(api_key, topic, source_title, source_url, source_text)`
passes each source's text (capped at 6 000 chars) to an LLM with a
prompt asking for 5–12 atomic factual claims. Each claim is:
- Stand-alone sentence (script-readable)
- Concrete (date / name / place / number / specific event)
- Not speculation, opinion, or definition of common terms
- Length 20–320 chars

## Dedup
`dedup_claims(claims, threshold=0.65)`. Token-Jaccard between every
pair; if a new claim's tokens overlap an existing claim's by ≥0.65,
it's dropped. Each survivor gets a sequential id `f1`, `f2`, …

## Caching
- HTML fetch cache: `data/cache/research/<sha>.txt`
- Research packs persisted: `data/research_packs/<slug>_<ts>.json`
  (for inspection and audit; not auto-cleaned)

## External dependencies
- `requests`
- `llm.py`
- HTTP egress to `en.wikipedia.org`, `html.duckduckgo.com`, and
  whatever URLs DDG returns

## Failure modes
- **Wikipedia returns nothing** — empty list, pipeline continues with
  whatever DDG produces
- **DDG layout changes** (regex misses) — empty list, pipeline
  continues with Wikipedia only
- **A source returns < 200 chars of usable text** — skipped
- **LLM fact extraction fails for a source** — that source is
  silently skipped, others proceed
- **All sources fail** — pack has `facts: []`; downstream script
  engine will silently produce a script without grounding (no
  hard error)

## Used by
- `server.py` `_run_script_job` (when `research=True`)
- `server.py` `_run_idea_to_video` (when `cfg.use_research=True`)

## Configuration
No config keys. Tuneable parameters are arguments to
`build_research_pack`.
