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

## Prototype: terminal chat with Cloudflare for retrieval

```
cp .env.example .env    # add ANTHROPIC_API_KEY and the Cloudflare account ID + token
uv run llm-pkm          # PKM_STORE=local runs offline, no Cloudflare needed
uv run pytest
uv run pytest tests/test_wiki.py::test_raw_and_log   # one test (no linter is configured)
uv run llm-pkm --timing # also print how long each step took
uv run pkm-ingest       # ingest files dropped into data/wiki/raw/ (--dry-run to just list them)
uv run pkm-timings      # median/max time per step, from data/timings.jsonl
```

Request flow: `cli.py` -> `Assistant.handle_message` (`core.py`) -> `run_turn`
(`llm.py`), which loops Claude <-> tools. The tool executor is a closure in
`_converse`: `remember` writes the raw log, the retrieval store and (if the
wiki is on) a `raw/` file; `recall` searches the store *plus* facts from the
local log saved in the last 10 minutes (the store lags 15 to 70 s); chat has
only read access to the wiki (`wiki_read`). Tool schemas and prompts live in
`llm.py`, their behavior in `core.py`.

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
  and `wiki_log` tools. `remember` also saves each message as an immutable
  file in `raw/`. The live vault is `data/wiki/` (git-ignored: real personal
  data; `PKM_WIKI_DIR=off` disables it). `wiki-example/` is the tracked
  template with invented sample data, and `SCHEMA.md` there is the rules
  Claude is given. `ingest.py` (`pkm-ingest`) handles files you drop into
  `raw/` by hand: each new .md/.txt file (tracked in the vault's hidden
  `.ingested.json`; chat captures are pre-marked) gets its own Claude
  conversation that writes wiki pages and calls `remember` per fact.
  **Never commit anything from the live vault.**
- `config.py`: all settings from env vars (see `.env.example`).
- `timing.py`: per-step timings. Code wraps a step in `span("name")`; the
  CLI prints each message's breakdown with `--timing`, and every message is
  logged to `data/timings.jsonl` either way.
- `cli.py`: the terminal loop. `lambda_handler.py`: an untested sketch of the
  Lambda entry point (the client passes the history in each request).

Things we learned:

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
- **Model:** `claude-opus-5` at effort `low` by default (`PKM_MODEL`,
  `PKM_EFFORT`), with server-side refusal fallback enabled.
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
