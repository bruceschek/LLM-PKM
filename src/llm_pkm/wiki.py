"""The wiki layer: a folder of markdown files (an Obsidian vault) that Claude
maintains, following Karpathy's LLM Wiki pattern. See `wiki-example/SCHEMA.md`.

The live vault holds real user data and lives under `data/` (git-ignored).
`wiki-example/` in the repo is invented sample data only.

Claude gets three tools (read, write, log). They are confined to the vault:
raw sources are written only by `save_raw`, and `write` only touches
`index.md` and pages under `wiki/`."""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "wiki-example"
RAW_SUFFIXES = {".md", ".txt"}  # what `pkm-ingest` picks up from raw/
MANIFEST = ".ingested.json"  # hidden, so Obsidian ignores it
SEED_FILES = (  # copied from the example into a vault that lacks them
    "SCHEMA.md",
    "lint-checklist.md",
    ".obsidian/core-plugins.json",
    ".obsidian/graph.json",  # colors raw sources, people, places and topics apart
)


class Wiki:
    def __init__(self, root: Path):
        self.root = root
        self._seed()

    def _seed(self) -> None:
        """Create an empty vault: the rules, a blank index and log."""
        for sub in ("raw", "wiki"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        for name in SEED_FILES:
            if not (self.root / name).exists() and (EXAMPLE_DIR / name).exists():
                (self.root / name).parent.mkdir(exist_ok=True)
                shutil.copy(EXAMPLE_DIR / name, self.root / name)
        if not (self.root / "index.md").exists():
            (self.root / "index.md").write_text(
                "# Index\n\nCatalog of every wiki page, one line each. "
                "Rules: [[SCHEMA]]. History: [[log]].\n\n## People\n\n## Places\n\n"
                "## Topics\n\n## Raw sources\n"
            )
        if not (self.root / "log.md").exists():
            (self.root / "log.md").write_text(
                "# Log\n\nAppend-only. Newest at the bottom.\n"
            )

    def schema(self) -> str:
        path = self.root / "SCHEMA.md"
        return path.read_text() if path.exists() else ""

    def _resolve(self, path: str, *, write: bool = False) -> Path:
        rel = Path(path)
        if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".md":
            raise ValueError(f"Bad path {path!r}: use a relative .md path inside the vault.")
        full = (self.root / rel).resolve()
        if not full.is_relative_to(self.root.resolve()):
            raise ValueError(f"Bad path {path!r}: outside the vault.")
        if write and rel.parts[0] != "wiki" and rel.as_posix() != "index.md":
            raise ValueError("Can only write index.md and pages under wiki/.")
        return full

    def read(self, path: str) -> str:
        """Read a file by vault path, or a page by its title the way Obsidian
        resolves a link: `Dana`, `[[Dana]]` and `wiki/people/Dana.md` all work."""
        name = path.strip().removeprefix("[[").removesuffix("]]")
        name = re.split(r"[|#]", name)[0].strip()  # drop a link's alias or heading
        if not name.endswith(".md"):
            name += ".md"
        full = self._resolve(name)
        if not full.exists():
            matches = sorted(self.root.rglob(Path(name).name)) if "/" not in name else []
            if not matches:
                return f"No such page: {path}"
            full = matches[0]
        return full.read_text()

    def list_pages(self) -> str:
        pages = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*.md"))
        return "\n".join(pages)

    def write(self, path: str, content: str) -> str:
        full = self._resolve(path, write=True)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content if content.endswith("\n") else content + "\n")
        return f"Wrote {path}."

    def log(self, kind: str, title: str, body: str, now: datetime | None = None) -> str:
        if kind not in ("ingest", "query", "lint", "schema"):
            raise ValueError("kind must be ingest, query, lint or schema.")
        now = now or datetime.now()
        with (self.root / "log.md").open("a") as f:
            f.write(f"\n## [{now:%Y-%m-%d}] {kind} | {title}\n{body.strip()}\n")
        return "Logged."

    def save_raw(self, text: str, now: datetime | None = None) -> str:
        """Store one user message as an immutable raw source; return its
        vault path (for citing). It counts as pending until `mark_ingested`."""
        now = now or datetime.now()
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "capture"
        name = f"{now:%Y-%m-%d-%H%M%S}-{slug}"
        (self.root / "raw" / f"{name}.md").write_text(
            f"---\ncaptured: {now.isoformat(timespec='seconds')}\nvia: chat\n---\n"
            f"Raw source. Do not edit.\n\n{text}\n"
        )
        return f"raw/{name}"

    def _manifest(self) -> dict[str, str]:
        path = self.root / MANIFEST
        return json.loads(path.read_text()) if path.exists() else {}

    def mark_ingested(self, rel: str, now: datetime | None = None) -> None:
        manifest = self._manifest()
        manifest[rel] = (now or datetime.now()).isoformat(timespec="seconds")
        (self.root / MANIFEST).write_text(json.dumps(manifest, indent=1) + "\n")

    def pending_raw(self) -> list[str]:
        """Vault-relative paths of files in raw/ (chat captures and files
        dropped in by hand) not yet folded into the wiki, oldest name first."""
        done = self._manifest()
        found = (
            p.relative_to(self.root).as_posix()
            for p in (self.root / "raw").rglob("*")
            if p.is_file() and p.suffix in RAW_SUFFIXES and not p.name.startswith(".")
        )
        return sorted(rel for rel in found if rel not in done)

    def read_raw(self, rel: str) -> str:
        return (self.root / rel).read_text()
