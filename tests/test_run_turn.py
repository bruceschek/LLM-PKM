import dataclasses
from types import SimpleNamespace

from llm_pkm.config import Settings
from llm_pkm.llm import SAVED_REPLY, run_turn


class FakeClient:
    """Returns the scripted responses in order and records the requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def tool_use(name, **input):
    return SimpleNamespace(
        type="tool_use", id=f"id_{name}", name=name, input=input,
        to_dict=lambda: {"type": "tool_use", "id": f"id_{name}", "name": name, "input": input},
    )


def text(t):
    return SimpleNamespace(type="text", text=t, to_dict=lambda: {"type": "text", "text": t})


def response(*content, stop="tool_use"):
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    return SimpleNamespace(content=list(content), stop_reason=stop, usage=usage)


SETTINGS = Settings.from_env()


def test_only_facts_skips_the_second_claude_call():
    client = FakeClient(response(tool_use("remember", fact="A.", also_asks=False)))
    messages = [{"role": "user", "content": "a"}]
    assert run_turn(client, SETTINGS, messages, lambda n, a: "Saved.") == SAVED_REPLY
    assert len(client.requests) == 1
    assert messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": SAVED_REPLY}]}


def test_fact_plus_question_still_gets_an_answer():
    client = FakeClient(
        response(tool_use("remember", fact="A.", also_asks=True)),
        response(text("Her name is Hemmie."), stop="end_turn"),
    )
    messages = [{"role": "user", "content": "a"}]
    assert run_turn(client, SETTINGS, messages, lambda n, a: "Saved.") == "Her name is Hemmie."
    assert len(client.requests) == 2


def test_failed_save_goes_back_to_claude():
    def boom(name, args):
        raise RuntimeError("down")

    client = FakeClient(
        response(tool_use("remember", fact="A.", also_asks=False)),
        response(text("Sorry, couldn't save that."), stop="end_turn"),
    )
    assert run_turn(client, SETTINGS, [{"role": "user", "content": "a"}], boom) == "Sorry, couldn't save that."


def test_haiku_gets_no_effort_or_fallback_options():
    client = FakeClient(response(text("hi"), stop="end_turn"), response(text("hi"), stop="end_turn"))
    run_turn(client, SETTINGS, [{"role": "user", "content": "a"}], lambda n, a: "", model="claude-haiku-4-5-20251001")
    run_turn(client, SETTINGS, [{"role": "user", "content": "a"}], lambda n, a: "", model="claude-opus-5")
    haiku, opus = client.requests
    assert "output_config" not in haiku and "fallbacks" not in haiku
    assert opus["output_config"] == {"effort": SETTINGS.effort} and opus["fallbacks"] == "default"
