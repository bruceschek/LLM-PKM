"""The single entry point: text in, reply out. No terminal or HTTP code here,
so the terminal loop (cli.py) and a future Lambda (lambda_handler.py) share it."""

import base64
import queue
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import anthropic

from . import timing
from .ambient import everyday_context
from .config import Settings
from .llm import (
    MAINTAIN_SYSTEM,
    SYSTEM,
    TOOLS,
    WIKI_CHAT_SYSTEM,
    WIKI_CHAT_TOOLS,
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
MAX_PENDING_SHOWN = 20  # captures not yet in the wiki that chat is told about


@dataclass
class WikiJob:
    """Facts just saved from one message, waiting for the wiki to catch up."""

    raw: str  # vault path of the raw source
    facts: list[str]


@dataclass
class IngestJob:
    """A file in raw/ the user asked to have ingested (/ingest in the chat)."""

    rel: str  # vault path, e.g. raw/trip-notes.pdf
    guidance: str | None  # what the user said about it


class Assistant:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore | None,
        log: LocalStore,
        client: anthropic.Anthropic | None = None,
        background: bool = False,
    ):
        """`background`: finish slow work (wiki updates; the store's own
        saves, if built with background=True) on worker threads, so a reply
        doesn't wait for it. Long-lived processes only.

        `store=None` is wiki-first: no fact store or fact log, the wiki is
        the memory, and chat answers by reading its pages."""
        if store is None and not settings.wiki_dir:
            raise RuntimeError("PKM_STORE=wiki needs the wiki, but PKM_WIKI_DIR is off.")
        self.settings = settings
        self.store = store
        self.log = log
        self.client = client or anthropic.Anthropic()
        self.background = background
        self.wiki = Wiki(settings.wiki_dir) if settings.wiki_dir else None
        self.facts_saved = 0  # `remember` calls so far (to know when background saves are done)
        self.wiki_jobs = 0  # wiki updates queued so far
        self.notices_seen = 0  # background outcomes already handed out by take_notices
        # One worker: wiki changes run one at a time, in order.
        self._wiki_queue: queue.Queue[WikiJob | IngestJob] = queue.Queue()
        self._wiki_notices: queue.Queue[Notice] = queue.Queue()
        self._wiki_worker: threading.Thread | None = None
        self._working_on: tuple[str, float] | None = None  # the wiki job running now, and when it began
        # This session's captures, oldest first: (raw path, history, the turn's
        # first message, how many messages the turn added). `rewind` uses it
        # to drop a rewound turn from the conversation too.
        self._captures: list[tuple[str, list[dict], dict, int]] = []
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

    def status(self) -> str:
        """What the background worker is doing, for the user."""
        working, waiting = self._working_on, self._wiki_queue.qsize()
        if not working:
            return "Nothing is running in the background."
        title, began = working
        more = f" {waiting} more waiting." if waiting else ""
        return f"Working on {title} ({time.monotonic() - began:.0f} s so far).{more}"

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
        knows what the user just said even if it isn't in the wiki or store yet.

        Updating the wiki is not part of the reply: it's queued as a job."""
        saved: list[str] = []
        raw: list[str] = []
        system, tools = SYSTEM, TOOLS
        if self.store is None:
            system = WIKI_CHAT_SYSTEM + everyday_context(self.settings) + self._wiki_context()
            tools = WIKI_CHAT_TOOLS
        elif self.wiki:
            system += WIKI_QUERY_SYSTEM
            tools = TOOLS + WIKI_TOOLS[:1]  # wiki_read only
        reply = self._converse(text, history, text, raw, saved, label=text, system=system, tools=tools)
        if self.wiki and saved:
            first = next(m for m in reversed(history) if m["role"] == "user" and m["content"] == text)
            added = len(history) - _index_of(history, first)
            self._captures.append((raw[0], history, first, added))
            self._queue_wiki_job(WikiJob(raw[0], saved))
        return reply

    def rewind(self) -> str:
        """Take back the most recent change to the wiki (normally the last
        capture): its pages, index and log entries, and its raw source. If
        that capture was made in this session, its turn is dropped from the
        conversation too, so Claude no longer knows it. Returns a sentence
        saying what was removed."""
        if self.store is not None:
            return f"Rewind only works with PKM_STORE=wiki (this is {self.settings.store})."
        self._wiki_queue.join()  # let any wiki update still running finish first
        entry = self.wiki.rewind()
        if entry is None:
            return "Nothing to rewind."
        if self._captures and f"{self._captures[-1][0]}.md" == entry["raw"]:
            _, history, first, added = self._captures.pop()
            start = _index_of(history, first)
            del history[start : start + added]
        new = sorted(p for p, before in entry["files"].items() if before is None)
        restored = sorted(p for p, before in entry["files"].items() if before is not None)
        parts = [f"Rewound the last {entry['kind']}: \"{entry['title']}\"."]
        if new:
            parts.append(f"Deleted {', '.join(new)}.")
        if restored:
            parts.append(f"Put back the earlier version of {', '.join(restored)}.")
        if entry["raw"] and entry["delete_raw"]:
            parts.append("Deleted its raw source.")
        elif entry["raw"]:
            parts.append(f"{entry['raw']} is kept and counts as not ingested.")
        return " ".join(parts)

    def delete_all(self, history: list[dict]) -> str:
        """Erase everything stored locally: the vault's content (see
        `Wiki.delete_all`), the fact log and the timing log (which holds the
        text of past messages), and this conversation. Cannot be undone; the
        caller is responsible for confirming with the user first."""
        self._wiki_queue.join()
        if self.wiki:
            self.wiki.delete_all()
        for path in (self.log.path, self._timings_path):
            path.unlink(missing_ok=True)
        self._captures.clear()
        history.clear()
        self.last_turn = None
        note = "" if self.store is None else f" The {self.settings.store} store was NOT cleared."
        return "Deleted everything." + note

    def _wiki_context(self) -> str:
        """What wiki-first chat is given on every turn: the index, and the
        raw sources the wiki hasn't caught up with (an update still running,
        one that failed, or a file the user dropped in)."""
        text = "\n\nindex.md right now:\n\n" + self.wiki.read("index.md")
        pending = self.wiki.pending_raw()[-MAX_PENDING_SHOWN:]
        if pending:
            text += (
                "\nRaw sources not yet in the wiki (a file the user added gets in when "
                "they type /ingest, which you can't do for them; a .pdf can't be read "
                "with `wiki_read`):\n" + "\n".join(f"- {p}" for p in pending)
            )
        return text

    def ingest_file(self, rel: str, guidance: str | None = None) -> str:
        """Fold one file from the vault's raw/ folder into the wiki (and the
        fact store, if there is one): the "ingest" operation in SCHEMA.md, in
        one conversation. `guidance` is anything the user said about the
        document. Returns Claude's short report. Marks the file ingested only
        if it succeeds."""
        if not self.wiki:
            raise RuntimeError("The wiki is off (PKM_WIKI_DIR=off); nothing to ingest into.")
        message = self._ingest_message(rel, guidance)
        with self.wiki.journal("ingest", rel, raw=rel, delete_raw=self.wiki.is_capture(rel)):
            if self.store is None:
                reply = self._maintain(message, label=f"ingest {rel}")
            else:
                reply = self._converse(
                    message,
                    [],
                    f"[{rel}]",
                    [rel.removesuffix(".md")],
                    [],
                    label=f"ingest {rel}",
                    system=SYSTEM + WIKI_SYSTEM + self.wiki.schema(),
                    tools=TOOLS + WIKI_TOOLS,
                    model=self.settings.wiki_model,
                )
            self.wiki.mark_ingested(rel)
        return reply

    def queue_ingest(self, rel: str, guidance: str | None = None) -> None:
        """Ingest a raw file on the worker, behind any wiki updates already
        waiting, so the chat stays free. The outcome comes back as a notice."""
        if self.store is not None:
            raise RuntimeError("Ingesting from the chat needs PKM_STORE=wiki; use `uv run pkm-ingest`.")
        self._queue_wiki_job(IngestJob(rel, guidance))

    def _ingest_message(self, rel: str, guidance: str | None) -> str | list[dict]:
        """The request to ingest one raw file, as message content: text, or
        for a PDF the document itself followed by the text."""
        pdf = rel.lower().endswith(".pdf")
        if pdf:
            data = self.wiki.read_pdf(rel)
            body = f"`{rel}` is the attached PDF."
        else:
            content = self.wiki.read_raw(rel)
            truncated = len(content) > MAX_INGEST_CHARS
            body = (
                f"Contents of `{rel}`"
                + (f" (truncated to the first {MAX_INGEST_CHARS} characters)" if truncated else "")
                + f":\n\n{content[:MAX_INGEST_CHARS]}"
            )
        remember = (
            "Also call `remember` once for each distinct fact worth keeping, as a "
            "self-contained statement. If the source isn't about the user, phrase the "
            "fact about its subject (e.g. \"The Eiffel Tower is 330 m tall.\"), and say "
            "where it came from. "
        )
        prompt = (
            f"Ingest the new raw source `{rel}` (already saved; don't save it again). "
            "Follow the wiki's ingest steps: summarize the takeaways, create or update "
            "the wiki pages it touches, update the index, and log it. "
            f"Cite it as `[[{rel.removesuffix('.md')}]]`. "
            + (remember if self.store is not None else "")
            + "Reply with one line saying what you did.\n\n"
            + (
                "What the user says about this document (follow it on what to keep "
                f"and what to leave out):\n{guidance.strip()}\n\n"
                if guidance and guidance.strip()
                else ""
            )
            + body
        )
        if not pdf:
            return prompt
        document = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(data).decode(),
            },
        }
        return [document, {"type": "text", "text": prompt}]

    def lint(self) -> str:
        """Health-check the wiki (the "lint" operation in SCHEMA.md). Returns
        Claude's report: what it fixed and what needs the user's decision."""
        if not self.wiki:
            raise RuntimeError("The wiki is off (PKM_WIKI_DIR=off); nothing to lint.")
        prompt = (
            "Lint the wiki. `wiki_read` `lint-checklist.md` and work through it: read "
            "`index.md`, list every file (path 'LIST') and read the pages. Raw sources "
            "listed below as not yet ingested are not your concern here. Fix what is "
            "safe to fix, then `wiki_log` the pass. Reply with a short report: what you "
            "fixed, then what needs the user's decision."
        )
        pending = self.wiki.pending_raw()
        if pending:
            prompt += "\n\nNot yet ingested:\n" + "\n".join(f"- {p}" for p in pending)
        with self.wiki.journal("lint", "lint pass"):
            return self._maintain(prompt, label="lint")

    def _maintain(self, prompt: str | list[dict], label: str) -> str:
        """One maintenance conversation: Claude with the wiki write tools."""
        return self._converse(
            prompt,
            [],
            "",
            [label],  # `remember` isn't offered, so no raw source gets saved
            [],
            label=label,
            system=MAINTAIN_SYSTEM + self.wiki.schema() + everyday_context(self.settings),
            tools=WIKI_TOOLS,
            model=self.settings.wiki_model,
        )

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
        model: str | None = None,
    ) -> str:
        """Run one user turn. `remember` appends each fact to `saved`, and
        saves `text` as a raw wiki source (appending its path to `raw`) unless
        `raw` already has one."""
        history.append({"role": "user", "content": text})

        def execute(name: str, args: dict) -> str:
            with span(name):
                if name == "remember":
                    fact = Fact(text=args["fact"], source_text=source_text)
                    result = "Saved."
                    if self.store is not None:
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
                if name == "rewind":
                    return self.rewind()
                if name == "recall" and self.store is not None:
                    return self._recall(args["query"])
                return self._wiki_tool(name, args)

        try:
            with timing.turn(label) as t:
                return run_turn(self.client, self.settings, history, execute, system, tools, model)
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

    def _queue_wiki_job(self, job: WikiJob | IngestJob) -> None:
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
            try:
                self._run_wiki_job(self._wiki_queue.get())
            finally:
                self._wiki_queue.task_done()  # `rewind` and `delete_all` join the queue

    def _run_wiki_job(self, job: WikiJob | IngestJob) -> None:
        """Update the wiki for a chat capture, or ingest a file the user
        asked for: a separate Claude conversation with the wiki tools. Its
        outcome is reported as a notice. If it fails, the raw source stays
        pending, to be retried by /ingest or `pkm-ingest`."""
        asked_for = isinstance(job, IngestJob)
        if asked_for:
            raw, kind, title, delete_raw = job.rel, "ingest", job.rel, self.wiki.is_capture(job.rel)
        else:
            raw, kind, title, delete_raw = f"{job.raw}.md", "capture", job.facts[0], True
        self._working_on = (raw, time.monotonic())
        with (
            timing.turn(f"wiki: {title}", kind="background wiki") as t,
            self.wiki.journal(kind, title, raw=raw, delete_raw=delete_raw),
        ):
            try:
                if asked_for:
                    message = self._ingest_message(job.rel, job.guidance)
                else:
                    facts = "\n".join(f"- {f}" for f in job.facts)
                    message = f"Ingest the raw source `{job.raw}`. The facts it states:\n{facts}"
                reply = run_turn(
                    self.client,
                    self.settings,
                    [{"role": "user", "content": message}],
                    lambda name, args: self._wiki_tool(name, args),
                    MAINTAIN_SYSTEM + self.wiki.schema() + everyday_context(self.settings),
                    WIKI_TOOLS,
                    self.settings.wiki_model,
                )
                self.wiki.mark_ingested(raw)
                outcome, failed = f"{'Ingested ' + raw if asked_for else 'Wiki updated'}: {reply}", False
            except Exception as e:
                outcome, failed = (
                    f"Wiki update FAILED for {raw} (/ingest or `uv run pkm-ingest` retries it): {e}",
                    True,
                )
        self._working_on = None
        self._wiki_notices.put(Notice(outcome, failed, t, asked_for))


def _index_of(history: list[dict], message: dict) -> int:
    """Where this very message object sits in the history."""
    return next(i for i, m in enumerate(history) if m is message)
