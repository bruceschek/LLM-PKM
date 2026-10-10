"""`uv run pkm-lint`: health-check the wiki against its lint-checklist.md
(orphans, broken links, contradictions, stale or uncited facts). Claude fixes
what is safe and reports the rest. `--check` only runs the checks done in
code (`checks.py`) and prints what they find: no Claude call, nothing changed."""

import argparse

from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(prog="pkm-lint", description="Health-check the wiki.")
    parser.add_argument(
        "--check", action="store_true", help="only run the code checks; no Claude call, no changes"
    )
    args = parser.parse_args()
    load_dotenv()
    from .core import Assistant  # after load_dotenv, so settings see .env

    if args.check:
        from .checks import check
        from .config import Settings
        from .wiki import Wiki

        settings = Settings.from_env()
        if not settings.wiki_dir:
            raise SystemExit("The wiki is off (PKM_WIKI_DIR=off).")
        found = check(Wiki(settings.wiki_dir))
        print("\n".join(found) or "The code checks found nothing.")
        return
    assistant = Assistant.from_env()
    if not assistant.wiki:
        raise SystemExit("The wiki is off (PKM_WIKI_DIR=off).")
    print(f"Linting {assistant.wiki.root} ...")
    print(assistant.lint())
