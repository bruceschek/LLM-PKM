"""PKM_STORE=wiki: no fact store; the wiki is the memory."""

import dataclasses

import pytest

from llm_pkm import core
from llm_pkm.config import Settings
from llm_pkm.core import Assistant
from llm_pkm.stores import build_stores


@pytest.fixture
def assistant(tmp_path):
    settings = dataclasses.replace(
        Settings.from_env(), store="wiki", data_dir=tmp_path, wiki_dir=tmp_path / "wiki"
    )
    store, log = build_stores(settings)
    assert store is None
    return Assistant(settings, store, log, client=object())


def test_needs_the_wiki(tmp_path):
    settings = dataclasses.replace(Settings.from_env(), store="wiki", data_dir=tmp_path, wiki_dir=None)
    with pytest.raises(RuntimeError):
        Assistant(settings, None, build_stores(settings)[1], client=object())


def test_capture_goes_to_raw_and_then_the_wiki(assistant, monkeypatch):
    calls = []

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        calls.append((system, [t["name"] for t in tools], model))
        if len(calls) == 1:  # the chat turn
            assert "Saved." in execute("remember", {"fact": "The user's dog is Rex."})
            assert len(assistant.wiki.pending_raw()) == 1  # not in the wiki yet
            return "Got it."
        assert "The user's dog is Rex." in messages[0]["content"]  # the wiki job
        execute("wiki_write", {"path": "wiki/topics/Pets.md", "content": "Rex."})
        return "Added Pets."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assert assistant.handle_message("my dog is Rex", []) == "Got it."

    chat, job = calls
    assert chat[1] == ["remember", "wiki_read"] and "index.md right now" in chat[0]
    assert "- Now: " in chat[0] and "- Now: " in job[0]
    assert job[1] == ["wiki_read", "wiki_write", "wiki_log"] and job[2] == assistant.settings.wiki_model
    assert not (assistant.settings.data_dir / "facts.jsonl").exists()
    assert assistant.wiki.pending_raw() == []
    assert (assistant.wiki.root / "wiki/topics/Pets.md").exists()


def test_question_sees_the_index_and_unfinished_captures(assistant, monkeypatch):
    pending = assistant.wiki.save_raw("my dog is Rex")

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        assert "Captures not yet in the wiki" in system and pending in system
        assert "my dog is Rex" in execute("wiki_read", {"path": pending})
        return "Rex."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assert assistant.handle_message("what is my dog called?", []) == "Rex."


def test_failed_wiki_update_leaves_the_capture_for_pkm_ingest(assistant, monkeypatch):
    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        if "remember" in [t["name"] for t in tools]:
            execute("remember", {"fact": "The user's dog is Rex."})
            return "Got it."
        raise OSError("network down")

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assistant.handle_message("my dog is Rex", [])
    [notice] = assistant.take_notices()
    assert notice.failed and len(assistant.wiki.pending_raw()) == 1


def test_ingest_and_lint_use_only_the_wiki_tools(assistant, monkeypatch):
    (assistant.wiki.root / "raw" / "article.md").write_text("Theo is Dana's son.")
    seen = []

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        seen.append(messages[0]["content"])
        assert [t["name"] for t in tools] == ["wiki_read", "wiki_write", "wiki_log"]
        assert "Three layers" in system  # the schema
        return "Done."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assert assistant.ingest_file("raw/article.md") == "Done."
    assert "Theo is Dana's son." in seen[0] and "`remember`" not in seen[0]
    assert assistant.wiki.pending_raw() == []
    assert assistant.lint() == "Done."
    assert "lint-checklist.md" in seen[1]
