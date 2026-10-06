"""Terminal chat loop: type a fact or a question, get a reply. Ctrl-D or
"quit" to exit. `--timing` prints how long each step took.

Wiki updates (and store saves) finish in the background, so "got it" comes
back before the wiki has the fact. How each ended (and, with --timing, its
timing) is shown right after the user's next entry; an empty entry just shows anything
waiting. Timings are logged to data/timings.jsonl either way."""

import argparse

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
    try:
        chat(assistant, history, args)
    finally:
        finish(assistant, args)


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
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        show_notices(assistant, args)
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            return
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


def finish(assistant, args) -> None:
    """Don't quit mid-save: background saves and wiki updates run on daemon
    threads, and a half-done wiki update would leave pages inconsistent."""
    if assistant.pending_notices() <= 0:
        return
    if args.notices:
        print("Finishing background saves...")
    for notice in assistant.wait_for_saves(assistant.settings.index_timeout + 60):
        print_notice(notice, args)


def show_notices(assistant, args) -> None:
    for notice in assistant.take_notices():
        print_notice(notice, args)


def print_notice(notice, args) -> None:
    """Quiet unless --notices; a failure always shows."""
    if not (args.notices or notice.failed):
        return
    print(f"[background] {notice.message}")
    if args.timing:
        print(notice.turn.report())
