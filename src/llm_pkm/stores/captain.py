"""Captain (https://docs.captain.dev) as the retrieval store.

Each fact is indexed as its own small text document. Captain indexes in the
background and returns a job ID, so add() waits for the job to finish:
otherwise a question asked straight after a fact might not find it.
"""

import time

import httpx

from .base import Fact, Hit

BASE_URL = "https://api.captain.dev"
_DONE = {"completed", "completed_with_errors", "failed", "cancelled", "timed_out"}


class CaptainStore:
    def __init__(
        self,
        api_key: str,
        collection: str,
        org_id: str | None = None,
        index_timeout: float = 90,
    ):
        headers = {"Authorization": f"Bearer {api_key}"}
        if org_id:
            headers["X-Organization-ID"] = org_id
        self.http = httpx.Client(base_url=BASE_URL, headers=headers, timeout=60)
        self.collection = collection
        self.index_timeout = index_timeout
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        response = self.http.put(
            f"/v2/collections/{self.collection}",
            json={"description": "LLM PKM: personal facts"},
        )
        response.raise_for_status()

    def add(self, fact: Fact) -> str:
        response = self.http.post(
            f"/v2/collections/{self.collection}/index/text",
            headers={"Idempotency-Key": fact.id},
            json={
                "content": fact.text,
                "filename": f"fact-{fact.id}.txt",
                "custom_metadata": {"fact_id": fact.id, "created_at": fact.created_at},
            },
        )
        response.raise_for_status()
        job_id = response.json()["job_id"]

        deadline = time.monotonic() + self.index_timeout
        while time.monotonic() < deadline:
            job = self.http.get(f"/v2/jobs/{job_id}").json()
            status = job.get("status")
            if status == "completed":
                return "Saved and indexed."
            if status in _DONE:
                raise RuntimeError(
                    f"Captain indexing job {job_id} ended as {status}: "
                    f"{job.get('error_message') or job.get('result')}"
                )
            time.sleep(1)
        return f"Saved, but Captain is still indexing it (job {job_id}); it may not show up in searches for a little while."

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        response = self.http.post(
            f"/v3/collections/{self.collection}/query",
            json={"query": query, "limit": limit},
        )
        response.raise_for_status()
        hits = []
        for result in response.json()["results"]:
            metadata = (result.get("document") or {}).get("custom_metadata") or {}
            hits.append(Hit(result["text"], result["score"], metadata.get("created_at")))
        return hits
