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
Timings are logged to data/timings.jsonl either way."""

import argparse
import difflib
import threading

import anthropic
import httpx
from dotenv import load_dotenv


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
    args = parser.parse_args()

    load_dotenv()
    from .core import Assistant  # after load_dotenv, so settings see .env

    from . import ambient

    assistant = Assistant.from_env(background=True)
    if not ambient.owner_name(assistant.settings) and not ask_owner(assistant.settings):
        return
    history: list[dict] = []
    print(
        f"LLM PKM for {ambient.owner_name(assistant.settings)} "
        f"({assistant.settings.store} store, {assistant.settings.model}). Ctrl-D to quit."
    )
    if assistant.wiki:
        print(f"Wiki: {assistant.wiki.root.resolve()} (in Obsidian: Open folder as vault)")
    print("Commands: /ingest (add a file from raw/), /status (what is running), /rewind (take back")
    print("          the last thing stored), /delete-all (erase everything)")
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
COMMANDS = ("/ingest", "/status", "/rewind", "/delete-all")


def watch_notices(assistant, args, stop: threading.Event) -> None:
    """Print each background outcome as soon as it is ready, then put the
    prompt back, since the user is usually sitting at it."""
    while not stop.wait(0.5):
        shown = [print_notice(n, args, lead="\n") for n in assistant.take_notices()]
        if any(shown):
            print(PROMPT, end="", flush=True)


def ask_owner(settings) -> bool:
    """This memory belongs to one person. Nobody has said who yet, so ask,
    and save the answer in the vault. False if the user quit instead."""
    from . import ambient

    print("This memory belongs to one person, and I don't know who yet.")
    name = ""
    while not name:
        try:
            name = input("What is your name? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
    ambient.save_owner(settings, name)
    return True


def chat(assistant, history: list[dict], args) -> None:
    while True:
        try:
            text = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            return
        if text.lower() in {"/rewind", "rewind", "/undo"}:
            print(f"pkm> {assistant.rewind()}")
            continue
        if text.lower().split()[0] == "/ingest":
            ingest(assistant, text[len("/ingest") :].strip())
            continue
        if text.lower() == "/status":
            print(f"pkm> {assistant.status()}")
            continue
        if text.startswith("/"):  # a mistyped command must not go to Claude as a message
            word = text.split()[0]
            close = difflib.get_close_matches(word.lower(), COMMANDS, n=1, cutoff=0.5)
            hint = f" Did you mean {close[0]}?" if close else ""
            print(f"pkm> There is no {word} command.{hint} Commands: {', '.join(COMMANDS)}")
            continue
        if text.lower() in {"/delete-all", "/delete all", "/deleteall"}:
            delete_all(assistant, history)
            continue
        try:
            reply = assistant.handle_message(text, history)
        except anthropic.APIStatusError as e:
            reply = f"[Claude API error {e.status_code}: {e.message}]"
            history.clear()  # a half-finished turn would break the next request
        except (anthropic.APIConnectionError, httpx.HTTPError) as e:
            reply = f"[network error: {e}]"
            history.clear()
        print(f"pkm> {reply}")
        if args.timing and assistant.last_turn:
            print(assistant.last_turn.report())


def ask(prompt: str) -> str | None:
    """A follow-up question inside a command. None if the user backed out."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def ingest(assistant, name: str) -> None:
    """/ingest [file]: pick one of the new files in raw/ (asked if there are
    several and none was named), ask what the user wants kept from it, and
    queue it. The result is shown when it finishes, after a later entry."""
    if not assistant.wiki:
        print("pkm> The wiki is off, so there is nothing to ingest into.")
        return
    pending = assistant.wiki.pending_raw()
    raw_dir = assistant.wiki.root.resolve() / "raw"
    if not pending:
        print(f"pkm> No new files. Put a .md, .txt or .pdf file in {raw_dir} first.")
        return
    if name:
        chosen = [p for p in pending if name in (p, p.removeprefix("raw/"))]
        if not chosen:
            print(f"pkm> No new file called {name!r}. New files: {', '.join(pending)}")
            return
    elif len(pending) == 1:
        chosen = pending
    else:
        print("New files in raw/:")
        for i, rel in enumerate(pending, 1):
            print(f"  {i}. {rel.removeprefix('raw/')}")
        answer = ask('Which one? (a number, "all", or Enter to cancel): ')
        if answer and answer.lower() == "all":
            chosen = pending
        elif answer and answer.isdigit() and 1 <= int(answer) <= len(pending):
            chosen = [pending[int(answer) - 1]]
        else:
            print("pkm> Nothing ingested.")
            return
    guidance = None
    if len(chosen) == 1:
        print(f"Ingesting {chosen[0]}. What is it, and what should I keep from it?")
        guidance = ask("(optional; Enter to let me decide): ")
        if guidance is None:
            print("pkm> Nothing ingested.")
            return
    try:
        for rel in chosen:
            assistant.queue_ingest(rel, guidance or None)
    except RuntimeError as e:
        print(f"pkm> {e}")
        return
    count = "it" if len(chosen) == 1 else f"each of the {len(chosen)} files"
    print(f"pkm> Started. Keep going; I'll say what {count} added as soon as it's done.")
    print("     A long file can take a few minutes; /status shows what is running.")


def delete_all(assistant, history: list[dict]) -> None:
    """Erase everything, but only if the user types DELETE (capitals)."""
    if assistant.wiki:
        raw, pages = assistant.wiki.counts()
        print(f"This permanently deletes everything stored: {raw} raw source(s), {pages} wiki page(s),")
        print("the index, the log and the saved history. It cannot be undone or rewound.")
    else:
        print("This permanently deletes every saved fact. It cannot be undone.")
    try:
        answer = input("Are you absolutely sure? If so, type DELETE: ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
        print()
    if answer.strip() != "DELETE":
        print("pkm> Nothing was deleted.")
        return
    print(f"pkm> {assistant.delete_all(history)}")


def finish(assistant, args) -> None:
    """Don't quit mid-save: background saves and wiki updates run on daemon
    threads, and a half-done wiki update would leave pages inconsistent."""
    if assistant.pending_notices() <= 0:
        return
    if args.notices:
        print("Finishing background saves...")
    for notice in assistant.wait_for_saves(assistant.settings.index_timeout + 60):
        print_notice(notice, args)


def print_notice(notice, args, lead: str = "") -> bool:
    """Quiet unless --notices; a failure, or something the user asked for,
    always shows. True if it printed."""
    if not (args.notices or notice.failed or notice.asked_for):
        return False
    print(lead + (f"pkm> {notice.message}" if notice.asked_for else f"[background] {notice.message}"))
    if args.timing:
        print(notice.turn.report())
    return True
