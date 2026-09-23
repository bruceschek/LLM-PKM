# Backlog

## Next

1. **Read and understand Karpathy's LLM Wiki gist** (Bruce)
   https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
   - Understand the three layers (raw sources / wiki / schema) and the three
     operations (ingest / query / lint).
   - Decide what carries over to short voice-captured facts, which are much
     smaller than the articles and papers the gist has in mind.
   - Form a view on the open question in `CLAUDE.md`: vector search, compiled
     wiki, or a hybrid.

## Up next

2. Research how the Claude iOS and macOS apps can call an external tool
   (remote MCP server / custom connector): what's supported, how auth works,
   and whether voice mode can trigger tools.
3. Decide the storage model (raw facts, embeddings, wiki layer) and write it
   down with reasoning.
4. Pick the AWS architecture and embedding model. Rough monthly cost at
   personal scale.
5. Define the tool interface (e.g. `remember`, `recall`, `forget`, `lint`)
   and the data schema for a single fact.
6. Build a local prototype (uv, Python 3.13) of capture and recall before
   touching AWS.

## Later

- Deploy to AWS (infra as code).
- Connect the Claude app to it and test end to end from iPhone by voice.
- Handle superseded or contradictory facts.
- Periodic lint / consolidation job.
- Export / backup (plain markdown in git?).

## Done

- 2026-09-22: Created repo, `CLAUDE.md`, and `BACKLOG.md`.
