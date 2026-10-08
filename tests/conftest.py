"""Keep every test away from the real data: settings read from the
environment point at a throwaway folder, never the live vault in data/."""

import os
import tempfile

os.environ["PKM_DATA_DIR"] = tempfile.mkdtemp(prefix="llm-pkm-tests-")
for name in ("PKM_WIKI_DIR", "PKM_OWNER", "PKM_STORE"):
    os.environ.pop(name, None)
