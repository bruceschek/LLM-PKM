from ..config import Settings
from .base import Fact, Hit, MemoryStore, Notice
from .captain import CaptainStore
from .local import LocalStore

__all__ = ["Fact", "Hit", "MemoryStore", "Notice", "CaptainStore", "LocalStore", "build_stores"]


def build_stores(
    settings: Settings, background: bool = False
) -> tuple[MemoryStore, LocalStore]:
    """Return (retrieval store, raw fact log). With PKM_STORE=local they are
    the same object. `background` lets a slow store finish saves on a worker
    thread (see CaptainStore)."""
    log = LocalStore(settings.data_dir / "facts.jsonl")
    if settings.store == "local":
        return log, log
    if settings.store == "captain":
        if not settings.captain_api_key:
            raise RuntimeError("CAPTAIN_API_KEY is not set (or set PKM_STORE=local).")
        store = CaptainStore(
            settings.captain_api_key,
            settings.captain_collection,
            settings.captain_org_id,
            settings.captain_index_timeout,
            background,
        )
        return store, log
    raise RuntimeError(f"Unknown PKM_STORE {settings.store!r}; use 'captain' or 'local'.")
