"""Shared base for stores that accept a fact at once but take a while to make
it searchable (Captain, Cloudflare Vectorize).

By default add() waits until the fact is searchable, so a question asked
straight after a fact finds it. With background=True (the CLI), add() returns
as soon as the store has accepted the fact and a worker thread does the
waiting; its outcome lands on `self.notices`. A question asked during that
window can miss the newest fact. Background mode is only for long-lived
processes: a Lambda would be frozen before the thread finishes.
"""

import queue
import threading
from typing import Any

from .. import timing
from .base import Fact, Notice


class IndexingStore:
    name = "the store"  # for messages, e.g. "Captain"

    def __init__(self, background: bool = False):
        self.background = background
        self.notices: queue.Queue[Notice] = queue.Queue()

    def _submit(self, fact: Fact) -> Any:
        """Hand the fact to the service. Returns a handle for _wait_for_index."""
        raise NotImplementedError

    def _wait_for_index(self, handle: Any) -> str:
        """Block until the fact is searchable. Returns a status message for
        the model; raises if indexing failed."""
        raise NotImplementedError

    def add(self, fact: Fact) -> str:
        handle = self._submit(fact)
        if not self.background:
            return self._wait_for_index(handle)
        threading.Thread(target=self._wait_in_background, args=(handle, fact), daemon=True).start()
        return f"Saved; {self.name} is indexing it in the background."

    def _wait_in_background(self, handle: Any, fact: Fact) -> None:
        """Queue the outcome, with its own timing report, for the CLI to show
        after the user's next entry."""
        with timing.turn(f"index: {fact.text}", kind="background index") as t:
            try:
                message = f'Indexed "{fact.text}": {self._wait_for_index(handle)}'
                failed = False
            except Exception as e:
                message = f'Indexing FAILED for "{fact.text}": {e}'
                failed = True
        self.notices.put(Notice(message, failed, t))
