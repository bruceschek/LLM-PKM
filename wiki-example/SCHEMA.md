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

Three special files at the vault root: [[index]] (catalog), [[log]]
(history) and [[questions]] (what the LLM is waiting for the human to settle).

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

## Decide, don't ask

The human wants the wiki kept up without being consulted. The LLM decides,
by these standing rulings, and records what it decided where a reader will
see it. None of them is outside knowledge: each only settles how to write
down what the sources already say.

- **Make the page.** Every person, place, organization or subject a source
  names gets its own page, even from a single mention and even if all that
  can be written is one line saying where it was mentioned (a stub). When
  unsure whether something deserves a page, it does. Never ask whether to
  create one.
- **A date with no year:** use the year given in the facts listed with the
  capture (the chat works it out from what was said: "we are going in
  January" is the coming January). If there is none, use the year the
  source was captured. Write the full date and note where the year came
  from.
- **Vague or conflicting wording inside one source** ("mid 30s" in one
  line, "1939-1945" in another): use the source's own words on the page, in
  quotes if needed, and don't turn them into something more exact.
- **A name shared by two people** (a nickname that is also someone else's
  name): keep it as an alias where the source gives it, and add a line on
  each page pointing to the other ("not to be confused with [[...]]").
- **An abbreviation or short name the source doesn't expand** stays as
  written. Don't expand it and don't ask what it stands for.
- **A relationship the sources don't state** is left unstated. Don't ask
  about it.
- **Something missing that would be nice to know** (a surname, a date, a
  fuller title) is not a question. Leave the gap.
- **Duplicates and leftovers:** merge duplicate pages into one and delete
  the other; delete a stray file that copies [[index]].
- **A source that can't be found:** say so in the lint report as an error.
  Don't ask the human to re-add it and don't drop the pages that cite it.

Ask only in two cases: two sources flatly contradict each other and
neither is newer, or the only fix would delete something a source states.
Then put the question in [[questions]] under Open, once:

```
- [ ] **Q7** (2026-10-09, [[Dana]]) One capture says Denver, another Boulder, same day. Which?
```

Number questions in order. Before adding one, read [[questions]]: anything
already there, open or answered, is never asked again. When a source or an
instruction from the human answers one, apply the answer to the pages and
move the line under Answered:

```
- [x] **Q7** (2026-10-09, [[Dana]]) ... Answer: Denver. ([[raw/2026-10-10-denver]])
```

The human may also type an answer under a question in [[questions]]
itself; treat that text as the answer at the next lint.

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

### Edit (the human asks for a change)

The human may tell the chat to change the wiki itself (rename or merge a
page, fix a heading, delete something, settle a question). Their message is
saved as a raw source; do what it says, cite it for anything it states,
keep [[index]] and the links right, and log it as `edit`.

### Lint (periodic health check)

Follow [[lint-checklist]]. Fix everything the rulings above let you decide,
put the rare real question in [[questions]], log the pass.

## Log format

Each entry starts with `## [YYYY-MM-DD] kind | title` so it can be grepped:

```
grep "^## \[" log.md | tail -5
```

`kind` is one of `ingest`, `query`, `lint`, `schema`, `edit`.
