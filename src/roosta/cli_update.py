"""Update the Python installation running this command."""
import asyncio
from importlib import metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

from packaging.version import Version

from roosta import __version__, updates


class UpdateError(Exception):
    """A fixed, user-facing explanation for a refused update."""


def manager_binary(name):
    binary = shutil.which(name)
    if not binary or not Path(binary).is_absolute():
        raise UpdateError(f"Put the original {name} executable on PATH, then retry.")
    path = Path(binary).resolve()
    workspace = updates.paths.WORKSPACE
    if path.parent == Path.cwd() or ((workspace / ".roosta").is_dir() and path.is_relative_to(workspace)):
        raise UpdateError(f"Use a {name} executable installed outside the workspace.")
    return binary


def exposed_bin_dir(prefix, env_key):
    # pipx records the venv scripts, but its external bin directory is independently configurable.
    script = "roosta.exe" if os.name == "nt" else "roosta"
    internal = prefix / ("Scripts" if os.name == "nt" else "bin") / script
    candidates = [sys.argv[0], shutil.which(script)]
    if os.getenv(env_key):
        candidates.append(Path(os.environ[env_key]) / script)
    candidates.append(Path.home() / ".local" / "bin" / script)
    for candidate in filter(None, candidates):
        path = Path(candidate).absolute()
        if path.name == script and not path.is_relative_to(prefix) and path.is_file() and path.samefile(internal):
            return str(path.parent)
    raise UpdateError(f"Run the exposed roosta command, or set {env_key} to its original bin directory.")


def manager_command(kind, version, prefix, env):
    spec = f"roosta=={version}"
    if prefix.is_symlink() or not (prefix / "pyvenv.cfg").is_file():
        raise UpdateError("Cannot confirm the original virtual environment. Use its original installer.")
    if kind in ("venv", "uv-venv"):
        if any((prefix.parent / f).exists() for f in ("uv.lock", "poetry.lock", "pdm.lock")):
            raise UpdateError("Update Roosta in the owning project's dependency file and sync its lockfile.")
        installer = (metadata.distribution("roosta").read_text("INSTALLER") or "").strip()
        if installer == "uv":
            return [manager_binary("uv"), "pip", "install", "--python", sys.executable, "--upgrade", spec]
        if installer != "pip":
            raise UpdateError("Use this virtual environment's original installer to update Roosta.")
        return [sys.executable, "-I", "-m", "pip", "--isolated", "install", "--upgrade", spec]

    if prefix.name != "roosta" or (kind == "pipx" and prefix.parent.name != "venvs"):
        raise UpdateError("Unexpected tool directory. Upgrade using the original manager and tool home.")
    binary = manager_binary(kind)
    if kind == "uv":
        env["UV_TOOL_DIR"] = str(prefix.parent)
        # uv records the original exposed executable, including custom tool-bin directories.
        receipt = tomllib.loads((prefix / "uv-receipt.toml").read_text())
        entries = receipt["tool"].get("entrypoints", [])
        scripts = [Path(e["install-path"]) for e in entries]
        if any(p.is_symlink() and not p.resolve().is_relative_to(prefix.resolve()) for p in scripts):
            raise UpdateError("A uv tool entry point belongs to another installation. Check the original bin directory.")
        bins = {p.parent for p in scripts}
        if bins:
            if len(bins) != 1 or not next(iter(bins)).is_absolute():
                raise UpdateError("Cannot identify the original uv tool bin directory.")
            env["UV_TOOL_BIN_DIR"] = str(bins.pop())
        else:
            env["UV_TOOL_BIN_DIR"] = exposed_bin_dir(prefix, "UV_TOOL_BIN_DIR")
        return [binary, "tool", "upgrade", spec]
    env["PIPX_BIN_DIR"] = exposed_bin_dir(prefix, "PIPX_BIN_DIR")
    env["PIPX_HOME"] = str(prefix.parent.parent)
    return [binary, "upgrade", "roosta"]


def update(check_only=False):
    try:
        version, _ = asyncio.run(updates.stable_release())
        latest = Version(version)
        running = Version(__version__)
        kind = updates.installation()
        print(f"Roosta {running} ({kind})   Latest stable {latest}")
        if kind in ("uv", "pipx", "venv", "uv-venv") and Version(metadata.version("roosta")) != running:
            print("Package metadata differs from the running CLI. Repair this environment before updating.")
            return 1
        if latest <= running:
            print("Already current." if latest == running else "This installation is newer. Keeping it.")
            return 0
        guidance = {
            "source": f"Preserve local edits and integrate tag v{version} in your development checkout. "
                      "Refresh its editable dependencies using the checkout's install instructions.",
            "mac": f"Download the matching disk image from {updates.RELEASES}/tag/v{version} and replace Roosta.app.",
            "unknown": f"Check which installer owns {sys.executable} and update through that manager. "
                       "For a separate managed CLI, use uv tool install roosta.",
        }
        if kind in guidance:
            print(guidance[kind])
            return 0 if check_only else 1
        if not asyncio.run(updates.python_release(version)):
            print("PyPI has no confirmed compatible, non-yanked wheel for this release.")
            return 1
        env = os.environ.copy()
        prefix = Path(sys.prefix)
        for key in ("UV_TARGET", "UV_PREFIX", "UV_BREAK_SYSTEM_PACKAGES", "PIP_BREAK_SYSTEM_PACKAGES",
                    "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_ROOT", "PIP_PYTHON", "PYTHONPATH", "PYTHONHOME"):
            env.pop(key, None)
        argv = manager_command(kind, version, prefix, env)
        print(f"Target environment: {prefix}")
        if check_only:
            print(f"Run roosta update to install {version} using {kind}.")
            return 0
        with tempfile.TemporaryDirectory() as temp:
            if kind == "pipx":
                # A transient constraint preserves pipx's recorded extras and injected packages.
                constraint = Path(temp) / "constraint.txt"
                constraint.write_text(f"roosta=={version}\n")
                for key in ("PIP_CONSTRAINT", "UV_CONSTRAINT"):
                    env[key] = (env.get(key, "") + " " + constraint.as_uri()).strip()
            if kind in ("venv", "uv-venv"):
                env["PIP_CONFIG_FILE"] = os.devnull
            manager = "pip" if argv[0] == sys.executable else Path(argv[0]).stem
            print(f"Installing Roosta {version} using {manager}...", flush=True)
            subprocess.run(argv, env=env, cwd=temp, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=True)
            actual = subprocess.check_output(
                [sys.executable, "-I", "-c", "from importlib.metadata import version; print(version('roosta'))"],
                cwd=temp, text=True, stderr=subprocess.DEVNULL, timeout=15)
            installed = Version(actual.strip())
        print(f"Verified installed version: {installed}")
        if installed != latest:
            print("The installer did not select the requested release. Check its constraints and tool home.")
            return 1
        print("Restart your existing runner or service, reload the dashboard, then run "
              "roosta skills sync --workspace <folder> for each workspace.")
        return 0
    except UpdateError as exc:
        print(exc)
    except subprocess.TimeoutExpired:
        print("Installer or version verification timed out. Check roosta --version before retrying.")
    except subprocess.CalledProcessError as exc:
        print(f"Installer or version verification failed (exit {exc.returncode}). Check the original environment.")
    except (metadata.PackageNotFoundError, *updates.CHECK_ERRORS):
        print("Could not verify release or installation metadata. Check connectivity and the original installation.")
    return 1
