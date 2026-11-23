"""Read-only release checks for the backend serving this dashboard."""
import asyncio
from importlib import metadata, util
import json
from pathlib import Path
import platform
import re
import sys
import tomllib

import httpx
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from roosta import __version__, paths
from roosta.workspace_settings import workspace_managed_by

RELEASES = "https://github.com/m0nkmaster/roosta/releases"
LATEST = "https://api.github.com/repos/m0nkmaster/roosta/releases/latest"
INTERVAL = 6 * 60 * 60


async def read_json(url):
    # Fixed public endpoints only. Do not forward credentials or follow redirects.
    async with asyncio.timeout(10), httpx.AsyncClient(trust_env=False) as client:
        async with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_raw():
                if len(body) + len(chunk) > 512 * 1024:
                    raise ValueError("Oversized release metadata")
                body.extend(chunk)
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("Invalid release metadata")
    return data


def installation():
    if getattr(sys, "frozen", False):
        return "mac" if sys.platform == "darwin" else "unknown"
    if paths.APP_ROOT.parent.name == "src" and (paths.APP_ROOT.parents[1] / "pyproject.toml").is_file():
        return "source"
    try:
        dist = metadata.distribution("roosta")
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        if direct.get("dir_info", {}).get("editable") is True:
            return "source"
        prefix = Path(sys.prefix)
        if (direct or sys.prefix == sys.base_prefix or
                dist.locate_file("roosta").resolve() != paths.APP_ROOT or
                not paths.APP_ROOT.is_relative_to(prefix.resolve())):
            return "unknown"
        receipt = prefix / "uv-receipt.toml"
        pipx = prefix / "pipx_metadata.json"
        if receipt.is_symlink() or pipx.is_symlink() or (receipt.exists() and pipx.exists()):
            return "unknown"
        if receipt.exists():
            requirements = tomllib.loads(receipt.read_text())["tool"]["requirements"]
            return "uv" if requirements and requirements[0]["name"] == "roosta" else "unknown"
        if pipx.exists():
            main = json.loads(pipx.read_text())["main_package"]
            return "pipx" if main["package"] == "roosta" and not main.get("suffix") else "unknown"
        if (prefix / "conda-meta").exists():
            return "unknown"
        if util.find_spec("pip"):
            return "venv"
        return "uv-venv" if (dist.read_text("INSTALLER") or "").strip() == "uv" else "unknown"
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RuntimeError, metadata.PackageNotFoundError):
        return "unknown"


def compatible_package(data, version):
    info = data["info"]
    python = platform.python_version()
    return (info["name"] == "roosta" and info["version"] == version and info.get("yanked", False) is False
            and python in SpecifierSet(info["requires_python"])
            and any(file["filename"] == f"roosta-{version}-py3-none-any.whl"
                    and file["yanked"] is False
                    and python in SpecifierSet(file["requires_python"] or info["requires_python"])
                    for file in data["urls"]))


async def stable_release():
    release = await read_json(LATEST)  # GitHub excludes drafts and prereleases here.
    tag = release["tag_name"]
    if (release["draft"] is not False or release["prerelease"] is not False
            or not re.fullmatch(r"v(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}", tag)):
        raise ValueError("Unexpected stable release")
    return tag[1:], release


async def python_release(version):
    data = await read_json(f"https://pypi.org/pypi/roosta/{version}/json")
    return compatible_package(data, version)


async def check():
    version, release = await stable_release()
    tag = release["tag_name"]
    if Version(version) <= Version(__version__):
        return {"state": "current"}
    result = {"state": "available", "latest": version, "notes": f"{RELEASES}/tag/{tag}"}
    kind = installation()
    if kind == "mac":
        arch = {"x86_64": "x64", "arm64": "arm64"}.get(platform.machine())
        name = f"Roosta-{version}-{arch}.dmg"
        if arch and any(a.get("name") == name for a in release.get("assets", [])):
            result["installer"] = f"{RELEASES}/download/{tag}/{name}"
        else:
            result["error"] = "Could not confirm a matching macOS installer."
        result["guidance"] = ("Use the disk image for this Mac. Quit Roosta, replace Roosta.app in "
                              "Applications and reopen it. The app includes its own Python backend.")
    elif kind == "source":
        result["guidance"] = ("This backend runs from a development checkout. Preserve local changes "
                              "and update it using that checkout’s development workflow.")
    else:
        try:
            compatible = await python_release(version)
        except CHECK_ERRORS:
            compatible = False
        if not compatible:
            result["error"] = "Could not confirm a compatible release on PyPI for this Python interpreter."
        elif kind in ("uv", "pipx", "venv", "uv-venv"):
            result["guidance"] = f"Run this command using the Roosta CLI from {sys.prefix}."
            result["command"] = "roosta update"
        else:
            result["guidance"] = (f"The backend uses {sys.executable}. Identify its owner in your "
                                  "runner or service configuration, then use that installation’s "
                                  "original manager and environment to update Roosta.")
    if kind != "mac" and "error" not in result:
        restarts = {
            "service": "Restart the existing launchd or systemd user service serving this workspace.",
            "terminal": ("For a foreground runner, stop it and relaunch roosta start with the same workspace, "
                         "address and port. If a service runs it, restart that existing service."),
            "desktop": "Use Restart Roosta in the app menu to relaunch its managed runner.",
        }
        result["restart"] = restarts[workspace_managed_by()] + " Then reload the dashboard."
    return result


CHECK_ERRORS = (httpx.HTTPError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError)


class ReleaseChecks:
    def __init__(self):
        self.result = {"state": "checking"}
        self.pending = None

    async def refresh(self):
        if self.pending is None or self.pending.done():
            self.pending = asyncio.create_task(self._refresh())
        return await asyncio.shield(self.pending)

    async def _refresh(self):
        try:
            self.result = await check()
        except CHECK_ERRORS:
            self.result = {"state": "failed", "error": "Could not check GitHub Releases."}
        return self.result

    async def run(self):
        try:
            while True:
                await self.refresh()
                await asyncio.sleep(INTERVAL)
        finally:
            if self.pending:
                self.pending.cancel()
                await asyncio.gather(self.pending, return_exceptions=True)
