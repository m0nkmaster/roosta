"""AI settings: runtime checks and options, model lists and validation, and background setup jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import ssl
import urllib.error

from roosta import ai_backend, ai_connections, ai_runtime
from roosta.claude_code import claude_model
from roosta.cursor_agent import CURSOR_AGENT, cursor_available, cursor_env, cursor_model
from roosta.opencode_ollama import (OLLAMA, opencode_model_compatible, opencode_ollama_available,
                                    opencode_ollama_env, parse_cursor_models, parse_ollama_models)
from roosta.task_config import (CLAUDE_HARNESS, CURSOR_HARNESS, HARNESS_LABELS, OPENCODE_OLLAMA_HARNESS,
                                VALID_HARNESSES, TaskConfig, runtime_model_key, task_engine)

log = logging.getLogger(__name__)


async def check_task_runtime(task: TaskConfig) -> bool:
    """Check the selected task harness without starting a model."""
    if task.connection or task.harness == "connection":
        return ai_backend.connection_available(task.connection)
    if task.harness == CLAUDE_HARNESS:
        return ai_backend.available(ai_backend.CLAUDE)
    if task.harness == CURSOR_HARNESS:
        return cursor_available()
    if task.harness == OPENCODE_OLLAMA_HARNESS:
        return opencode_ollama_available(task.model)
    return False


def runtime_unavailable_message(task: TaskConfig) -> str:
    if task.connection or task.harness == "connection":
        try:
            ai_connections.get(task.connection)
        except ValueError as exc:
            return str(exc)
        return "Install or repair the software for this worker’s AI connection in Settings"
    if task.harness == OPENCODE_OLLAMA_HARNESS:
        if not opencode_model_compatible(task.model):
            return f"{task.model} cannot execute OpenCode tool calls; choose another Ollama model"
        return "OpenCode or Ollama is unavailable"
    if task.harness not in VALID_HARNESSES:
        return f"Unknown harness {task.harness!r}; choose Claude Code, Cursor or Ollama"
    return ai_backend.unavailable_message(task_engine(task))


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


async def claude_model_choices(key: str = "legacy:claude") -> list[dict]:
    listing = await ai_backend.claude_models(key)
    return [{"id": entry["value"], "label": entry.get("displayName") or entry["value"]}
            for entry in listing["models"]]


def cursor_model_choices(models: list[dict]) -> list[dict]:
    """Mark the user's CURSOR_MODEL, if set, as the default; otherwise Cursor's own default stands."""
    default = cursor_model()
    return [
        {**m, "label": re.sub(r"\s*\((?:current|default)\)$", "", m["label"], flags=re.I)
         + (" (default)" if m["id"] == default else "")}
        for m in models
    ]


async def available_runtime_options() -> dict:
    """List every task harness with its models and whether it can run now.

    `model_key` says which task field the model choice fills.
    """
    cursor_stdout, ollama_stdout = await asyncio.gather(
        command_output(CURSOR_AGENT, "models", env=cursor_env()),
        command_output(OLLAMA, "list", env=opencode_ollama_env()),
    )
    ollama_models = parse_ollama_models(ollama_stdout)
    harnesses = [
        {
            "id": CLAUDE_HARNESS,
            "label": HARNESS_LABELS[CLAUDE_HARNESS],
            "model_key": runtime_model_key(CLAUDE_HARNESS),
            "default_model": claude_model(),
            "models": await claude_model_choices(),
            "available": ai_backend.available(ai_backend.CLAUDE),
        },
        {
            "id": CURSOR_HARNESS,
            "label": HARNESS_LABELS[CURSOR_HARNESS],
            "model_key": runtime_model_key(CURSOR_HARNESS),
            "default_model": cursor_model(),
            "models": cursor_model_choices(parse_cursor_models(cursor_stdout)),
            "available": cursor_available(),
        },
        {
            "id": OPENCODE_OLLAMA_HARNESS,
            "label": HARNESS_LABELS[OPENCODE_OLLAMA_HARNESS],
            "model_key": runtime_model_key(OPENCODE_OLLAMA_HARNESS),
            "default_model": "",
            "models": ollama_models,
            "available": bool(ollama_models) and opencode_ollama_available(ollama_models[0]["id"]),
        },
    ]
    return {"backend": ai_backend.current(), "harnesses": harnesses,
            "connections": ai_connections.load()["connections"], "default_connection": ai_backend.default_connection()}


# Settings' install, test and sign-in operations, by runtime or connection id.
jobs: dict[str, dict] = {}
job_tasks: dict[str, asyncio.Task] = {}


async def ollama_model_ids() -> list[str]:
    stdout = await command_output(OLLAMA, "list", env=opencode_ollama_env())
    return [m["id"] for m in parse_ollama_models(stdout)]


async def provider_models(provider: str, general: bool = False, key: str = "", refresh: bool = False) -> dict:
    default = await asyncio.to_thread(ai_connections.default_model, provider, general=general)
    if provider == "anthropic":
        listing = await ai_backend.claude_models(key or "legacy:claude", refresh=refresh)
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
    if model == current:
        return
    if provider == "anthropic":
        listing = await ai_backend.claude_models(key or "legacy:claude")
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
