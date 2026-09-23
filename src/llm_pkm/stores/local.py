"""A JSON Lines file of facts. Serves two purposes:

- the raw, append-only record of every captured fact (Karpathy's "raw
  sources" layer), written no matter which store does retrieval, so the data
  never lives only inside a third-party service;
- an offline store (PKM_STORE=local) with naive keyword search, for trying
  the loop without Captain.

On Lambda the file would move to S3; the interface stays the same.
"""

import json
import re
from pathlib import Path

from .base import Fact, Hit

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "of", "to", "in", "on", "and",
    "or", "my", "i", "me", "what", "who", "where", "when", "how", "do", "does",
    "user", "user's", "s",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in _STOPWORDS}


class LocalStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, fact: Fact) -> str:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fact.to_dict()) + "\n")
        return "Saved."

    def all(self) -> list[Fact]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [Fact(**json.loads(line)) for line in f if line.strip()]

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        query_words = _words(query)
        scored = []
        for fact in self.all():
            overlap = len(query_words & _words(fact.text))
            if overlap:
                scored.append(Hit(fact.text, overlap / len(query_words), fact.created_at))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]
