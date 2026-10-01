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
using what it returns plus anything the user said earlier in this \
conversation (a fact they just told you may not be searchable yet; `recall` \
also lists recently saved facts), speaking to the user directly ("Her name is \
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
                },
                "also_asks": {
                    "type": "boolean",
                    "description": (
                        "True if the user's message also asks a question or makes a "
                        "request that you must still answer after saving. False if "
                        "it only states facts."
                    ),
                },
            },
            "required": ["fact", "also_asks"],
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

# Interactive chat: the wiki is read-only. Maintenance happens afterwards on a
# background thread (MAINTAIN_SYSTEM), so the reply isn't held up by it.
WIKI_QUERY_SYSTEM = """

The user's facts are also kept as a markdown wiki. When its pages would give \
a fuller answer than `recall`, use `wiki_read` (`index.md` lists the pages; \
path 'LIST' lists every file). You can't change the wiki; that happens \
separately."""

MAINTAIN_SYSTEM = """You maintain a markdown wiki (an Obsidian vault) of what the \
user tells their personal memory, following the rules below. You'll be given \
facts that were just saved and the raw source they came from. Do the ingest \
steps: `wiki_read` `index.md` and any pages the facts touch, then `wiki_write` \
the new or updated pages and the updated index, citing the raw source, then \
`wiki_log`. Keep it quick: a short fact touches one to three pages. Don't \
call `remember` (the facts are already saved). Put nothing in the wiki but \
what the facts say. Reply with one short line saying what you did.

Wiki rules (SCHEMA.md):

"""

# pkm-ingest: one conversation does both the facts and the wiki pages.
WIKI_SYSTEM = """

You also maintain a markdown wiki (an Obsidian vault) of what the user tells \
you, following the rules below. `remember` returns the raw source's path; after \
saving facts, do the ingest steps: use `wiki_read` on `index.md` and any pages \
the facts touch, then `wiki_write` the new or updated pages and the updated \
index, citing the raw source, then `wiki_log`. Keep this quick: a short \
fact touches one to three pages. Put nothing in the wiki but what the user \
told you.

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

# When every tool call in a round is a `remember` of a message that only
# states facts, the reply is always this: skip the second Claude call.
SAVED_REPLY = "Got it."


def _model_options(model: str, effort: str) -> dict:
    """Effort and the refusal fallback are only sent to the larger models;
    Haiku isn't known to accept them."""
    if "haiku" in model:
        return {}
    return {
        "output_config": {"effort": effort},
        # If Claude declines on safety grounds, retry on Anthropic's
        # recommended fallback model instead of returning a refusal.
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }


def run_turn(
    client: anthropic.Anthropic,
    settings: Settings,
    messages: list[dict],
    execute: ToolExecutor,
    system: str = SYSTEM,
    tools: list[dict] = TOOLS,
    model: str | None = None,
) -> str:
    """Run Claude until it stops calling tools. Appends every assistant and
    tool-result message to `messages` (as plain dicts, so the history can be
    serialized, e.g. returned from a Lambda). Returns the reply text."""
    while True:
        with span("claude") as s:
            response = client.beta.messages.create(
                model=model or settings.model,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                **_model_options(model or settings.model, settings.effort),
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
        if all(
            u.name == "remember" and not u.input.get("also_asks", True) for u in tool_uses
        ) and not any(r.get("is_error") for r in results):
            messages.append({"role": "assistant", "content": [{"type": "text", "text": SAVED_REPLY}]})
            return SAVED_REPLY
