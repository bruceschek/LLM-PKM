# Backlog

## Next

**Direction changed 2026-10-06: wiki-first, vector search on hold** (see
`CLAUDE.md`; tag `vector-prototype` is the state before).

W. **Wiki-first prototype** (Karpathy's LLM Wiki pattern, no fact store)
   - [x] Step 1 (2026-10-06): `PKM_STORE=wiki` is the default. Chat has
     `remember` and `wiki_read`; the index is in its prompt; answers name
     the pages they came from.
   - [x] Step 2 (2026-10-06): one maintenance conversation for every wiki
     change. A capture stays pending until its update succeeds; `pkm-ingest`
     retries failures. `uv run pkm-lint` added.
   - [x] Step 3 (2026-10-06): Obsidian fit. Valid frontmatter properties,
     aliases, graph colors, `wiki_read` by page title, vault path shown at
     startup.
   - [x] First real run on a throwaway vault (2026-10-06): captures,
     background updates and answers from pages all worked.
   - [ ] Try it on the live vault: capture, ask, open `data/wiki/` in
     Obsidian, run `pkm-lint`. Check Haiku still picks the right pages
     once the index is long.
   - [x] 2026-10-06: everyday context (owner's name, date and time,
     public holidays); `/rewind` (also in plain words) and `/delete-all`
     (must type DELETE).
   - [ ] File useful answers back into the wiki (the gist's query step 3).
     Chat can't write pages; give it a tool that queues a maintenance job.
   - [x] 2026-10-08: lint from inside the chat (`/lint` or plain words).
   - [ ] A code-side check for broken links and orphans, so Claude doesn't
     have to find them by reading every page. Try lint on the live vault.
   - [ ] Superseded facts: check the maintenance conversation marks the old
     fact as the schema says.
   - [x] 2026-10-07: PDFs can be ingested; `/ingest` in the chat, with
     optional guidance on what to keep.
   - [x] 2026-10-08: sources only. The wiki holds nothing from Claude's
     general knowledge; chat may add it only after "Not from your wiki:".
     It speaks up, in bright blue, when a statement contradicts general
     knowledge. Prompt wording, tried twice for real. [ ] Try it on a long document
     ingest, where adding background is most tempting.
   - [ ] Ingest: `--watch` mode; web clips; long sources (a text file is cut
     at 100,000 characters, a PDF at 20 MB); other formats (Word, images).
   - [ ] When the index outgrows the prompt: split it by category, or add
     search over the pages (the point at which vectors might come back).

0. **ON HOLD: terminal chat with Cloudflare for retrieval** (see `CLAUDE.md`)
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
   - [ ] Run the full chat with Cloudflare.
   - [x] A question asked within about a minute of saving a fact could
     miss it: `recall` now also lists facts saved in the last 10 minutes.
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
   - (Ingest and lint follow-ups moved to item W.)

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

7. **Local MCP server for Claude Desktop** (the likely next step; focus is
   local for now, decided 2026-10-08). A small stdio server in this project
   offering `wiki_read` and `remember` (maybe `lint`, `rewind`), added to
   Claude Desktop's config. Desktop's Claude replaces our Haiku chat; wiki
   updates still run on the API key. Our prompt rules become tool
   descriptions, so "Not from your wiki" will hold less firmly.

## Later

- **AWS sketch for the cloud version (parked 2026-10-08, not built or
  priced).** API Gateway + a Python Lambda speaking MCP; the vault as
  objects in an encrypted, versioned S3 bucket (`wiki.py` needs an S3
  backend; versioning could replace `.undo/`); wiki updates through an SQS
  FIFO queue to a worker Lambda calling Opus, one at a time; Cognito for
  login; Secrets Manager for the key (or Claude via Bedrock); CDK or SAM.
  Open: the OAuth flow the Claude apps expect (Cognito alone likely isn't
  enough), syncing the vault back to the Mac for Obsidian, and reports
  fetched by a tool since the app can't be sent notices.

- Deploy to AWS (infra as code).
- Connect the Claude app to it and test end to end from iPhone by voice.
- Handle superseded or contradictory facts.
- Periodic lint / consolidation job.
- Export / backup (plain markdown in git?).

## Done

- 2026-09-22: Created repo, `CLAUDE.md`, and `BACKLOG.md`.
- 2026-09-23: First draft of the local prototype (uv, Python 3.13): capture
  and recall in a terminal chat (`uv run llm-pkm`), before touching AWS.
