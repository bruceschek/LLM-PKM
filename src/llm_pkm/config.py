"""All settings come from environment variables so the same code runs in a
terminal (via a .env file) and in AWS Lambda (via function configuration)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    store: str  # "cloudflare", "captain" or "local"
    model: str
    effort: str
    data_dir: Path
    captain_api_key: str | None
    captain_org_id: str | None
    captain_collection: str
    cloudflare_account_id: str | None
    cloudflare_api_token: str | None
    cloudflare_index: str
    index_timeout: float  # longest wait for a new fact to become searchable

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            store=os.environ.get("PKM_STORE", "cloudflare"),
            model=os.environ.get("PKM_MODEL", "claude-opus-5"),
            effort=os.environ.get("PKM_EFFORT", "low"),
            data_dir=Path(os.environ.get("PKM_DATA_DIR", "data")),
            captain_api_key=os.environ.get("CAPTAIN_API_KEY"),
            captain_org_id=os.environ.get("CAPTAIN_ORG_ID"),
            captain_collection=os.environ.get("CAPTAIN_COLLECTION", "llm_pkm"),
            cloudflare_account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID"),
            cloudflare_api_token=os.environ.get("CLOUDFLARE_API_TOKEN"),
            cloudflare_index=os.environ.get("CLOUDFLARE_VECTORIZE_INDEX", "llm-pkm"),
            index_timeout=float(os.environ.get("PKM_INDEX_TIMEOUT", "90")),
        )
