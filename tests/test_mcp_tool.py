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
    return Assistant(settings, store, log, client=object())


def test_remember_saves_raw_from_source_text(assistant):
    result = assistant.mcp_tool(
        "remember",
        {"fact": "The user's cat is Luna.", "source_text": "my cat is Luna", "doubt": ""},
    )
    assert result == "Got it."
    raw_files = list((assistant.wiki.root / "raw").glob("*.md"))
    assert len(raw_files) == 1
    assert "my cat is Luna" in raw_files[0].read_text()


def test_remember_falls_back_to_fact_when_source_text_empty(assistant):
    assistant.mcp_tool(
        "remember",
        {"fact": "The user's cat is Luna.", "source_text": "", "doubt": ""},
    )
    raw_files = list((assistant.wiki.root / "raw").glob("*.md"))
    assert len(raw_files) == 1
    assert "The user's cat is Luna." in raw_files[0].read_text()


def test_remember_queues_wiki_job(assistant):
    assert assistant.wiki_jobs == 0
    assistant.mcp_tool(
        "remember",
        {"fact": "The user's cat is Luna.", "source_text": "my cat is Luna", "doubt": ""},
    )
    assert assistant.wiki_jobs == 1


def test_remember_with_doubt_includes_outside_line(assistant):
    result = assistant.mcp_tool(
        "remember",
        {
            "fact": "The user says Lisbon is the capital of Spain.",
            "source_text": "Lisbon is the capital of Spain",
            "doubt": "Lisbon is the capital of Portugal, not Spain.",
        },
    )
    assert "Got it." in result
    assert "Not from your wiki:" in result
    assert "Portugal" in result


def test_wiki_read_returns_page_content(assistant):
    assistant.wiki.write("wiki/people/Dana.md", "# Dana\n\nA friend.")
    result = assistant.mcp_tool("wiki_read", {"path": "Dana"})
    assert "A friend." in result


def test_wiki_read_list_returns_file_listing(assistant):
    assistant.wiki.write("wiki/people/Dana.md", "# Dana")
    result = assistant.mcp_tool("wiki_read", {"path": "LIST"})
    assert "wiki/people/Dana.md" in result


def test_rewind_nothing_to_rewind(assistant):
    result = assistant.mcp_tool("rewind", {})
    assert result == "Nothing to rewind."


def test_mcp_tool_lint_calls_lint_synchronously(assistant, monkeypatch):
    called = []

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        called.append(True)
        execute("wiki_log", {"kind": "lint", "title": "lint pass", "body": "All good."})
        return "No issues found."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    result = assistant.mcp_tool("lint", {})
    assert "No issues found." in result
    assert called


def test_unknown_tool_raises(assistant):
    with pytest.raises(ValueError, match="Unknown MCP tool"):
        assistant.mcp_tool("bogus", {})


def test_main_exits_when_wiki_dir_is_off(monkeypatch, tmp_path):
    import dataclasses
    from llm_pkm import mcp_server

    no_wiki = dataclasses.replace(Settings.from_env(), wiki_dir=None, data_dir=tmp_path)
    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: no_wiki))
    with pytest.raises(SystemExit):
        mcp_server.main()
