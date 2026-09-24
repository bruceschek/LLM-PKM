import time

import httpx

from llm_pkm.stores import CaptainStore, Fact


def fake_captain(final_status: str) -> httpx.MockTransport:
    """Accepts one indexing job, reports it running once, then final_status."""
    polls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"job_id": "job1", "status": "pending"})
        polls["n"] += 1
        if polls["n"] == 1:
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(
            200,
            json={
                "status": final_status,
                "error_message": "boom" if final_status == "failed" else None,
                "created_at": "2026-09-23T10:00:00Z",
                "started_at": "2026-09-23T10:00:00Z",
                "completed_at": "2026-09-23T10:00:12Z",
            },
        )

    return httpx.MockTransport(handler)


def background_store(monkeypatch, final_status: str) -> CaptainStore:
    monkeypatch.setattr(CaptainStore, "_ensure_collection", lambda self: None)
    monkeypatch.setattr("llm_pkm.stores.captain.time.sleep", lambda s: None)
    store = CaptainStore("key", "test", background=True)
    store.http = httpx.Client(base_url="https://captain.test", transport=fake_captain(final_status))
    return store


def wait_for_notice(store: CaptainStore):
    deadline = time.monotonic() + 5
    while store.notices.empty():
        assert time.monotonic() < deadline, "no notice from the background thread"
        time.sleep(0.01)
    return store.notices.get_nowait()


def test_add_returns_before_indexing_and_reports_later(monkeypatch):
    store = background_store(monkeypatch, "completed")

    assert "background" in store.add(Fact("The test widget is blue.", "x"))

    notice = wait_for_notice(store)
    assert not notice.failed
    assert "The test widget is blue." in notice.message
    [wait] = notice.turn.spans
    assert wait.name == "captain.wait_for_index"
    assert wait.info["captain_processing_s"] == 12.0
    assert notice.turn.kind == "background index"


def test_background_failure_is_reported(monkeypatch):
    store = background_store(monkeypatch, "failed")
    store.add(Fact("The test widget is red.", "x"))

    notice = wait_for_notice(store)
    assert notice.failed
    assert "boom" in notice.message
