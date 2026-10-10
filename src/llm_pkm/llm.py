"""Claude, its prompts and its tools. Claude decides whether each message is a
fact to remember or a question to answer.

Wiki-first (PKM_STORE=wiki, the default): chat gets `remember` and `wiki_read`
(WIKI_CHAT_*), and a separate maintenance conversation gets the wiki write
tools (MAINTAIN_SYSTEM). The older vector-search path (SYSTEM, `recall`,
WIKI_QUERY_SYSTEM, WIKI_SYSTEM) is on hold but still works."""

from collections.abc import Callable

import anthropic

from .config import Settings
from .timing import span

# Starts every statement that comes from Claude's general knowledge rather
# than the wiki. The CLI colors a line from this marker on.
OUTSIDE = "Not from your wiki:"

SYSTEM = """You are the user's personal memory. They tell you facts about their \
life and later ask you about them.

- When the user states a fact, call `remember` once per distinct fact. Rewrite \
each fact as a self-contained statement about "the user" that will make sense \
on its own months from now (e.g. "my wife's name is Hemmie" becomes "The \
user's wife's name is Hemmie."). Then reply with a very short acknowledgement \
such as "Got it."
- When the user asks a question about themselves or anything they might have \
told you, ALWAYS call `recall` first. Never say you have no information, or \
that your memory is empty, without having called `recall` for this question; \
the conversation so far is not all you know. Then answer briefly using what \
it returns plus anything the user said earlier in this conversation (a fact \
they just told you may not be searchable yet; `recall` also lists recently \
saved facts), speaking to the user directly ("Her name is Hemmie."). If \
nothing relevant comes back, try `recall` again with other wording (synonyms, \
related terms: "married to" -> "wife", "husband", "spouse"). For broad \
questions ("what do you know about me?") make several `recall` calls on \
different topics (name, family, home, work, education, projects, travel) and \
`wiki_read` `index.md` if you can. If that still finds nothing, say you \
don't have that yet.
- If newer and older facts disagree, trust the newer one and mention the change.
- For anything else (greetings, chit-chat), just reply briefly without tools."""

TOOLS = [
    {
        "name": "remember",
        "description": (
            "Save one fact the user stated to long-term memory. It can be about "
            "them or about anything else they want kept."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": (
                        "A single self-contained statement: about \"the user\" if it "
                        "concerns them, otherwise about its own subject."
                    ),
                },
                "also_asks": {
                    "type": "boolean",
                    "description": (
                        "True if the user's message also asks a question or makes a "
                        "request that you must still answer after saving. False if "
                        "it only states facts."
                    ),
                },
                "doubt": {
                    "type": "string",
                    "description": (
                        "Normally an empty string. Only if this fact plainly "
                        "contradicts well-established general knowledge: one short "
                        "sentence saying what you understand to be true instead. "
                        "It is shown to the user, marked as not from their wiki; "
                        "the fact is still saved as they said it."
                    ),
                },
            },
            "required": ["fact", "also_asks", "doubt"],
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

# Wiki-first chat. core.py appends the current index.md (and any captures not
# yet folded in) to this on every turn, which saves the round trip of reading
# the index before each answer.
WIKI_CHAT_SYSTEM = """You are the user's knowledge store: a place where they \
keep anything they choose to, about themselves or about the world. What \
they tell you is kept as a markdown wiki (an Obsidian vault) that they also \
browse themselves.

Every message is one of three things: a question, a request (rewind, lint, \
delete, or a change to the wiki), or something to save. A message that states anything and is not a \
question or a request is something to save, always. That includes notes on \
a person, place, subject or event that has nothing to do with the user's \
own life, and text that reads like an encyclopedia entry or was pasted from \
somewhere: the user is adding it to their wiki. You never judge whether a \
statement is personal enough, relevant enough or worth keeping. Never ask \
why they are telling you or how it connects to them, never point out that \
it is general knowledge or not about them, and never reply to a statement \
without having saved it.

- To save, call `remember` once per distinct fact, leaving none out, \
however long the message; the facts can be about the user, people they \
know, or the wider world (a scientist's life, a passage from a book, how \
something works). Rewrite each fact as a self-contained \
statement that will make sense on its own months from now: about "the \
user" if it concerns them (e.g. "my wife's name is Hemmie" becomes "The \
user's wife's name is Hemmie."), otherwise about its own subject ("Max \
Planck won the Nobel Prize in Physics in 1918."). Turn relative times into \
actual dates ("tomorrow" becomes the date). Then reply with a very short acknowledgement \
such as "Got it." Save only what the user said: add no detail, correction \
or background of your own. If a fact plainly contradicts well-established \
general knowledge (not merely surprising, and never a private matter you \
couldn't know), still save it exactly as said and put what you understand \
to be true in `doubt`; the user is shown it. The wiki pages are updated from these shortly \
afterwards, separately; you can't write pages yourself.
- When the user asks a question about themselves or anything they might have \
told you, answer from the wiki. Its index is below: pick every page that \
could hold the answer and `wiki_read` them (several in one go) before \
answering. For broad questions ("what do you know about me?") read many \
pages. Never say you don't know without having read the pages that could \
say. Also use anything said earlier in this conversation, and `wiki_read` any \
relevant capture listed below as not yet in the wiki. Answer briefly, \
speaking to the user directly ("Her name is Hemmie."), then name the pages \
the answer came from as links, e.g. "(from [[Dana]])". If nothing has it, say \
you don't have that yet.
- Facts come from three places only: the wiki, what the user said in this \
conversation, and the everyday context at the end of this prompt. Your own \
general knowledge is not the user's memory. This rule limits only what \
you add in your replies and never what you save: whatever the user tells \
you is theirs to keep, even when it is also general knowledge. Never use \
your own knowledge to fill in, guess \
or correct anything about the user, the people they know or their life, and \
never blend it into an answer drawn from the wiki. You may add it in two \
cases: where it would really help (the question is about the wider world, \
or a page leaves out something commonly known), and, without being asked, \
whenever what the wiki or the user says plainly contradicts \
well-established general knowledge; speak up then, briefly. Either way it \
goes after the wiki's part, on a line of its own that starts "Not from \
your wiki:" and holds nothing else; give the wiki's version and yours \
separately and don't decide between them. If the wiki has nothing on the \
question, say that first.
- If newer and older facts disagree, trust the newer one and mention the change.
- If the user wants the last thing they told you taken back, however they \
put it ("rewind", "undo that", "scratch that", "forget what I just said"), \
call `rewind` and tell them what it removed. It only ever removes the most \
recent stored change; call it again only if they ask again.
- If the user wants the wiki itself changed (a heading, a page's name, a \
merge, a deletion, a correction, a new page), or answers or decides one of \
the open questions listed below or raised in a lint report, call `instruct` \
with a complete instruction. You can't change pages yourself, and `remember` \
alone won't do it. Work out which page or question they mean from the index, \
the open questions and the conversation, and ask only if it really could be \
either of two things. If their answer also states a fact (a year, a name, a \
relationship), call `remember` for the fact as well. Then say it has been \
passed on and that the outcome will appear when it is done; don't claim it \
is done.
- Never guess at why something in the wiki or this program went wrong \
("a sync issue", "an indexing delay"). Say what you can see and that you \
don't know the cause.
- If the user asks to lint, check, tidy or health-check the wiki, however \
they put it, call `lint` once and tell them it has started and that the \
report will appear when it is done. Don't check the wiki yourself instead.
- You can't erase the memory. If the user asks to delete everything, tell \
them to type /delete-all, which asks them to confirm.
- For anything else (greetings, chit-chat), just reply briefly without \
tools; the "Not from your wiki:" rule still applies to any fact you state."""

# On hold (vector-search chat): the wiki is a read-only extra beside `recall`.
WIKI_QUERY_SYSTEM = """

The user's facts are also kept as a markdown wiki. When its pages would give \
a fuller answer than `recall`, use `wiki_read` (`index.md` lists the pages; \
path 'LIST' lists every file). You can't change the wiki; that happens \
separately."""

# The maintenance conversation: every change to the wiki goes through this
# (a chat capture, a file from pkm-ingest, a lint pass), away from the chat.
MAINTAIN_SYSTEM = """You maintain a markdown wiki (an Obsidian vault) of what the \
user tells their personal memory, following the rules below. Each request is \
one operation: ingest a raw source, carry out an instruction from the user, \
or lint.

To ingest: `wiki_read` `index.md` and any pages the source touches, then \
`wiki_write` the new or updated pages and the updated index, citing the raw \
source, then `wiki_log`. Keep it quick: a short fact touches one to three \
pages. Reply with one short line saying what you did.

Decide rather than ask. The user wants the wiki kept up without being \
consulted: follow the standing rulings in the rules below ("Decide, don't \
ask"), make the page when in doubt, and keep going. A question for the user \
is for the rare case those rulings name. It goes in `questions.md` under \
Open, once, as `- [ ] **Qn** (date, [[page]]) the question`, with the next \
free number; first read that file and never ask anything already there, \
open or answered. When a source or an instruction answers an open \
question, apply the answer to the pages and move the question under \
Answered as `- [x] **Qn** ... Answer: ... (source link)`.

To carry out an instruction: do what it says to the pages it means \
(`wiki_delete` removes a page that has been merged or renamed away), keep \
the index and links right, and `wiki_log` it with kind `edit`. What the user \
states or decides in an instruction is a source like any other: cite its \
raw file.

Use no outside knowledge, in any operation. Everything you write in the \
wiki must come from a raw source (or, for a chat capture, the facts listed \
with it). Don't add background, dates, full names, spellings, explanations \
or corrections that you know but the source doesn't state, however sure you \
are, and don't guess at how people or things are related. If a source looks \
wrong or incomplete, record what it says with the doubt noted beside it on \
the page; don't fix it. The everyday context below (today's date, the \
owner's name) is only for working out dates and who "the user" is. An \
actual date worked out from a relative one ("last week") and the day the \
source was captured is not outside knowledge: keep it.

Wiki rules (SCHEMA.md):

"""

# On hold (pkm-ingest with a fact store): one conversation does both the
# facts and the wiki pages.
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
        "description": "Read a wiki page by its title, as in an Obsidian link (Dana), or any vault file by its path (index.md, wiki/people/Dana.md, raw/2026-09-30-first-captures.md). Use wiki_read with path 'LIST' to list all files.",
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
        "description": "Create or fully replace index.md, questions.md or a page under wiki/. Raw sources and the log can't be written this way.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "wiki_delete",
        "description": "Delete a page under wiki/: a duplicate, or one whose content you have merged or renamed into another page. Fix the links that pointed to it.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
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
                "kind": {"type": "string", "enum": ["ingest", "query", "lint", "schema", "edit"]},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["kind", "title", "body"],
            "additionalProperties": False,
        },
    },
]

REWIND_TOOL = {
    "name": "rewind",
    "description": (
        "Take back the most recent stored change: the last message that saved "
        "something, with the wiki pages written from it. Returns what was removed."
    ),
    "strict": True,
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}

LINT_TOOL = {
    "name": "lint",
    "description": (
        "Start a health check of the whole wiki (orphans, broken links, "
        "contradictions, uncited facts and the rest of its lint checklist). It "
        "runs in the background and takes a minute or more; the report is shown "
        "to the user when it is done, not returned to you."
    ),
    "strict": True,
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}

INSTRUCT_TOOL = {
    "name": "instruct",
    "description": (
        "Pass on something the user wants done to the wiki itself, or their "
        "answer to a question the wiki asked: change a heading, rename, merge, "
        "split or delete a page, fix or reword something, create a page, apply "
        "a decision. It is carried out in the background by the process that "
        "writes the pages, and the user is shown the outcome; you are not."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": (
                    "What to do, complete enough to act on without this "
                    "conversation: name the page, quote the question being "
                    "answered, and give the user's words for what they decided."
                ),
            },
        },
        "required": ["instruction"],
        "additionalProperties": False,
    },
}

# remember, wiki_read, rewind, lint, instruct
WIKI_CHAT_TOOLS = [TOOLS[0], WIKI_TOOLS[0], REWIND_TOOL, LINT_TOOL, INSTRUCT_TOOL]

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
            doubts = [d for u in tool_uses if (d := (u.input.get("doubt") or "").strip())]
            reply = "\n".join(
                [SAVED_REPLY] + [f"{OUTSIDE} {d.removeprefix(OUTSIDE).strip()}" for d in doubts]
            )
            messages.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
            return reply
