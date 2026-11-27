"""Where Roosta reads and writes.

The app (code, static pages, policy templates) lives in this package and is never edited in
place. Everything a user owns lives in their workspace: tracked config in `.roosta/`, runtime
state in the gitignored `.roosta/state/`. The workspace comes from `ROOSTA_WORKSPACE`, set by
`roosta start`, else the current directory.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
STATIC_DIR = APP_ROOT / "static"
SKELETON_DIR = APP_ROOT / "skeleton"
CORE_SKILLS_DIR = APP_ROOT / "skills"


def workspace_root() -> Path:
    raw = os.environ.get("ROOSTA_WORKSPACE", "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


WORKSPACE = workspace_root()
ROOSTA_DIR = WORKSPACE / ".roosta"
STATE_DIR = ROOSTA_DIR / "state"
CACHE_DIR = STATE_DIR / "cache"
ASSISTANT_DIR = STATE_DIR / "assistant"
TASKS_FILE = ROOSTA_DIR / "tasks.yaml"
CONNECTORS_FILE = ROOSTA_DIR / "connectors.yaml"
PAGES_DIR = ROOSTA_DIR / "pages"
PROFILE_FILE = WORKSPACE / "PROFILE.md"
PORT = int(os.environ.get("ROOSTA_PORT") or 7667)
BASE_URL = f"http://127.0.0.1:{PORT}"


def write_atomic(path: Path, text: str) -> None:
    """Replace a file whole and private (0600): a crash leaves the old content or the new, never half."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json(path: Path, data) -> None:
    write_atomic(path, json.dumps(data, indent=2))
