"""Cloudflare as the retrieval store: Workers AI turns each fact (and each
question) into an embedding, and a Vectorize index stores and searches them.

Both are called over Cloudflare's REST API, so this runs anywhere, not only
inside a Worker. Vectorize accepts a write at once but makes it searchable
later, in a batch job: 15 to 70 s for a single fact in testing, and searches
can miss it for a little while after that. See
IndexingStore for waiting on that in the foreground or the background.
"""

import json
import threading
import time
from dataclasses import dataclass

import httpx

from ..timing import span
from .background import IndexingStore
from .base import Fact, Hit

BASE_URL = "https://api.cloudflare.com/client/v4"
# bge-base-en-v1.5 returns 768 numbers per text. "cls" pooling is Cloudflare's
# recommended setting; vectors made with a different pooling are not
# comparable, so changing either means creating a new index.
EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"
EMBED_POOLING = "cls"
DIMENSIONS = 768


_STILL_INDEXING = (
    "Saved, but Vectorize is still indexing it; it may not show up in searches for a little while."
)


class CloudflareError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pending:
    """A write that isn't searchable yet."""

    mutation_id: str
    fact_id: str
    values: list[float]  # the fact's embedding, to search for itself


class CloudflareStore(IndexingStore):
    name = "Vectorize"

    def __init__(
        self,
        account_id: str,
        api_token: str,
        index: str,
        index_timeout: float = 90,
        background: bool = False,
    ):
        super().__init__(background)
        self.http = httpx.Client(
            base_url=f"{BASE_URL}/accounts/{account_id}",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=60,
        )
        self.index_path = f"/vectorize/v2/indexes/{index}"
        self.index = index
        self.index_timeout = index_timeout
        self._mutations: list[str] = []  # our writes, oldest first
        self._lock = threading.Lock()  # background waits read the list
        self._ensure_index()

    def _call(self, method: str, path: str, **kwargs) -> dict | list:
        """Make a request and return its `result`, raising Cloudflare's own
        error message on failure."""
        response = self.http.request(method, path, **kwargs)
        try:
            body = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        if not body.get("success", response.is_success):
            errors = "; ".join(e.get("message", str(e)) for e in body.get("errors") or [])
            raise CloudflareError(f"{method} {path}: HTTP {response.status_code}: {errors}")
        return body.get("result")

    def _ensure_index(self) -> None:
        response = self.http.get(self.index_path)
        if response.status_code == 404 or not response.json().get("success"):
            self._call(
                "POST",
                "/vectorize/v2/indexes",
                json={
                    "name": self.index,
                    "description": "LLM PKM: personal facts",
                    "config": {"dimensions": DIMENSIONS, "metric": "cosine"},
                },
            )

    def _embed(self, text: str) -> list[float]:
        with span("workers_ai.embed"):
            result = self._call(
                "POST", f"/ai/run/{EMBED_MODEL}", json={"text": [text], "pooling": EMBED_POOLING}
            )
        return result["data"][0]

    def _submit(self, fact: Fact) -> Pending:
        vector = {
            "id": fact.id,
            "values": self._embed(fact.text),
            "metadata": {"text": fact.text, "created_at": fact.created_at},
        }
        with span("vectorize.upsert"):
            result = self._call(
                "POST",
                f"{self.index_path}/upsert",
                files={"vectors": ("fact.ndjson", json.dumps(vector) + "\n", "application/x-ndjson")},
            )
        with self._lock:
            self._mutations.append(result["mutationId"])
        return Pending(result["mutationId"], fact.id, vector["values"])

    def _wait_for_index(self, pending: Pending) -> str:
        """Wait in two steps, because neither signal alone was reliable in
        testing: a lookup by vector ID finds the vector long before searches
        do, and even once the index reports the write processed, a search
        can miss it for a while.

        1. Poll the index's "processed up to" mutation until it reaches ours
           (cheap). Writes are processed in order, so a later write of ours
           being processed means this one is too. Writes from other
           processes aren't tracked; waiting on those runs into the timeout.
        2. Search with the fact's own vector until the fact comes back.

        Even then it's not a guarantee: in testing, a search a moment later
        sometimes still missed the fact, as if served by a copy of the index
        that hadn't caught up yet."""
        deadline = time.monotonic() + self.index_timeout
        with span("vectorize.wait_processed") as s:
            polls = 0
            while True:
                info = self._call("GET", f"{self.index_path}/info")
                polls += 1
                with self._lock:
                    ours_and_later = self._mutations[self._mutations.index(pending.mutation_id) :]
                if info.get("processedUpToMutation") in ours_and_later:
                    break
                if time.monotonic() > deadline:
                    s.info.update(polls=polls, timed_out=True)
                    return _STILL_INDEXING
                time.sleep(1)
            s.info.update(polls=polls)
        with span("vectorize.wait_searchable") as s:
            polls = 0
            while True:
                result = self._call(
                    "POST", f"{self.index_path}/query", json={"vector": pending.values, "topK": 1}
                )
                polls += 1
                if any(m.get("id") == pending.fact_id for m in result.get("matches") or []):
                    s.info.update(polls=polls)
                    return "Saved and indexed."
                if time.monotonic() > deadline:
                    s.info.update(polls=polls, timed_out=True)
                    return _STILL_INDEXING
                time.sleep(1)

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        vector = self._embed(query)
        with span("vectorize.query"):
            result = self._call(
                "POST",
                f"{self.index_path}/query",
                json={"vector": vector, "topK": limit, "returnMetadata": "all"},
            )
        return [
            Hit(m["metadata"]["text"], m["score"], m["metadata"].get("created_at"))
            for m in result.get("matches") or []
            if (m.get("metadata") or {}).get("text")
        ]
