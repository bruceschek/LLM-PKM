"""Everyday context: things anyone in the room would know without being told,
which aren't in the wiki. So far: who the owner is, the date and time, and public holidays.

Each provider is a function that takes the settings and returns one line
("Label: value"), or None when it has nothing to say. `everyday_context()` puts them all into the system
prompt of every conversation (chat and wiki maintenance), so knowing them
costs Claude no tool call. To add one, write a function and list it in
PROVIDERS. That suits things that are cheap to get and short to state; if one
is ever slow or only sometimes relevant (weather, the calendar), make it a
tool in llm.py instead."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import holidays

from .config import Settings

Provider = Callable[[Settings], str | None]

OWNER_FILE = ".owner"  # hidden, so Obsidian ignores it


def _owner_path(settings: Settings) -> Path:
    return (settings.wiki_dir or settings.data_dir) / OWNER_FILE


def owner_name(settings: Settings) -> str | None:
    """Whose memory this is: PKM_OWNER if set, else the name saved in the
    vault. None means nobody has said yet (the CLI asks at startup)."""
    if settings.owner:
        return settings.owner
    path = _owner_path(settings)
    return (path.read_text().strip() or None) if path.exists() else None


def save_owner(settings: Settings, name: str) -> None:
    path = _owner_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name.strip() + "\n")


def owner(settings: Settings) -> str | None:
    name = owner_name(settings)
    if not name:
        return None
    return (
        f"Owner: this memory belongs to one person, {name}. They are the only one "
        'who talks to you: "the user", "I" and "me" all mean them.'
    )


def now(settings: Settings, at: datetime | None = None) -> str:
    """The clock of the machine this runs on, in its own time zone."""
    at = (at or datetime.now()).astimezone()
    return f"Now: {at:%A, %Y-%m-%d, %H:%M} ({at:%Z}, UTC{at:%z})"


def public_holidays(settings: Settings, today: date | None = None) -> str | None:
    """The country's public holidays from a year back to a year ahead, with
    their dates, so "the Friday after Thanksgiving" or "last Christmas" can be
    worked out without guessing. PKM_COUNTRY=off turns it off."""
    if settings.country.lower() == "off":
        return None
    today = today or date.today()
    start, end = today - timedelta(days=365), today + timedelta(days=365)
    days = holidays.country_holidays(settings.country, years=range(start.year, end.year + 1))
    listed = [f"{day} {name}" for day, name in sorted(days.items()) if start <= day <= end]
    return f"Public holidays ({settings.country}): " + "; ".join(listed)


PROVIDERS: list[Provider] = [owner, now, public_holidays]


def everyday_context(settings: Settings) -> str:
    lines = [line for provider in PROVIDERS if (line := provider(settings))]
    if not lines:
        return ""
    return "\n\nThings you can take for granted:\n" + "\n".join(f"- {line}" for line in lines)
