"""AI dispatch: isolated named connections, their runs and process cleanup."""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import signal
import sys
import tempfile
import time
import uuid
import json
import os
from pathlib import Path

from roosta import claude_code
from roosta import cursor_agent

from roosta import paths, ai_connections as connections, ai_runtime, pi_agent

CURSOR = "cursor"
CLAUDE = "claude"


def label() -> str:
    """The default AI connection's name, for logs and status."""
    try:
        return connections.get(connected=False)["label"]
    except ValueError:
        return "AI connection"


def unavailable_message() -> str:
    """Why chats can't run, specific enough to act on."""
    try:
        connections.get()
    except ValueError as exc:
        return str(exc)
    return "Install or repair the software for your AI connection in Settings"


async def new_session(connection_id: str, workspace: str) -> str:
    """A fresh chat session id: Cursor names its own chats; the other runtimes accept ours."""
    try:
        connection = connections.get(connection_id)
    except ValueError:
        return str(uuid.uuid4())  # the turn itself reports the missing connection
    if connections.engine(connection["provider"]) != CURSOR:
        return str(uuid.uuid4())
    env = {**connection_env(connection), "CURSOR_API_KEY": connections.credential(connection)}
    return await cursor_agent.create_chat(ai_runtime.find("cursor"), env, workspace)


async def stop_all() -> None:
    await asyncio.gather(*(terminate(proc) for proc in list(LIVE_PROCESSES)))


ACTIVE_CONNECTIONS = Counter()
LIVE_PROCESSES = set()


@dataclass
class ConnectionRun:
    connection: dict
    backend: str
    args: list[str]
    env: dict = field(repr=False)
    workspace: str = ""
    session_id: str = ""
    secret: str = field(default="", repr=False)
    model: str = ""
    probe: bool = False
    cursor_config: tempfile.TemporaryDirectory | None = field(default=None, repr=False)

    def text(self, output: str) -> str:
        return {CLAUDE: claude_code.claude_result_text, CURSOR: cursor_agent.cursor_result_text}.get(
            self.backend, pi_agent.result_text)(output)

    def parse(self, line: str) -> dict | None:
        return {CLAUDE: claude_code.parse_claude_chat_line, CURSOR: cursor_agent.parse_chat_line}.get(
            self.backend, pi_agent.parse_line)(line)

    def redact(self, text: str) -> str:
        return text.replace(self.secret, "[credential]") if self.secret else text


CLAUDE_MODELS_TTL = 3600
CLAUDE_MODELS_TIMEOUT = 20


def parse_claude_models(output: str) -> dict:
    for event in pi_agent.events(output):
        if event.get("type") == "control_response":
            response = (event.get("response") or {}).get("response") or {}
            models = [m for m in response.get("models") or [] if isinstance(m, dict) and isinstance(m.get("value"), str)]
            return {"default": next((m for m in models if m["value"] == "default"), None),
                    "models": [m for m in models if m["value"] != "default"]}
    raise ValueError("Claude Code couldn't list models; check it's signed in")


def claude_fallback() -> dict:
    """Aliases offered, and validated against, only when the handshake fails; never cached."""
    return {"default": None, "fallback": True, "error": "Claude Code couldn't list models; check it's signed in",
            "models": [{"value": alias, "displayName": alias.capitalize(), "description": ""}
                       for alias in claude_code.CLAUDE_FALLBACK_ALIASES]}


async def claude_models(key: str, *, refresh: bool = False) -> dict:
    """Claude Code's own model list for a connection id (or "" for the user's own sign-in), cached for an hour."""
    cached = ai_runtime.CLAUDE_MODELS.get(key)
    if cached and not refresh and time.monotonic() - cached[0] < CLAUDE_MODELS_TTL:
        return cached[1]
    if not key:  # a provider's list before any Anthropic account exists
        binary, env = ai_runtime.find("claude"), claude_code.claude_env(os.environ)
    else:
        binary = ai_runtime.find("claude")
        env = connection_env(connections.get(key, connected=False))
        # The nonessential-traffic switch also suppresses the account's full model list.
        env.pop("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", None)
    if not binary:
        return claude_fallback()
    args = [binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose", "--setting-sources", ""]
    request = {"type": "control_request", "request_id": "roosta-models", "request": {"subtype": "initialize"}}
    proc, chunks = None, []
    with tempfile.TemporaryDirectory(prefix="roosta-models-") as temporary:
        try:
            proc = await asyncio.create_subprocess_exec(*args, cwd=temporary, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True, limit=16 * 1024 * 1024)
            proc.stdin.write((json.dumps(request) + "\n").encode())
            await proc.stdin.drain()
            async def read():
                while raw := await proc.stdout.readline():
                    chunks.append(raw.decode(errors="replace"))
                    if '"control_response"' in chunks[-1]:
                        return
            await asyncio.wait_for(read(), CLAUDE_MODELS_TIMEOUT)
            result = parse_claude_models("".join(chunks))
        except (OSError, asyncio.TimeoutError, ValueError):
            return claude_fallback()
        finally:
            if proc is not None:
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.close()
                await terminate(proc)
    ai_runtime.CLAUDE_MODELS[key] = (time.monotonic(), result)
    return result


def claude_model_choice(entry: dict) -> dict:
    return {"id": entry["value"], "label": entry.get("displayName") or entry["value"],
            "description": entry.get("description", ""), "efforts": entry.get("supportedEffortLevels") or []}


def default_label(entry: dict | None) -> str:
    return str((entry or {}).get("description", "")).split(" · ")[0]


def claude_member(listing: dict, model: str) -> dict | None:
    """The list entry a model id (optionally `@effort`) names, by value or resolvedModel."""
    name, _, effort = model.partition("@")
    for entry in listing["models"]:
        if name in (entry["value"], entry.get("resolvedModel")):
            if effort and effort not in (entry.get("supportedEffortLevels") or []):
                raise ValueError(f"{entry.get('displayName', name)} does not support {effort} effort")
            return entry
    return None


def default_connection() -> str:
    return connections.load().get("default", "")


def connection_available(connection_id: str = "") -> bool:
    try:
        connection = connections.get(connection_id)
        return bool(ai_runtime.find(connections.engine(connection["provider"])))
    except ValueError:
        return False


def connection_env(connection: dict) -> dict:
    env = dict(os.environ)
    # Model credentials/routing from the parent must never select another account.
    for key in list(env):
        if key.startswith(("ANTHROPIC_", "OPENAI_", "OPENROUTER_", "CLAUDE_", "PI_")) or key in {
            "CLAUDECODE", "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "GEMINI_API_KEY", "CURSOR_API_KEY",
        }:
            env.pop(key, None)
    env["PATH"] = cursor_agent.agent_path(env.get("PATH"))
    directory = connections.directory(connection["id"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    env.update({"PI_CODING_AGENT_DIR": str(directory / "pi"),
                "MCP_CONNECTION_NONBLOCKING": "false", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"})
    if connection["auth"] == "system":
        # Reuse the user's own Claude Code sign-in: its config and login live in ~/.claude.
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = str(directory / "claude")
        env["CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST"] = "1"
    for runtime in ("claude", "pi", "cursor"):
        target = directory / runtime
        if target.is_symlink() or not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError("AI runtime state cannot use a symlink outside its connection")
        target.mkdir(exist_ok=True, mode=0o700)
    if connection["provider"] == "openai" and connection["auth"] == "cli":
        auth = directory / "pi/auth.json"
        if auth.is_symlink() or (auth.exists() and not auth.is_file()):
            raise ValueError("Invalid AI authentication storage")
        if not auth.exists():
            with open(auth, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                output.write("{}")
    return env


def signed_in(connection: dict) -> bool | None:
    """Whether an account sign-in left credentials behind; None when this connection can't tell."""
    if connection.get("auth") != "cli" or connection.get("provider") != "openai":
        return None
    try:
        directory = connections.directory(connection["id"])
        auth = directory / "pi/auth.json"
        if auth.is_symlink() or not auth.resolve().is_relative_to(directory.resolve()):
            return False
        entry = json.loads(auth.read_text()).get("openai")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(entry, dict) and any(isinstance(entry.get(k), str) and entry[k] for k in ("refresh", "access"))


def mcp_config(workspace: str) -> dict:
    """Keep existing explicitly configured tools without copying runtime/account state."""
    servers = {}
    for path in (Path.home() / ".cursor/mcp.json", Path.home() / ".claude.json",
                 Path.home() / ".pi/agent/mcp.json", Path(workspace) / ".mcp.json", Path(workspace) / ".pi/mcp.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
            servers.update(data["mcpServers"])
        if path.name == ".claude.json" and isinstance(data, dict):
            projects = data.get("projects", {})
            local = projects.get(str(Path(workspace).resolve()), {}) if isinstance(projects, dict) else {}
            if isinstance(local, dict) and isinstance(local.get("mcpServers"), dict):
                servers.update(local["mcpServers"])
    return {"mcpServers": servers}


def _private_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(value, output)
    temporary.replace(path)


def prepare(connection_id: str, workspace: str, *, model: str = "", session_id: str = "", profile: str = "safe", probe: bool = False, subject: str = "chat") -> ConnectionRun:
    connection = connections.get(connection_id)
    model = model or connections.default_model(connection["provider"])
    if not model and connection["provider"] not in ("anthropic", "cursor"):  # these pick their own default
        raise ValueError("Choose a model in Settings" if subject == "chat"
                         else "Choose a model for this worker in its settings")
    effort = connections.selected_effort(connection["provider"], model)
    if effort and connection["provider"] == "anthropic":
        model = model.partition("@")[0] + "@" + effort
    backend = connections.runtime(connection["provider"], model) if model else connections.engine(connection["provider"])
    binary = ai_runtime.find(backend)
    if not binary:
        raise ValueError("AI runtime is missing or incompatible; use Install / repair in Settings")
    env = connection_env(connection)
    env.update({
        "PATH": str(paths.APP_ROOT / "worker-bin") + os.pathsep + env["PATH"],
        "ROOSTA_WORKER_EXECUTABLE": sys.executable,
        "ROOSTA_WORKER_PACKAGE_PARENT": "" if getattr(sys, "frozen", False) else str(paths.APP_ROOT.parent),
        "ROOSTA_WORKSPACE": str(paths.WORKSPACE),
        "ROOSTA_PORT": str(paths.PORT),
    })
    secret = connections.credential(connection)
    if secret:
        env[{"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY",
             "cursor": "CURSOR_API_KEY"}[connection["provider"]]] = secret
    directory = connections.directory(connection["id"])
    sid = session_id or ("" if backend == CURSOR else str(uuid.uuid4()))  # Cursor mints its own chat ids
    mcp = {"mcpServers": {}} if probe else mcp_config(workspace)
    workspace_root = Path(workspace).resolve()
    workspace_key = hashlib.sha256(str(workspace_root).encode()).hexdigest()[:16]
    private_roots = (connections.CONNECTIONS_DIR.resolve(), ai_runtime.RUNTIME_ROOT.resolve())
    package = paths.APP_ROOT.resolve()
    external_package = not package.is_relative_to(workspace_root)
    cursor_config = None
    if backend == CLAUDE:
        mcp_path = directory / f"mcp-{workspace_key}.json"
        _private_json(mcp_path, mcp)
        projects = (Path.home() / ".claude" / "projects" if connection["auth"] == "system"
                    else directory / "claude" / "projects")
        args = claude_code.claude_args(binary=binary, model=model or None, profile=profile,
                                      session_id=sid, partial=True, projects=projects)
        settings_index = args.index("--settings") + 1
        settings = json.loads(Path(args[settings_index]).read_text())
        permissions = settings["permissions"]
        for protected in private_roots:
            for tool in ("Read", "Edit", "Write"):
                permissions["deny"].append(f"{tool}(/{protected}/**)")
        if external_package:
            for tool in ("Edit", "Write"):
                permissions["deny"].append(f"{tool}(/{package}/**)")
        settings_path = directory / f"permissions-{profile}-{workspace_key}.json"
        _private_json(settings_path, settings)
        args[settings_index] = str(settings_path)
        args.extend(["--setting-sources", "", "--strict-mcp-config", "--mcp-config", str(mcp_path)])
        if probe:
            args.extend(["--tools", "Read", "--allowedTools", "Read"])
    elif backend == CURSOR:
        permissions = ({"allow": ["Read(**)", "Write(**)"], "deny": []} if profile == "unrestricted" else
                       cursor_agent.merged_permissions(json.loads(cursor_agent.SAFE_CONFIG_TEMPLATE.read_text())["permissions"]))
        permissions["deny"] += [f"{tool}({root}/**)" for root in private_roots for tool in ("Read", "Write")]
        if external_package:
            permissions["deny"].append(f"Write({package}/**)")
        cursor_config = cursor_agent.run_config(directory / "cursor", permissions, mcp)
        env["CURSOR_CONFIG_DIR"] = cursor_config.name
        args = cursor_agent.cursor_args(workspace=workspace, session_id=sid, model=model, binary=binary)
    else:
        pi_dir = directory / "pi" / workspace_key
        if pi_dir.is_symlink() or not pi_dir.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Invalid AI workspace state directory")
        pi_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if connection["auth"] == "cli":
            # Pi locks the resolved auth file, sharing refreshes across this account's workspaces.
            auth, shared_auth = pi_dir / "auth.json", directory / "pi/auth.json"
            if auth.is_symlink():
                if auth.resolve() != shared_auth.resolve():
                    raise ValueError("AI authentication storage belongs to another connection")
            elif auth.exists():
                raise ValueError("AI workspace authentication must use its connection's sign-in")
            else:
                auth.symlink_to(shared_auth)
        env["PI_CODING_AGENT_DIR"] = str(pi_dir)
        _private_json(pi_dir / "mcp.json", mcp)
        _private_json(pi_dir / "settings.json", {"retry": {"enabled": False}})
        if connection["provider"] == "ollama":
            _private_json(pi_dir / "models.json", {"providers": {"ollama": {
                "baseUrl": "http://127.0.0.1:11434/v1", "api": "openai-completions", "apiKey": "ollama",
                "models": [{"id": model, "name": model, "reasoning": False,
                            "input": ["text"], "contextWindow": 32768, "maxTokens": 8192,
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}],
            }}})
        policy = cursor_agent.merged_permissions(json.loads(cursor_agent.SAFE_CONFIG_TEMPLATE.read_text())["permissions"])
        if profile == "unrestricted":
            policy = {"allow": [], "deny": [], "unrestricted": True}
        policy["protected"] = [str(p) for p in private_roots]
        if external_package:
            policy["readOnlyRoot"] = str(package)
        env["ROOSTA_PI_POLICY"] = json.dumps(policy)
        args = pi_agent.pi_args(binary, connection, model, pi_dir, sid, workspace)
        if effort:
            args.extend(["--thinking", effort])
        if probe:
            args.extend(["--no-mcp", "--no-context-files", "--tools", "read"])
    return ConnectionRun(connection, backend, args, env, workspace, sid, secret, model, probe, cursor_config)


async def kill_group(proc) -> None:
    # The leader can exit while a descendant still holds the output pipes.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await proc.communicate()  # Drain any buffered pipes before waiting for transport shutdown.


async def spawn_group(*args, **kwargs):
    # Keep ownership if cancellation arrives between fork and transport creation.
    spawning = asyncio.create_task(asyncio.create_subprocess_exec(*args, start_new_session=True, **kwargs))
    try:
        return await asyncio.shield(spawning)
    except asyncio.CancelledError:
        await kill_group(await spawning)
        raise


async def kill(proc) -> None:
    """Kill a still-running child process group at once and reap its leader."""
    if proc and proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (AttributeError, ProcessLookupError):
            proc.kill()
        await proc.wait()


async def terminate(proc) -> None:
    if proc is None or proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), 3)
    except (ProcessLookupError, asyncio.TimeoutError):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()


def repair_message(output: str) -> str:
    lowered = output.lower()
    if any(word in lowered for word in ("401", "unauthorized", "authentication", "api key", "oauth", "login")):
        return "Sign-in failed or expired; reconnect this account in Settings"
    if any(word in lowered for word in ("credit", "quota", "billing", "insufficient")):
        return "This account needs API credit or a higher allowance; check its billing"
    if any(word in lowered for word in ("429", "rate limit", "too many requests")):
        return "This account is rate limited; wait and retry (no account was switched)"
    if any(word in lowered for word in ("model", "404", "not found")):
        return "This model is unavailable on this connection; change the model in Settings"
    return "AI request failed; check the connection in Settings."


async def stream(run: ConnectionRun, prompt: str, *, idle: float = 300, maximum: float = 3600):
    """A foreground turn with stderr draining, bounded silence and process-group cleanup."""
    ACTIVE_CONNECTIONS[run.connection["id"]] += 1
    proc = None
    stderr_task = None
    chunks, errors = [], []
    try:
        connections.get(run.connection["id"])
        if run.backend in ai_runtime.INSTALLING:
            raise ValueError("This AI runtime is being repaired; retry when Settings reports success")
        args = run.args
        if run.backend == CURSOR:
            if not run.session_id:
                run.session_id = await cursor_agent.create_chat(run.args[0], run.env, run.workspace)
                run.args = [*run.args, "--resume", run.session_id]
            args = [*run.args, prompt]  # Cursor takes the prompt as its last argument
        proc = await spawn_group(*args, cwd=run.workspace, env=run.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024)
        LIVE_PROCESSES.add(proc)
        async def drain():
            while chunk := await proc.stderr.read(65536):
                errors.append(chunk)
                if len(errors) > 8:
                    del errors[0]
        stderr_task = asyncio.create_task(drain())
        waiting_for_policy = run.backend == "pi"
        prompt_sent = not waiting_for_policy
        if prompt_sent:
            if run.backend != CURSOR:
                proc.stdin.write(prompt.encode())
                await proc.stdin.drain()
            proc.stdin.close()
        deadline, last_output = time.monotonic() + maximum, time.monotonic()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(f"AI turn exceeded {maximum:g}s")
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), min(idle if prompt_sent else 30, remaining))
            except asyncio.TimeoutError:
                if not prompt_sent:
                    raise ValueError("Pi did not confirm its permission policy; repair the runtime in Settings")
                if time.monotonic() - last_output < idle / 2 and time.monotonic() < deadline:
                    continue
                raise ValueError("AI runtime stopped responding; retry this connection")
            if not raw:
                break
            line = run.redact(raw.decode(errors="replace"))
            chunks.append(line)
            last_output = time.monotonic()
            if run.backend == "pi":
                for event in pi_agent.events(line):
                    if event.get("type") == "extension_ui_request" and event.get("method") == "notify" and event.get("message") == "roosta-policy-ready" and waiting_for_policy:
                        waiting_for_policy = False
                        proc.stdin.write(b'{"id":"roosta-state","type":"get_state"}\n')
                        await proc.stdin.drain()
                    if event.get("type") == "response" and event.get("id") == "roosta-state" and not prompt_sent:
                        model = (event.get("data") or {}).get("model") or {}
                        if (model.get("provider"), model.get("id")) != (run.connection["provider"], run.model):
                            raise ValueError("Pi selected a different model; choose an exact compatible model in Settings")
                        if "--thinking" in run.args and (event.get("data") or {}).get("thinkingLevel") != run.args[run.args.index("--thinking") + 1]:
                            raise ValueError("Pi selected a different effort; choose a supported effort in Settings")
                        proc.stdin.write((json.dumps({"id": "roosta-prompt", "type": "prompt", "message": prompt}) + "\n").encode())
                        await proc.stdin.drain()
                        prompt_sent = True
                    if event.get("type") == "response" and event.get("success") is False:
                        raise ValueError(repair_message(run.redact(str(event.get("error", "Pi command failed")))))
                    if event.get("type") == "agent_settled" and prompt_sent:
                        proc.stdin.close()
            yield line
        await asyncio.wait_for(proc.wait(), max(.1, deadline - time.monotonic()))
        await stderr_task
        if not prompt_sent:
            raise ValueError("Pi permission policy did not load; no prompt was sent")
        stdout = "".join(chunks)
        failure = pi_agent.failure(stdout) if run.backend == "pi" else ""
        if run.backend in (CLAUDE, CURSOR):
            for event in pi_agent.events(stdout):
                if event.get("type") == "result" and event.get("is_error"):
                    failure = str(event.get("result") or event.get("errors") or "AI request failed")
        if proc.returncode is not None and proc.returncode < 0 and not stdout.strip():
            raise ValueError(f"The AI runtime was stopped by macOS (signal {-proc.returncode}) before it replied. "
                             "Endpoint security can kill a process over a word in the message, so try "
                             "rephrasing or removing a link.")
        if proc.returncode or failure:
            diagnostic = run.redact(failure or b"".join(errors).decode(errors="replace") or stdout)
            raise ValueError(repair_message(diagnostic))
    finally:
        async def cleanup():
            if run.probe and proc is not None:
                if stderr_task is not None:
                    stderr_task.cancel()
                    await asyncio.gather(stderr_task, return_exceptions=True)
                await kill_group(proc)
            else:
                await terminate(proc)
                if stderr_task is not None and not stderr_task.done():
                    stderr_task.cancel()
                    await asyncio.gather(stderr_task, return_exceptions=True)
        try:
            await _join_on_cancel(cleanup())
        finally:
            ACTIVE_CONNECTIONS[run.connection["id"]] -= 1
            LIVE_PROCESSES.discard(proc)
            if run.cursor_config is not None:
                run.cursor_config.cleanup()


async def _join_on_cancel(work):
    # Cancellation must join cleanup and bounded offline lookups before releasing the job.
    task = asyncio.create_task(work)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def _first_model(provider: str) -> str:
    """A model to probe with when the harness reports no default: the first one it lists."""
    if provider == "ollama":
        proc = await spawn_group(ai_runtime.OLLAMA, "list", env={**os.environ, "PATH": cursor_agent.agent_path()},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), 20)
        except (asyncio.TimeoutError, OSError):
            stdout = b""
        finally:
            await kill_group(proc)
        models = [m["id"] for m in ai_runtime.parse_ollama_models(stdout.decode(errors="replace"))]
    else:
        models = [m for m in await _join_on_cancel(asyncio.to_thread(ai_runtime.model_catalog, provider))
                  if _acceptable(provider, m)]
    if not models:
        raise ValueError("No models are available for this connection; install or download one first")
    return models[0]


def _acceptable(provider: str, model: str) -> bool:
    try:
        connections.runtime(provider, model)
        return True
    except ValueError:
        return False


async def test_connection(connection_id: str) -> dict:
    """One disclosed billable response plus a read of a random, harmless local file."""
    with tempfile.TemporaryDirectory(prefix="roosta-ai-test-") as temporary:
        nonce = uuid.uuid4().hex
        test_file = Path(temporary) / "connection-test.txt"
        test_file.write_text(nonce)
        connection = connections.get(connection_id)
        model = await _join_on_cancel(asyncio.to_thread(connections.default_model, connection["provider"]))
        if not model and connection["provider"] not in ("anthropic", "cursor"):
            model = await _first_model(connection["provider"])
        run = await _join_on_cancel(asyncio.to_thread(prepare, connection_id, temporary, model=model, probe=True))
        output = "".join([line async for line in stream(run,
            f"Use the read tool to read {test_file}. Reply with only the file contents. Do not run any other tool.",
            idle=90, maximum=120)])
        tool_read = False
        for event in pi_agent.events(output):
            if run.backend == "pi" and event.get("type") == "tool_execution_end" and event.get("toolName") == "read" and not event.get("isError"):
                tool_read = nonce in json.dumps(event.get("result", {}))
            if run.backend == CURSOR and event.get("type") == "tool_call" and event.get("subtype") == "completed":
                tool_read = tool_read or nonce in json.dumps(event.get("tool_call"))
            if run.backend == CLAUDE and event.get("type") == "user":
                tool_read = tool_read or any(p.get("type") == "tool_result" and not p.get("is_error") and nonce in json.dumps(p.get("content"))
                                            for p in event.get("message", {}).get("content", []) if isinstance(p, dict))
        if not tool_read or nonce not in run.text(output):
            raise ValueError("The model responded but did not prove local tool use; choose a tool-capable model")
    ai_runtime.CLAUDE_MODELS.pop(connection_id, None)
    updated = connections.update(connection_id, tested=True)
    if not connections.load().get("default"):
        connections.set_default(connection_id)
    return updated
