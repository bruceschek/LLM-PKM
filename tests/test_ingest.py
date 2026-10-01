import dataclasses

import pytest

from llm_pkm import core
from llm_pkm.config import Settings
from llm_pkm.core import Assistant
from llm_pkm.stores import LocalStore


@pytest.fixture
def assistant(tmp_path):
    settings = dataclasses.replace(
        Settings.from_env(), store="local", data_dir=tmp_path, wiki_dir=tmp_path / "wiki"
    )
    log = LocalStore(tmp_path / "facts.jsonl")
    return Assistant(settings, log, log, client=object())


def test_ingest_remembers_facts_without_new_raw_file(assistant, monkeypatch):
    (assistant.wiki.root / "raw" / "article.md").write_text("Theo is Dana's son.")

    def fake_run_turn(client, settings, messages, execute, system, tools):
        assert "raw/article.md" in messages[0]["content"]
        assert "Theo is Dana's son." in messages[0]["content"]
        assert "Raw source saved as raw/article." in execute("remember", {"fact": "Theo is Dana's son."})
        execute("wiki_write", {"path": "wiki/people/Theo.md", "content": "# Theo"})
        return "Ingested."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assert assistant.ingest_file("raw/article.md") == "Ingested."

    assert [f.text for f in assistant.log.all()] == ["Theo is Dana's son."]
    assert sorted(p.name for p in (assistant.wiki.root / "raw").iterdir()) == ["article.md"]
    assert assistant.wiki.pending_raw() == []
    assert (assistant.wiki.root / "wiki/people/Theo.md").exists()


def test_failed_ingest_stays_pending(assistant, monkeypatch):
    (assistant.wiki.root / "raw" / "x.md").write_text("x")

    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(core, "run_turn", boom)
    with pytest.raises(OSError):
        assistant.ingest_file("raw/x.md")
    assert assistant.wiki.pending_raw() == ["raw/x.md"]


def test_chat_reply_does_not_wait_for_wiki_update(assistant, monkeypatch):
    """With background=True the wiki job is queued; a worker runs it later."""
    import threading

    assistant.background = True
    gate = threading.Event()
    calls = []

    def fake_run_turn(client, settings, messages, execute, system, tools):
        calls.append([t["name"] for t in tools])
        if len(calls) == 1:  # the chat turn: only wiki_read among wiki tools
            execute("remember", {"fact": "The user's dog is Rex."})
            return "Got it."
        gate.wait(5)  # the wiki job
        assert "The user's dog is Rex." in messages[0]["content"]
        execute("wiki_write", {"path": "wiki/topics/Pets.md", "content": "# Pets"})
        return "Added Pets."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    history = []
    assert assistant.handle_message("my dog is Rex", history) == "Got it."
    assert "wiki_write" not in calls[0] and "wiki_read" in calls[0]
    assert not (assistant.wiki.root / "wiki/topics/Pets.md").exists()  # reply came first
    gate.set()
    notices = assistant.wait_for_saves(5)
    assert [n.message for n in notices] == ["Wiki updated: Added Pets."]
    assert (assistant.wiki.root / "wiki/topics/Pets.md").exists()
    assert assistant.pending_notices() == 0


def test_recall_includes_recent_facts_the_store_misses(tmp_path):
    from llm_pkm.stores import Fact, Hit

    class SlowStore:  # hasn't indexed anything yet
        def add(self, fact):
            return "Saved"

        def search(self, query, limit=5):
            return []

    settings = dataclasses.replace(
        Settings.from_env(), store="local", data_dir=tmp_path, wiki_dir=None
    )
    log = LocalStore(tmp_path / "facts.jsonl")
    log.add(Fact("The user's dog is Rex.", "my dog is Rex"))
    old = Fact("Old fact.", "old", created_at="2020-01-01T00:00:00+00:00")
    log.add(old)
    out = Assistant(settings, SlowStore(), log, client=object())._recall("dog name")
    assert "The user's dog is Rex." in out and "Old fact." not in out
