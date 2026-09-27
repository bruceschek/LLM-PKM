import json

import httpx
import pytest

from llm_pkm.stores import CloudflareStore, Fact
from llm_pkm.stores.cloudflare import DIMENSIONS, CloudflareError


def ok(result) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "errors": [], "result": result})


class FakeCloudflare:
    """Just enough of Workers AI and Vectorize: the index starts missing, and
    the latest write shows as processed on the second status check, as after
    a batch job."""

    def __init__(self):
        self.created = None
        self.vectors: dict[str, dict] = {}
        self.lookups = 0
        self.last_mutation = None
        self.token_revoked = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.token_revoked:
            return httpx.Response(403, json={"success": False, "errors": [{"message": "Authentication error"}]})
        path = request.url.path
        if request.method == "GET" and path.endswith("/indexes/facts"):
            if self.created is None:
                return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
            return ok({"name": "facts"})
        if path.endswith("/vectorize/v2/indexes"):
            self.created = json.loads(request.content)
            return ok(self.created)
        if "/ai/run/" in path:
            return ok({"shape": [1, DIMENSIONS], "data": [[0.1] * DIMENSIONS]})
        if path.endswith("/upsert"):
            body = request.content.decode()
            line = body[body.index("{") : body.rindex("}") + 1]
            vector = json.loads(line)
            self.vectors[vector["id"]] = vector
            self.last_mutation = f"m{len(self.vectors)}"
            return ok({"mutationId": self.last_mutation})
        if path.endswith("/info"):
            self.lookups += 1
            processed = self.last_mutation if self.lookups > 1 else None
            return ok({"vectorCount": len(self.vectors), "processedUpToMutation": processed})
        if path.endswith("/query"):
            if self.lookups < 2:  # not processed yet: searches can't see it
                return ok({"count": 0, "matches": []})
            matches = [{"id": v["id"], "score": 0.9, "metadata": v["metadata"]} for v in self.vectors.values()]
            return ok({"count": len(matches), "matches": matches})
        return httpx.Response(404, json={"success": False, "errors": [{"message": f"unexpected {path}"}]})


def make_store(monkeypatch, fake: FakeCloudflare) -> CloudflareStore:
    monkeypatch.setattr("llm_pkm.stores.cloudflare.time.sleep", lambda s: None)
    real_client = httpx.Client

    def client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(fake))

    monkeypatch.setattr("llm_pkm.stores.cloudflare.httpx.Client", client)
    return CloudflareStore("acct", "token", "facts")


def test_creates_index_adds_and_finds_a_fact(monkeypatch):
    fake = FakeCloudflare()
    store = make_store(monkeypatch, fake)
    assert fake.created["config"] == {"dimensions": DIMENSIONS, "metric": "cosine"}

    assert store.add(Fact("The user's wife's name is Hemmie.", "x")) == "Saved and indexed."
    assert fake.lookups == 2  # waited until the vector was visible

    [hit] = store.search("who is the user married to?")
    assert hit.text == "The user's wife's name is Hemmie."
    assert hit.created_at


def test_cloudflare_errors_are_readable(monkeypatch):
    fake = FakeCloudflare()
    store = make_store(monkeypatch, fake)
    fake.token_revoked = True
    with pytest.raises(CloudflareError, match="Authentication error"):
        store.search("anything")
