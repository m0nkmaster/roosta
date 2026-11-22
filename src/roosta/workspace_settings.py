"""Workspace settings: how Roosta is run, and choosing a workspace folder."""

from __future__ import annotations

import io
import os
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path

from roosta import cli


def workspace_managed_by() -> str:
    if os.environ.get("ASSISTANT_DESKTOP") == "1":
        return "desktop"
    if os.environ.get("XPC_SERVICE_NAME") == cli.LAUNCHD_LABEL or (
            sys.platform.startswith("linux") and os.environ.get("INVOCATION_ID")):
        return "service"
    return "terminal"


def workspace_target(body: dict) -> tuple[Path | None, str]:
    raw = body.get("path")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 1024:
        return None, "Enter the full path to the folder."
    target = Path(raw.strip()).expanduser()
    if not target.is_absolute():
        return None, "Enter the full path to the folder."
    try:
        target = target.resolve()
    except (OSError, RuntimeError):
        return None, "That folder path cannot be used."
    if target.exists() and not target.is_dir():
        return None, f"{target} is not a folder."
    return target, ""


def captured(call: Callable[[], int]) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = call()
    return code, out.getvalue().strip()


FOLDER_LIST_LIMIT = 500


def list_folders(directory: Path) -> dict:
    names = []
    for entry in os.scandir(directory):
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                names.append(entry.name)
        except OSError:
            continue
    names.sort(key=str.casefold)
    folders = []
    for name in names[:FOLDER_LIST_LIMIT]:
        child = directory / name
        try:
            workspace = (child / ".roosta").is_dir()
        except OSError:
            workspace = False
        folders.append({"name": name, "path": str(child), "workspace": workspace})
    return {"path": str(directory), "parent": str(directory.parent) if directory.parent != directory else None,
            "home": str(Path.home()), "is_workspace": (directory / ".roosta").is_dir(),
            "is_empty": not any(True for _ in os.scandir(directory)),
            "folders": folders, "truncated": len(names) > FOLDER_LIST_LIMIT}
