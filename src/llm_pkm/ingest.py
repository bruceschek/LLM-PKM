"""`uv run pkm-ingest`: fold files dropped into the vault's raw/ folder into
the wiki. Run it by hand after adding sources; files already ingested
(tracked in the vault's .ingested.json) are skipped. It also retries chat
captures whose wiki update failed. Takes .md, .txt and .pdf files (a PDF is
sent to Claude as a document, so scanned pages and figures are read too).
`/ingest` in the chat does one file at a time and lets you say what to keep.

Each file is a separate Claude conversation that writes the wiki pages. With
a fact store (PKM_STORE other than wiki) Claude also calls `remember` for
each fact it extracts, so `recall` finds them too."""

import argparse

import anthropic
import httpx
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pkm-ingest", description="Ingest new files from the wiki's raw/ folder."
    )
    parser.add_argument("--dry-run", action="store_true", help="list pending files and stop")
    args = parser.parse_args()

    load_dotenv()
    from .core import Assistant  # after load_dotenv, so settings see .env

    assistant = Assistant.from_env(background=True)
    if not assistant.wiki:
        raise SystemExit("The wiki is off (PKM_WIKI_DIR=off).")
    pending = assistant.wiki.pending_raw()
    print(f"{len(pending)} new file(s) in {assistant.wiki.root / 'raw'}")
    if args.dry_run:
        for rel in pending:
            print(f"  {rel}")
        return

    failed = 0
    for rel in pending:
        print(f"\n{rel} ...")
        try:
            print(assistant.ingest_file(rel))
        except (anthropic.APIError, httpx.HTTPError, OSError, ValueError) as e:
            failed += 1
            print(f"  FAILED, will retry next run: {e}")
    if assistant.pending_notices() > 0:
        print(f"\nWaiting for {assistant.pending_notices()} background save(s) to become searchable...")
        for notice in assistant.wait_for_saves(assistant.settings.index_timeout + 10):
            print(f"  {notice.message}")
    if failed:
        raise SystemExit(f"{failed} file(s) failed.")
