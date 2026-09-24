import json
from types import SimpleNamespace

from llm_pkm.config import Settings
from llm_pkm.core import Assistant
from llm_pkm.stores import LocalStore
from llm_pkm.timing import span, summarize


class Block(SimpleNamespace):
    def to_dict(self):
        return dict(vars(self))


def fake_client(*responses):
    """A stand-in for anthropic.Anthropic that returns canned responses."""
    queue = list(responses)
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)

    def create(**_):
        stop, content = queue.pop(0)
        return SimpleNamespace(stop_reason=stop, content=content, usage=usage)

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


class TimedStore(LocalStore):
    def add(self, fact):
        with span("store.add"):
            return super().add(fact)


def test_remember_turn_is_timed_and_logged(tmp_path):
    settings = Settings.from_env()
    settings = Settings(**{**vars(settings), "data_dir": tmp_path})
    log = LocalStore(tmp_path / "facts.jsonl")
    client = fake_client(
        ("tool_use", [Block(type="tool_use", id="t1", name="remember", input={"fact": "X."})]),
        ("end_turn", [Block(type="text", text="Got it.")]),
    )
    assistant = Assistant(settings, TimedStore(tmp_path / "store.jsonl"), log, client)

    assert assistant.handle_message("x", []) == "Got it."

    names = [(s.name, s.depth) for s in assistant.last_turn.spans]
    assert names == [("claude", 0), ("remember", 0), ("store.add", 1), ("claude", 0)]
    assert "store.add" in assistant.last_turn.report()

    logged = json.loads((tmp_path / "timings.jsonl").read_text())
    assert logged["tools"] == ["remember"]
    assert "remember turns: 1" in summarize(tmp_path / "timings.jsonl")
