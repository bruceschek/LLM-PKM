"""Per-turn timing, to find where a slow reply spends its time.

Code anywhere in a turn wraps a step in `span("name")`; the spans land in
whichever `Turn` is active (set by `Assistant.handle_message`). Outside a
turn, `span` does nothing, so stores work the same when timing is off.
"""

import json
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class Span:
    name: str
    depth: int = 0  # nesting level, for indenting the report
    seconds: float = 0.0
    info: dict = field(default_factory=dict)  # extra detail, e.g. token counts


@dataclass
class Turn:
    text: str
    kind: str | None = None  # label for the log; default: the tools used
    spans: list[Span] = field(default_factory=list)  # in start order
    seconds: float = 0.0
    _depth: int = 0

    def report(self) -> str:
        lines = [f"  total {self.seconds:6.2f}s"]
        for s in self.spans:
            extra = "  " + " ".join(f"{k}={v}" for k, v in s.info.items()) if s.info else ""
            name = "  " * s.depth + s.name
            lines.append(f"  {name:<24}{s.seconds:6.2f}s{extra}")
        return "\n".join(lines)

    def to_json(self) -> str:
        tools = [self.kind] if self.kind else sorted(
            {s.name for s in self.spans if s.name in ("remember", "recall")}
        )
        return json.dumps(
            {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "tools": tools,
                "seconds": round(self.seconds, 3),
                "spans": [{"name": s.name, "seconds": round(s.seconds, 3), **s.info} for s in self.spans],
            }
        )


_current: ContextVar[Turn | None] = ContextVar("pkm_turn", default=None)


@contextmanager
def turn(text: str, kind: str | None = None) -> Iterator[Turn]:
    t = Turn(text, kind)
    token = _current.set(t)
    start = time.perf_counter()
    try:
        yield t
    finally:
        t.seconds = time.perf_counter() - start
        _current.reset(token)


@contextmanager
def span(name: str) -> Iterator[Span]:
    """Time a step. Add details with `s.info[...] = ...` inside the block."""
    s = Span(name)
    t = _current.get()
    if t is not None:
        s.depth = t._depth
        t.spans.append(s)
        t._depth += 1
    start = time.perf_counter()
    try:
        yield s
    finally:
        s.seconds = time.perf_counter() - start
        if t is not None:
            t._depth -= 1


def append_log(path: Path, t: Turn) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(t.to_json() + "\n")


def summarize(path: Path) -> str:
    """Median and max seconds per step, split by the kind of turn (remember,
    recall, both, or neither), from the timings log."""
    if not path.exists():
        return f"No timings yet ({path})."
    turns = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for t in turns:
        kind = "+".join(t["tools"]) or "no tools"
        groups[kind]["TOTAL"].append(t["seconds"])
        per_turn: dict[str, float] = defaultdict(float)
        for s in t["spans"]:
            per_turn[s["name"]] += s["seconds"]  # e.g. two Claude calls in one turn
            for k in ("captain_queue_s", "captain_processing_s"):
                if k in s:
                    per_turn[k.removesuffix("_s")] += s[k]
        for name, secs in per_turn.items():
            groups[kind][name].append(secs)

    out = []
    for kind, steps in groups.items():
        out.append(f"\n{kind} turns: {len(steps['TOTAL'])}")
        out.append(f"  {'step (sum per turn)':<24}{'median':>8}{'max':>8}{'n':>5}")
        for name, vals in sorted(steps.items(), key=lambda kv: -statistics.median(kv[1])):
            out.append(f"  {name:<24}{statistics.median(vals):7.2f}s{max(vals):7.2f}s{len(vals):5}")
    return "\n".join(out)


def main() -> None:
    """`uv run pkm-timings [path]`: summarize the timings log."""
    from dotenv import load_dotenv

    from .config import Settings

    load_dotenv()
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Settings.from_env().data_dir / "timings.jsonl"
    print(summarize(path))
