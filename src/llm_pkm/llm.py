"""Claude and its two tools. Claude decides whether each message is a fact to
remember or a question to answer; the same two tools can later be exposed as
an MCP server for the Claude app."""

from collections.abc import Callable

import anthropic

from .config import Settings
from .timing import span

SYSTEM = """You are the user's personal memory. They tell you facts about their \
life and later ask you about them.

- When the user states a fact, call `remember` once per distinct fact. Rewrite \
each fact as a self-contained statement about "the user" that will make sense \
on its own months from now (e.g. "my wife's name is Hemmie" becomes "The \
user's wife's name is Hemmie."). Then reply with a very short acknowledgement \
such as "Got it."
- When the user asks a question, call `recall` first, then answer briefly \
using only what it returns, speaking to the user directly ("Her name is \
Hemmie."). If nothing relevant comes back, try `recall` again with other \
wording (synonyms, related terms: "married to" -> "wife", "husband", \
"spouse"). If that still finds nothing, say you don't have that yet.
- If newer and older facts disagree, trust the newer one and mention the change.
- For anything else (greetings, chit-chat), just reply briefly without tools."""

TOOLS = [
    {
        "name": "remember",
        "description": "Save one fact about the user to long-term memory.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "A single self-contained statement about the user.",
                }
            },
            "required": ["fact"],
            "additionalProperties": False,
        },
    },
    {
        "name": "recall",
        "description": (
            "Search long-term memory for facts relevant to a question. Returns "
            "matching facts with the date each was saved, best match first."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look for, in plain language.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]

WIKI_SYSTEM = """

You also maintain a markdown wiki (an Obsidian vault) of what the user tells \
you, following the rules below. `remember` returns the raw source's path; after \
saving facts, do the ingest steps: use `wiki_read` on `index.md` and any pages \
the facts touch, then `wiki_write` the new or updated pages and the updated \
index, citing the raw source, then `wiki_log`. Keep this quick: a short \
fact touches one to three pages. For questions, `recall` finds facts; use \
`wiki_read` when the wiki's pages would give a fuller answer. Never put \
anything but facts the user told you in the wiki.

Wiki rules (SCHEMA.md):

"""

WIKI_TOOLS = [
    {
        "name": "wiki_read",
        "description": "Read a wiki file by vault-relative path, e.g. index.md or wiki/people/Dana.md. Use wiki_read with path 'LIST' to list all files.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "wiki_write",
        "description": "Create or fully replace index.md or a page under wiki/. Raw sources and the log can't be written this way.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "wiki_log",
        "description": "Append an entry to log.md.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["ingest", "query", "lint", "schema"]},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["kind", "title", "body"],
            "additionalProperties": False,
        },
    },
]

ToolExecutor = Callable[[str, dict], str]


def run_turn(
    client: anthropic.Anthropic,
    settings: Settings,
    messages: list[dict],
    execute: ToolExecutor,
    system: str = SYSTEM,
    tools: list[dict] = TOOLS,
) -> str:
    """Run Claude until it stops calling tools. Appends every assistant and
    tool-result message to `messages` (as plain dicts, so the history can be
    serialized, e.g. returned from a Lambda). Returns the reply text."""
    while True:
        with span("claude") as s:
            response = client.beta.messages.create(
                model=settings.model,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": settings.effort},
                # If Claude declines on safety grounds, retry on Anthropic's
                # recommended fallback model instead of returning a refusal.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            s.info.update(
                stop=response.stop_reason,
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
            )
        if response.stop_reason == "refusal":
            return "Sorry, I can't help with that."

        messages.append(
            {"role": "assistant", "content": [block.to_dict() for block in response.content]}
        )
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            return "".join(b.text for b in response.content if b.type == "text").strip()

        results = []
        for tool_use in tool_uses:
            try:
                output = execute(tool_use.name, tool_use.input)
                results.append(
                    {"type": "tool_result", "tool_use_id": tool_use.id, "content": output}
                )
            except Exception as e:  # report the failure to Claude rather than crash
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": results})
