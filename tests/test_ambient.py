import dataclasses
from datetime import date, datetime

from llm_pkm import ambient
from llm_pkm.config import Settings

SETTINGS = dataclasses.replace(Settings.from_env(), country="US", owner=None)


def test_now_gives_weekday_date_and_time():
    line = ambient.now(SETTINGS, datetime(2026, 10, 6, 13, 15))
    assert line.startswith("Now: Tuesday, 2026-10-06, 13:15 (")


def test_public_holidays_cover_a_year_each_way():
    line = ambient.public_holidays(SETTINGS, date(2026, 10, 6))
    assert line.startswith("Public holidays (US): ")
    assert "2026-11-26 Thanksgiving Day" in line and "2025-12-25 Christmas Day" in line
    assert "2025-09-01" not in line and "2027-11-25" not in line  # outside the window
    assert ambient.public_holidays(dataclasses.replace(SETTINGS, country="off")) is None


def test_everyday_context_lists_every_provider(monkeypatch):
    monkeypatch.setattr(ambient, "PROVIDERS", [lambda s: "A: 1", lambda s: None, lambda s: "B: 2"])
    assert ambient.everyday_context(SETTINGS).endswith("- A: 1\n- B: 2")
    monkeypatch.setattr(ambient, "PROVIDERS", [])
    assert ambient.everyday_context(SETTINGS) == ""


def test_owner_is_unknown_until_saved_in_the_vault(tmp_path):
    settings = dataclasses.replace(SETTINGS, wiki_dir=tmp_path / "wiki", data_dir=tmp_path)
    assert ambient.owner_name(settings) is None and ambient.owner(settings) is None
    ambient.save_owner(settings, " Dana Reyes ")
    assert ambient.owner_name(settings) == "Dana Reyes"
    assert "belongs to one person, Dana Reyes" in ambient.owner(settings)
    assert ambient.owner_name(dataclasses.replace(settings, owner="Sam")) == "Sam"


def test_cli_asks_for_the_owner_once(tmp_path, monkeypatch, capsys):
    from llm_pkm import cli

    settings = dataclasses.replace(SETTINGS, wiki_dir=tmp_path / "wiki", data_dir=tmp_path)
    answers = iter(["", "Dana Reyes"])  # an empty answer is asked again
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert cli.ask_owner(settings) is True
    assert ambient.owner_name(settings) == "Dana Reyes"

    def quit_(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", quit_)
    assert cli.ask_owner(dataclasses.replace(settings, wiki_dir=tmp_path / "other")) is False
