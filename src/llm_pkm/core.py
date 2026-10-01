"""The single entry point: text in, reply out. No terminal or HTTP code here,
so the terminal loop (cli.py) and a future Lambda (lambda_handler.py) share it."""

import queue
import time

import anthropic

from . import timing
from .config import Settings
from .llm import SYSTEM, TOOLS, WIKI_SYSTEM, WIKI_TOOLS, run_turn
from .stores import Fact, LocalStore, MemoryStore, Notice, build_stores
from .timing import span
from .wiki import Wiki


MAX_INGEST_CHARS = 100_000  # longer sources are cut off


class Assistant:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        log: LocalStore,
        client: anthropic.Anthropic | None = None,
    ):
        self.settings = settings
        self.store = store
        self.log = log
        self.client = client or anthropic.Anthropic()
        self.wiki = Wiki(settings.wiki_dir) if settings.wiki_dir else None
        self.facts_saved = 0  # `remember` calls so far (to know when background saves are done)
        self.last_turn: timing.Turn | None = None  # step timings of the latest message

    @classmethod
    def from_env(cls, background: bool = False) -> "Assistant":
        """`background`: let saves finish on a worker thread (long-lived
        processes only); collect their outcomes with `take_notices`."""
        settings = Settings.from_env()
        store, log = build_stores(settings, background)
        return cls(settings, store, log)

    def take_notices(self) -> list[Notice]:
        """Outcomes of background saves that finished since the last call.
        Their timings are logged here, like a message's."""
        notices: queue.Queue[Notice] | None = getattr(self.store, "notices", None)
        taken = []
        while notices is not None and not notices.empty():
            notice = notices.get_nowait()
            timing.append_log(self._timings_path, notice.turn)
            taken.append(notice)
        return taken

    def wait_for_saves(self, timeout: float) -> list[Notice]:
        """Wait (up to `timeout` seconds) for every background save to report,
        for processes that are about to exit. Returns the outcomes."""
        notices: list[Notice] = []
        deadline = time.monotonic() + timeout
        while len(notices) < self.facts_saved and time.monotonic() < deadline:
            notices += self.take_notices()
            time.sleep(0.5)
        return notices

    @property
    def _timings_path(self):
        return self.settings.data_dir / "timings.jsonl"

    def handle_message(self, text: str, history: list[dict]) -> str:
        """Answer one user message. `history` is this conversation's messages
        so far; it is updated in place."""
        return self._converse(text, history, source_text=text, raw=None, label=text)

    def ingest_file(self, rel: str) -> str:
        """Fold one file that was dropped into the vault's raw/ folder into the
        wiki and the fact store (the "ingest" operation in SCHEMA.md). Returns
        Claude's short report. Marks the file ingested only if it succeeds."""
        if not self.wiki:
            raise RuntimeError("The wiki is off (PKM_WIKI_DIR=off); nothing to ingest into.")
        content = self.wiki.read_raw(rel)
        truncated = len(content) > MAX_INGEST_CHARS
        prompt = (
            f"Ingest the new raw source `{rel}` (already saved; don't save it again). "
            "Follow the wiki's ingest steps: summarize the takeaways, create or update "
            "the wiki pages it touches, update the index, and log it. Also call "
            "`remember` once for each distinct fact worth keeping, as a self-contained "
            "statement. If the source isn't about the user, phrase the fact about its "
            "subject (e.g. \"The Eiffel Tower is 330 m tall.\"), and say where it came "
            "from. Reply with one line saying what you did.\n\n"
            f"Contents of `{rel}`"
            + (f" (truncated to the first {MAX_INGEST_CHARS} characters)" if truncated else "")
            + f":\n\n{content[:MAX_INGEST_CHARS]}"
        )
        reply = self._converse(
            prompt, [], source_text=f"[{rel}] {content[:500]}", raw=rel.removesuffix(".md"), label=f"ingest {rel}"
        )
        self.wiki.mark_ingested(rel)
        return reply

    def _converse(
        self, text: str, history: list[dict], source_text: str, raw: str | None, label: str
    ) -> str:
        """Run one user turn. `raw`: the wiki raw source this turn is about,
        if it already exists; otherwise `remember` saves `text` as one."""
        history.append({"role": "user", "content": text})
        raw_path: list[str] = [raw] if raw else []  # saved at most once per turn

        def execute(name: str, args: dict) -> str:
            with span(name):
                if name == "remember":
                    fact = Fact(text=args["fact"], source_text=source_text)
                    if self.log is not self.store:
                        self.log.add(fact)
                    result = self.store.add(fact)
                    self.facts_saved += 1
                    if self.wiki:
                        if not raw_path:
                            raw_path.append(self.wiki.save_raw(text))
                        result += f" Raw source saved as {raw_path[0]}."
                    return result
                if self.wiki and name == "wiki_read":
                    path = args["path"]
                    return self.wiki.list_pages() if path == "LIST" else self.wiki.read(path)
                if self.wiki and name == "wiki_write":
                    return self.wiki.write(args["path"], args["content"])
                if self.wiki and name == "wiki_log":
                    return self.wiki.log(args["kind"], args["title"], args["body"])
                if name == "recall":
                    hits = self.store.search(args["query"])
                    if not hits:
                        return "No matching facts."
                    return "\n".join(f"- [saved {h.created_at or 'unknown'}] {h.text}" for h in hits)
                raise ValueError(f"Unknown tool {name!r}")

        system, tools = SYSTEM, TOOLS
        if self.wiki:
            system = SYSTEM + WIKI_SYSTEM + self.wiki.schema()
            tools = TOOLS + WIKI_TOOLS
        try:
            with timing.turn(label) as t:
                return run_turn(self.client, self.settings, history, execute, system, tools)
        finally:  # after the `with`, so the turn's total time is filled in
            self.last_turn = t
            timing.append_log(self._timings_path, t)
