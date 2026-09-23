"""The storage interface. Anything that can save a fact and search facts by a
natural-language query can back the tool: Captain today, maybe our own AWS
vector store later."""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class Fact:
    text: str  # self-contained statement, e.g. "The user's wife's name is Hemmie."
    source_text: str  # exactly what the user typed or said
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Hit:
    text: str
    score: float
    created_at: str | None = None


class MemoryStore(Protocol):
    def add(self, fact: Fact) -> str:
        """Save a fact. Returns a short status message for the model."""
        ...

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        """Return the facts that best match the query, best first."""
        ...
