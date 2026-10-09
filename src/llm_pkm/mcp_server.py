"""stdio MCP server. Exposes remember, wiki_read, rewind, lint as MCP tools
and WIKI_CHAT_SYSTEM as a prompt. Run via `uv run pkm-mcp`."""

import sys

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from .config import Settings
from .core import Assistant
from .llm import WIKI_CHAT_SYSTEM
from .stores import build_stores

mcp = MCPServer("llm-pkm")
_assistant: Assistant | None = None


@mcp.tool()
def remember(fact: str, source_text: str, doubt: str) -> str:
    """Save one fact the user stated to long-term memory. Call once per distinct fact.
    Rewrite each fact as a self-contained statement about "the user" that will make
    sense on its own months from now (e.g. "my wife is Hemmie" becomes "The user's
    wife's name is Hemmie."). Pass the user's verbatim message as source_text.
    Set doubt only if the fact plainly contradicts well-established general knowledge;
    leave it empty otherwise. The wiki is updated in the background after this returns."""
    assert _assistant is not None
    return _assistant.mcp_tool("remember", {"fact": fact, "source_text": source_text, "doubt": doubt})


@mcp.tool()
def wiki_read(path: str) -> str:
    """Read a wiki page by its title (e.g. "Dana"), as in an Obsidian link, or any
    vault file by path (e.g. "index.md"). Use path="LIST" to list all vault files.
    Read index.md and any relevant pages before answering questions about the user."""
    assert _assistant is not None
    return _assistant.mcp_tool("wiki_read", {"path": path})


@mcp.tool()
def rewind() -> str:
    """Take back the most recent stored change: its wiki pages and raw source.
    Call when the user asks to undo, rewind, or forget their last statement."""
    assert _assistant is not None
    return _assistant.mcp_tool("rewind", {})


@mcp.tool()
def lint() -> str:
    """Health-check the entire wiki: orphans, broken links, contradictions, uncited
    facts. Takes 30-60 seconds and returns the full report when done."""
    assert _assistant is not None
    return _assistant.mcp_tool("lint", {})


@mcp.prompt()
def wiki_chat_system() -> str:
    """System prompt for the PKM wiki chat interface. Load this into your Claude
    project instructions to enable wiki-aware conversation."""
    return WIKI_CHAT_SYSTEM


def main() -> None:
    global _assistant
    load_dotenv()
    settings = Settings.from_env()
    if not settings.wiki_dir:
        sys.exit(
            "The MCP server needs the wiki vault. "
            "Remove PKM_WIKI_DIR=off or set PKM_WIKI_DIR to a path (default: data/wiki)."
        )
    store, log = build_stores(settings, background=True)
    _assistant = Assistant(settings, store, log, background=True)
    mcp.run(transport="stdio")
