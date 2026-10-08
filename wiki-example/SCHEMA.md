# Schema

The rules for this wiki. You and the LLM edit this file together as you learn
what works. (It plays the role `CLAUDE.md` plays for Claude Code.)

Pattern: Karpathy's "LLM Wiki",
https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Three layers

1. **Raw sources** (`raw/`). Immutable. One file per capture or document,
   named `YYYY-MM-DD-short-slug.md`. The LLM reads these and never edits them.
2. **The wiki** (`wiki/`). Pages the LLM writes and maintains. The LLM owns
   this layer; the human reads it.
   - `wiki/people/`, `wiki/places/`, `wiki/topics/`: one page per entity or
     topic. Filenames are the page title, so `[[Dana]]` just works. Titles
     must be unique across the whole vault, and can't contain `/ \ : # ^ [ ] |`.
3. **The schema** (this file).

Two special files at the vault root: [[index]] (catalog) and [[log]] (history).

## Page format

The human reads this wiki in Obsidian, so pages must be valid there. Every
wiki page starts with frontmatter (Obsidian shows it as Properties), then a
one-line summary, then details:

```markdown
---
type: person
aliases:
  - Dana Reyes
updated: 2026-09-30
sources:
  - "[[raw/2026-09-30-first-captures]]"
---
One-sentence summary.

## Facts
- Fact, with a link to the source it came from.

## Related
- [[Other Page]]
```

Rules:

- `type` is `person`, `place` or `topic`. `aliases` (optional) lists other
  names the page goes by, so links and search find it. `sources` is a list
  with one quoted link per line, exactly as above: an unquoted `[[link]]` is
  not valid in frontmatter.
- No `# Title` heading at the top: Obsidian shows the filename as the title.
- Link generously with `[[wikilinks]]`; every page should link to at least
  one other page and be linked from [[index]].
- Every fact cites a raw source. If the source is unclear, say so.
- Sources only: the wiki holds what the raw sources say and nothing else.
  The LLM adds no general knowledge of its own (background, dates, full
  names, corrections), even when it is sure. A source that looks wrong is
  recorded as written, with the doubt noted for the human.
- When a new fact contradicts an old one, don't delete the old one. Mark it
  `(superseded 2026-10-02: moved to Denver)` and add the new one.
- Keep pages short. Split a page when it passes about a screen.

## Operations

### Ingest (a new source arrives)

1. Save it in `raw/` with a dated filename.
2. Read it. Write a short summary of the takeaways.
3. Create or update the wiki pages it touches (often several). Add
   cross-links both ways.
4. Add any new pages to [[index]] with a one-line summary.
5. Append an entry to [[log]].

### Query (a question arrives)

1. Read [[index]] to find the relevant pages, then read those.
2. Answer, citing the pages (and through them, the raw sources).
3. If the answer took real synthesis, file it back as a new page or a
   section, so the work isn't lost in chat. Log it. (Not automatic yet: the
   chat can read the wiki but not write it.)

### Lint (periodic health check)

Follow [[lint-checklist]]. Fix what's safe, list what needs a human decision,
log the pass.

## Log format

Each entry starts with `## [YYYY-MM-DD] kind | title` so it can be grepped:

```
grep "^## \[" log.md | tail -5
```

`kind` is one of `ingest`, `query`, `lint`, `schema`.
