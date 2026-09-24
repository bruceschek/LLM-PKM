"""All settings come from environment variables so the same code runs in a
terminal (via a .env file) and in AWS Lambda (via function configuration)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    store: str  # "captain" or "local"
    model: str
    effort: str
    data_dir: Path
    captain_api_key: str | None
    captain_org_id: str | None
    captain_collection: str
    captain_index_timeout: float
    show_timing: bool  # print step timings after each reply

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            store=os.environ.get("PKM_STORE", "captain"),
            model=os.environ.get("PKM_MODEL", "claude-opus-5"),
            effort=os.environ.get("PKM_EFFORT", "low"),
            data_dir=Path(os.environ.get("PKM_DATA_DIR", "data")),
            captain_api_key=os.environ.get("CAPTAIN_API_KEY"),
            captain_org_id=os.environ.get("CAPTAIN_ORG_ID"),
            captain_collection=os.environ.get("CAPTAIN_COLLECTION", "llm_pkm"),
            captain_index_timeout=float(os.environ.get("CAPTAIN_INDEX_TIMEOUT", "90")),
            show_timing=os.environ.get("PKM_TIMING", "1") != "0",
        )
