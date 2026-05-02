# `llm.py` — OpenRouter Chat Client

## Purpose
Single point of LLM access for the entire system. Wraps OpenRouter's
OpenAI-compatible chat completions API with three behaviours every
caller depends on:

1. **Free-model cascade** — tries up to five free models in order
2. **Content-hash file cache** — identical prompts return instantly
3. **Robust JSON extraction** — survives code-fenced or prose-prefixed
   responses

## File
`/home/user/obscure_vault/llm.py` (top-level, not in `engines/`).

## Public API

### `call(api_key, messages, *, models=None, temperature=0.7, max_tokens=4096, json_mode=False, use_cache=True, timeout=90)`
Cascading chat call. Returns `{"text": str, "json": dict|list|None,
"model": str, "cached": bool}`.

- `messages` — OpenAI-format chat list (`[{"role": "user", "content": ...}]`)
- `models` — override the default cascade list
- `json_mode` — when True, validates the response parses as JSON;
  on failure tries the next model
- `use_cache` — set False to bypass cache (e.g. retry attempts in
  the script engine)
- Raises `LLMError` if every model fails

### `validate_key(api_key)`
Quick boolean check used by the Settings UI's "Validate & Save"
button. Sends a 1-token "Reply with the single word: ok" prompt.

## Configuration
Reads no config keys directly — every caller passes the API key
explicitly. The cascade list is hardcoded in `DEFAULT_MODELS`:

```python
DEFAULT_MODELS = [
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]
```

## Caching
Cache directory: `data/cache/llm/<sha256>.json`. Key derived from
`sha256(model + temperature + json.dumps(messages, sort_keys=True))`.

Each cache file: `{"text": str, "model": str, "ts": int}`.

To force a cache miss: pass `use_cache=False` (already done by
`engines/script.py` on retry attempts).

## External dependencies
- `requests` (already in requirements)
- HTTP egress to `openrouter.ai` (no proxy support)

## Failure modes
- **All cascade models 4xx (auth)** — `LLMError`, surfaced to caller
- **All cascade models 429/5xx** — same; per-model retry exists
  (3 attempts with exponential backoff per model) before falling
  through
- **JSON-mode parse failure on a model** — falls through to next
  model; if all fail, `LLMError` with parse details
- **Empty content from a model** — falls through

## Internal helpers
- `_extract_json(text)` — pulls the first balanced `{...}` or `[...]`
  block. Strips ```json``` fences, walks character-by-character with
  string and escape awareness. Used internally when `json_mode=True`.

## Used by
Every other engine: `script.py`, `seo.py`, `research.py`, `footage.py`
(query generation), `thumbnail.py` (punchline + image prompt),
`ideas.py` (niche scoring), `review.py` (scorecard).
