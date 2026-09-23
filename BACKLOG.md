# Backlog

## Next

0. **Experiment: terminal chat with Captain for retrieval** (see `CLAUDE.md`)
   - [x] Built it and tested it with the local store.
   - [ ] Add `CAPTAIN_API_KEY` to `.env` and test with Captain: how long
     indexing takes, whether meaning-based search finds "married to" → wife,
     and credit cost per fact.
   - [ ] Decide whether Captain stays in the running as the long-term store.

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
7. **Cloud version both developers can use, behind GitHub login.** A remote
   MCP server on Cloudflare Workers that the Claude app connects to. Users
   log in with GitHub, and only allowlisted usernames get in.
   Steps:
   1. Create the project from Cloudflare's `remote-mcp-github-oauth`
      template (in the `cloudflare/ai` repo) with `npm create cloudflare`.
   2. Create a GitHub OAuth App in GitHub settings, with its callback set
      to `https://<your-worker>.workers.dev/callback`.
   3. Store the secrets with `wrangler secret put`: `GITHUB_CLIENT_ID`,
      `GITHUB_CLIENT_SECRET`, `COOKIE_ENCRYPTION_KEY`, and `CAPTAIN_API_KEY`.
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
