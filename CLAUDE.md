# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# LLM PKM

A personal knowledge store you feed by voice or text through the Claude app
(iOS or macOS), then query in plain language later. Loosely based on Andrej
Karpathy's "LLM Wiki" pattern:
https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Status

Early design, plus an experimental terminal prototype (below). See
`BACKLOG.md` for what's next.

## Direction: wiki-first (decided 2026-10-06)

Vector embeddings are **on hold**. The focus is Karpathy's pattern alone: raw
sources, a wiki Claude maintains, a schema, and the ingest / query / lint
operations. The wiki is the memory, there is no fact store, and the vault is
meant to be read in Obsidian.

- `PKM_STORE=wiki` is the default and means "no retrieval store".
- The vector code is kept and still runs with `PKM_STORE=cloudflare`,
  `captain` or `local`: `stores/`, `recall`, `facts.jsonl`, and the prompts
  marked "on hold" in `llm.py`. Don't extend it; don't delete it yet.
- The git tag `vector-prototype` is the last commit before this change.
- Why: the gist's point is that knowledge is compiled once and kept current
  rather than re-derived from chunks per question, and we want to find out
  how far that goes on its own for short personal facts before adding
  search back (the gist suggests search only once the index stops being
  enough).
- First real run, 2026-10-06, on a throwaway vault: a capture replied in
  about 3 s, a question answered from the wiki in about 5 s (one page read),
  and a background wiki update took 13 to 23 s. Pages came out with valid
  frontmatter. Not yet tried on the live vault or with many pages.
- The Anthropic key is exported in `~/.zshrc`, and the `claude` alias there
  strips it, so shells started by Claude Code don't have it.

## Prototype: terminal chat over the wiki

```
cp .env.example .env    # add ANTHROPIC_API_KEY
uv run llm-pkm          # chat; the vault is data/wiki/ (open that folder in Obsidian)
uv run pytest
uv run pytest tests/test_wiki.py::test_raw_and_log   # one test (no linter is configured)
uv run llm-pkm --timing # also print how long each step took
                        # in the chat: /ingest (add a file from raw/), /lint, /status,
                        # /rewind (undo the last stored change), /delete-all
uv run llm-pkm --notices # also show how background wiki updates ended (failures always show)
uv run llm-pkm --script prompts.txt  # feed a text file in, one entry per line, then exit
uv run pkm-ingest       # ingest every new .md/.txt/.pdf in data/wiki/raw/ (--dry-run to just list them)
uv run pkm-lint         # health-check the wiki against its lint-checklist.md
uv run pkm-lint --check # only the checks done in code: no Claude call, nothing changed
uv run pkm-timings      # median/max time per step, from data/timings.jsonl
```

## MCP server (Claude Desktop / Claude Code connector)

```
claude mcp add llm-pkm uv -- run pkm-mcp   # register once per machine
claude mcp remove llm-pkm                  # remove the registration
```

After a code change, exit and start a new session (`/exit`, then `claude` or
`claude --continue`) — this kills and respawns the subprocess, and `uv run`
picks up the latest code automatically. No re-registration needed.
Remove and re-add only if the command itself changes (different binary or args).

Request flow (wiki-first): `cli.py` -> `Assistant.handle_message` (`core.py`)
-> `run_turn` (`llm.py`), which loops Claude <-> tools. Chat gets two tools:
`remember` (saves the message as a `raw/` file and collects the facts) and
`wiki_read`. The current `index.md` is put in the system prompt on every
turn, with a list of captures the wiki hasn't absorbed yet, so a question
costs one round of page reads and then the answer. After the reply, the
facts are queued as a `WikiJob`; a maintenance conversation (`_maintain` /
`_run_wiki_job`, `MAINTAIN_SYSTEM`, the write tools) folds them into pages.
A raw file counts as pending until that succeeds, so a failed update is
retried by `pkm-ingest`. Tool schemas and prompts live in `llm.py`, their
behavior in `core.py`.

With a fact store (on hold), `remember` also writes the raw log and the
store, and `recall` searches the store plus facts saved in the last 10
minutes.

Replies don't wait for slow work. The full session history goes to Claude on
every call, so it knows what the user just said even if nothing is indexed.
Store indexing runs on a thread per fact (`stores/background.py`); wiki
updates are queued as a `WikiJob` and run, one at a time in order, by a
worker thread in a separate Claude conversation that has the write tools
(`MAINTAIN_SYSTEM`). Both report back as `Notice`s, shown after the user's
next entry, and the CLI waits for them on exit. `Assistant(background=False)`
(tests, Lambda) runs the wiki job inline instead.

Layout (`src/llm_pkm/`):

- `core.py`: `Assistant.handle_message(text, history) -> reply`. The only
  entry point; no terminal or HTTP code, so the CLI and Lambda share it.
- `llm.py`: the system prompt, the `remember` / `recall` tools, and the tool
  loop. Claude decides whether a message is a fact or a question. The same
  two tools are meant to become MCP tools for the Claude app later.
- `stores/`: the `MemoryStore` interface (`add`, `search`), with
  `CloudflareStore` (the default), `CaptainStore` (set aside) and
  `LocalStore` implementations. Adding another backend means one new file
  here. `stores/background.py` is the shared base for stores that take a
  while to make a new fact searchable; in the CLI the wait runs on a worker
  thread (see below).
- `stores/cloudflare.py`: Workers AI (`@cf/baai/bge-base-en-v1.5`, 768
  numbers per text, `cls` pooling) turns facts and questions into
  embeddings; a Vectorize index (`llm-pkm`, cosine, created on first run)
  stores and searches them. All over Cloudflare's REST API, so no Worker is
  needed yet.
- `stores/local.py` also serves as the raw fact log (`data/facts.jsonl`,
  git-ignored). Every fact is written there whichever store is active, so
  the data never lives in only one service.
- `wiki.py`: the wiki layer (Karpathy's pattern): a folder of markdown files,
  an Obsidian vault, that Claude maintains through `wiki_read`, `wiki_write`
  and `wiki_log` tools. `wiki_read` takes a path or a page title, resolved
  like an Obsidian link; it also reads a .txt file in `raw/`, and 'LIST'
  includes the .txt and .pdf sources there (fixed 2026-10-09: lint kept
  reporting an ingested .txt source as missing because both handled only
  .md). `remember` saves each message as an immutable file
  in `raw/`. The live vault is `data/wiki/` (git-ignored: real personal
  data). `wiki-example/` is the tracked template with invented sample data.
  A new vault is seeded from it with `SCHEMA.md` (the rules Claude is
  given), `lint-checklist.md` and two `.obsidian/` settings files; an
  existing vault keeps its own copies, so a change to the template's
  `SCHEMA.md` has to be copied into the live vault by hand. `ingest.py`
  (`pkm-ingest`) handles raw files not yet in the wiki: each pending
  .md/.txt file (the vault's hidden `.ingested.json` lists the done ones)
  gets its own maintenance conversation. `lint.py` (`pkm-lint`) runs the
  lint operation.
  **Never commit anything from the live vault.**
- **Sources only (decided 2026-10-08):** Claude's general knowledge is
  kept out of the memory. Wiki maintenance (ingest, capture updates, lint)
  may write only what a raw source states: no added background, dates,
  full names or corrections; a source that looks wrong is recorded as
  written with the doubt noted. `remember` saves only what the user said.
  Chat answers come from the wiki, the conversation and the everyday
  context; outside knowledge is allowed only as a separate sentence
  starting "Not from your wiki:". This is prompt wording
  (`WIKI_CHAT_SYSTEM`, `MAINTAIN_SYSTEM`, `SCHEMA.md`, the lint
  checklist's "Outside knowledge" item), not checked in code. Why: the
  user must be able to trust that everything in the vault came from them
  or their documents. Real run 2026-10-08: "Lisbon" stayed without a
  country on its page, and chat labeled Portugal and Dune's author.
  Chat should also speak up unasked when the wiki or a new statement
  plainly contradicts general knowledge. For a capture that goes through
  `remember`'s `doubt` field (the fact is saved as said; `run_turn` adds
  the doubt to "Got it." without a second Claude call). The CLI prints
  everything from the marker (`OUTSIDE` in `llm.py`) to the end of its
  paragraph (the next blank line) in bright blue, so each such statement
  must start on its own line. The user confirmed this design 2026-10-09:
  world knowledge is welcome when the wiki lacks it, clearly labeled and
  in blue.
  Tried for real: "Lisbon, the capital of Spain" got the blue correction,
  and the page recorded the claim as written with a question for the user.
- **Any subject is accepted (decided 2026-10-09):** the memory is not
  limited to facts about the user. A statement of general knowledge the
  user enters (a scientist's biography, say) is saved like any other
  fact, phrased about its own subject, without comment. Sources-only still
  holds in the other direction: Claude adds nothing of its own. Why: a
  real run on Haiku refused a paragraph about Max Planck as "general
  knowledge, not something about you". Prompt wording only
  (`WIKI_CHAT_SYSTEM`, the `remember` tool, the MCP `remember`
  docstring). A first, milder rewording did not stop the refusal; what
  worked was dropping "personal memory" from the opening line and adding
  the "question, request, or something to save" rule above the bullets.
  Real runs 2026-10-09 on throwaway vaults: the Planck paragraph was
  saved in 4 of 4 tries, and a question the wiki couldn't answer still
  got "I don't have that" plus a "Not from your wiki:" line.
- **Obsidian:** page frontmatter must be valid YAML for the Properties
  panel: `sources` is a list of quoted links (`- "[[raw/...]]"`); a bare
  `[[link]]` there is read as a nested list. Page titles are filenames and
  must be unique. The seeded `graph.json` colors raw sources, people,
  places and topics differently.
- **Ingesting files:** .md, .txt and .pdf files put in the vault's `raw/`.
  A PDF goes to Claude as a base64 `document` block (no text-extraction
  library), so scanned pages and figures are read; the limit is 20 MB, and
  pages cite it as `[[raw/name.pdf]]`, which Obsidian opens. `/ingest` in
  the chat picks one new file, asks the user what it is and what to keep
  (passed to Claude as guidance), and queues an `IngestJob` on the same
  worker as capture updates, so wiki changes never overlap. Its result is a
  `Notice` with `asked_for=True`, shown even without `--notices`.
  `pkm-ingest` does all new files in the foreground, without guidance.
  First real PDF run 2026-10-07: a 2-page PDF took 20 s and the guidance
  was followed.
- **Lint from the chat:** `/lint`, or asking in plain words (Claude has a
  `lint` tool), queues a `LintJob` on the same worker as wiki updates; the
  report arrives as a `Notice` with `asked_for=True`. `pkm-lint` runs the
  same pass in the foreground. It is Claude reading every page against
  `lint-checklist.md`; no code checks links or orphans yet. First real run
  2026-10-08 on a 5-page throwaway vault: 58 s, sensible fixes and
  questions.
- **Decide, don't ask (decided 2026-10-09):** the user wants the wiki kept
  up without being consulted. Five pieces, after a lint pass on the live
  vault came back with seven questions:
  - *Standing rulings* in `SCHEMA.md` ("Decide, don't ask") and the lint
    checklist: make a page for anything a source names, even a one-line
    stub (the user: "create pages, even empty ones, when in doubt"); how to
    write a date with no year, a shared nickname, an unexpanded
    abbreviation; gaps are left alone. A question is allowed only when two
    sources flatly contradict and neither is newer, or a fix would delete
    something a source states.
  - *`questions.md`* at the vault root: each question is written there once,
    numbered, under Open, and moved to Answered when a source or
    instruction settles it; nothing listed is asked again. The open ones
    are put in chat's system prompt and in every capture's and
    instruction's job message (`Wiki.open_questions`).
  - *`instruct`*, a chat tool: "rename that page", "change the heading to
    X", or an answer to a question. The message is saved as a raw source
    and queued as an `InstructJob` (log kind `edit`, notice "Wiki
    changed: ..."), rewindable like a capture. Maintenance also got
    `wiki_delete` (pages under `wiki/` only), so it can merge and rename.
    Chat is also given the last lint report (in memory only, lost on
    restart) and told never to guess at causes; it had invented "a sync
    issue".
  - *Code checks* (`checks.py`): broken links, pages missing from the index
    or linked from nowhere, frontmatter, uncited pages, duplicate titles
    and misplaced files are found exactly in Python and handed to the lint
    conversation; whatever still fails afterwards is appended to the
    report. Links resolve as in Obsidian, so a non-.md source must be
    linked with its extension.
  - *`PKM_LINT_MODEL`*: lint's own model, default the wiki model. The live
    `.env` uses `claude-haiku-5-5` for updates and `claude-sonnet-5-5` for
    lint.
  Real run 2026-10-09 on a throwaway vault (7 script lines, 128 s): stubs
  were made for a school and a club mentioned once, a shared nickname got
  "not to be confused" notes, a rename instruction was carried out, and
  two Sonnet lint passes (10 s each) asked nothing. Not yet seen: a real
  contradiction producing a question, or an answer closing one.
- **Rewind:** every change to the wiki (a capture's update, an ingest, a
  lint pass) runs inside `Wiki.journal`, which records the earlier content
  of each page it writes and the log's length in the vault's hidden
  `.undo/` (last 20 kept). `Assistant.rewind` takes back the newest record,
  deletes a chat capture's raw file (a hand-dropped file is kept and goes
  back to pending), and removes that turn from the session history. It is
  both the `/rewind` command and a `rewind` tool, so plain words work.
  It waits for any running wiki update first.
- **Delete all:** `/delete-all` in the chat, which requires typing `DELETE`.
  Claude has no tool for it, so the confirmation can't be skipped. It
  erases raw sources, pages, index, log, `.undo/`, `facts.jsonl` and
  `timings.jsonl` (which holds message text); it keeps `SCHEMA.md`,
  `lint-checklist.md`, the Obsidian settings and the owner's name. A remote
  store is not cleared.
- `ambient.py`: everyday context that isn't in the wiki (so far the
  owner's name, the date and time, and the public holidays of `PKM_COUNTRY`, default US, from the
  `holidays` package). Each provider is a function returning one line;
  `everyday_context()` adds them to the system prompt of chat and of wiki
  maintenance, so they cost no tool call. Slow or rarely needed ones should
  become tools instead. The memory has a single owner: their name comes
  from `PKM_OWNER` or the vault's hidden `.owner` file, and if neither is
  set the chat asks for it at startup and saves it there (`pkm-ingest` and
  `pkm-lint` don't ask). The chat prompt also tells Claude to turn "next
  Tuesday" into the actual date when saving a fact.
- **Scripts:** `--script FILE` (`run_script` in `cli.py`) sends each line
  of a text file as if typed, and waits for that entry's wiki update,
  ingest or lint (up to `SCRIPT_WAIT`, 15 minutes) before the next, printing
  every outcome with its time, then a count of problems by line number.
  Blank lines and `#` lines are skipped and `quit` stops early. Nothing can
  be asked mid-script: `/ingest` takes no guidance and needs a file name if
  several are pending, and `/delete-all` is refused. Lines share one session
  history, as in a typed chat. First real run 2026-10-09 on the live
  vault: 22 entries in 735 s, 20 wiki updates; the last two failed because
  the Anthropic account hit its monthly usage limit, and the script kept
  going rather than stopping.
- `config.py`: all settings from env vars (see `.env.example`).
- `timing.py`: per-step timings. Code wraps a step in `span("name")`; the
  CLI prints each message's breakdown with `--timing`, and every message is
  logged to `data/timings.jsonl` either way.
- `cli.py`: the terminal loop. All output goes through `say` (green) and
  all input through `read` (the `you>` prompt and typed text in yellow);
  `say_reply` prints "Not from your wiki:" lines in bright blue;
  colors are off when output isn't a terminal or `NO_COLOR` is set. `lambda_handler.py`: an untested sketch of the
  Lambda entry point (the client passes the history in each request).

Things we learned (most of these are about the on-hold vector path):

- **Stores make new facts searchable asynchronously** (Captain: a job;
  Vectorize: a batch job after the write). In the CLI the wait runs on a
  worker thread, so the bot says "got it" right away; how the save ended,
  with its timing, is printed after the user's next entry. Elsewhere (the
  Lambda sketch), `add` waits before returning.
- **Captain** (docs.captain.dev), set aside 2026-09-23 in favor of
  Cloudflare. It returns matching chunks, not answers, so Claude does the
  answering. Each fact is indexed as its own tiny text document, an unusual
  fit for a service built to index files.
- **Captain indexing is slow for our use** (measured 2026-09-23): 9 to 14 s
  of Captain-side processing per one-sentence fact, no queue time. Its text
  pipeline writes a summary and tags for each section before embedding, and
  the docs offer no faster mode. Search is fast (about 0.5 s).
- **Cloudflare, measured 2026-09-25:** saving a fact (embed + write) takes
  about 1 s and a search about 0.2 s. But a new fact takes 15 to 70 s to
  become searchable, and searches can still miss it briefly after Vectorize
  reports it processed. Meaning-based search works: "who is the user
  married to?" matched "The user's wife's name is Hemmie." at 0.79,
  against 0.48 for the next fact.
- **Model:** chat turns use `claude-haiku-4-5-20251001` (`PKM_MODEL`; the
  user waits for these); wiki updates and file ingest use `claude-opus-5`
  (`PKM_WIKI_MODEL`; background, so quality over speed; the live `.env`
  overrides it with `claude-haiku-5-5` since 2026-10-09, for cost). Effort `low`
  (`PKM_EFFORT`) and the server-side refusal fallback are sent only to
  non-Haiku models. Haiku was chosen for speed and is untested for quality:
  if it misjudges fact vs. question, set `PKM_MODEL=claude-opus-5`.
- **Reply speed (measured 2026-10-01):** a capture took 4 to 8 s, nearly all
  in two sequential Claude calls plus the Cloudflare write. Fixes: when a
  message only states facts (`remember`'s `also_asks` is false) `run_turn`
  replies "Got it." itself, skipping the second call; the embed and upsert
  now run on the background thread too; Haiku for chat.
- **Search wording:** the local store's keyword search misses synonyms
  ("married to" vs "wife"). The prompt tells Claude to retry `recall` with
  other wording, which fixed it in testing.
- The chatbot only remembers what is in the store. Conversation history is
  kept for the current session only.

## The idea

- **Capture:** From the Claude app, say or type a stray fact ("Dana's kid is
  named Theo", "the garage code is on the fridge sticky note", "I liked the
  pho at X"). Claude sends it to this tool.
- **Store:** The fact is saved in the cloud (probably AWS). Format and
  structure aren't decided yet.
- **Retrieve:** Later, ask in plain language ("what was Dana's kid's name?")
  and get the answer back, with the source fact it came from.

## Karpathy's pattern, briefly

Three layers:

1. **Raw sources.** Immutable inputs. Here, each captured fact, with a
   timestamp.
2. **The wiki.** Markdown pages the LLM writes and maintains (entities,
   topics, summaries, cross-links), plus `index.md` (catalog) and `log.md`
   (append-only record of changes).
3. **The schema.** A config doc (like this file) telling the LLM how to
   maintain the wiki.

Operations: **ingest** (fold a new source into the wiki), **query** (answer
from the wiki, and file useful answers back), **lint** (find contradictions,
stale facts, orphans, gaps).

His point is that the knowledge gets *compiled once and kept current*, rather
than re-derived from raw chunks on every question the way plain RAG does it.

## Open design questions

- **Vector search vs. compiled wiki vs. both.** The starting assumption is
  embeddings plus cosine similarity. Karpathy's pattern is partly a reaction
  *against* plain vector RAG. A likely hybrid: keep raw facts (with
  embeddings) as the source of truth, and have the LLM maintain an
  entity/topic layer on top of them. To be decided after the gist is read
  (see backlog).
- **How the Claude app connects.** Most likely a remote MCP server (a custom
  connector) exposing tools like `remember(fact)` and `recall(query)`. Needs
  checking: which connector types the iOS and macOS apps support, and how
  auth works.
- **AWS shape.** Options include Lambda + API Gateway, S3 (markdown / raw
  JSON), S3 Vectors, OpenSearch Serverless, Aurora Postgres + pgvector, or
  DynamoDB. Cost at personal scale matters more than throughput.
- **Embedding model.** Amazon Titan / Cohere on Bedrock, Voyage, or another.
- **Privacy.** This will hold personal data. It needs encryption at rest and
  real auth, and it should be single-user to start.
- **Updates and contradictions.** What happens when a new fact supersedes an
  old one ("Dana moved to Denver").

## Conventions

- Python projects use `uv` with Python 3.13 (`uv init --python 3.13`),
  unless a Lambda runtime requires otherwise.
- Keep `BACKLOG.md` current: move items to Done with the date when finished.
- Record design decisions in this file (or a `docs/decisions/` folder once
  there are several) with the reasoning behind them.

## Repo

GitHub: https://github.com/bruceschek/LLM-PKM (public). Don't commit secrets,
AWS credentials, or real personal facts.
