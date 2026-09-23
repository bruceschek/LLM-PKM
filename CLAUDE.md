# LLM PKM

A personal knowledge store you feed by voice or text through the Claude app
(iOS or macOS), then query in plain language later. Loosely based on Andrej
Karpathy's "LLM Wiki" pattern:
https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Status

Early design. No code yet. See `BACKLOG.md` for what's next.

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
