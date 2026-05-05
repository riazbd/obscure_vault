"""
Shared text utilities used across engines.
Import from here instead of duplicating in each engine.
"""

import re

_STOPWORDS = frozenset({
    "the", "a", "an", "of", "and", "in", "on", "at", "to", "for", "with",
    "is", "was", "were", "what", "why", "how", "that", "this", "these",
    "those", "but", "or", "by", "from", "be", "been", "being",
    "their", "they", "them", "its", "not", "no", "yes",
})


def tokens(s: str) -> set[str]:
    """Lowercase alphanumeric tokens, stopwords and short words removed."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return {w for w in s.split() if len(w) > 2 and w not in _STOPWORDS}


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets; 0.0 if either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
