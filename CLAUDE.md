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
                        # in the chat: /ingest (add a file from raw/), /rewind (undo the
                        # last stored change), /delete-all
uv run llm-pkm --notices # also show how background wiki updates ended (failures always show)
uv run pkm-ingest       # ingest every new .md/.txt/.pdf in data/wiki/raw/ (--dry-run to just list them)
uv run pkm-lint         # health-check the wiki against its lint-checklist.md
uv run pkm-timings      # median/max time per step, from data/timings.jsonl
```

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
  like an Obsidian link. `remember` saves each message as an immutable file
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
- `config.py`: all settings from env vars (see `.env.example`).
- `timing.py`: per-step timings. Code wraps a step in `span("name")`; the
  CLI prints each message's breakdown with `--timing`, and every message is
  logged to `data/timings.jsonl` either way.
- `cli.py`: the terminal loop. `lambda_handler.py`: an untested sketch of the
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
  (`PKM_WIKI_MODEL`; background, so quality over speed). Effort `low`
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
