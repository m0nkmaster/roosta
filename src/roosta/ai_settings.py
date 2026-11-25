"""AI settings: runtime checks and options, model lists and validation, and background setup jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import urllib.error

from roosta import ai_backend, ai_connections, ai_runtime
from roosta.cursor_agent import agent_path, parse_cursor_models
from roosta.task_config import TaskConfig

log = logging.getLogger(__name__)


async def check_task_runtime(task: TaskConfig) -> bool:
    """Check the worker's AI connection without starting a model."""
    return ai_backend.connection_available(task.connection)


def runtime_unavailable_message(task: TaskConfig) -> str:
    try:
        ai_connections.get(task.connection)
    except ValueError as exc:
        return str(exc)
    return "Install or repair the software for this worker’s AI connection in Settings"


async def command_output(
    *command: str,
    env: dict | None = None,
    timeout: float = 20,
    cwd: str | None = None,
) -> str:
    """Capture a bounded local command output."""
    proc = None
    try:
        # SECURITY-REVIEW: fixed local executables and arguments only; no shell.
        proc = await asyncio.create_subprocess_exec(
            *command,
            env=env,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await ai_backend.kill(proc)
        return ""
    except OSError:
        return ""
    return stdout.decode(errors="replace") if proc.returncode == 0 else ""


async def available_runtime_options() -> dict:
    """The AI connections a worker can choose, and which one it follows by default."""
    return {"connections": ai_connections.load()["connections"], "default_connection": ai_backend.default_connection()}


# Settings' install, test and sign-in operations, by runtime or connection id.
jobs: dict[str, dict] = {}
job_tasks: dict[str, asyncio.Task] = {}


async def ollama_model_ids() -> list[str]:
    stdout = await command_output(ai_runtime.OLLAMA, "list", env={**os.environ, "PATH": agent_path()})
    return [m["id"] for m in ai_runtime.parse_ollama_models(stdout)]


async def provider_models(provider: str, general: bool = False, key: str = "", refresh: bool = False) -> dict:
    default = await asyncio.to_thread(ai_connections.default_model, provider, general=general)
    if provider == "anthropic":
        listing = await ai_backend.claude_models(key, refresh=refresh)
        models = [ai_backend.claude_model_choice(entry) for entry in listing["models"]]
        member = ai_backend.claude_member(listing, default) if default else None
        label = ((member or {}).get("displayName") or default) if default else ai_backend.default_label(listing["default"])
        shown = member or listing["default"] or {}
        result = {"default": default, "default_label": label, "models": models,
                  "default_efforts": shown.get("supportedEffortLevels") or []}
        if listing.get("fallback"):
            result["error"] = listing["error"]
        return result
    if provider == "ollama":
        return {"default": "", "default_label": "", "models": [{"id": m, "label": m} for m in await ollama_model_ids()]}
    if provider == "cursor":
        binary, models = ai_runtime.find("cursor"), []
        if key and binary:  # Cursor lists models only for a signed-in account
            connection = ai_connections.get(key, connected=False)
            env = {**ai_backend.connection_env(connection), "CURSOR_API_KEY": ai_connections.credential(connection)}
            models = parse_cursor_models(await command_output(binary, "models", env=env))
        return {"default": default, "default_label": default or "Cursor's default", "models": models}
    models = []
    for model in await asyncio.to_thread(ai_runtime.model_catalog, provider):
        try:
            ai_connections.runtime(provider, model)
        except ValueError:
            continue
        models.append({"id": model, "label": model})
    default = default if any(m["id"] == default for m in models) else ""
    return {"default": default, "default_label": default, "models": models}


async def validate_model(provider: str, model: str, key: str = "", current: str = "") -> None:
    """A new model choice must be in the harness's own list; an already-stored valid one stays accepted."""
    if not model:
        return
    ai_connections.runtime(provider, model)
    if model == current or provider == "cursor":  # Cursor's list needs the account's key; its id format was checked
        return
    if provider == "anthropic":
        listing = await ai_backend.claude_models(key)
        name, _, effort = model.partition("@")
        if not name and effort:
            return
        if ai_backend.claude_member(listing, model) is None:
            raise ValueError("Claude Code doesn't offer that model; choose one from the list")
        return
    try:
        available = await ollama_model_ids() if provider == "ollama" else await asyncio.to_thread(ai_runtime.model_catalog, provider)
    except (ValueError, OSError):
        return
    if model not in available:
        raise ValueError("That model isn't offered by this provider; choose one from the list")


async def model_efforts(connection: dict, model: str) -> list[str]:
    if connection["provider"] == "anthropic":
        listing = await ai_backend.claude_models(connection["id"])
        member = ai_backend.claude_member(listing, model)
        return (member or {}).get("supportedEffortLevels") or []
    return await asyncio.to_thread(ai_runtime.model_efforts, connection["provider"], model)


async def run_operation(key: str, operation: str) -> None:
    """Install a runtime, test a connection or sign an account in, recording the outcome in `jobs`."""
    job = jobs.setdefault(key, {"operation": operation})
    proc = None
    terminal = None
    try:
        if operation == "install":
            await asyncio.to_thread(ai_runtime.install, key)
        elif operation == "test":
            if job.get("cancelling"):
                raise asyncio.CancelledError
            job["started"] = True
            await ai_backend.test_connection(key)
        else:
            connection = ai_connections.get(key)
            if connection["provider"] not in {"anthropic", "openai"} or connection["auth"] != "cli":
                raise ValueError("Choose an OpenAI or Anthropic account sign-in connection")
            binary = ai_runtime.find(ai_connections.engine(connection["provider"]))
            if not binary:
                raise ValueError("Install the AI runtime first")
            env = ai_backend.connection_env(connection)
            if connection["provider"] == "openai":
                # Pi requires a terminal; its browser callback completes sign-in without pasted tokens.
                terminal, slave = os.openpty()
                os.set_blocking(terminal, False)
                def discard_auth_output():
                    try:
                        if os.read(terminal, 65536):
                            return
                    except BlockingIOError:
                        return
                    except OSError:
                        pass
                    asyncio.get_running_loop().remove_reader(terminal)
                asyncio.get_running_loop().add_reader(terminal, discard_auth_output)
                try:
                    proc = await asyncio.create_subprocess_exec(binary, "auth", "login", "openai",
                        cwd=env["PI_CODING_AGENT_DIR"], env=env, stdin=slave, stdout=slave, stderr=slave,
                        start_new_session=True)
                finally:
                    os.close(slave)
            else:
                proc = await asyncio.create_subprocess_exec(binary, "auth", "login", "--sso",
                    env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            try:
                await asyncio.wait_for(proc.wait(), 300)
            except asyncio.TimeoutError:
                raise ValueError("Sign-in timed out; retry in a browser on this computer and close any other pending AI sign-in") from None
            if proc.returncode:
                raise ValueError("Sign-in did not complete; close other pending AI sign-ins, retry and check your organisation's account access")
        job.update(status="success")
    except asyncio.CancelledError:
        job.update(status="interrupted")
        raise
    except Exception as exc:
        log.exception("AI %s operation failed", operation)
        if isinstance(exc, ValueError):
            reason = str(exc)
        elif isinstance(exc, ssl.SSLError) or (isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ssl.SSLError)):
            reason = "Download failed: this computer's security certificates couldn't be verified"
        elif isinstance(exc, urllib.error.URLError) and operation == "install":
            reason = f"Download failed: {exc.reason}"
        elif isinstance(exc, OSError) and operation == "install":
            reason = f"Download failed: {exc}"
        else:
            reason = "Operation failed; check network access and the OS credential store, then retry"
        job.update(status="error", error=reason)
    finally:
        job.pop("started", None)
        job.pop("cancelling", None)
        if operation == "install":
            ai_runtime.INSTALLING.discard(key)
        await ai_backend.terminate(proc)
        if terminal is not None:
            asyncio.get_running_loop().remove_reader(terminal)
            os.close(terminal)
