"""The single entry point: text in, reply out. No terminal or HTTP code here,
so the terminal loop (cli.py) and a future Lambda (lambda_handler.py) share it."""

import queue
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import anthropic

from . import timing
from .config import Settings
from .llm import (
    MAINTAIN_SYSTEM,
    SYSTEM,
    TOOLS,
    WIKI_QUERY_SYSTEM,
    WIKI_SYSTEM,
    WIKI_TOOLS,
    run_turn,
)
from .stores import Fact, LocalStore, MemoryStore, Notice, build_stores
from .timing import span
from .wiki import Wiki


MAX_INGEST_CHARS = 100_000  # longer sources are cut off
RECENT_WINDOW = timedelta(minutes=10)  # `recall` also lists facts saved this recently


@dataclass
class WikiJob:
    """Facts just saved from one message, waiting for the wiki to catch up."""

    raw: str  # vault path of the raw source
    facts: list[str]


class Assistant:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        log: LocalStore,
        client: anthropic.Anthropic | None = None,
        background: bool = False,
    ):
        """`background`: finish slow work (wiki updates; the store's own
        saves, if built with background=True) on worker threads, so a reply
        doesn't wait for it. Long-lived processes only."""
        self.settings = settings
        self.store = store
        self.log = log
        self.client = client or anthropic.Anthropic()
        self.background = background
        self.wiki = Wiki(settings.wiki_dir) if settings.wiki_dir else None
        self.facts_saved = 0  # `remember` calls so far (to know when background saves are done)
        self.wiki_jobs = 0  # wiki updates queued so far
        self.notices_seen = 0  # background outcomes already handed out by take_notices
        self._wiki_queue: queue.Queue[WikiJob] = queue.Queue()  # one worker: updates run in order
        self._wiki_notices: queue.Queue[Notice] = queue.Queue()
        self._wiki_worker: threading.Thread | None = None
        self.last_turn: timing.Turn | None = None  # step timings of the latest message

    @classmethod
    def from_env(cls, background: bool = False) -> "Assistant":
        settings = Settings.from_env()
        store, log = build_stores(settings, background)
        return cls(settings, store, log, background=background)

    def take_notices(self) -> list[Notice]:
        """Outcomes of background work (saves, wiki updates) that finished
        since the last call. Their timings are logged here, like a message's."""
        taken = []
        for notices in (getattr(self.store, "notices", None), self._wiki_notices):
            while notices is not None and not notices.empty():
                notice = notices.get_nowait()
                timing.append_log(self._timings_path, notice.turn)
                taken.append(notice)
        self.notices_seen += len(taken)
        return taken

    def wait_for_saves(self, timeout: float) -> list[Notice]:
        """Wait (up to `timeout` seconds) for all background work to report,
        for processes about to exit. Returns the outcomes."""
        notices: list[Notice] = []
        deadline = time.monotonic() + timeout
        while self.pending_notices() > 0 and time.monotonic() < deadline:
            notices += self.take_notices()
            if self.pending_notices() > 0:
                time.sleep(0.5)
        return notices

    def pending_notices(self) -> int:
        """Background outcomes still to come."""
        return self._expected_notices() - self.notices_seen

    def _expected_notices(self) -> int:
        saves = self.facts_saved if getattr(self.store, "background", False) else 0
        return saves + self.wiki_jobs

    @property
    def _timings_path(self):
        return self.settings.data_dir / "timings.jsonl"

    def handle_message(self, text: str, history: list[dict]) -> str:
        """Answer one user message. `history` is this conversation's messages
        so far (updated in place), and goes to Claude with every call, so it
        knows what the user just said even if the store hasn't indexed it.

        Saving to the wiki is not part of the reply: it's queued as a job."""
        saved: list[str] = []
        raw: list[str] = []
        system, tools = SYSTEM, TOOLS
        if self.wiki:
            system += WIKI_QUERY_SYSTEM
            tools = TOOLS + WIKI_TOOLS[:1]  # wiki_read only
        reply = self._converse(text, history, text, raw, saved, label=text, system=system, tools=tools)
        if self.wiki and saved:
            self._queue_wiki_job(WikiJob(raw[0], saved))
        return reply

    def ingest_file(self, rel: str) -> str:
        """Fold one file that was dropped into the vault's raw/ folder into the
        wiki and the fact store (the "ingest" operation in SCHEMA.md), in one
        conversation. Returns Claude's short report. Marks the file ingested
        only if it succeeds."""
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
            prompt,
            [],
            f"[{rel}] {content[:500]}",
            [rel.removesuffix(".md")],
            [],
            label=f"ingest {rel}",
            system=SYSTEM + WIKI_SYSTEM + self.wiki.schema(),
            tools=TOOLS + WIKI_TOOLS,
        )
        self.wiki.mark_ingested(rel)
        return reply

    def _converse(
        self,
        text: str,
        history: list[dict],
        source_text: str,
        raw: list[str],
        saved: list[str],
        label: str,
        system: str,
        tools: list[dict],
    ) -> str:
        """Run one user turn. `remember` appends each fact to `saved`, and
        saves `text` as a raw wiki source (appending its path to `raw`) unless
        `raw` already has one."""
        history.append({"role": "user", "content": text})

        def execute(name: str, args: dict) -> str:
            with span(name):
                if name == "remember":
                    fact = Fact(text=args["fact"], source_text=source_text)
                    if self.log is not self.store:
                        self.log.add(fact)
                    result = self.store.add(fact)
                    self.facts_saved += 1
                    saved.append(fact.text)
                    if self.wiki:
                        if not raw:
                            raw.append(self.wiki.save_raw(text))
                        result += f" Raw source saved as {raw[0]}."
                    return result
                if name == "recall":
                    return self._recall(args["query"])
                return self._wiki_tool(name, args)

        try:
            with timing.turn(label) as t:
                return run_turn(self.client, self.settings, history, execute, system, tools)
        finally:  # after the `with`, so the turn's total time is filled in
            self.last_turn = t
            timing.append_log(self._timings_path, t)

    def _recall(self, query: str) -> str:
        """Search the store, then add facts saved in the last few minutes from
        the local log: the store may not have indexed those yet, so a question
        right after a fact would otherwise miss it."""
        lines = [f"- [saved {h.created_at or 'unknown'}] {h.text}" for h in self.store.search(query)]
        if self.log is not self.store:
            cutoff = datetime.now(UTC) - RECENT_WINDOW
            recent = [f for f in self.log.all() if datetime.fromisoformat(f.created_at) >= cutoff]
            new = [f"- [saved {f.created_at}] {f.text}" for f in recent[-10:]]
            new = [line for line in new if line not in lines]
            if new:
                lines += ["Recently saved (may not be searchable yet; use if relevant):", *new]
        return "\n".join(lines) or "No matching facts."

    def _wiki_tool(self, name: str, args: dict) -> str:
        if not self.wiki:
            raise ValueError(f"Unknown tool {name!r}")
        if name == "wiki_read":
            return self.wiki.list_pages() if args["path"] == "LIST" else self.wiki.read(args["path"])
        if name == "wiki_write":
            return self.wiki.write(args["path"], args["content"])
        if name == "wiki_log":
            return self.wiki.log(args["kind"], args["title"], args["body"])
        raise ValueError(f"Unknown tool {name!r}")

    def _queue_wiki_job(self, job: WikiJob) -> None:
        self.wiki_jobs += 1
        if not self.background:
            self._run_wiki_job(job)
            return
        self._wiki_queue.put(job)
        if self._wiki_worker is None:
            self._wiki_worker = threading.Thread(target=self._wiki_loop, daemon=True)
            self._wiki_worker.start()

    def _wiki_loop(self) -> None:
        while True:
            self._run_wiki_job(self._wiki_queue.get())

    def _run_wiki_job(self, job: WikiJob) -> None:
        """Update the wiki for facts just saved: a separate Claude conversation
        with the wiki tools. Its outcome is reported as a notice."""
        facts = "\n".join(f"- {f}" for f in job.facts)
        prompt = f"Raw source: `{job.raw}`\n\nFacts just saved from it:\n{facts}"
        with timing.turn(f"wiki: {job.facts[0]}", kind="background wiki") as t:
            try:
                reply = run_turn(
                    self.client,
                    self.settings,
                    [{"role": "user", "content": prompt}],
                    lambda name, args: self._wiki_tool(name, args),
                    MAINTAIN_SYSTEM + self.wiki.schema(),
                    WIKI_TOOLS,
                )
                message, failed = f"Wiki updated: {reply}", False
            except Exception as e:
                message, failed = f"Wiki update FAILED for {job.raw}: {e}", True
        self._wiki_notices.put(Notice(message, failed, t))
