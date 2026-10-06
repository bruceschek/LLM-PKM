"""`uv run pkm-lint`: health-check the wiki against its lint-checklist.md
(orphans, broken links, contradictions, stale or uncited facts). Claude fixes
what is safe and reports the rest."""

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    from .core import Assistant  # after load_dotenv, so settings see .env

    assistant = Assistant.from_env()
    if not assistant.wiki:
        raise SystemExit("The wiki is off (PKM_WIKI_DIR=off).")
    print(f"Linting {assistant.wiki.root} ...")
    print(assistant.lint())
