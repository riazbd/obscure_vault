"""
ResearchEngine — pull facts about a topic from free sources, extract
atomic claims with source URLs, dedup, and persist a research_pack
that the script engine cites.

Sources (all free, no API keys):
  - Wikipedia search + extract (REST + Action API)
  - DuckDuckGo HTML search (scraped, no JS required)

HTML → text uses the stdlib html.parser to avoid a BeautifulSoup
dependency. Cache by sha256(url) at data/cache/research/.
"""

import re
import json
import time
import hashlib
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

import requests

import llm
from engines.utils import tokens as _tokens, jaccard as _jaccard


BASE_DIR    = Path(__file__).resolve().parent.parent
CACHE_DIR   = BASE_DIR / "data" / "cache" / "research"
PACKS_DIR   = BASE_DIR / "data" / "research_packs"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
PACKS_DIR.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (compatible; ObscuraVault/1.0; "
      "+https://github.com/riazbd/obscure_vault)")


# ════════════════════════════════════════════════════════
#  HTML → text (stdlib only)
# ════════════════════════════════════════════════════════

class _TextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "nav", "footer", "header",
                 "aside", "noscript", "form", "button", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1
        elif tag in ("p", "li", "h1", "h2", "h3", "h4"):
            self.parts.append(" ")

    def handle_data(self, data):
        if self.skip_depth == 0:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    text = "".join(p.parts)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ════════════════════════════════════════════════════════
#  HTTP fetch + cache
# ════════════════════════════════════════════════════════

def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{h}.txt"


def fetch_url_text(url: str, timeout: int = 15,
                   max_chars: int = 8000) -> str:
    """Fetch URL, strip HTML, cache. Returns plain text or empty string."""
    cp = _cache_path(url)
    if cp.exists():
        try:
            return cp.read_text()[:max_chars]
        except Exception:
            pass

    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code != 200:
            return ""
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            return ""
        text = html_to_text(r.text)
        try:
            cp.write_text(text)
        except Exception:
            pass
        return text[:max_chars]
    except requests.RequestException:
        return ""


# ════════════════════════════════════════════════════════
#  Wikipedia
# ════════════════════════════════════════════════════════

def wikipedia_search(query: str, limit: int = 5) -> list[str]:
    """Returns matching article titles."""
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "opensearch", "search": query,
                    "limit": limit, "format": "json"},
            headers={"User-Agent": UA},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return data[1] if len(data) > 1 else []
    except (requests.RequestException, ValueError):
        return []


def wikipedia_extract(title: str) -> dict:
    """Returns {title, url, text} for a Wikipedia article (plain-text intro+body)."""
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "titles": title,
                "prop": "extracts|info", "explaintext": 1,
                "exsectionformat": "plain", "inprop": "url",
                "redirects": 1, "format": "json",
            },
            headers={"User-Agent": UA},
            timeout=12,
        )
        if r.status_code != 200:
            return {}
        pages = r.json().get("query", {}).get("pages", {})
        for _, page in pages.items():
            if "missing" in page:
                continue
            extract = page.get("extract", "") or ""
            return {
                "title": page.get("title", title),
                "url":   page.get("fullurl", ""),
                "text":  extract[:8000],
            }
    except (requests.RequestException, ValueError):
        pass
    return {}


# ════════════════════════════════════════════════════════
#  DuckDuckGo HTML
# ════════════════════════════════════════════════════════

_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.S,
)


def ddg_search(query: str, limit: int = 5) -> list[dict]:
    """Scrape duckduckgo.com/html/. Returns [{title, url}, ...]."""
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": UA},
            timeout=15,
        )
        if r.status_code != 200:
            return []
    except requests.RequestException:
        return []

    out = []
    for m in _DDG_RESULT_RE.finditer(r.text):
        href = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        # DDG redirect-cleans: //duckduckgo.com/l/?uddg=<encoded url>
        if href.startswith("//duckduckgo.com/l/"):
            qs = urllib.parse.urlparse("https:" + href).query
            params = urllib.parse.parse_qs(qs)
            real = params.get("uddg", [""])[0]
            if real:
                href = urllib.parse.unquote(real)
        if href.startswith("http") and title:
            # Skip social media + obvious junk
            low = href.lower()
            if any(k in low for k in (
                "youtube.com/watch", "twitter.com", "x.com/",
                "facebook.com", "instagram.com", "tiktok.com",
                "pinterest.com", "reddit.com",
            )):
                continue
            out.append({"title": title, "url": href})
            if len(out) >= limit:
                break
    return out


# ════════════════════════════════════════════════════════
#  Fact extraction (LLM)
# ════════════════════════════════════════════════════════

def extract_facts(api_key: str, topic: str, source_title: str,
                  source_url: str, source_text: str,
                  on_log=None) -> list[dict]:
    log = on_log or (lambda m: None)
    snippet = source_text[:6000]
    if len(snippet) < 200:
        return []

    msgs = [
        {"role": "system", "content":
            "You extract atomic factual claims from sources. Output ONLY valid JSON."},
        {"role": "user", "content": f"""
Topic: {topic}
Source: {source_title}
URL: {source_url}

Extract 5 to 12 atomic factual claims from this source that are
RELEVANT to the topic. Each claim:
  - Stand-alone sentence (a script narrator could read it).
  - Concrete: contains a date, name, place, number, or specific event.
  - NOT speculation, opinion, or a question.
  - NOT just a definition of a common term.

Source text:
\"\"\"
{snippet}
\"\"\"

Return JSON: {{"claims": ["claim 1", "claim 2", ...]}}
""".strip()}]

    try:
        res = llm.call(api_key, msgs, json_mode=True,
                       temperature=0.3, max_tokens=1800)
    except Exception as e:
        log(f"   ⚠️  fact-extract LLM failed: {e}")
        return []

    raw = (res["json"] or {}).get("claims", []) or []
    out = []
    for c in raw:
        if not isinstance(c, str):
            continue
        c = c.strip()
        if 20 <= len(c) <= 320:
            out.append({"claim": c, "source": source_url, "source_title": source_title})
    return out


# ════════════════════════════════════════════════════════
#  Dedup
# ════════════════════════════════════════════════════════

def dedup_claims(claims: list[dict], threshold: float = 0.65) -> list[dict]:
    out = []
    seen_tokens = []
    for c in claims:
        t = _tokens(c["claim"])
        if any(_jaccard(t, st) >= threshold for st in seen_tokens):
            continue
        seen_tokens.append(t)
        c["id"] = "f" + str(len(out) + 1)
        out.append(c)
    return out


# ════════════════════════════════════════════════════════
#  Top-level
# ════════════════════════════════════════════════════════

def build_research_pack(
    api_key: str,
    topic: str,
    *,
    wikipedia_articles: int = 3,
    ddg_results: int = 4,
    on_log=None,
) -> dict:
    """
    Returns:
      {
        "topic": "...",
        "facts": [{id, claim, source, source_title}, ...],
        "sources": [{title, url}, ...]
      }
    """
    log = on_log or (lambda m: None)

    log(f"🔎 researching: {topic}")
    sources_used = []
    raw_claims   = []

    # ── Wikipedia ────────────────────────────────────────
    titles = wikipedia_search(topic, limit=wikipedia_articles)
    log(f"   📚 wikipedia: {len(titles)} candidate articles")
    for title in titles[:wikipedia_articles]:
        art = wikipedia_extract(title)
        if not art or len(art.get("text", "")) < 200:
            continue
        log(f"      ↳ {art['title']}")
        sources_used.append({"title": art["title"], "url": art["url"]})
        claims = extract_facts(api_key, topic, art["title"], art["url"],
                               art["text"], on_log=log)
        raw_claims.extend(claims)

    # ── DuckDuckGo ───────────────────────────────────────
    if ddg_results > 0:
        ddg_hits = ddg_search(topic, limit=ddg_results)
        log(f"   🌐 ddg: {len(ddg_hits)} results")
        for hit in ddg_hits:
            text = fetch_url_text(hit["url"])
            if len(text) < 400:
                continue
            log(f"      ↳ {hit['title'][:60]}")
            sources_used.append({"title": hit["title"], "url": hit["url"]})
            claims = extract_facts(api_key, topic, hit["title"], hit["url"],
                                   text, on_log=log)
            raw_claims.extend(claims)

    log(f"   ✏️  {len(raw_claims)} raw claims → deduping...")
    facts = dedup_claims(raw_claims)
    log(f"   ✅ {len(facts)} unique facts")

    pack = {
        "topic":   topic,
        "facts":   facts,
        "sources": sources_used,
    }

    # Persist for reproducibility / inspection
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60]
    out_path = PACKS_DIR / f"{slug}_{int(time.time())}.json"
    try:
        out_path.write_text(json.dumps(pack, indent=2, ensure_ascii=False))
        pack["_persisted_at"] = str(out_path)
    except Exception:
        pass

    return pack


# ════════════════════════════════════════════════════════
#  Format pack for the script-engine prompt
# ════════════════════════════════════════════════════════

def render_pack_for_prompt(pack: dict, max_facts: int = 60) -> str:
    """Compact text representation injected into script-engine prompts."""
    lines = []
    for f in pack.get("facts", [])[:max_facts]:
        lines.append(f"- [{f['id']}] {f['claim']}")
    facts_block = "\n".join(lines) if lines else "(no facts)"
    sources_block = "\n".join(
        f"- {s['title']}: {s['url']}" for s in pack.get("sources", [])[:15]
    ) or "(no sources)"
    return (
        f"RESEARCH PACK for topic: {pack.get('topic','')}\n\n"
        f"FACTS (use only these — every concrete claim in the script must be backed by one of these):\n"
        f"{facts_block}\n\n"
        f"SOURCES:\n{sources_block}"
    )
