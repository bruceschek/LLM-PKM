"""Captain (https://docs.captain.dev) as the retrieval store.

Each fact is indexed as its own small text document. Captain indexes in the
background and returns a job ID, and indexing takes 10 to 15 seconds. By
default add() waits for the job to finish, so a question asked straight
after a fact finds it. With background=True (the CLI), add() returns at once
and a worker thread waits instead; a question asked during that window can
miss the newest fact.
"""

import queue
import threading
import time
from datetime import datetime

import httpx

from .. import timing
from ..timing import span
from .base import Fact, Hit, Notice

BASE_URL = "https://api.captain.dev"
_DONE = {"completed", "completed_with_errors", "failed", "cancelled", "timed_out"}


def _job_timings(job: dict) -> dict:
    """Split Captain's own job timestamps into time spent queued (created ->
    started) and processing (started -> completed). Whatever is left of our
    wait on top of those is network and polling delay."""

    def ts(key: str) -> datetime | None:
        value = job.get(key)
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

    created, started, completed = ts("created_at"), ts("started_at"), ts("completed_at")
    out = {}
    if created and started:
        out["captain_queue_s"] = round((started - created).total_seconds(), 2)
    if started and completed:
        out["captain_processing_s"] = round((completed - started).total_seconds(), 2)
    return out


class CaptainStore:
    def __init__(
        self,
        api_key: str,
        collection: str,
        org_id: str | None = None,
        index_timeout: float = 90,
        background: bool = False,
    ):
        """With `background`, add() returns as soon as Captain accepts the
        fact and the indexing wait moves to a worker thread; its outcome lands
        on `self.notices`. Only for long-lived processes like the CLI: a
        Lambda would be frozen before the thread finishes."""
        headers = {"Authorization": f"Bearer {api_key}"}
        if org_id:
            headers["X-Organization-ID"] = org_id
        self.http = httpx.Client(base_url=BASE_URL, headers=headers, timeout=60)
        self.collection = collection
        self.index_timeout = index_timeout
        self.background = background
        self.notices: queue.Queue[Notice] = queue.Queue()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        response = self.http.put(
            f"/v2/collections/{self.collection}",
            json={"description": "LLM PKM: personal facts"},
        )
        response.raise_for_status()

    def add(self, fact: Fact) -> str:
        with span("captain.submit"):
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

        if not self.background:
            return self._wait_for_index(job_id)
        threading.Thread(target=self._wait_in_background, args=(job_id, fact), daemon=True).start()
        return "Saved; Captain is indexing it in the background."

    def _wait_in_background(self, job_id: str, fact: Fact) -> None:
        """Wait for the job on a worker thread and queue the outcome, with its
        own timing report, for the CLI to show after the user's next entry."""
        with timing.turn(f"index: {fact.text}", kind="background index") as t:
            try:
                message = f'Indexed "{fact.text}": {self._wait_for_index(job_id)}'
                failed = False
            except Exception as e:
                message = f'Indexing FAILED for "{fact.text}": {e}'
                failed = True
        self.notices.put(Notice(message, failed, t))

    def _wait_for_index(self, job_id: str) -> str:
        with span("captain.wait_for_index") as s:
            polls = 0
            deadline = time.monotonic() + self.index_timeout
            while time.monotonic() < deadline:
                job = self.http.get(f"/v2/jobs/{job_id}").json()
                polls += 1
                status = job.get("status")
                if status in _DONE:
                    s.info.update(polls=polls, **_job_timings(job))
                if status == "completed":
                    return "Saved and indexed."
                if status in _DONE:
                    raise RuntimeError(
                        f"Captain indexing job {job_id} ended as {status}: "
                        f"{job.get('error_message') or job.get('result')}"
                    )
                time.sleep(1)
            s.info.update(polls=polls, timed_out=True)
        return f"Saved, but Captain is still indexing it (job {job_id}); it may not show up in searches for a little while."

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        with span("captain.query"):
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
