"""Terminal chat loop: type a fact or a question, get a reply. Ctrl-D or
"quit" to exit. `--timing` prints how long each step took.

Saves and wiki updates finish in the background, so "got it" comes back before the store has
indexed the fact. How each save ended (and, with --timing, its timing) is
shown right after the user's next entry; an empty entry just shows anything
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
    args = parser.parse_args()

    load_dotenv()
    from .core import Assistant  # after load_dotenv, so settings see .env

    assistant = Assistant.from_env(background=True)
    history: list[dict] = []
    print(f"LLM PKM ({assistant.settings.store} store, {assistant.settings.model}). Ctrl-D to quit.")
    try:
        chat(assistant, history, args.timing)
    finally:
        finish(assistant, args.timing)


def chat(assistant, history: list[dict], timing: bool) -> None:
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        show_notices(assistant, timing)
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
        if timing and assistant.last_turn:
            print(assistant.last_turn.report())


def finish(assistant, timing: bool) -> None:
    """Don't quit mid-save: background saves and wiki updates run on daemon
    threads, and a half-done wiki update would leave pages inconsistent."""
    if assistant.pending_notices() <= 0:
        return
    print("Finishing background saves...")
    for notice in assistant.wait_for_saves(assistant.settings.index_timeout + 60):
        print(f"[background] {notice.message}")


def show_notices(assistant, timing: bool) -> None:
    for notice in assistant.take_notices():
        print(f"[background] {notice.message}")
        if timing:
            print(notice.turn.report())
