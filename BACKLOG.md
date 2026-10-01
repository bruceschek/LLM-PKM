# Backlog

## Next

0. **Experiment: terminal chat with Cloudflare for retrieval** (see `CLAUDE.md`)
   - [x] Built it and tested it with the local store.
   - [x] Tried Captain: meaning-based search, but 10 to 15 s to index each
     fact. Set aside 2026-09-23 (code kept, `PKM_STORE=captain`).
   - [x] Timing per step (`uv run pkm-timings`).
   - [x] Saves finish in the background in the CLI, so "got it" comes back
     without waiting for the store.
   - [x] Wrote the Cloudflare store (Workers AI embeddings + Vectorize),
     tested against a fake API only.
   - [x] Created the Cloudflare account and token; tested the store for
     real (2026-09-25). Saves about 1 s, searches 0.2 s, "married to" finds
     "wife". But a new fact takes 15 to 70 s to become searchable.
   - [ ] Run the full chat with Cloudflare once the Anthropic API limit is
     sorted.
   - [ ] **Risk, parked (bigger with Vectorize):** a question asked within
     about a minute of saving a fact may not find it. Possible fix: have
     `recall` also search the local fact log for facts saved in the last
     few minutes.
   - [x] Speed (2026-10-01): skip the second Claude call when a message only
     saves facts; Cloudflare write on the background thread; Haiku for chat.
     Tested with fakes only. [ ] Re-measure with `uv run pkm-timings` and
     check Haiku's fact/question judgment.
   - [ ] Vector search always returns its closest matches, even when none
     is relevant. Watch whether Claude answers from weak matches; if so,
     drop hits below a score threshold.

1. **Read and understand Karpathy's LLM Wiki gist** (Bruce)
   https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
   - Understand the three layers (raw sources / wiki / schema) and the three
     operations (ingest / query / lint).
   - Decide what carries over to short voice-captured facts, which are much
     smaller than the articles and papers the gist has in mind.
   - Form a view on the open question in `CLAUDE.md`: vector search, compiled
     wiki, or a hybrid.

   - [x] Starter wiki vault in `wiki-example/` and wiki tools wired into the
     chat (2026-09-30). Untested with the real model.
   - [ ] Try it: capture a few facts, open `data/wiki/` in Obsidian, check the
     pages. Watch the latency (each save now costs extra Claude calls) and
     whether `recall` or the wiki answers questions better.
   - [x] `uv run pkm-ingest`: ingests files dropped into `raw/` (wiki pages
     plus `remember` per fact), 2026-09-30. Tested with a fake model only.
   - [ ] Ingest: `--watch` mode; PDFs/web clips; chunking long sources into
     the vector store.
   - [ ] Add a `lint` command that runs the checklist.

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
6. **Cloud version both developers can use, behind GitHub login.** A remote
   MCP server on Cloudflare Workers that the Claude app connects to. Users
   log in with GitHub, and only allowlisted usernames get in.
   Steps:
   1. Create the project from Cloudflare's `remote-mcp-github-oauth`
      template (in the `cloudflare/ai` repo) with `npm create cloudflare`.
   2. Create a GitHub OAuth App in GitHub settings, with its callback set
      to `https://<your-worker>.workers.dev/callback`.
   3. Store the secrets with `wrangler secret put`: `GITHUB_CLIENT_ID`,
      `GITHUB_CLIENT_SECRET`, and `COOKIE_ENCRYPTION_KEY`. Bind the
      existing `llm-pkm` Vectorize index and Workers AI directly instead of
      calling them over REST.
   4. Add the allowlist, following the example pattern already in the
      template. Reject any login whose GitHub username isn't on the list.
      Usernames: TBD (the two developers).

   Open questions:
   - This runs on Cloudflare, not AWS. Does it replace the AWS Lambda plan
     (item 4), or sit in front of it?
   - The template is TypeScript, so the Python `remember` / `recall` logic
     would need porting or calling over HTTP.
   - Should the two developers share one memory store, or each have their
     own (e.g. a separate Captain collection per GitHub username)?

## Later

- Deploy to AWS (infra as code).
- Connect the Claude app to it and test end to end from iPhone by voice.
- Handle superseded or contradictory facts.
- Periodic lint / consolidation job.
- Export / backup (plain markdown in git?).

## Done

- 2026-09-22: Created repo, `CLAUDE.md`, and `BACKLOG.md`.
- 2026-09-23: First draft of the local prototype (uv, Python 3.13): capture
  and recall in a terminal chat (`uv run llm-pkm`), before touching AWS.
