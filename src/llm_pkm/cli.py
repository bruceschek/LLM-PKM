"""Terminal chat loop: type a fact or a question, get a reply. Ctrl-D or
"quit" to exit. `--timing` prints how long each step took.

Commands: `/rewind` takes back the most recent stored change (asking in plain
words works too: Claude has a `rewind` tool). `/delete-all` erases everything
after the user types DELETE to confirm; Claude can't do that one itself.
`/ingest` folds a file the user put in the vault's raw/ folder into the wiki,
after asking what they want kept from it; it runs in the background.

Wiki updates (and store saves) finish in the background, so "got it" comes
back before the wiki has the fact. How each ended is printed the moment it
finishes, by a watcher thread, even while the prompt is waiting (with
--timing, so is its timing). Without --notices only failures and things the
user asked for (/ingest) are shown. `/status` says what is running now.
Timings are logged to data/timings.jsonl either way.

`--script FILE` feeds a text file in instead of the keyboard: one entry per
line, each waiting for the wiki to finish absorbing the one before
(`run_script`).

Everything the program says is in one color and what the user types in
another (`say` and `read`), when the output is a terminal and NO_COLOR is
unset."""

import argparse
import difflib
import os
import sys
import threading
import time
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv


REPLY = "\033[32m"  # green: everything the program says
OUTSIDE_COLOR = "\033[94m"  # bright blue: Claude's general knowledge, not the wiki
USER = "\033[33m"  # yellow: the "you>" prompt and what the user types
RESET = "\033[0m"


def colored() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def say(text: str = "", color: str = REPLY, reset: bool = True, **kwargs) -> None:
    """Print in the program's color. `reset=False` leaves the color on (for
    a prompt the user is about to type after)."""
    if colored():
        text = f"{color}{text}{RESET if reset else ''}"
    print(text, **kwargs)


def say_reply(reply: str) -> None:
    """Print Claude's reply. Anything from the "Not from your wiki:" marker
    to the end of its paragraph (the next blank line) is general knowledge,
    shown in its own color; that covers an answer Claude spread over
    several lines or a list."""
    from .llm import OUTSIDE

    lines, outside = [], False
    for line in f"pkm> {reply}".split("\n"):
        if not line.strip():
            outside = False
        elif outside and colored():
            line = f"{OUTSIDE_COLOR}{line}{REPLY}"
        before, marker, after = line.partition(OUTSIDE)
        if marker and not outside:
            outside = True
            if colored():
                line = f"{before}{OUTSIDE_COLOR}{marker}{after}{REPLY}"
        lines.append(line)
    say("\n".join(lines))


def read(prompt: str, color: str = REPLY) -> str:
    """Ask for a line: the prompt in `color`, what the user types in theirs."""
    if not colored():
        return input(prompt)
    try:
        return input(f"{color}{prompt}{USER}")
    finally:
        sys.stdout.write(RESET)
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(prog="llm-pkm", description="Chat with your personal memory.")
    parser.add_argument(
        "--timing", action="store_true", help="print how long each step took after every reply"
    )
    parser.add_argument(
        "--notices",
        action="store_true",
        help="show how each background save and wiki update ended (failures always show)",
    )
    parser.add_argument(
        "--script",
        metavar="FILE",
        type=Path,
        help="feed FILE in, one entry per line, waiting for the wiki after each; then exit",
    )
    args = parser.parse_args()
    if args.script and not args.script.is_file():
        parser.error(f"no such file: {args.script}")

    load_dotenv()
    from .core import Assistant  # after load_dotenv, so settings see .env

    from . import ambient

    assistant = Assistant.from_env(background=True)
    if not ambient.owner_name(assistant.settings) and not ask_owner(assistant.settings):
        return
    history: list[dict] = []
    say(
        f"LLM PKM for {ambient.owner_name(assistant.settings)} "
        f"({assistant.settings.store} store, {assistant.settings.model}). Ctrl-D to quit."
    )
    if assistant.wiki:
        say(f"Wiki: {assistant.wiki.root.resolve()} (in Obsidian: Open folder as vault)")
    if args.script:
        try:
            run_script(assistant, history, args)
        finally:
            finish(assistant, args)
        return
    say("Commands: /ingest (add a file from raw/), /lint (health-check the wiki), /status (what")
    say("          is running), /rewind (take back the last thing stored), /delete-all (erase everything)")
    stop = threading.Event()
    watcher = threading.Thread(target=watch_notices, args=(assistant, args, stop), daemon=True)
    watcher.start()
    try:
        chat(assistant, history, args)
    finally:
        stop.set()
        watcher.join()
        finish(assistant, args)


PROMPT = "\nyou> "
COMMANDS = ("/ingest", "/lint", "/status", "/rewind", "/delete-all")


def watch_notices(assistant, args, stop: threading.Event) -> None:
    """Print each background outcome as soon as it is ready, then put the
    prompt back, since the user is usually sitting at it."""
    while not stop.wait(0.5):
        shown = [print_notice(n, args, lead="\n") for n in assistant.take_notices()]
        if any(shown):
            say(PROMPT, color=USER, end="", flush=True, reset=False)


def ask_owner(settings) -> bool:
    """This memory belongs to one person. Nobody has said who yet, so ask,
    and save the answer in the vault. False if the user quit instead."""
    from . import ambient

    say("This memory belongs to one person, and I don't know who yet.")
    name = ""
    while not name:
        try:
            name = read("What is your name? ").strip()
        except (EOFError, KeyboardInterrupt):
            say()
            return False
    ambient.save_owner(settings, name)
    return True


def chat(assistant, history: list[dict], args) -> None:
    while True:
        try:
            text = read(PROMPT, color=USER).strip()
        except (EOFError, KeyboardInterrupt):
            say()
            return
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            return
        handle(assistant, history, args, text)


def handle(assistant, history: list[dict], args, text: str, scripted: bool = False) -> bool:
    """One entry: a command or a message for Claude. False if it failed.
    `scripted` means nobody is there to answer a follow-up question."""
    if text.lower() in {"/rewind", "rewind", "/undo"}:
        say(f"pkm> {assistant.rewind()}")
        return True
    if text.lower().split()[0] == "/ingest":
        return ingest(assistant, text[len("/ingest") :].strip(), scripted)
    if text.lower() == "/status":
        say(f"pkm> {assistant.status()}")
        return True
    if text.lower() == "/lint":
        return lint(assistant)
    if text.lower() in {"/delete-all", "/delete all", "/deleteall"}:
        if scripted:  # the typed DELETE is the safeguard, and a file can't give it
            say("pkm> /delete-all only works typed in the chat. Nothing was deleted.")
            return False
        delete_all(assistant, history)
        return True
    if text.startswith("/"):  # a mistyped command must not go to Claude as a message
        word = text.split()[0]
        close = difflib.get_close_matches(word.lower(), COMMANDS, n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]}?" if close else ""
        say(f"pkm> There is no {word} command.{hint} Commands: {', '.join(COMMANDS)}")
        return False
    failed = True
    try:
        reply = assistant.handle_message(text, history)
        failed = False
    except anthropic.APIStatusError as e:
        reply = f"[Claude API error {e.status_code}: {e.message}]"
        history.clear()  # a half-finished turn would break the next request
    except (anthropic.APIConnectionError, httpx.HTTPError) as e:
        reply = f"[network error: {e}]"
        history.clear()
    say_reply(reply)
    if args.timing and assistant.last_turn:
        say(assistant.last_turn.report())
    return not failed


SCRIPT_WAIT = 900  # seconds a script waits for one entry's background work (a long PDF ingest)


def run_script(assistant, history: list[dict], args) -> None:
    """--script: feed a text file in, one entry per line, as if typed. Each
    entry's background work (the wiki update, an ingest, a lint pass) is
    waited for and its outcome printed before the next line is sent, so
    every entry meets a wiki that has absorbed the ones before it. Blank
    lines and lines starting with # are skipped; `quit` stops early."""
    entries = [
        (number, line.strip())
        for number, line in enumerate(args.script.read_text().split("\n"), 1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    say(f"Script: {args.script} ({len(entries)} entries)")
    began = time.monotonic()
    done, updates, problems = 0, 0, []
    for number, text in entries:
        if text.lower() in {"quit", "exit"}:
            break
        say(f"\n[{done + 1}/{len(entries)}, line {number}] you> {text}", color=USER)
        ok = handle(assistant, history, args, text, scripted=True)
        waited = time.monotonic()
        notices = assistant.wait_for_saves(SCRIPT_WAIT)
        for notice in notices:
            say(f"[{'FAILED' if notice.failed else 'wiki'}, {notice.turn.seconds:.0f} s] {notice.message}")
            if args.timing:
                say(notice.turn.report())
        timed_out = assistant.pending_notices() > 0
        if timed_out:
            say(f"[still running after {time.monotonic() - waited:.0f} s; going on without it]")
        done += 1
        updates += sum(not n.failed for n in notices)
        if not ok or timed_out or any(n.failed for n in notices):
            problems.append(number)
    say(
        f"\nScript done: {done} of {len(entries)} entries, {updates} wiki update(s), "
        f"{len(problems)} problem(s), {time.monotonic() - began:.0f} s."
    )
    if problems:
        say(f"Problems at line(s): {', '.join(map(str, problems))}")


def ask(prompt: str) -> str | None:
    """A follow-up question inside a command. None if the user backed out."""
    try:
        return read(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        say()
        return None


def ingest(assistant, name: str, scripted: bool = False) -> bool:
    """/ingest [file]: pick one of the new files in raw/ (asked if there are
    several and none was named), ask what the user wants kept from it, and
    queue it. The result is shown when it finishes, after a later entry.
    From a script nothing is asked: the file must be named unless there is
    only one, and Claude decides what to keep. False if nothing was queued."""
    if not assistant.wiki:
        say("pkm> The wiki is off, so there is nothing to ingest into.")
        return False
    pending = assistant.wiki.pending_raw()
    raw_dir = assistant.wiki.root.resolve() / "raw"
    if not pending:
        say(f"pkm> No new files. Put a .md, .txt or .pdf file in {raw_dir} first.")
        return False
    if name:
        chosen = [p for p in pending if name in (p, p.removeprefix("raw/"))]
        if not chosen:
            say(f"pkm> No new file called {name!r}. New files: {', '.join(pending)}")
            return False
    elif len(pending) == 1:
        chosen = pending
    elif scripted:
        say(f"pkm> Several new files; name one after /ingest: {', '.join(pending)}")
        return False
    else:
        say("New files in raw/:")
        for i, rel in enumerate(pending, 1):
            say(f"  {i}. {rel.removeprefix('raw/')}")
        answer = ask('Which one? (a number, "all", or Enter to cancel): ')
        if answer and answer.lower() == "all":
            chosen = pending
        elif answer and answer.isdigit() and 1 <= int(answer) <= len(pending):
            chosen = [pending[int(answer) - 1]]
        else:
            say("pkm> Nothing ingested.")
            return False
    guidance = None
    if len(chosen) == 1 and not scripted:
        say(f"Ingesting {chosen[0]}. What is it, and what should I keep from it?")
        guidance = ask("(optional; Enter to let me decide): ")
        if guidance is None:
            say("pkm> Nothing ingested.")
            return False
    try:
        for rel in chosen:
            assistant.queue_ingest(rel, guidance or None)
    except RuntimeError as e:
        say(f"pkm> {e}")
        return False
    count = "it" if len(chosen) == 1 else f"each of the {len(chosen)} files"
    say(f"pkm> Started. Keep going; I'll say what {count} added as soon as it's done.")
    say("     A long file can take a few minutes; /status shows what is running.")
    return True


def delete_all(assistant, history: list[dict]) -> None:
    """Erase everything, but only if the user types DELETE (capitals)."""
    if assistant.wiki:
        raw, pages = assistant.wiki.counts()
        say(f"This permanently deletes everything stored: {raw} raw source(s), {pages} wiki page(s),")
        say("the index, the log and the saved history. It cannot be undone or rewound.")
    else:
        say("This permanently deletes every saved fact. It cannot be undone.")
    try:
        answer = read("Are you absolutely sure? If so, type DELETE: ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
        say()
    if answer.strip() != "DELETE":
        say("pkm> Nothing was deleted.")
        return
    say(f"pkm> {assistant.delete_all(history)}")


def lint(assistant) -> bool:
    """/lint: start a health check of the wiki in the background. False if
    it couldn't start."""
    try:
        assistant.queue_lint()
    except RuntimeError as e:
        say(f"pkm> {e}")
        return False
    say("pkm> Lint started. Keep going; the report will appear here when it's done.")
    return True


def finish(assistant, args) -> None:
    """Don't quit mid-save: background saves and wiki updates run on daemon
    threads, and a half-done wiki update would leave pages inconsistent."""
    if assistant.pending_notices() <= 0:
        return
    if args.notices:
        say("Finishing background saves...")
    for notice in assistant.wait_for_saves(assistant.settings.index_timeout + 60):
        print_notice(notice, args)


def print_notice(notice, args, lead: str = "") -> bool:
    """Quiet unless --notices; a failure, or something the user asked for,
    always shows. True if it printed."""
    if not (args.notices or notice.failed or notice.asked_for):
        return False
    say(lead + (f"pkm> {notice.message}" if notice.asked_for else f"[background] {notice.message}"))
    if args.timing:
        say(notice.turn.report())
    return True
