"""The single entry point: text in, reply out. No terminal or HTTP code here,
so the terminal loop (cli.py) and a future Lambda (lambda_handler.py) share it."""

import anthropic

from .config import Settings
from .llm import run_turn
from .stores import Fact, LocalStore, MemoryStore, build_stores


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

    @classmethod
    def from_env(cls) -> "Assistant":
        settings = Settings.from_env()
        store, log = build_stores(settings)
        return cls(settings, store, log)

    def handle_message(self, text: str, history: list[dict]) -> str:
        """Answer one user message. `history` is this conversation's messages
        so far; it is updated in place."""
        history.append({"role": "user", "content": text})

        def execute(name: str, args: dict) -> str:
            if name == "remember":
                fact = Fact(text=args["fact"], source_text=text)
                if self.log is not self.store:
                    self.log.add(fact)
                return self.store.add(fact)
            if name == "recall":
                hits = self.store.search(args["query"])
                if not hits:
                    return "No matching facts."
                return "\n".join(f"- [saved {h.created_at or 'unknown'}] {h.text}" for h in hits)
            raise ValueError(f"Unknown tool {name!r}")

        return run_turn(self.client, self.settings, history, execute)
