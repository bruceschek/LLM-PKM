"""The single entry point: text in, reply out. No terminal or HTTP code here,
so the terminal loop (cli.py) and a future Lambda (lambda_handler.py) share it."""

import queue

import anthropic

from . import timing
from .config import Settings
from .llm import SYSTEM, TOOLS, WIKI_SYSTEM, WIKI_TOOLS, run_turn
from .stores import Fact, LocalStore, MemoryStore, Notice, build_stores
from .timing import span
from .wiki import Wiki


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

    @property
    def _timings_path(self):
        return self.settings.data_dir / "timings.jsonl"

    def handle_message(self, text: str, history: list[dict]) -> str:
        """Answer one user message. `history` is this conversation's messages
        so far; it is updated in place."""
        history.append({"role": "user", "content": text})

        raw_path: list[str] = []  # this message's raw wiki source, saved once

        def execute(name: str, args: dict) -> str:
            with span(name):
                if name == "remember":
                    fact = Fact(text=args["fact"], source_text=text)
                    if self.log is not self.store:
                        self.log.add(fact)
                    result = self.store.add(fact)
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
            with timing.turn(text) as t:
                return run_turn(self.client, self.settings, history, execute, system, tools)
        finally:  # after the `with`, so the turn's total time is filled in
            self.last_turn = t
            timing.append_log(self._timings_path, t)
