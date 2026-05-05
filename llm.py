"""
OpenRouter client with model cascade, file-based caching, and JSON parsing.
Free-tier focused: rotates across free models on rate-limit / error.
"""

import os
import re
import json
import time
import hashlib
from pathlib import Path
from typing import Iterable

import requests


BASE_DIR  = Path(__file__).parent
CACHE_DIR = BASE_DIR / "data" / "cache" / "llm"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default cascade of free OpenRouter models, best → fallback.
# Override per-call by passing `models=[...]`.
DEFAULT_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "openai/gpt-oss-120b:free",
    "minimax/minimax-m2.5:free",
]


class LLMError(Exception):
    pass


# Circuit breaker: tracks when each model is next usable (monotonic seconds).
# 429 → back off for 60 s; 5xx transient → back off per-attempt only.
_model_fail_until: dict[str, float] = {}


def _cache_key(model: str, messages: list, temperature: float) -> str:
    h = hashlib.sha256()
    h.update(model.encode())
    h.update(str(temperature).encode())
    h.update(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def _cache_get(key: str):
    p = CACHE_DIR / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())["text"]
        except Exception:
            return None
    return None


def _cache_put(key: str, text: str, model: str):
    p = CACHE_DIR / f"{key}.json"
    p.write_text(json.dumps({"text": text, "model": model, "ts": int(time.time())}))


def _extract_json(text: str):
    """
    Extract the first valid JSON object or array from model output.

    Improvements over the original:
    - Tries every candidate { / [ position in order (not just the first one),
      so preamble text with stray braces doesn't break parsing.
    - Guards depth against going negative (malformed close before open).
    - Only sets the escape flag while inside a string.
    - Hard size limit to prevent runaway scanning on huge responses.
    """
    if not text:
        raise LLMError("empty response")
    if len(text) > 500_000:
        raise LLMError("response too large to parse safely")

    # Strip code fences first
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()

    # Collect every { and [ position in document order
    candidates: list[int] = []
    for ch in ("{", "["):
        pos = 0
        while True:
            idx = text.find(ch, pos)
            if idx < 0:
                break
            candidates.append(idx)
            pos = idx + 1
    candidates.sort()

    if not candidates:
        raise LLMError(f"no JSON found in response: {text[:200]}")

    last_err = "no valid JSON block found"
    for start in candidates:
        open_ch  = text[start]
        close_ch = "}" if open_ch == "{" else "]"
        depth, in_str, esc = 0, False, False

        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == "\\" and in_str:
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch and depth > 0:
                depth -= 1
                if depth == 0:
                    blob = text[start : i + 1]
                    try:
                        return json.loads(blob)
                    except json.JSONDecodeError as e:
                        last_err = f"parse failed at pos {start}: {e}; blob={blob[:120]}"
                        break  # try next candidate start

    raise LLMError(f"no valid JSON in response — {last_err}")


def call(
    api_key: str,
    messages: list,
    *,
    models: Iterable[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    json_mode: bool = False,
    use_cache: bool = True,
    timeout: int = 90,
):
    """
    Call OpenRouter cascading through free models. Returns dict:
      {text, json, model, cached}
    Raises LLMError if every model fails.
    """
    if not api_key:
        raise LLMError("OpenRouter API key not set")

    models   = list(models or DEFAULT_MODELS)
    last_err = None
    now      = time.monotonic()

    for model in models:
        # Circuit breaker: skip models that are cooling down after a 429
        if now < _model_fail_until.get(model, 0):
            last_err = f"{model}: skipped (rate-limited, cooling down)"
            continue

        ck = _cache_key(model, messages, temperature)
        if use_cache:
            cached = _cache_get(ck)
            if cached is not None:
                out = {"text": cached, "json": None, "model": model, "cached": True}
                if json_mode:
                    try:
                        out["json"] = _extract_json(cached)
                    except LLMError:
                        pass  # fall through to live call
                    else:
                        return out
                else:
                    return out

        body = {
            "model":       model,
            "messages":    messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }

        # Try up to 3 times per model with backoff for transient errors.
        for attempt in range(3):
            try:
                r = requests.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/riazbd/obscure_vault",
                        "X-Title": "Obscura Vault",
                    },
                    json=body,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                last_err = f"{model}: network {e}"
                time.sleep(2 ** attempt)
                continue

            if r.status_code == 200:
                try:
                    data = r.json()
                    text = data["choices"][0]["message"]["content"]
                except Exception as e:
                    last_err = f"{model}: parse {e}"
                    break

                if not text or not text.strip():
                    last_err = f"{model}: empty content"
                    break

                if json_mode:
                    try:
                        parsed = _extract_json(text)
                    except LLMError as e:
                        last_err = f"{model}: {e}"
                        break  # try next model
                    _cache_put(ck, text, model)
                    return {"text": text, "json": parsed, "model": model, "cached": False}

                _cache_put(ck, text, model)
                return {"text": text, "json": None, "model": model, "cached": False}

            if r.status_code == 429:
                # Rate-limited: cool this model down for 60 s, try the next one
                _model_fail_until[model] = time.monotonic() + 60
                last_err = f"{model}: rate-limited (429) — skipping for 60 s"
                break  # move to next model immediately
            elif 500 <= r.status_code < 600:
                # Transient server error: exponential backoff, then retry same model
                last_err = f"{model}: HTTP {r.status_code}"
                time.sleep((2 ** attempt) + 1)
                continue
            else:
                # Other 4xx: not retryable, try next model
                last_err = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                break

    raise LLMError(f"all models failed; last={last_err}")


def validate_key(api_key: str) -> bool:
    """Quick check: send a tiny prompt and see if at least one free model responds."""
    if not api_key or len(api_key) < 20:
        return False
    try:
        call(
            api_key,
            [{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=8,
            use_cache=False,
            timeout=20,
        )
        return True
    except Exception:
        return False
