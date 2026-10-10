"""--script: a text file fed to the chat, one entry per line."""

import argparse
import dataclasses

import pytest

from llm_pkm import cli, core
from llm_pkm.config import Settings
from llm_pkm.core import Assistant
from llm_pkm.stores import build_stores


@pytest.fixture
def assistant(tmp_path):
    settings = dataclasses.replace(
        Settings.from_env(), store="wiki", data_dir=tmp_path, wiki_dir=tmp_path / "wiki"
    )
    store, log = build_stores(settings)
    return Assistant(settings, store, log, client=object(), background=True)


def run(assistant, tmp_path, text):
    script = tmp_path / "script.txt"
    script.write_text(text)
    cli.run_script(assistant, [], argparse.Namespace(script=script, timing=False, notices=False))


def test_each_line_waits_for_the_wiki(assistant, tmp_path, monkeypatch, capsys):
    events = []

    def fake_run_turn(client, settings, messages, execute, system, tools, model=None):
        if "wiki_write" in [t["name"] for t in tools]:  # the wiki job, on the worker thread
            events.append("wiki")
            if "Rex" in messages[0]["content"]:
                raise RuntimeError("boom")
            return "Added a page."
        text = messages[-1]["content"]
        events.append(text)
        if text.endswith("?"):
            return "Theo."
        execute("remember", {"fact": text})
        return "Got it."

    monkeypatch.setattr(core, "run_turn", fake_run_turn)
    run(assistant, tmp_path, "# people\nDana's kid is Theo\n\nmy dog is Rex\nwho is Dana's kid?\n/nope\n")

    assert events == ["Dana's kid is Theo", "wiki", "my dog is Rex", "wiki", "who is Dana's kid?"]
    out = capsys.readouterr().out
    assert "[1/4, line 2] you> Dana's kid is Theo" in out
    assert "s] Wiki updated: Added a page." in out
    assert "[FAILED, " in out and "boom" in out
    assert "pkm> Theo." in out
    assert "Script done: 4 of 4 entries, 1 wiki update(s), 2 problem(s)" in out
    assert "Problems at line(s): 4, 6" in out


def test_script_cannot_delete_all_and_quit_stops_it(assistant, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core, "run_turn", lambda *a, **k: pytest.fail("nothing should reach Claude"))
    assistant.wiki.save_raw("my dog is Rex")
    run(assistant, tmp_path, "/delete-all\nquit\nmy cat is Tom\n")

    assert assistant.wiki.counts()[0] == 1
    out = capsys.readouterr().out
    assert "Nothing was deleted." in out and "Tom" not in out
    assert "Script done: 1 of 3 entries" in out


def test_outside_knowledge_is_blue_to_the_end_of_its_paragraph(monkeypatch, capsys):
    monkeypatch.setattr(cli, "colored", lambda: True)
    cli.say_reply("Not in your wiki yet.\n\nNot from your wiki: Paris.\n- on the Seine\n\n(from [[France]])")
    wiki, blank, first, second, blank2, cited = capsys.readouterr().out.split("\n")[:6]
    blue = cli.OUTSIDE_COLOR
    assert blue not in wiki and blue not in cited
    assert first == f"{blue}Not from your wiki: Paris.{cli.REPLY}"
    assert second == f"{blue}- on the Seine{cli.REPLY}"
