"""Terminal chat loop: type a fact or a question, get a reply. Ctrl-D or
"quit" to exit.

Saves finish in the background, so "got it" comes back before Captain has
indexed the fact. How each save ended (and its timing) is shown right after
the user's next entry; an empty entry just shows anything waiting."""

import anthropic
import httpx
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    from .core import Assistant  # after load_dotenv, so settings see .env

    assistant = Assistant.from_env(background=True)
    history: list[dict] = []
    print(f"LLM PKM ({assistant.settings.store} store, {assistant.settings.model}). Ctrl-D to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        show_notices(assistant)
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
        if assistant.settings.show_timing and assistant.last_turn:
            print(assistant.last_turn.report())


def show_notices(assistant) -> None:
    for notice in assistant.take_notices():
        print(f"[earlier save] {notice.message}")
        if assistant.settings.show_timing or notice.failed:
            print(notice.turn.report())
