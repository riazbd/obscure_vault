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
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]


class LLMError(Exception):
    pass


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
    """Pull the first balanced {...} or [...] block out of the model output."""
    if not text:
        raise LLMError("empty response")

    # Strip code fences
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1)

    # Find first { or [
    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [s for s in (start_obj, start_arr) if s >= 0]
    if not starts:
        raise LLMError(f"no JSON found in response: {text[:200]}")
    start = min(starts)
    open_ch  = text[start]
    close_ch = "}" if open_ch == "{" else "]"

    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                blob = text[start:i+1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError as e:
                    raise LLMError(f"json parse: {e}; blob={blob[:200]}") from e
    raise LLMError("unbalanced JSON")


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

    for model in models:
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

            # 429 or 5xx → backoff and retry; 4xx (other) → next model
            if r.status_code == 429 or 500 <= r.status_code < 600:
                last_err = f"{model}: HTTP {r.status_code}"
                time.sleep((2 ** attempt) + 1)
                continue
            else:
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
