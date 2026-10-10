"""The lint checks that need no judgment, done exactly in code: broken links,
pages missing from the index or linked from nowhere, frontmatter Obsidian
can't read, pages citing no source, duplicate titles. `check` returns one
line per problem; the lint pass hands them to Claude to fix (see
`Assistant._lint_message`), and `pkm-lint --check` prints them without
calling Claude at all. What does need judgment (contradictions, stale
claims, outside knowledge, index summaries) stays with Claude."""

import re
from pathlib import Path

from .wiki import RAW_SUFFIXES, Wiki

LINK = re.compile(r"\[\[([^\[\]]+)\]\]")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
SOURCE_ITEM = re.compile(r'\s*-\s*"\[\[[^\[\]]+\]\]"\s*')
FOLDER_TYPES = {"people": "person", "places": "place", "topics": "topic"}


def links(text: str) -> list[str]:
    """Link targets in a page, without alias or heading, skipping code."""
    found = (re.split(r"[|#]", m)[0].strip() for m in LINK.findall(CODE.sub("", text)))
    return [target for target in found if target]


def _title(target: str) -> str:
    """What a link or a file is called, for matching one to the other."""
    return Path(target).name.removesuffix(".md").casefold()


def check(wiki: Wiki) -> list[str]:
    root = wiki.root
    files = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in RAW_SUFFIXES
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    ]
    rel = {p: p.relative_to(root).as_posix() for p in files}
    pages = sorted((p for p in files if rel[p].startswith("wiki/")), key=rel.get)
    by_title: dict[str, list[str]] = {}
    for p in files:
        if p.suffix == ".md":
            by_title.setdefault(_title(p.name), []).append(rel[p])

    def resolves(target: str) -> bool:
        if "/" in target:
            return (root / target).is_file() or (root / f"{target}.md").is_file()
        return _title(target) in by_title or any(p.name.casefold() == target.casefold() for p in files)

    problems = []
    for title, paths in sorted(by_title.items()):
        if len(paths) > 1:
            problems.append(f"Duplicate title (titles must be unique): {', '.join(sorted(paths))}")

    texts = {p: p.read_text() for p in pages}
    for name in ("index.md", "questions.md"):
        if (root / name).is_file():
            texts[root / name] = (root / name).read_text()
            rel[root / name] = name
    for p, text in texts.items():
        for target in sorted(set(links(text))):
            if not resolves(target):
                problems.append(f"Broken link in {rel[p]}: [[{target}]] matches no file")

    indexed = {_title(t) for t in links(texts.get(root / "index.md", ""))}
    linked = {_title(t) for p in pages for t in links(texts[p]) if _title(t) != _title(p.name)}
    for p in pages:
        text, where = texts[p], rel[p]
        folder = Path(where).parts[1] if len(Path(where).parts) == 3 else None
        if folder not in FOLDER_TYPES:
            problems.append(f"Misplaced page: {where} is not in wiki/people, wiki/places or wiki/topics")
        if _title(p.name) not in indexed:
            problems.append(f"Not in index.md: {where}")
        if _title(p.name) not in linked:
            problems.append(f"Orphan: no other page links to {where}")
        problems += [f"{what}: {where}" for what in _frontmatter_problems(text, FOLDER_TYPES.get(folder))]
        if not any(t.startswith("raw/") for t in links(text)):
            problems.append(f"Cites no raw source: {where}")
    return problems


def _frontmatter_problems(text: str, expected_type: str | None) -> list[str]:
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        return ["No frontmatter"]
    head, _, body = text[4:].partition("\n---")
    lines = head.split("\n")
    problems = []
    kind = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("type:")), None)
    if kind not in FOLDER_TYPES.values():
        problems.append(f"Frontmatter type is {kind!r}, not person, place or topic")
    elif expected_type and kind != expected_type:
        problems.append(f"Frontmatter type {kind!r} doesn't match its folder ({expected_type})")
    if "sources:" not in lines:
        problems.append("Frontmatter has no sources list (or it isn't written as a list)")
    else:
        items = []
        for line in lines[lines.index("sources:") + 1 :]:
            if not line.startswith((" ", "-")):
                break
            items.append(line)
        if not items:
            problems.append("Frontmatter sources list is empty")
        elif not all(SOURCE_ITEM.fullmatch(item) for item in items):
            problems.append('Frontmatter sources must each be a quoted link (- "[[raw/...]]")')
    first = next((line for line in body.split("\n")[1:] if line.strip()), "")
    if first.startswith("# "):
        problems.append("Starts with a # Title heading (the filename is the title)")
    return problems
