"""Latest unmodified agent binaries. Installation never runs a downloaded shell script."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from roosta import paths

INSTALLING: set[str] = set()
CLAUDE_MODELS: dict[str, tuple[float, dict]] = {}
RUNTIMES = ("pi", "claude")
RUNTIME_ROOT = paths.CACHE_DIR / "runtimes"
CLAUDE_RELEASES = "https://downloads.claude.ai/claude-code-releases"


def target_platform() -> str:
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(platform.machine())
    target = f"{platform.system().lower()}-{arch}"
    if target not in {"darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64"}:
        raise ValueError("Managed AI runtimes require macOS or glibc Linux on arm64 or x64")
    return target


def binary_path(root: Path, runtime: str, release: str) -> Path:
    return root / f"{runtime}-{release}" / runtime


def version(binary: str) -> str:
    try:
        resolved = Path(binary).resolve()
        stat = resolved.stat()
        return _binary_version(str(resolved), stat.st_mtime_ns, stat.st_size)
    except (OSError, RuntimeError):
        return ""


@lru_cache(maxsize=32)
def _binary_version(binary: str, modified: int, size: int) -> str:
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
        match = re.search(r"\b\d+\.\d+\.\d+\b", result.stdout)
        return match.group() if result.returncode == 0 and match else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _version_tuple(text: str) -> tuple:
    return tuple(int(part) for part in text.split("."))


def _runtime_path_allowed(binary: Path) -> bool:
    try:
        for path in (binary, binary.resolve()):
            if ("cmux-cli-shims" in path.parts or path.name == "cmux-claude-wrapper"
                    or path.match("cmux.app/Contents/Resources/bin/claude")):
                return False
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def find(runtime: str) -> str:
    if runtime not in RUNTIMES:
        raise ValueError("Unknown AI runtime")
    candidates = []
    for directory in os.get_exec_path():
        candidate = shutil.which(str(Path(directory).absolute() / runtime))
        if candidate and _runtime_path_allowed(Path(candidate)):
            candidates.append(candidate)
            break
    if runtime == "claude":
        local = Path.home() / ".local/bin/claude"
        if _runtime_path_allowed(local):
            candidates.append(str(local))
    for binary in RUNTIME_ROOT.glob(f"{runtime}-*/{runtime}"):
        try:
            if binary.resolve().is_relative_to(RUNTIME_ROOT.resolve()) and _runtime_path_allowed(binary):
                candidates.append(str(binary))
        except (OSError, RuntimeError, ValueError):
            continue
    selected, newest = "", ()
    for binary in candidates:
        found = version(binary)
        if found and _version_tuple(found) > newest:
            selected, newest = binary, _version_tuple(found)
    return selected


def describe(runtime: str) -> dict:
    """Report the newest installed copy, preferring the user's copy on a version tie."""
    binary = find(runtime)
    return {"installed": bool(binary), "version": version(binary) if binary else "",
            "source": "" if not binary else ("managed" if Path(binary).is_relative_to(RUNTIME_ROOT) else "yours")}


def _ssl_context() -> ssl.SSLContext:
    """Frozen builds can lack the OpenSSL default paths; fall back to the system bundle."""
    context = ssl.create_default_context()
    verify = ssl.get_default_verify_paths()
    if not any(path and Path(path).exists() for path in (verify.cafile, verify.capath)):
        bundle = Path("/etc/ssl/cert.pem")
        if bundle.exists():
            context.load_verify_locations(str(bundle))
    return context


def latest_release(runtime: str, target: str) -> tuple[str, str, str]:
    """Resolve version and checksum from the publisher over verified HTTPS."""
    def read(url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "Roosta"})
        with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("AI release metadata exceeds the size limit")
        return data

    try:
        if runtime == "pi":
            metadata = json.loads(read("https://api.github.com/repos/earendil-works/pi/releases/latest"))
            release = metadata["tag_name"].removeprefix("v")
            asset = next(a for a in metadata["assets"] if a["name"] == f"pi-{target}.tar.gz")
            checksum = asset["digest"].removeprefix("sha256:")
            url = f"https://github.com/earendil-works/pi/releases/download/v{release}/pi-{target}.tar.gz"
        elif runtime == "claude":
            release = read(f"{CLAUDE_RELEASES}/latest").decode().strip()
            if not re.fullmatch(r"\d+\.\d+\.\d+", release):
                raise ValueError("Invalid AI release version")
            metadata = json.loads(read(f"{CLAUDE_RELEASES}/{release}/manifest.json"))
            if metadata["version"] != release:
                raise ValueError("AI release manifest does not match its version")
            checksum = metadata["platforms"][target]["checksum"]
            url = f"{CLAUDE_RELEASES}/{release}/{target}/claude"
        else:
            raise ValueError("Unknown AI runtime")
        if not re.fullmatch(r"\d+\.\d+\.\d+", release) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Invalid AI release version or checksum")
    except (KeyError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as exc:
        raise ValueError("Could not verify the latest AI release metadata") from exc
    return release, url, checksum


def install(runtime: str, root: Path | None = None) -> str:
    """Download and verify the latest release; leave other installations untouched."""
    if runtime not in RUNTIMES:
        raise ValueError("Unknown AI runtime")
    target = target_platform()
    root = Path(root or RUNTIME_ROOT)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    release, url, checksum = latest_release(runtime, target)
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        work = Path(temporary).resolve()
        archive = work / "download"
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60, context=_ssl_context()) as response, archive.open("wb") as output:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 700 * 1024 * 1024:
                    raise ValueError("Runtime download exceeds the size limit")
                digest.update(block)
                output.write(block)
        if digest.hexdigest() != checksum:
            raise ValueError("Runtime checksum failed; existing installation was preserved")
        if runtime == "pi":
            with tarfile.open(archive) as package:
                # No links or special files may escape the private staging directory.
                for entry in package.getmembers():
                    if not (entry.isfile() or entry.isdir()) or not (work / entry.name).resolve().is_relative_to(work):
                        raise ValueError("Unsafe runtime archive")
                package.extractall(work, filter="data")
            staged = work / "pi"
        else:
            staged = work / "claude-package"
            staged.mkdir()
            archive.rename(staged / "claude")
        (staged / runtime).chmod(0o755)
        if version(str(staged / runtime)) != release:
            raise ValueError("Downloaded runtime failed its version check")
        destination = binary_path(root, runtime, release).parent
        previous = work / "previous"
        if destination.exists():
            destination.rename(previous)
        try:
            staged.rename(destination)
        except OSError:
            if previous.exists():
                previous.rename(destination)
            raise
    _binary_version.cache_clear()
    model_catalog.cache_clear()
    default_model.cache_clear()
    model_efforts.cache_clear()
    CLAUDE_MODELS.clear()
    return str(destination / runtime)


@lru_cache(maxsize=4)
def model_catalog(provider: str) -> list[str]:
    """Read Pi's bundled catalogue offline, without loading any account or project config."""
    if provider not in {"openai", "openrouter"}:
        return []
    binary = find("pi")
    if not binary:
        return []
    with tempfile.TemporaryDirectory(prefix="roosta-models-") as temporary:
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()),
               "PI_CODING_AGENT_DIR": temporary, "PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1",
               "OPENAI_API_KEY": "catalogue-only", "OPENROUTER_API_KEY": "catalogue-only"}
        result = subprocess.run([binary, "--offline", "--no-approve", "--no-extensions", "--list-models"],
                                cwd=temporary, env=env, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError("The AI model catalogue is unavailable; update or reinstall the runtime in Settings")
    return [parts[1] for line in result.stdout.splitlines()
            if len(parts := line.split()) >= 2 and parts[0] == provider]


@lru_cache(maxsize=4)
def default_model(provider: str) -> str:
    """The model Pi itself would pick when this provider is the only one configured; "" if unknown."""
    key = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(provider)
    binary = find("pi") if key else ""
    if not binary:
        return ""
    with tempfile.TemporaryDirectory(prefix="roosta-default-model-") as temporary:
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()),
               "PI_CODING_AGENT_DIR": temporary, "PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1", key: "catalogue-only"}
        try:
            result = subprocess.run([binary, "--mode", "rpc", "--offline", "--no-approve", "--no-extensions",
                                     "--session-dir", temporary], input='{"id":"state","type":"get_state"}\n',
                                    cwd=temporary, env=env, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return ""
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        model = ((event.get("data") or {}).get("model") or {}) if isinstance(event, dict) and event.get("id") == "state" else {}
        if model.get("provider") == provider and isinstance(model.get("id"), str):
            return model["id"]
    return ""


@lru_cache(maxsize=128)
def model_efforts(provider: str, model: str) -> list[str]:
    """Ask the installed runtime for this model's supported reasoning levels, offline."""
    key = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(provider)
    if not key:
        return []
    binary = find("pi")
    if not binary:
        raise ValueError("Install the AI runtime in Settings to choose effort")
    with tempfile.TemporaryDirectory(prefix="roosta-effort-") as temporary:
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()),
               "PI_CODING_AGENT_DIR": temporary, "PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1", key: "catalogue-only"}
        result = subprocess.run([binary, "--mode", "rpc", "--offline", "--no-approve", "--no-extensions",
                                 "--provider", provider, "--model", model, "--session-dir", temporary],
                                input='{"id":"efforts","type":"get_available_thinking_levels"}\n',
                                cwd=temporary, env=env, capture_output=True, text=True, timeout=20)
    if not result.returncode:
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("id") == "efforts" and event.get("success"):
                levels = (event.get("data") or {}).get("levels")
                if isinstance(levels, list) and all(isinstance(level, str) and level in {"off", "minimal", "low", "medium", "high", "xhigh", "max"} for level in levels):
                    return levels if levels != ["off"] else []
    raise ValueError("Could not load supported effort levels")
