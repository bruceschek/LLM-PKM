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
    assert chat[1] == ["remember", "wiki_read", "rewind"] and "index.md right now" in chat[0]
    assert "- Now: " in chat[0] and "- Now: " in job[0]
    assert job[1] == ["wiki_read", "wiki_write", "wiki_log"] and job[2] == assistant.settings.wiki_model
    assert not (assistant.settings.data_dir / "facts.jsonl").exists()
    assert assistant.wiki.pending_raw() == []
    assert (assistant.wiki.root / "wiki/topics/Pets.md").exists()


def test_question_sees_the_index_and_unfinished_captures(assistant, monkeypatch):
    pending = assistant.wiki.save_raw("my dog is Rex")

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        assert "Raw sources not yet in the wiki" in system and pending in system
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


def capture(assistant, monkeypatch, history, text, fact, page, content):
    """One chat capture whose wiki update writes `page` and the index."""

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        if "remember" in [t["name"] for t in tools]:
            execute("remember", {"fact": fact})
            messages.append({"role": "assistant", "content": "Got it."})
            return "Got it."
        execute("wiki_write", {"path": page, "content": content})
        execute("wiki_write", {"path": "index.md", "content": f"# Index\n- {content}"})
        execute("wiki_log", {"kind": "ingest", "title": fact, "body": "x"})
        return "Done."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assistant.handle_message(text, history)


def test_rewind_takes_back_the_last_capture_only(assistant, monkeypatch):
    wiki, history = assistant.wiki, []
    capture(assistant, monkeypatch, history, "my dog is Rex", "Dog is Rex.", "wiki/topics/Pets.md", "Rex")
    after_first = {p: (wiki.root / p).read_text() for p in ("index.md", "log.md", "wiki/topics/Pets.md")}
    capture(assistant, monkeypatch, history, "also a cat, Tom", "Cat is Tom.", "wiki/topics/Pets.md", "Rex, Tom")
    capture(assistant, monkeypatch, history, "I like pho", "Likes pho.", "wiki/topics/Food.md", "pho")
    assert len(history) == 6 and wiki.counts() == (3, 2)

    out = assistant.rewind()
    assert "Likes pho." in out and "wiki/topics/Food.md" in out
    assert not (wiki.root / "wiki/topics/Food.md").exists()
    assert (wiki.root / "wiki/topics/Pets.md").read_text() == "Rex, Tom\n"
    assert wiki.counts() == (2, 1) and len(history) == 4

    assistant.rewind()  # a second rewind goes one further back
    assert {p: (wiki.root / p).read_text() for p in after_first} == after_first
    assert [m["content"] for m in history] == ["my dog is Rex", "Got it."]
    assert wiki.counts() == (1, 1) and wiki.pending_raw() == []

    assistant.rewind()
    assert wiki.counts() == (0, 0)
    assert assistant.rewind() == "Nothing to rewind."


def test_rewind_can_be_asked_for_in_plain_words(assistant, monkeypatch):
    history = []
    capture(assistant, monkeypatch, history, "my dog is Rex", "Dog is Rex.", "wiki/topics/Pets.md", "Rex")

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        return execute("rewind", {})

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assert "Dog is Rex." in assistant.handle_message("scratch that", history)
    assert assistant.wiki.counts() == (0, 0)
    assert [m["content"] for m in history] == ["scratch that"]  # the capture's turn is gone


def test_rewinding_an_ingest_keeps_a_file_the_user_dropped_in(assistant, monkeypatch):
    (assistant.wiki.root / "raw" / "article.md").write_text("Theo is Dana's son.")

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        execute("wiki_write", {"path": "wiki/people/Theo.md", "content": "Theo"})
        return "Done."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assistant.ingest_file("raw/article.md")
    assert "kept" in assistant.rewind()
    assert assistant.wiki.counts() == (1, 0) and assistant.wiki.pending_raw() == ["raw/article.md"]


def test_delete_all_needs_the_word_DELETE(assistant, monkeypatch, capsys):
    from llm_pkm import ambient, cli

    history = []
    capture(assistant, monkeypatch, history, "my dog is Rex", "Dog is Rex.", "wiki/topics/Pets.md", "Rex")
    ambient.save_owner(assistant.settings, "Dana Reyes")

    for answer in ("yes", "delete", ""):
        monkeypatch.setattr("builtins.input", lambda prompt: answer)
        cli.delete_all(assistant, history)
        assert assistant.wiki.counts() == (1, 1) and history
    assert capsys.readouterr().out.count("Nothing was deleted.") == 3

    monkeypatch.setattr("builtins.input", lambda prompt: "DELETE")
    cli.delete_all(assistant, history)
    wiki = assistant.wiki
    assert wiki.counts() == (0, 0) and history == []
    assert "Rex" not in wiki.read("index.md") and "Dog is Rex" not in wiki.read("log.md")
    assert assistant.rewind() == "Nothing to rewind."
    assert "Three layers" in wiki.schema() and ambient.owner_name(assistant.settings) == "Dana Reyes"
    assert not (assistant.settings.data_dir / "timings.jsonl").exists()


def test_pdf_is_sent_as_a_document_with_the_users_guidance(assistant, monkeypatch):
    (assistant.wiki.root / "raw" / "trip.pdf").write_bytes(b"%PDF-1.4 fake")
    (assistant.wiki.root / "raw" / "notes.txt").write_text("not a pdf")
    seen = []

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        seen.append(messages[0]["content"])
        execute("wiki_write", {"path": "wiki/topics/Trip.md", "content": "Trip"})
        return "Added Trip."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    assistant.queue_ingest("raw/trip.pdf", "Our Maui itinerary. Keep only the flight times.")
    document, text = seen[0]
    assert document["type"] == "document" and document["source"]["media_type"] == "application/pdf"
    assert "Keep only the flight times." in text["text"] and "[[raw/trip.pdf]]" in text["text"]
    [notice] = assistant.take_notices()
    assert notice.asked_for and notice.message == "Ingested raw/trip.pdf: Added Trip."
    assert assistant.wiki.pending_raw() == ["raw/notes.txt"]

    assert "kept" in assistant.rewind()  # the user's file is never deleted
    assert (assistant.wiki.root / "raw" / "trip.pdf").exists()
    assert not (assistant.wiki.root / "wiki/topics/Trip.md").exists()


def test_a_file_that_is_not_really_a_pdf_fails_and_stays_pending(assistant):
    (assistant.wiki.root / "raw" / "bad.pdf").write_bytes(b"hello")
    assistant.queue_ingest("raw/bad.pdf")
    [notice] = assistant.take_notices()
    assert notice.failed and "doesn't look like a PDF" in notice.message
    assert assistant.wiki.pending_raw() == ["raw/bad.pdf"]


def test_ingest_command_asks_which_file_and_what_to_keep(assistant, monkeypatch, capsys):
    from llm_pkm import cli

    queued = []
    monkeypatch.setattr(assistant, "queue_ingest", lambda rel, guidance=None: queued.append((rel, guidance)))
    cli.ingest(assistant, "")
    assert "No new files" in capsys.readouterr().out

    for name in ("a.md", "b.pdf"):
        (assistant.wiki.root / "raw" / name).write_bytes(b"%PDF x")
    answers = iter(["2", "the lease; keep the dates"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    cli.ingest(assistant, "")
    monkeypatch.setattr("builtins.input", lambda prompt: "")  # named file, no guidance
    cli.ingest(assistant, "a.md")
    cli.ingest(assistant, "nope.md")
    assert queued == [("raw/b.pdf", "the lease; keep the dates"), ("raw/a.md", None)]
    assert "No new file called 'nope.md'" in capsys.readouterr().out

    answers = iter(["", "all"])  # Enter cancels; "all" takes every file, without asking about each
    cli.ingest(assistant, "")
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    cli.ingest(assistant, "")
    cli.ingest(assistant, "")
    assert queued[2:] == [("raw/a.md", None), ("raw/b.pdf", None)]


def test_mistyped_command_is_not_sent_to_claude(assistant, monkeypatch, capsys):
    from types import SimpleNamespace

    from llm_pkm import cli

    def no_claude(*args, **kwargs):
        raise AssertionError("went to Claude")

    monkeypatch.setattr(core, "run_turn", no_claude)
    entries = iter(["/injest", "/status", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(entries))
    cli.chat(assistant, [], SimpleNamespace(timing=False, notices=False))
    out = capsys.readouterr().out
    assert "There is no /injest command. Did you mean /ingest?" in out
    assert "Nothing is running in the background." in out


def test_settings_in_tests_never_point_at_the_live_vault():
    import tempfile
    from pathlib import Path

    settings = Settings.from_env()
    assert Path(tempfile.gettempdir()).resolve() in settings.wiki_dir.resolve().parents
