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
