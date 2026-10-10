# Lint checklist

Run now and then (say "lint the wiki"). Fix every item yourself, following
the "Decide, don't ask" rulings in [[SCHEMA]]. A question for the human is
the exception: only when two sources flatly contradict each other and
neither is newer, or when the only fix would delete something a source
states. It goes in [[questions]], once.

The first group is checked exactly by code before you start, and you are
given the list of what it found. Fix those and don't hunt for more.

- [ ] **Orphans:** wiki pages that nothing links to, or that are missing from [[index]]. Link them.
- [ ] **Broken links:** `[[links]]` pointing at pages that don't exist. Create the page (a stub is fine) or fix the link.
- [ ] **Bad frontmatter:** pages whose properties don't follow [[SCHEMA]] (e.g. `sources` written as a bare `[[link]]` instead of a list of quoted links).
- [ ] **Uncited pages:** pages that link to no raw source.
- [ ] **Duplicate or misplaced files:** two files with one title, or a page outside `wiki/people`, `wiki/places` and `wiki/topics`. Merge and delete.

The rest needs reading:

- [ ] **Open questions:** read [[questions]]. If the pages or a newer source now answer one, or the human typed an answer under it, apply it and move it to Answered.
- [ ] **Contradictions:** two pages (or two facts on one page) that disagree and aren't marked superseded. If one source is newer, mark the older fact superseded.
- [ ] **Stale claims:** facts that a newer raw source has overtaken. Mark them superseded.
- [ ] **Uncited facts:** facts with no link to a raw source. Find the source among the page's sources and cite it.
- [ ] **Outside knowledge:** facts on a page that its cited raw source doesn't state. Remove them; never fill a gap from general knowledge. (A date worked out from "last week" and the source's capture date is fine, and so is a year taken from the capture date.)
- [ ] **Missing pages:** any person, place, organization or subject named on a page that has no page of its own. Create it, as a stub if that is all the sources support.
- [ ] **Index drift:** one-line summaries in [[index]] that no longer match the page. Rewrite them.

Not on this list any more: "gaps" (things the wiki can't answer yet). Leave
gaps alone; don't ask the human to fill them.

Finish by appending a `lint` entry to [[log]]. Report what you fixed, then
only the questions you added in this pass.
