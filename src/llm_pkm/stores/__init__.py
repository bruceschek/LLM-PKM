from ..config import Settings
from .base import Fact, Hit, MemoryStore, Notice
from .captain import CaptainStore
from .cloudflare import CloudflareStore
from .local import LocalStore

__all__ = ["Fact", "Hit", "MemoryStore", "Notice", "CaptainStore", "CloudflareStore", "LocalStore", "build_stores"]


def build_stores(
    settings: Settings, background: bool = False
) -> tuple[MemoryStore | None, LocalStore]:
    """Return (retrieval store, raw fact log). With PKM_STORE=wiki there is no
    retrieval store (the wiki is the memory, and the log goes unused); with
    PKM_STORE=local they are the same object. `background` lets a slow store
    finish saves on a worker thread (see CaptainStore)."""
    log = LocalStore(settings.data_dir / "facts.jsonl")
    if settings.store == "wiki":
        return None, log
    if settings.store == "local":
        return log, log
    if settings.store == "captain":
        if not settings.captain_api_key:
            raise RuntimeError("CAPTAIN_API_KEY is not set (or set PKM_STORE=local).")
        store = CaptainStore(
            settings.captain_api_key,
            settings.captain_collection,
            settings.captain_org_id,
            settings.index_timeout,
            background,
        )
        return store, log
    if settings.store == "cloudflare":
        if not (settings.cloudflare_account_id and settings.cloudflare_api_token):
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN must be set (or set PKM_STORE=local)."
            )
        store = CloudflareStore(
            settings.cloudflare_account_id,
            settings.cloudflare_api_token,
            settings.cloudflare_index,
            settings.index_timeout,
            background,
        )
        return store, log
    raise RuntimeError(
        f"Unknown PKM_STORE {settings.store!r}; use 'wiki', 'cloudflare', 'captain' or 'local'."
    )
