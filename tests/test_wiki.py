from datetime import datetime

import pytest

from llm_pkm.wiki import Wiki


def test_new_vault_has_rules_index_and_log(tmp_path):
    wiki = Wiki(tmp_path / "vault")
    assert "Three layers" in wiki.schema()
    for name in ("index.md", "log.md", "lint-checklist.md"):
        assert (tmp_path / "vault" / name).exists()
    assert (tmp_path / "vault" / "raw").is_dir()
    assert (tmp_path / "vault" / ".obsidian" / "graph.json").exists()


def test_write_and_read_pages(tmp_path):
    wiki = Wiki(tmp_path)
    wiki.write("wiki/people/Dana.md", "# Dana")
    assert wiki.read("wiki/people/Dana.md") == "# Dana\n"
    assert "wiki/people/Dana.md" in wiki.list_pages()
    assert wiki.read("wiki/nope.md").startswith("No such page")


@pytest.mark.parametrize("name", ["Dana", "[[Dana]]", "[[Dana|her]]", "Dana#Facts", "Dana.md"])
def test_read_by_title_like_an_obsidian_link(tmp_path, name):
    wiki = Wiki(tmp_path)
    wiki.write("wiki/people/Dana.md", "A friend.")
    assert wiki.read(name) == "A friend.\n"
    assert wiki.read("Nobody").startswith("No such page")


@pytest.mark.parametrize(
    "path", ["../x.md", "/etc/x.md", "wiki/../../x.md", "wiki/x.txt", "raw/a.md", "log.md", "SCHEMA.md"]
)
def test_write_is_confined(tmp_path, path):
    with pytest.raises(ValueError):
        Wiki(tmp_path).write(path, "x")


def test_read_is_confined(tmp_path):
    with pytest.raises(ValueError):
        Wiki(tmp_path).read("../secret.md")


def test_raw_and_log(tmp_path):
    wiki = Wiki(tmp_path)
    now = datetime(2026, 9, 30, 12, 0, 0)
    path = wiki.save_raw("Dana's kid is Theo", now)
    assert path == "raw/2026-09-30-120000-dana-s-kid-is-theo"
    assert "Dana's kid is Theo" in (tmp_path / f"{path}.md").read_text()
    wiki.log("ingest", "Dana", "Created [[Dana]].", now)
    assert "## [2026-09-30] ingest | Dana" in (tmp_path / "log.md").read_text()
    with pytest.raises(ValueError):
        wiki.log("bogus", "x", "y")


def test_pending_raw_skips_ingested_hidden_and_other_types(tmp_path):
    wiki = Wiki(tmp_path)
    (tmp_path / "raw" / "b.md").write_text("b")
    (tmp_path / "raw" / "a.txt").write_text("a")
    (tmp_path / "raw" / "pic.png").write_bytes(b"x")
    (tmp_path / "raw" / ".hidden.md").write_text("h")
    (tmp_path / "raw" / "c.pdf").write_bytes(b"%PDF-1.4 x")
    assert wiki.pending_raw() == ["raw/a.txt", "raw/b.md", "raw/c.pdf"]
    wiki.mark_ingested("raw/c.pdf")
    wiki.mark_ingested("raw/a.txt")
    assert wiki.pending_raw() == ["raw/b.md"]


def test_chat_capture_is_pending_until_marked(tmp_path):
    wiki = Wiki(tmp_path)
    path = wiki.save_raw("hello there")
    assert wiki.pending_raw() == [f"{path}.md"]
    wiki.mark_ingested(f"{path}.md")
    assert wiki.pending_raw() == []


def test_text_and_pdf_sources_are_listed_and_readable(tmp_path):
    """A lint pass once reported an ingested .txt source as missing: LIST
    showed only .md files and wiki_read refused anything else."""
    from llm_pkm.wiki import Wiki

    wiki = Wiki(tmp_path / "vault")
    (wiki.root / "raw" / "bio notes.txt").write_text("Born 1879.")
    (wiki.root / "raw" / "scan.pdf").write_bytes(b"%PDF-1.4")
    listing = wiki.list_pages().split("\n")
    assert "raw/bio notes.txt" in listing and "raw/scan.pdf" in listing
    assert wiki.read("raw/bio notes.txt") == "Born 1879."
    assert wiki.read("[[raw/bio notes.txt]]") == "Born 1879."
    assert "can't be read" in wiki.read("raw/scan.pdf")
    assert wiki.read("raw/../SCHEMA.txt").startswith("No such file")
    assert wiki.read("raw/nothing.txt").startswith("No such file")
