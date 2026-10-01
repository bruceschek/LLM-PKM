# Lint checklist

Run now and then (say "lint the wiki"). For each item, fix it if the fix is
obvious; otherwise list it for the human.

- [ ] **Orphans:** wiki pages that nothing links to, or that are missing from [[index]].
- [ ] **Broken links:** `[[links]]` pointing at pages that don't exist. Create the page or fix the link.
- [ ] **Contradictions:** two pages (or two facts on one page) that disagree and aren't marked superseded.
- [ ] **Stale claims:** facts that a newer raw source has overtaken.
- [ ] **Uncited facts:** facts with no link to a raw source.
- [ ] **Missing pages:** names or topics mentioned on several pages that have no page of their own.
- [ ] **Gaps:** questions the wiki can't answer yet, worth asking the human about.
- [ ] **Index drift:** one-line summaries in [[index]] that no longer match the page.

Finish by appending a `lint` entry to [[log]].
