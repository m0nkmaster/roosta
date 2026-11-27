"""Office: workspace looks for the pixel-art workers."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from roosta import paths

OFFICE_CAST_FILE = paths.ROOSTA_DIR / "office-cast.yaml"
LPC_DIR = paths.STATIC_DIR / "vendor" / "lpc"


def office_cast(path: Path = OFFICE_CAST_FILE, lpc: Path = LPC_DIR) -> dict:
    """Workspace looks for Office workers, keyed by lower-case nickname or task id.

    Only looks whose every sprite layer is vendored pass, so a typo cannot break the page.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    cast = {}
    for name, look in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(look, dict):
            continue
        look = {k: str(v) for k, v in look.items()
                if k in {"body", "head", "tone", "hair", "beard", "glasses"} and isinstance(v, str)}
        body, tone = look.get("body"), look.get("tone", "")
        suffix = "-f" if body == "f" else ""
        head = {"m": "head", "f": "head-f", "old": "head-old"}.get(look.get("head") or body or "")
        needed = [f"body{suffix}/{tone}", f"{head}/{tone}", f"hair/{look.get('hair', '')}"]
        needed += [f"hair/{look['beard']}"] if look.get("beard") else []
        needed += [f"glasses/{look['glasses']}"] if look.get("glasses") else []
        safe = all(re.fullmatch(r"[A-Za-z0-9 _/-]+", n) and ".." not in n for n in needed)
        if body in {"m", "f"} and head and safe and all((lpc / n / "Walk.png").is_file() for n in needed):
            cast[str(name).strip().lower()] = look
    return cast
