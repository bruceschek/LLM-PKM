"""All settings come from environment variables so the same code runs in a
terminal (via a .env file) and in AWS Lambda (via function configuration)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    store: str  # "wiki" (no fact store: the wiki is the memory), "cloudflare", "captain" or "local"
    model: str  # chat turns: fast, since the user waits for these
    wiki_model: str  # wiki updates and file ingest: run in the background, so quality over speed
    lint_model: str  # lint passes: rare and all judgment, so it can be a stronger model than wiki_model
    effort: str
    data_dir: Path
    captain_api_key: str | None
    captain_org_id: str | None
    captain_collection: str
    cloudflare_account_id: str | None
    cloudflare_api_token: str | None
    cloudflare_index: str
    index_timeout: float  # longest wait for a new fact to become searchable
    wiki_dir: Path | None  # the Obsidian vault Claude maintains; None turns the wiki off
    owner: str | None  # the one person this memory belongs to; if unset, the name saved in the vault
    country: str  # whose public holidays Claude is told about (ISO code), or "off"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            store=os.environ.get("PKM_STORE", "wiki"),
            model=os.environ.get("PKM_MODEL", "claude-haiku-4-5-20251001"),
            wiki_model=os.environ.get("PKM_WIKI_MODEL", "claude-opus-5"),
            lint_model=os.environ.get("PKM_LINT_MODEL")
            or os.environ.get("PKM_WIKI_MODEL", "claude-opus-5"),
            effort=os.environ.get("PKM_EFFORT", "low"),
            data_dir=Path(os.environ.get("PKM_DATA_DIR", "data")),
            captain_api_key=os.environ.get("CAPTAIN_API_KEY"),
            captain_org_id=os.environ.get("CAPTAIN_ORG_ID"),
            captain_collection=os.environ.get("CAPTAIN_COLLECTION", "llm_pkm"),
            cloudflare_account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID"),
            cloudflare_api_token=os.environ.get("CLOUDFLARE_API_TOKEN"),
            cloudflare_index=os.environ.get("CLOUDFLARE_VECTORIZE_INDEX", "llm-pkm"),
            index_timeout=float(os.environ.get("PKM_INDEX_TIMEOUT", "90")),
            wiki_dir=_wiki_dir(),
            owner=os.environ.get("PKM_OWNER") or None,
            country=os.environ.get("PKM_COUNTRY", "US"),
        )


def _wiki_dir() -> Path | None:
    """PKM_WIKI_DIR sets the vault; "off" disables the wiki layer. The default
    is under the (git-ignored) data dir because it holds real personal data."""
    value = os.environ.get("PKM_WIKI_DIR")
    if value and value.lower() == "off":
        return None
    return Path(value) if value else Path(os.environ.get("PKM_DATA_DIR", "data")) / "wiki"
