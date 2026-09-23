# LLM PKM

A personal knowledge store you feed by voice or text through the Claude app
(iOS or macOS), then query in plain language later. Loosely based on Andrej
Karpathy's "LLM Wiki" pattern:
https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Status

Early design, plus an experimental terminal prototype (below). See
`BACKLOG.md` for what's next.

## Prototype: terminal chat with Captain for retrieval

```
cp .env.example .env    # add ANTHROPIC_API_KEY and CAPTAIN_API_KEY
uv run llm-pkm          # PKM_STORE=local runs offline, no Captain needed
uv run pytest
```

Layout (`src/llm_pkm/`):

- `core.py`: `Assistant.handle_message(text, history) -> reply`. The only
  entry point; no terminal or HTTP code, so the CLI and Lambda share it.
- `llm.py`: the system prompt, the `remember` / `recall` tools, and the tool
  loop. Claude decides whether a message is a fact or a question. The same
  two tools are meant to become MCP tools for the Claude app later.
- `stores/`: the `MemoryStore` interface (`add`, `search`), with
  `CaptainStore` and `LocalStore` implementations. Swapping Captain for an
  AWS vector store means writing one new file here.
- `stores/local.py` also serves as the raw fact log (`data/facts.jsonl`,
  git-ignored). Every fact is written there whichever store is active, so
  the data never lives only inside Captain.
- `config.py`: all settings from env vars (see `.env.example`).
- `cli.py`: the terminal loop. `lambda_handler.py`: an untested sketch of the
  Lambda entry point (the client passes the history in each request).

Things we learned:

- **Captain** (docs.captain.dev) returns matching chunks, not answers, so
  Claude does the answering. Indexing runs in the background (you get a job
  ID back), so `CaptainStore.add` waits for the job to finish before the bot
  says "got it". Each fact is indexed as its own tiny text document, an
  unusual fit for a service built to index files. Captain is a candidate for
  the long-term store; not decided.
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
