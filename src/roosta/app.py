"""Roosta's FastAPI app: the API routes and pages, lifespan, and the shared runner, chat router and activity log."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import FastAPI, Request, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from roosta import attachments, updates
from roosta import connectors as connectors_mod
from roosta import cli, paths, profile, skills
from roosta import __version__
from roosta.chat import (ChatRouter, clip_body, ConversationHistoryStore, SessionMap, TopicStore,
                  is_general_chat_id, normalise_defer_until)
from roosta import ai_backend
from roosta import ai_connections, ai_runtime, ai_settings, pages, pi_agent, teletext
from roosta.activity_log import ActivityLog
from roosta.claude_code import (
    read_claude_transcript,
    session_exists as claude_session_exists,
)
from roosta.cursor_agent import (
    GIT_PUSH_CONFIG_DIR,
    SAFE_CONFIG_DIR,
)
from roosta.cursor_sessions import read_cursor_transcript, valid_session_id
from roosta.board import (
    AI_SETUP_ITEM_ID,
    SETUP_ITEM_ID,
    attach_raised_at,
    board_health,
    board_merges,
    collect_board_items,
    merge_board_feed_items,
    merge_pushed_notifications,
    normalise_board_doc,
    push_notification,
    recently_closed,
    restart_pending,
    setup_gaps,
    setup_item,
    snooze_deadline,
    split_due_reminders,
    split_snoozed_items,
)
from roosta.chat_items import (
    DOCUMENT_CHAT_PREFIX,
    GENERAL_CHAT_ITEM,
    HIRE_CHAT_PREFIX,
    WORKER_CHAT_PREFIX,
    chat_list,
    document_chat_item,
    hire_chat_item,
    is_chat_id,
    standing_thread_ids,
    worker_chat_item,
)
from roosta.ai_settings import (available_runtime_options, model_efforts, provider_models,
                                validate_model)
from roosta.workspace_settings import captured, list_folders, skills_lock, workspace_managed_by, workspace_target
from roosta.scheduler import TaskRunner, outcome_summary, parse_task_output
from roosta.task_config import (
    CLAUDE_HARNESS,
    load_tasks,
    load_tasks_map,
    skill_files,
    unscheduled_skills,
    valid_runtime,
    workspace_skills,
)
from roosta.pulse import build_pulse, markdown_title, project_brief, review_project
from roosta.usage import UsageStore
from roosta.workspace import (VAULT_SOURCE_SUFFIXES, build_catalogue, context_documents,
                              read_document, resolve_vault_markdown, resolve_vault_text,
                              source_as_markdown)
from roosta.workspace import metadata as workspace_metadata
from roosta.workspace import visible_path as workspace_visible

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

DASHBOARD_ROOT = paths.APP_ROOT
CACHE_DIR = paths.CACHE_DIR
PRODUCT_USAGE_FILE = CACHE_DIR / "product-usage.jsonl"
ASSISTANT_DIR = paths.ASSISTANT_DIR
SESSIONS_FILE = ASSISTANT_DIR / "sessions.json"
TOPICS_FILE = ASSISTANT_DIR / "topics.json"
CHAT_HISTORY_FILE = ASSISTANT_DIR / "chat-history.json"
UPLOADS_DIR = ASSISTANT_DIR / "uploads"
HANDLED_FILE = ASSISTANT_DIR / "handled.json"
SNOOZED_FILE = ASSISTANT_DIR / "snoozed.json"
RAISED_FILE = ASSISTANT_DIR / "raised.json"
MERGED_FILE = ASSISTANT_DIR / "merged.json"
REMINDERS_FILE = ASSISTANT_DIR / "reminders.json"
product_usage = UsageStore(PRODUCT_USAGE_FILE)
ARCHIVED_CHATS_FILE = ASSISTANT_DIR / "archived-chats.json"

agent = ai_backend.AIAgent()
chat_router: ChatRouter | None = None  # set in lifespan once the AI backend is available


# One activity log sees every AI spawn; the runner records into it.
activity = ActivityLog()
activity.hydrate()
connectors = connectors_mod.Connectors(path=paths.CONNECTORS_FILE)
runner = TaskRunner(activity_log=activity, connector_registry=connectors)


# --- FastAPI app ---


async def ensure_chat_router() -> bool:
    """Retry starting chats, so installing or signing in to an engine needs no restart."""
    if chat_router is None:
        await _start_chat_router()
    return chat_router is not None


def chat_unavailable() -> JSONResponse:
    """Say which engine is missing and what to do, not just that chats are off."""
    return JSONResponse({"error": f"{ai_backend.unavailable_message()}. Open Settings → AI connections, then try again."},
                        status_code=503)


async def _start_chat_router() -> None:
    """Create the chat router once the selected AI backend is usable."""
    global chat_router
    if chat_router is not None:
        return
    try:
        # History and per-chat connections remain available even when the default is disconnected.
        chat_router = ChatRouter(
            agent,
            SessionMap(SESSIONS_FILE),
            str(paths.WORKSPACE),  # chats run at the workspace root
            HANDLED_FILE,
            SNOOZED_FILE,
            TopicStore(TOPICS_FILE),
            ConversationHistoryStore(CHAT_HISTORY_FILE),
            reminders_path=REMINDERS_FILE,
            raised_path=RAISED_FILE,
            merged_path=MERGED_FILE,
        )
        log.info("%s ready", ai_backend.label())
    except Exception as e:
        log.warning("%s unavailable: %s (chats disabled)", ai_backend.label(), e)


# Cursor's CLI writes a per-run SQLite session store under each config dir's `chats/`
# tree. The dashboard never reads these (it renders Cursor history from
# ~/.cursor/projects and Claude history from ~/.claude/projects); they are pure CLI
# scratch that otherwise grows without bound - thousands of stores, many with orphaned
# -wal files from sessions that never closed. Reclaim the old ones at startup, the same
# way activity.jsonl is compacted. ~/.claude and ~/.cursor transcript trees are left
# alone: they are the surfaces the drill-down reads and mingle with the user's own non-dashboard
# CLI history, so pruning them would be real context loss.
SESSION_STORE_RETENTION_DAYS = 30


def prune_cursor_session_stores(
    retention_days: int = SESSION_STORE_RETENTION_DAYS,
    referenced: set[str] | None = None,
) -> int:
    """Delete Cursor CLI session-store dirs older than the retention window.

    Each store is `<config>/chats/<hash>/<session-uuid>/`. A store is kept when its
    newest file is within the window or its uuid is still referenced by the activity
    log (so a resumable chat is never pulled out from under the CLI). Returns the count
    removed. Never raises: a stale store is cheaper than a crashed startup.
    """
    keep = referenced or {e.get("session_id", "") for e in activity._entries.values()}
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for config_dir in (SAFE_CONFIG_DIR, GIT_PUSH_CONFIG_DIR):
        chats = config_dir / "chats"
        if not chats.is_dir():
            continue
        for store in chats.glob("*/*"):
            if not store.is_dir() or store.name in keep:
                continue
            try:
                newest = max((p.stat().st_mtime for p in store.rglob("*")), default=store.stat().st_mtime)
                if newest >= cutoff:
                    continue
                shutil.rmtree(store)
                removed += 1
            except OSError:
                continue
    if removed:
        log.info("pruned %d stale Cursor session store(s)", removed)
    return removed


@asynccontextmanager
async def lifespan(app: FastAPI):
    activity.compact()  # before runner.start(), so no spawn is appending
    prune_cursor_session_stores()    # reclaim unread Cursor CLI scratch, same timing
    try:
        await ai_connections.offer_system()
    except (ValueError, OSError):
        log.warning("Could not detect an existing Claude Code account; open AI settings to continue")
    runner.start()
    await _start_chat_router()
    app.state.release_checks = updates.ReleaseChecks()
    update_task = asyncio.create_task(app.state.release_checks.run())
    yield
    jobs = [task for task in ai_settings.job_tasks.values() if not task.done()]
    jobs.append(update_task)
    for task in jobs:
        task.cancel()
    await asyncio.gather(*jobs, return_exceptions=True)
    await agent.stop()
    await runner.stop()


app = FastAPI(title="Skill Runner", lifespan=lifespan)


class NoCacheHtmlMiddleware(BaseHTTPMiddleware):
    """Keep the desktop shell nav in sync when dashboard HTML changes."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith(("/runner", "/assistant", "/pulse", "/constellation", "/document", "/workspace", "/office", "/settings", "/changelog", "/pages")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        elif path.startswith("/static/") and path.endswith((".css", ".js")):
            # Shared styles change with the pages; revalidate against the ETag so
            # a page never renders new markup with a stale control family.
            response.headers["Cache-Control"] = "no-cache"
        return response


app.add_middleware(NoCacheHtmlMiddleware)


@app.get("/api/tasks")
async def api_tasks():
    return JSONResponse(runner.get_states())


@app.get("/api/ai-backend")
async def api_ai_backend():
    return JSONResponse(ai_backend.status())


@app.post("/api/ai-backend")
async def api_set_ai_backend(body: dict):
    """Switch every dashboard AI turn (tasks, chats, sends) between engines."""
    backend = str(body.get("backend", "")).strip() if isinstance(body, dict) else ""
    if backend not in ai_backend.BACKENDS:
        return JSONResponse({"error": "invalid backend"}, status_code=400)
    ai_backend.set_backend(backend)
    log.info("AI backend switched to %s", ai_backend.label(backend))
    await _start_chat_router()
    return JSONResponse(ai_backend.status())


def local_ai_settings(request: Request) -> None:
    """Credential/runtime changes are local-only and reject cross-origin browser requests."""
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "AI settings are available only on this computer")
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "Invalid local host")
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Cross-origin AI settings request denied")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site AI settings request denied")


def same_origin_upload(request: Request) -> None:
    """A raw-body POST is a CORS simple request, so refuse other sites writing files here."""
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Cross-origin upload denied")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site upload denied")


def ai_settings_result(data: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code, headers={"Cache-Control": "no-store"})


AFFECTED_CHAT_LIMIT = 10


def connection_affected(connection_id: str) -> dict:
    default = ai_backend.default_connection()
    workers = [t.id for t in load_tasks() if t.connection == connection_id or
               (t.harness == "connection" and t.connection in ("", "default") and default == connection_id)]
    chats = [item for item, selected in chat_router._sessions._connections.items() if selected == connection_id] if chat_router else []
    pending = [run for run, pause in chat_router._paused.items() if pause.get("connection") == connection_id] if chat_router else []
    chat_count = len(chats)
    if chat_router:
        active = chat_router.last_active()
        chats = sorted(chats, key=lambda item: active.get(item, ""), reverse=True)[:AFFECTED_CHAT_LIMIT]
    titles = {item: (chat_router.known_item(item) or {}).get("title", item) for item in chats}
    return {"workers": workers, "chats": chats, "chat_count": chat_count, "chat_titles": titles,
            "pending_approvals": pending}


@app.get("/api/updates")
async def api_update_notice():
    result = app.state.release_checks.result
    return ai_settings_result({k: result[k] for k in ("latest", "notes") if k in result})


@app.get("/api/settings/updates", dependencies=[Depends(local_ai_settings)])
async def api_settings_updates():
    return ai_settings_result({"version": __version__, **app.state.release_checks.result})


@app.post("/api/settings/updates", dependencies=[Depends(local_ai_settings)])
async def api_check_updates():
    result = await app.state.release_checks.refresh()
    return ai_settings_result({"version": __version__, **result})


@app.get("/api/settings/workspace", dependencies=[Depends(local_ai_settings)])
async def api_settings_workspace():
    config = cli.read_config()
    port = config.get("port")
    lock = skills_lock()
    entries = lock.get("skills") if isinstance(lock.get("skills"), dict) else {}
    service = await asyncio.to_thread(cli.service_status, paths.WORKSPACE)
    return ai_settings_result({
        "version": __version__, "workspace": str(paths.WORKSPACE),
        "remembered": config.get("workspace") if isinstance(config.get("workspace"), str) else "",
        "host": os.environ.get("ROOSTA_HOST") or "127.0.0.1", "port": paths.PORT,
        "saved_host": config.get("host") if isinstance(config.get("host"), str) else "",
        "saved_port": port if isinstance(port, int) and not isinstance(port, bool) else None,
        "managed_by": workspace_managed_by(), "service": service,
        "skills": {"modified": sorted(n for n, e in entries.items() if isinstance(e, dict) and e.get("modified")),
                   "roosta": str(lock.get("roosta") or "")}})


@app.get("/api/settings/folders", dependencies=[Depends(local_ai_settings)])
async def api_settings_folders(path: str = ""):
    if path.strip():
        target, error = workspace_target({"path": path})
        if error:
            return ai_settings_result({"error": error}, 400)
    else:
        target = Path.home()
    if not target.is_dir():
        return ai_settings_result({"error": "That folder does not exist."}, 400)
    try:
        return ai_settings_result(await asyncio.to_thread(list_folders, target))
    except OSError:
        return ai_settings_result({"error": "Roosta cannot read that folder."}, 400)


@app.post("/api/settings/workspace", dependencies=[Depends(local_ai_settings)])
async def api_settings_workspace_set(body: dict):
    action = body.get("action")
    if action not in ("select", "create", "adopt"):
        return ai_settings_result({"error": "Choose select, create or adopt."}, 400)
    target, error = workspace_target(body)
    if error:
        return ai_settings_result({"error": error}, 400)
    git = body.get("git", True) is not False
    message = ""
    if action == "select":
        if not (target / ".roosta").is_dir():
            return ai_settings_result(
                {"error": f"{target} is not a Roosta workspace. Create or adopt it instead."}, 400)
        cli.remember_workspace(target)
    else:
        if action == "adopt" and not target.is_dir():
            return ai_settings_result({"error": f"{target} does not exist, so there is nothing to adopt."}, 400)
        code, message = await asyncio.to_thread(
            captured, lambda: cli.init(target, adopt=action == "adopt", initialise_git=git))
        if code:
            return ai_settings_result({"error": message or "Could not set up the workspace."}, 400)
    return ai_settings_result({"workspace": str(target), "active": str(paths.WORKSPACE),
                               "restart_required": target != paths.WORKSPACE, "message": message})


@app.post("/api/settings/address", dependencies=[Depends(local_ai_settings)])
async def api_settings_address(body: dict):
    if workspace_managed_by() == "desktop":
        return ai_settings_result({"error": "The Roosta app always runs on 127.0.0.1:7667."}, 409)
    host, port = body.get("host"), body.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        return ai_settings_result({"error": "Enter a port between 1024 and 65535."}, 400)
    host = host.strip() if isinstance(host, str) else ""
    if host.lower() == "localhost":
        host, loopback = "localhost", True
    else:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            return ai_settings_result({"error": "Enter an IP address such as 127.0.0.1, or localhost."}, 400)
    if not loopback and body.get("confirm_network") is not True:
        return ai_settings_result({"error": "Confirm that anyone on your network may reach Roosta.",
                                   "needs_confirmation": True}, 400)
    cli.remember_address(host, port)
    return ai_settings_result({"saved_host": host, "saved_port": port, "restart_required": True})


@app.post("/api/settings/service", dependencies=[Depends(local_ai_settings)])
async def api_settings_service():
    if workspace_managed_by() == "desktop":
        return ai_settings_result({"error": "The Roosta app already runs Roosta for you. "
                                   "A background service would start a second runner."}, 409)
    if not (await asyncio.to_thread(cli.service_status, paths.WORKSPACE))["supported"]:
        return ai_settings_result({"error": "Background services are not available on this platform."}, 400)
    code, message = await asyncio.to_thread(captured, lambda: cli.service_install(paths.WORKSPACE, paths.PORT))
    if code:
        return ai_settings_result({"error": message or "Could not install the service."}, 400)
    return ai_settings_result({"service": await asyncio.to_thread(cli.service_status, paths.WORKSPACE),
                               "message": message})


@app.get("/api/settings/notifications", dependencies=[Depends(local_ai_settings)])
async def api_settings_notifications():
    return ai_settings_result({"enabled": cli.notifications_enabled(), "managed_by": workspace_managed_by()})


@app.post("/api/settings/notifications", dependencies=[Depends(local_ai_settings)])
async def api_settings_notifications_set(body: dict):
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return ai_settings_result({"error": "Choose on or off."}, 400)
    cli.remember_notifications(enabled)
    return ai_settings_result({"enabled": enabled, "managed_by": workspace_managed_by()})


@app.post("/api/settings/skills-sync", dependencies=[Depends(local_ai_settings)])
async def api_settings_skills_sync():
    report = await asyncio.to_thread(skills.sync, paths.CORE_SKILLS_DIR, paths.WORKSPACE)
    return ai_settings_result({"installed": report.installed, "updated": report.updated,
                               "current": report.current, "modified": report.modified})


@app.get("/api/ai/connections", dependencies=[Depends(local_ai_settings)])
async def api_ai_connections(item_id: str = ""):
    try:
        await ai_connections.offer_system()
        engines = {name: await asyncio.to_thread(ai_runtime.describe, name) for name in ai_runtime.RUNTIMES}
        runtimes = {name: {"version": engine["version"], "installed": engine["installed"]}
                    for name, engine in engines.items()}
        onboarding = await asyncio.to_thread(setup_item, chat_router)
        data = ai_connections.load()
        selected, selected_model = "", ""
        if item_id and chat_router:
            sessions = chat_router._sessions
            selected = sessions._connections.get(item_id) or (
                f"legacy:{ai_backend.current()}" if sessions.get(item_id) else ai_backend.default_connection())
            selected_model = sessions.model(item_id)
        data = {**data, "connections": [{**c, "signed_in": ai_backend.signed_in(c)} for c in data["connections"]]}
        missing = setup_gaps() if (onboarding and onboarding["id"] == SETUP_ITEM_ID
                                   and SETUP_ITEM_ID not in (chat_router.handled() if chat_router else {})) else []
        return ai_settings_result({**data, "providers": ai_connections.PROVIDERS, "runtimes": runtimes,
            "engines": engines, "terminal_available": sys.platform == "darwin",
            "workspace_setup_ready": bool(missing), "workspace_setup_missing": missing,
            "jobs": ai_settings.jobs, "selected": selected, "selected_model": selected_model,
            "legacy": ai_backend.current(),
            "affected": {c["id"]: connection_affected(c["id"]) for c in data["connections"]}})
    except ValueError as exc:
        return ai_settings_result({"error": str(exc)}, 400)


@app.get("/api/ai/models", dependencies=[Depends(local_ai_settings)])
async def api_ai_models(provider: str = "", connection: str = "", general: int = 0, refresh: int = 0):
    try:
        if connection == "legacy:cursor":
            return ai_settings_result({"default": "", "models": []})
        if connection == "legacy:claude":
            provider = "anthropic"
        elif connection:
            selected = ai_connections.get("" if connection == "default" else connection, connected=False)
            provider, connection = selected["provider"], selected["id"]
        if provider not in ai_connections.PROVIDERS:
            raise ValueError("Choose a provider or connection")
        return ai_settings_result(await provider_models(provider, bool(general), connection, bool(refresh)))
    except (ValueError, OSError) as exc:
        return ai_settings_result({"error": str(exc)}, 400)


@app.post("/api/ai/connections", dependencies=[Depends(local_ai_settings)])
async def api_ai_connection_create(body: dict):
    try:
        return ai_settings_result(ai_connections.create(body), 201)
    except ValueError as exc:
        return ai_settings_result({"error": str(exc)}, 400)
    except Exception:
        return ai_settings_result({"error": "The OS credential store could not save this key; unlock it and try again"}, 400)


@app.get("/api/ai/efforts", dependencies=[Depends(local_ai_settings)])
async def api_ai_efforts(connection: str, model: str):
    try:
        if not model:
            raise ValueError("Choose a model")
        selected = ai_connections.get(connection)
        await validate_model(selected["provider"], model, selected["id"])
        return ai_settings_result({"levels": await model_efforts(selected, model)})
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return ai_settings_result({"error": str(exc)}, 400)


@app.post("/api/ai/default", dependencies=[Depends(local_ai_settings)])
async def api_ai_default(body: dict):
    try:
        model = body.get("model")
        effort = body.get("effort", "")
        if not isinstance(effort, str) or (effort and model is None):
            raise ValueError("Choose a model and a supported effort")
        if model is not None:
            if not isinstance(model, str) or not model.strip():
                raise ValueError("Choose a model")
            model = model.strip()
            connection = ai_connections.get(body.get("connection", ""))
            await validate_model(connection["provider"], model, connection["id"])
            if effort and effort not in await model_efforts(connection, model):
                raise ValueError("This model does not support that effort")
        if chat_router:
            for item in list(chat_router._sessions._map):
                chat_router._sessions.connection(item)
        ai_connections.set_default(body.get("connection", ""), model, effort)
        await ensure_chat_router()
        return ai_settings_result({"ok": True})
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return ai_settings_result({"error": str(exc)}, 400)


@app.post("/api/ai/chat-connection", dependencies=[Depends(local_ai_settings)])
async def api_ai_chat_connection(body: dict):
    await ensure_chat_router()
    item_id, connection_id = body.get("item_id"), body.get("connection")
    if not isinstance(item_id, str) or not 1 <= len(item_id) <= 200:
        return ai_settings_result({"error": "Choose a chat"}, 400)
    if item_id in chat_router.active_items() or any(p["item_id"] == item_id for p in chat_router._paused.values()):
        return ai_settings_result({"error": "Finish this turn or its pending approval before changing connection"}, 409)
    try:
        selected = ai_connections.get(connection_id)
        chat_router._sessions.bind(item_id, selected["id"])
        return ai_settings_result({"ok": True, "message": "Connection changed. Visible history and summary are retained; execution starts a new session."})
    except ValueError as exc:
        return ai_settings_result({"error": str(exc)}, 400)


@app.post("/api/ai/chat-model", dependencies=[Depends(local_ai_settings)])
async def api_ai_chat_model(body: dict):
    await ensure_chat_router()
    item_id, model = body.get("item_id"), body.get("model", "")
    if not isinstance(item_id, str) or not 1 <= len(item_id) <= 200 or not isinstance(model, str):
        return ai_settings_result({"error": "Choose a chat and a model"}, 400)
    if item_id in chat_router.active_items():
        return ai_settings_result({"error": "Finish this turn before changing the model"}, 409)
    model = model.strip()
    try:
        if model:
            selected = chat_router._sessions.connection(item_id)
            if selected == "legacy:cursor":
                raise ValueError("Choose a model after switching this chat to a connection")
            current = chat_router._sessions.model(item_id)
            if selected == "legacy:claude":
                await validate_model("anthropic", model, "legacy:claude", current)
            else:
                await validate_model(ai_connections.get(selected, connected=False)["provider"], model, selected, current)
        chat_router._sessions.set_model(item_id, model)
        return ai_settings_result({"ok": True, "model": model})
    except ValueError as exc:
        return ai_settings_result({"error": str(exc)}, 400)


async def validate_claude_task_model(task_id: str, harness: str, model: str) -> None:
    """Cursor model names must not reach Claude: a new Claude pick has to be in Claude Code's own list."""
    if harness == CLAUDE_HARNESS and model:
        existing = runner.get_state(task_id) if runner else None
        await validate_model("anthropic", model, "legacy:claude", (existing or {}).get("claude_model", ""))


@app.post("/api/ai/operations", dependencies=[Depends(local_ai_settings)])
async def api_ai_operation(body: dict):
    key, operation = body.get("id"), body.get("operation")
    try:
        if operation == "install":
            if key not in ai_runtime.RUNTIMES:
                raise ValueError("Unknown runtime")
            if any(ai_backend.ACTIVE_CONNECTIONS.values()):
                raise ValueError("Wait for current AI turns to finish before repairing a runtime")
        elif operation in {"test", "login"}:
            connection = ai_connections.get(key)
            key = connection["id"]
            if operation == "login" and connection["auth"] == "system":
                raise ValueError("This connection uses your own Claude Code sign-in; run `claude` in a terminal to sign in")
            if operation == "login" and (ai_backend.ACTIVE_CONNECTIONS[key] or connection_affected(key)["pending_approvals"]):
                raise ValueError("Finish current turns and pending approvals before signing this account in again")
            if operation == "login" and connection["provider"] == "openai" and any(
                job.get("operation") == "login" and job.get("status") == "running"
                and ai_connections.get(other)["provider"] == "openai" for other, job in ai_settings.jobs.items()
            ):
                raise ValueError("Finish the other OpenAI sign-in before starting this one")
        else:
            raise ValueError("Unknown operation")
        if key in ai_settings.job_tasks and not ai_settings.job_tasks[key].done():
            return ai_settings_result({"error": "This operation is already running"}, 409)
        if operation == "install":
            ai_runtime.INSTALLING.add(key)
        elif operation == "login":
            ai_connections.update(key, tested=False)
        ai_settings.jobs[key] = {"status": "running", "operation": operation, "run_id": uuid.uuid4().hex}
        ai_settings.job_tasks[key] = asyncio.create_task(ai_settings.run_operation(key, operation))
        return ai_settings_result({"status": "running"}, 202)
    except ValueError as exc:
        return ai_settings_result({"error": str(exc)}, 400)


@app.post("/api/ai/operations/{key}/cancel", dependencies=[Depends(local_ai_settings)])
async def api_ai_cancel_test(key: str, body: dict):
    job = ai_settings.jobs.get(key)
    if not job or job["operation"] != "test":
        return ai_settings_result({"error": "Only connection tests can be cancelled"}, 409)
    if job.get("run_id") != body.get("run_id"):
        return ai_settings_result({"error": "This test has been replaced"}, 409)
    if job["status"] == "running":
        task = ai_settings.job_tasks[key]
        if not job.get("cancelling"):
            job["cancelling"] = True
            if job.get("started"):
                task.cancel()
        # A disconnected caller must not interrupt cleanup.
        await asyncio.wait({task})
    return ai_settings_result({"ok": True})


@app.post("/api/ai/terminal", dependencies=[Depends(local_ai_settings)])
async def api_ai_terminal(body: dict):
    runtime = body.get("id")
    if runtime not in ("claude", "pi"):
        return ai_settings_result({"error": "Unknown AI software"}, 400)
    if sys.platform != "darwin":
        return ai_settings_result({"error": "Opening Terminal is available on macOS"}, 400)
    binary = await asyncio.to_thread(ai_runtime.find, runtime)
    if not binary:
        return ai_settings_result({"error": "Install this AI software first"}, 400)
    if runtime in ai_runtime.INSTALLING:
        return ai_settings_result({"error": "Wait for installation to finish"}, 409)
    # Pass shell-quoted paths as data to a fixed AppleScript; never inject account credentials.
    command = f"cd -- {shlex.quote(str(paths.WORKSPACE))} && exec {shlex.quote(binary)}"
    script = '\n'.join(['on run argv', 'tell application "Terminal"', 'activate',
                        'do script (item 1 of argv)', 'end tell', 'return "opened"', 'end run'])
    result = await ai_settings.command_output("/usr/bin/osascript", "-e", script, command)
    if result.strip() != "opened":
        return ai_settings_result({"error": "Could not open Terminal; check macOS automation permissions and try again"}, 400)
    return ai_settings_result({"ok": True})


@app.post("/api/ai/connections/{connection_id}/change", dependencies=[Depends(local_ai_settings)])
async def api_ai_change(connection_id: str, body: dict):
    affected = connection_affected(connection_id)
    if (ai_backend.ACTIVE_CONNECTIONS[connection_id] or affected["pending_approvals"] or
            ai_settings.jobs.get(connection_id, {}).get("status") == "running"):
        return ai_settings_result({"error": "Finish current turns, setup operations and pending approvals before changing this connection"}, 409)
    try:
        changed = ai_connections.change(connection_id, body)
        ai_settings.jobs.pop(connection_id, None)
        return ai_settings_result(changed)
    except ValueError as exc:
        return ai_settings_result({"error": str(exc)}, 400)
    except Exception:
        return ai_settings_result({"error": "Could not update the OS credential store; unlock it and retry"}, 400)


@app.post("/api/ai/connections/{connection_id}/disconnect", dependencies=[Depends(local_ai_settings)])
async def api_ai_disconnect(connection_id: str):
    if ai_backend.ACTIVE_CONNECTIONS[connection_id] or ai_settings.jobs.get(connection_id, {}).get("status") == "running":
        return ai_settings_result({"error": "Wait for this account's current turn or setup operation to finish"}, 409)
    try:
        connection = ai_connections.get(connection_id, connected=False)
        affected = connection_affected(connection_id)
        if connection["auth"] == "api_key":
            ai_connections._vault().delete_password("Roosta AI", connection["credential_ref"])
        if connection["auth"] == "cli":
            binary = ai_runtime.find(ai_connections.engine(connection["provider"]))
            if not binary:
                raise ValueError("Repair the runtime before signing this account out")
            ai_connections.update(connection_id, connected=False, tested=False)
            env = ai_backend.connection_env(connection)
            args = [binary, "auth", "logout"] + (["openai"] if connection["provider"] == "openai" else [])
            proc = await asyncio.create_subprocess_exec(*args, env=env, cwd=env["PI_CODING_AGENT_DIR"],
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            try:
                await asyncio.wait_for(proc.wait(), 20)
                if proc.returncode:
                    raise ValueError("The account could not sign out; retry")
            finally:
                await ai_backend.terminate(proc)
        ai_connections.update(connection_id, connected=False, tested=False)
        ai_settings.jobs.pop(connection_id, None)
        return ai_settings_result({"ok": True, "affected": affected})
    except ValueError as exc:
        return ai_settings_result({"error": str(exc)}, 400)
    except Exception:
        return ai_settings_result({"error": "The credential store could not remove this key; unlock it and retry"}, 400)


@app.get("/api/runtime-options")
async def api_runtime_options():
    return JSONResponse(await available_runtime_options())


@app.get("/api/tasks/{task_id}")
async def api_task(task_id: str):
    state = runner.get_state(task_id)
    if not state:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(state)


@app.get("/api/tasks/{task_id}/skill")
async def api_task_skill(task_id: str):
    """Preview a configured worker's skill using the runner's lookup order."""
    task = load_tasks_map().get(task_id)
    if task is None:
        return JSONResponse({"error": "Worker not found"}, status_code=404)
    return skill_preview(task.skill, task.dir)


def skill_preview(skill: str, working_dir) -> JSONResponse:
    files = skill_files(skill, working_dir)
    if not files:
        return JSONResponse({"error": "SKILL.md not found"}, status_code=404)
    candidate = files[0]
    try:
        _, content, _ = read_document(candidate.parent.parent, f"{skill}/SKILL.md")
    except (OSError, ValueError):
        return JSONResponse({"error": "SKILL.md could not be previewed; it must be UTF-8 Markdown within its skill root and under 2 MB"}, status_code=400)
    return JSONResponse({"skill": skill, "content": content}, headers={"Cache-Control": "no-store"})


@app.get("/api/skills/unscheduled")
async def api_unscheduled_skills():
    """Workspace skills that no worker runs yet, so the Workers page can offer to schedule them."""
    tasks = load_tasks_map().values()
    skills = await asyncio.to_thread(unscheduled_skills, tasks)
    return JSONResponse({"skills": skills}, headers={"Cache-Control": "no-store"})


@app.get("/api/skills/{skill}/skill")
async def api_workspace_skill(skill: str):
    """Preview one of the workspace's own skills; global and unknown names are refused."""
    if skill not in await asyncio.to_thread(workspace_skills):
        return JSONResponse({"error": "Skill not found in this workspace"}, status_code=404)
    return skill_preview(skill, paths.WORKSPACE)


@app.post("/api/tasks/{task_id}/runtime")
async def api_task_runtime(task_id: str, body: dict):
    """Persist the harness and model used by this task's future runs."""
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid request"}, status_code=400)
    harness = str(body.get("harness", "")).strip()
    model = str(body.get("model", "")).strip()
    if not valid_runtime(harness, model):
        return JSONResponse({"error": "invalid harness or model"}, status_code=400)
    try:
        await validate_claude_task_model(task_id, harness, model)
        state = runner.set_runtime(task_id, harness, model)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if state is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(state)


@app.post("/api/tasks/{task_id}/settings")
async def api_task_settings(task_id: str, body: dict, request: Request = None):
    """Persist a task's name, nickname, description, schedule, harness and model."""
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid request"}, status_code=400)
    if "connection" in body and request is not None:
        local_ai_settings(request)
    try:
        await validate_claude_task_model(task_id, str(body.get("harness", "") or "").strip(),
                                         str(body.get("model", "") or "").strip())
        if isinstance(body.get("connection_model"), str) and body["connection_model"].strip():
            existing = runner.get_state(task_id)
            chosen = body["connection"] if isinstance(body.get("connection"), str) else (existing or {}).get("connection", "")
            if existing and chosen:
                connection = ai_connections.get("" if chosen == "default" else chosen, connected=False)
                current = (existing.get("claude_model") if connection["provider"] == "anthropic" else existing.get("model")) or ""
                await validate_model(connection["provider"], body["connection_model"].strip(), connection["id"], current)
        state = runner.set_settings(task_id, body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if state is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(state)


@app.delete("/api/tasks/{task_id}")
async def api_task_delete(task_id: str):
    """Fire a worker: remove it from tasks.yaml with its caches, state and 1:1 chat.
    Its skill and anything it wrote to the vault stay."""
    try:
        removed = runner.remove(task_id)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if not removed:
        return JSONResponse({"error": "not found"}, status_code=404)
    if chat_router is not None:
        chat_router.forget(f"{WORKER_CHAT_PREFIX}{task_id}")
        attachments.remove(UPLOADS_DIR, f"{WORKER_CHAT_PREFIX}{task_id}")
    return JSONResponse({"removed": True})


@app.post("/api/tasks/{task_id}/run")
async def api_task_run(task_id: str):
    """Trigger an immediate run of a task, bypassing its interval gate."""
    if not runner.trigger(task_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"triggered": True})


@app.post("/api/tasks/{task_id}/cancel")
async def api_task_cancel(task_id: str):
    """Drop a queued manual run before it starts."""
    if task_id not in runner._states:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not runner.cancel_queued(task_id):
        return JSONResponse({"error": "not queued"}, status_code=409)
    return JSONResponse({"cancelled": True})


@app.get("/api/activity")
async def api_activity(limit: int = 50):
    """Recent AI spawns (newest last). Snapshot for first paint / no-SSE clients."""
    return JSONResponse(activity.recent(limit))


@app.post("/api/usage")
async def api_usage(body: dict):
    """Record coarse local product interactions without content or item identifiers."""
    try:
        product_usage.record(body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"recorded": True})


@app.get("/api/activity/stream")
async def api_activity_stream():
    """Live SSE feed of every AI spawn: replays recent, then streams changes."""
    q = activity.subscribe()

    async def gen():
        try:
            for entry in activity.recent(50):
                yield f"data: {json.dumps(entry)}\n\n"
            while True:
                entry = await q.get()
                yield f"data: {json.dumps(entry)}\n\n"
        finally:
            activity.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/activity/{activity_id}")
async def api_activity_entry(activity_id: str):
    entry = activity.get(activity_id)
    if entry is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(entry)


@app.get("/api/activity/{activity_id}/transcript")
async def api_activity_transcript(activity_id: str):
    entry = activity.get(activity_id)
    if entry is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    session_id = entry.get("session_id", "")
    if not valid_session_id(session_id):
        return JSONResponse({"error": "no session"}, status_code=404)
    if entry.get("connection_id"):
        directory = ai_connections.directory(entry["connection_id"])
        turns = (read_claude_transcript(session_id, directory / "claude/projects")
                 if entry.get("backend") == ai_backend.CLAUDE else pi_agent.read_transcript(directory / "pi", session_id))
        resume = "Continue this conversation in Roosta using its original connection"
    elif entry.get("backend") == ai_backend.CLAUDE or claude_session_exists(session_id):
        turns = read_claude_transcript(session_id)
        resume = f"cd {shlex.quote(str(paths.WORKSPACE))} && claude --resume {session_id}"
    else:
        turns = read_cursor_transcript(session_id)
        resume = (
            f"CURSOR_CONFIG_DIR={CACHE_DIR / 'cursor-agent-config'} "
            f"agent --resume {session_id}"
        )
    return JSONResponse({
        "activity_id": activity_id,
        "session_id": session_id,
        "turns": turns,
        "outcome": entry.get("summary") or transcript_outcome(turns),
        "resume_command": resume,
    })


def transcript_outcome(turns: list[dict]) -> str:
    """The <task-output> summary from a run's last assistant turn, for rows logged before outcomes were."""
    for turn in reversed(turns):
        if turn.get("role") == "assistant" and "<task-output>" in turn.get("text", ""):
            return outcome_summary(parse_task_output(turn["text"]), "")
    return ""


@app.get("/")
async def index(request: Request):
    """The Assistant is the landing page; a ?task= deep link still opens the Skill runner."""
    if request.url.query:
        return RedirectResponse(f"/runner?{request.url.query}", status_code=307)
    return RedirectResponse("/assistant", status_code=307)


# --- Custom pages (see pages.py) ---


def vault_files(pattern: str, root: Path | None = None) -> list[dict]:
    """Workspace Markdown matching a glob, with titles and frontmatter but no bodies."""
    root = (root or paths.WORKSPACE).resolve()
    if not pattern or pattern.startswith("/") or ".." in pattern.split("/") or len(pattern) > 200:
        raise ValueError("invalid pattern")
    out = []
    for path in sorted(root.glob(pattern)):
        try:
            relative = path.relative_to(root).as_posix()
            resolved = resolve_vault_markdown(relative, root)
        except (ValueError, FileNotFoundError):
            continue
        if not workspace_visible(Path(relative)):
            continue
        text = resolved.read_text(encoding="utf-8", errors="ignore")
        out.append({
            "path": relative,
            "title": markdown_title(text, path.stem),
            "frontmatter": workspace_metadata(text),
            "modified": datetime.fromtimestamp(resolved.stat().st_mtime, timezone.utc).isoformat(),
        })
        if len(out) >= pages.PAGE_FILES_LIMIT:
            break
    return out


@app.get("/api/pages")
async def api_pages():
    return JSONResponse(pages.custom_pages())


@app.get("/api/vault/files")
async def api_vault_files(glob: str = "**/*.md"):
    """Read-only: Markdown files matching a glob, with frontmatter, for custom pages."""
    try:
        files = await asyncio.to_thread(vault_files, glob)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(files, headers={"Cache-Control": "no-store"})


@app.get("/api/pages/{name}/data/{file}")
async def api_page_data(name: str, file: str):
    """JSON a scheduled skill wrote for a page, from .roosta/state/pages/<name>/<file>."""
    if not pages.PAGE_NAME.fullmatch(name) or not file.endswith(".json"):
        return JSONResponse({"error": "not found"}, status_code=404)
    target = pages.contained(pages.PAGE_DATA_DIR / name, file)
    if target is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target, media_type="application/json", headers={"Cache-Control": "no-store"})


@app.get("/pages/{name}/{asset:path}")
async def custom_page(name: str, asset: str = ""):
    if not pages.PAGE_NAME.fullmatch(name):
        return JSONResponse({"error": "not found"}, status_code=404)
    target = pages.contained(paths.PAGES_DIR / name, asset or "index.html")
    if target is None or target.suffix.lower() not in pages.PAGE_TYPES:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target, media_type=pages.PAGE_TYPES[target.suffix.lower()],
                        headers={"Cache-Control": "no-cache"})


@app.get("/pages/{name}")
async def custom_page_root(name: str):
    return RedirectResponse(f"/pages/{name}/")


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


@app.get("/api/office/cast")
async def api_office_cast():
    return JSONResponse(office_cast())


@app.get("/api/profile")
async def api_profile():
    """Who Roosta works for, from PROFILE.md, so pages can say their name."""
    return JSONResponse(profile.load().public())


CHAT_IDEAS_FILE = ASSISTANT_DIR / "chat-ideas.json"
CHAT_IDEA_KINDS = {"focus", "project", "tool", "remember", "build", "learn"}
CHAT_IDEAS_MAX = 8


def load_chat_ideas(path: Path | None = None) -> dict:
    """Starter prompts the `chat-ideas` skill wrote from this workspace, validated.

    The file is model-written, so anything malformed is dropped rather than shown: an idea
    is a non-empty one-line `text` (at most 240 characters) with an optional short `label`
    and a `kind` from CHAT_IDEA_KINDS. No usable ideas means the page keeps its built-in ones.
    """
    try:
        raw = json.loads((path or CHAT_IDEAS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ideas": [], "generated": None}
    entries = raw.get("ideas") if isinstance(raw, dict) else None
    ideas, seen = [], set()
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, str):
            entry = {"text": entry}
        if not isinstance(entry, dict):
            continue
        text = " ".join(str(entry.get("text") or "").split())
        if not text or len(text) > 240 or text.lower() in seen:
            continue
        seen.add(text.lower())
        label = " ".join(str(entry.get("label") or "").split())[:40]
        kind = str(entry.get("kind") or "").strip().lower()
        ideas.append({"text": text, "label": label, "kind": kind if kind in CHAT_IDEA_KINDS else ""})
        if len(ideas) == CHAT_IDEAS_MAX:
            break
    generated = raw.get("generated") if isinstance(raw, dict) else None
    return {"ideas": ideas, "generated": generated if isinstance(generated, str) and ideas else None}


@app.get("/api/chat-ideas")
async def api_chat_ideas():
    """Workspace-specific ideas for a new chat; an empty list means use the page's own."""
    return JSONResponse(load_chat_ideas(), headers={"Cache-Control": "no-store"})


@app.get("/runner")
async def runner_page():
    return FileResponse(pages.page_file("index"))


def archived_chats(*, strict: bool = False) -> dict:
    try:
        data = json.loads(ARCHIVED_CHATS_FILE.read_text())
        if not isinstance(data, dict):
            raise ValueError("Invalid chat archive")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if strict:  # Never replace an unreadable archive with a partial one.
            raise
        return {}


@app.get("/api/board")
async def api_board(threads: str = "", thread: Annotated[list[str] | None, Query()] = None):
    """Cached conductor output for the rail + done-today, plus agent health.

    Handled items (AI-solved or user-closed) are filtered out of the rail
    immediately and surfaced as done_today, so a resolved item disappears
    without waiting for the next conductor pass.
    """
    state = runner.get_state("assistant")
    doc = normalise_board_doc((state or {}).get("last_output", {}).get("details", {}))
    states = runner.get_states()
    reminders = chat_router.reminders() if chat_router else []
    doc["items"], later_reminders = collect_board_items(doc["items"], states, reminders, chat_router)
    handled = chat_router.handled() if chat_router else {}
    current_items = [i for i in doc["items"] if i["id"] not in handled]
    snoozed = chat_router.snoozed() if chat_router else {}
    doc["items"], doc["later"] = split_snoozed_items(current_items, snoozed)
    parked = {i["id"] for i in doc["later"]}
    doc["later"] = doc["later"] + [r for r in later_reminders
                                   if r["id"] not in parked and r["id"] not in handled]
    doc["later"].sort(key=lambda i: i.get("snoozed_until", ""))
    if chat_router:
        track_ids = [
            item["id"] for item in doc["items"] + doc["later"] if item.get("id")
        ]
        raised = chat_router.record_raised(track_ids)
        attach_raised_at(doc["items"], raised)
        attach_raised_at(doc["later"], raised)
    done = [{"text": v.get("result", ""), "at": v.get("at", "")}
            for v in sorted(handled.values(), key=lambda v: v.get("at", ""), reverse=True)]
    doc["done_today"] = done + doc.get("done_today", [])
    doc["closed"] = recently_closed(handled, chat_router)
    conversation_ids = [
        item["id"] for item in doc["items"] + doc["later"]
    ] + standing_thread_ids(threads, thread)
    histories = (chat_router.conversation_histories() if chat_router else
                 ConversationHistoryStore(CHAT_HISTORY_FILE).read_all())
    topics = TopicStore(TOPICS_FILE)._read()
    chat_histories = {
        item_id: history
        for item_id in conversation_ids
        if (history := histories.get(item_id))
    }
    return JSONResponse({
        "status": (state or {}).get("status", "idle"),
        "last_run": (state or {}).get("last_run", ""),
        "agent_up": agent.alive,
        "ai_backend": ai_backend.label(),
        "health": {**board_health(states), "restart_pending": restart_pending()},
        "chat_progress": chat_router.active_progress if chat_router else {},
        "active_chat_ids": chat_router.active_items() if chat_router else [],
        "chat_histories": chat_histories,
        "chat_contexts": {
            key: {"boundaries": record.get("boundaries", []), "refreshed_at": record.get("refreshed_at")}
            for key in conversation_ids if isinstance(record := topics.get(key), dict)
            and (record.get("boundaries") or record.get("refreshed_at"))
        },
        "chats": chat_list(histories, archived_chats()),
        "pending_approvals": chat_router.pending_approvals() if chat_router else {},
        "document": doc,
    })


@app.get("/api/board/count")
async def api_board_count():
    """Rail item count for the nav badge; mirrors api_board's filtering without its side effects."""
    state = runner.get_state("assistant")
    doc = normalise_board_doc((state or {}).get("last_output", {}).get("details", {}))
    reminders = chat_router.reminders() if chat_router else []
    items, _ = collect_board_items(doc["items"], runner.get_states(), reminders, chat_router)
    handled = chat_router.handled() if chat_router else {}
    snoozed = chat_router.snoozed() if chat_router else {}
    items, later = split_snoozed_items([i for i in items if i["id"] not in handled], snoozed)
    today = datetime.now(timezone.utc).date().isoformat()
    # notes/later/done feed the Office whiteboard kanban
    notes = [{"title": i.get("title", ""), "owner": i.get("action_owner", "assistant"),
              "type": i.get("action_type", ""), "new": bool(i.get("new"))} for i in items]
    return JSONResponse({"items": len(items), "notes": notes, "later": len(later),
                         "done": sum(str(v.get("at", "")).startswith(today) for v in handled.values())})


@app.post("/api/board/refresh")
async def api_board_refresh():
    if not runner.trigger("assistant"):
        return JSONResponse({"error": "conductor task not configured"}, status_code=404)
    return JSONResponse({"triggered": True})


@app.post("/api/notify")
async def api_notify(body: dict):
    """Let a skill push a notification straight onto the board.

    Minimal shape: {title, body?, id?, url?, due?}. It becomes a board item with
    new=true, so the desktop notifier fires it (deduped by id) and the board
    shows it on its next poll. Closing it on the board removes it.

    With a `due` (ISO-8601, timezone-aware, in the future), it is instead saved
    as a durable, file-backed reminder that survives a restart and only surfaces
    when due - so a one-line curl can schedule a reminder, not just ping now.
    """
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid request"}, status_code=400)
    title = str(body.get("title", "")).strip()[:120]
    if not title:
        return JSONResponse({"error": "need title"}, status_code=400)
    if body.get("due") is not None:
        due = normalise_defer_until(body.get("due"))
        if due is None:
            return JSONResponse({"error": "invalid due time"}, status_code=400)
        if chat_router is None:
            return JSONResponse({"error": "reminders unavailable"}, status_code=503)
        reminder_id = chat_router.add_reminder(
            title, str(body.get("body", "")).strip(), due)
        return JSONResponse({"ok": True, "id": reminder_id, "due": due})
    item_id = str(body.get("id") or f"notify-{uuid.uuid4().hex[:8]}")
    url = str(body.get("url", "")).strip()
    links = [{"label": str(body.get("label", "Open"))[:40], "url": url}] \
        if url.startswith("http") else []
    item = {
        "id": item_id, "project_ref": None, "title": title,
        "why": clip_body(body.get("body", "")),
        "situation": str(body.get("situation", "")).strip(),
        "opening_move": str(body.get("opening_move", "Take a look")).strip()[:200],
        "action_owner": "user", "action_label": "Review",
        "action_type": str(body.get("action_type", "task"))[:20],
        "links": links, "new": True,
    }
    push_notification(item)
    return JSONResponse({"ok": True, "id": item_id})


def _current_board_item(item_id: str) -> dict | None:
    """Resolve one visible board item across all sources, or None."""
    state = runner.get_state("assistant")
    doc = normalise_board_doc((state or {}).get("last_output", {}).get("details", {}))
    active, later = collect_board_items(
        doc["items"], runner.get_states(),
        chat_router.reminders() if chat_router else [], chat_router)
    return next((i for i in active + later if i["id"] == item_id), None)


@app.post("/api/board/close")
async def api_board_close(body: dict):
    """Explicitly close an item (the user's call). Drops it from the rail now and
    the conductor suppresses it next pass. A snapshot of the item is stored so
    it can be reviewed and revived from the Recently closed list."""
    if chat_router is None and not await ensure_chat_router():
        return chat_unavailable()
    if not isinstance(body, dict) or "item_id" not in body:
        return JSONResponse({"error": "need item_id"}, status_code=400)
    item_id = str(body["item_id"])
    snapshot = _current_board_item(item_id) or chat_router.known_item(item_id)
    chat_router.mark_handled(item_id, str(body.get("result", "Closed by " + profile.load().user)), snapshot)
    return JSONResponse({"closed": True})


@app.post("/api/board/reopen")
async def api_board_reopen(body: dict):
    """Revive a recently closed item. Drops it from the handled store and, using
    its stored snapshot, pushes it back onto the rail under its original id so the
    conversation thread is preserved. If the conductor still produces it, the
    un-handle alone suffices and the pushed copy is skipped as a duplicate."""
    if chat_router is None and not await ensure_chat_router():
        return chat_unavailable()
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid request"}, status_code=400)
    item_id = str(body.get("item_id", "")).strip()
    if not item_id or len(item_id) > 200:
        return JSONResponse({"error": "need valid item_id"}, status_code=400)
    if item_id not in chat_router.handled():
        return JSONResponse({"error": "item not closed"}, status_code=404)
    snapshot = chat_router.unhandle(item_id)
    if snapshot:
        item = normalise_board_doc({"items": [{**snapshot, "id": item_id}]})["items"][0]
        item["title"] = item["title"] or "Reopened item"
        item["opening_move"] = item["opening_move"] or "Take a look"
        item["new"] = True
        push_notification(item)
    return JSONResponse({"reopened": True, "restored": bool(snapshot)})


@app.post("/api/board/snooze")
async def api_board_snooze(body: dict):
    """Park a current item until an allowlisted future point."""
    if chat_router is None and not await ensure_chat_router():
        return chat_unavailable()
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid request"}, status_code=400)
    item_id = str(body.get("item_id", "")).strip()
    preset = str(body.get("preset", "")).strip()
    if not item_id or len(item_id) > 200:
        return JSONResponse({"error": "need valid item_id"}, status_code=400)
    try:
        until = snooze_deadline(preset)
    except ValueError:
        return JSONResponse({"error": "unknown snooze preset"}, status_code=400)
    state = runner.get_state("assistant")
    doc = normalise_board_doc((state or {}).get("last_output", {}).get("details", {}))
    current_items, _ = collect_board_items(
        doc["items"], runner.get_states(), chat_router.reminders(), chat_router)
    handled = chat_router.handled()
    current_items = [item for item in current_items if item["id"] not in handled]
    active_items, _ = split_snoozed_items(current_items, chat_router.snoozed())
    if not any(item["id"] == item_id for item in active_items):
        return JSONResponse({"error": "item not found"}, status_code=404)
    chat_router.snooze(item_id, until)
    return JSONResponse({"snoozed": True, "until": until})


@app.post("/api/board/unsnooze")
async def api_board_unsnooze(body: dict):
    """Bring a parked item back into the active queue now."""
    if chat_router is None and not await ensure_chat_router():
        return chat_unavailable()
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid request"}, status_code=400)
    item_id = str(body.get("item_id", "")).strip()
    if not item_id or len(item_id) > 200:
        return JSONResponse({"error": "need valid item_id"}, status_code=400)
    chat_router.unsnooze(item_id)
    return JSONResponse({"unsnoozed": True})


@app.post("/api/board/chat")
async def api_board_chat(body: dict):
    if chat_router is None and not await ensure_chat_router():
        return chat_unavailable()
    if not isinstance(body, dict) or "item_id" not in body:
        return JSONResponse({"error": "need item_id"}, status_code=400)
    item_id = str(body["item_id"])
    if item_id == AI_SETUP_ITEM_ID or (
        (setup_item(chat_router) or {}).get("id") == AI_SETUP_ITEM_ID
        and (item_id == SETUP_ITEM_ID or not chat_router._sessions.get(item_id))
    ):
        return JSONResponse({"error": "Choose a default AI account in Settings and finish its software and model setup.",
                             "settings_url": "/settings#account-setup"}, status_code=503)
    if is_general_chat_id(item_id):
        item = {**GENERAL_CHAT_ITEM, "id": item_id}
    elif item_id.startswith(DOCUMENT_CHAT_PREFIX):
        # Likewise a document thread is opened from the viewer, not the rail.
        item = document_chat_item(item_id)
        if item is None:
            return JSONResponse({"error": "document not found"}, status_code=404)
    elif item_id.startswith(WORKER_CHAT_PREFIX):
        # A 1:1 with a worker, opened from its Office dossier or its Workers row.
        item = worker_chat_item(item_id, load_tasks_map(),
                                runner.get_state(item_id[len(WORKER_CHAT_PREFIX):]),
                                activity.recent(ActivityLog.MAX))
        if item is None:
            return JSONResponse({"error": "worker not found"}, status_code=404)
    elif item_id.startswith(HIRE_CHAT_PREFIX):
        # New worker on the Workers page: design a skill and put it on the schedule.
        item = hire_chat_item(item_id)
        if item is None:
            return JSONResponse({"error": "invalid chat id"}, status_code=404)
    else:
        state = runner.get_state("assistant")
        doc = normalise_board_doc((state or {}).get("last_output", {}).get("details", {}))
        active, later = collect_board_items(
            doc["items"], runner.get_states(), chat_router.reminders(), chat_router)
        item = next((i for i in active + later if i["id"] == item_id), None)
        if item is None:
            # The conductor drops items it considers resolved, capped out or aged
            # off, but the user may still be mid-conversation about one. Continue the
            # existing thread rather than 404ing a live chat off the board.
            item = chat_router.known_item(item_id)
        if item is None:
            return JSONResponse({"error": "item not found"}, status_code=404)

    if "context_paths" in body:
        try:
            documents = await asyncio.to_thread(context_documents, paths.WORKSPACE, body["context_paths"])
        except (OSError, UnicodeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        item = {**item, "context_documents": documents}
    if "uploads" in body:
        try:
            files = await asyncio.to_thread(attachments.describe, UPLOADS_DIR, item_id, body["uploads"])
        except FileNotFoundError:
            return JSONResponse({"error": "Attachment not found. Add it again."}, status_code=400)
        except (OSError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if files:
            vault = paths.WORKSPACE.resolve()
            item = {**item, "uploaded_files": [
                {**{key: file[key] for key in ("id", "name", "size", "image")},
                 "path": Path(file["path"]).relative_to(vault).as_posix()
                         if Path(file["path"]).is_relative_to(vault) else file["path"]}
                for file in files]}
    handle = chat_router.start_turn(item["id"], item, str(body.get("message", "")))
    if handle.queued:
        return JSONResponse({"queued": True, "position": handle.position}, status_code=202)

    events = handle.events
    if events is None:
        return JSONResponse({"error": "chat could not start"}, status_code=500)

    async def gen():
        while True:
            ev = await events.get()
            yield f"data: {json.dumps(ev)}\n\n"
            if ev.get("kind") == "_close":
                break

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/board/chat/upload", dependencies=[Depends(same_origin_upload)])
async def api_board_chat_upload(request: Request, item_id: str = "", name: str = ""):
    """Store one raw-body file for a conversation; the chat send references it by id."""
    if not item_id or len(item_id) > attachments.MAX_ITEM_ID:
        return JSONResponse({"error": "need valid item_id"}, status_code=400)
    too_big = JSONResponse({"error": "File exceeds the 20 MB upload limit."}, status_code=413)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > attachments.MAX_UPLOAD_BYTES:
        return too_big
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > attachments.MAX_UPLOAD_BYTES:
            return too_big
    try:
        saved = await asyncio.to_thread(attachments.save, UPLOADS_DIR, item_id, name, bytes(data))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(saved)


@app.get("/api/board/chat/upload/{upload_id}")
async def api_board_chat_upload_get(upload_id: str, item_id: str = ""):
    """Serve an upload back: sniffed images inline, everything else as a download."""
    try:
        path = attachments.resolve(UPLOADS_DIR, item_id, upload_id)
    except ValueError:
        return JSONResponse({"error": "invalid attachment"}, status_code=400)
    except FileNotFoundError:
        return JSONResponse({"error": "attachment not found"}, status_code=404)
    with path.open("rb") as handle:
        kind = attachments.image_type(handle.read(16))
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    if kind:
        return FileResponse(path, media_type=kind, headers=headers)
    return FileResponse(path, media_type="application/octet-stream",
                        filename=path.name[len(upload_id) + 1:], headers=headers)


@app.post("/api/chats/context")
async def api_chat_context(body: dict):
    item_id, mode = body.get("item_id"), body.get("mode")
    revision, handoff = body.get("revision"), body.get("handoff", "")
    if (not isinstance(item_id, str) or not 0 < len(item_id) <= attachments.MAX_ITEM_ID
            or item_id.startswith(HIRE_CHAT_PREFIX) or item_id == AI_SETUP_ITEM_ID
            or mode not in ("preview", "fresh", "summary")
            or not isinstance(handoff, str) or len(handoff) > 8000
            or (mode == "summary" and not handoff.strip())
            or (mode != "preview" and not isinstance(revision, str))):
        return JSONResponse({"error": "Invalid conversation or handoff."}, status_code=400)
    if chat_router is None and not await ensure_chat_router():
        return chat_unavailable()
    try:
        result = chat_router.reset_context(item_id, mode, revision, handoff)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except (ValueError, OSError):
        return JSONResponse({"error": "Could not read or save the conversation."}, status_code=500)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/api/chats/archive")
async def api_chats_archive(body: dict):
    """Hide a chat from the Chats tab. History is kept; new activity brings it back."""
    item_id = str((body or {}).get("item_id", "")).strip() if isinstance(body, dict) else ""
    if not is_chat_id(item_id):
        return JSONResponse({"error": "need a chat id"}, status_code=400)
    if not ConversationHistoryStore(CHAT_HISTORY_FILE).read(item_id):
        return JSONResponse({"archived": False})
    title = body.get("title")
    save_chat_state(archived_chats(strict=True), item_id, {
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "title": title.strip()[:200] if isinstance(title, str) else "",
    })
    return JSONResponse({"archived": True})


def save_chat_state(archived: dict, item_id: str, record: dict) -> None:
    archived[item_id] = record
    ARCHIVED_CHATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=ARCHIVED_CHATS_FILE.parent, delete=False, mode="w") as temp:
        try:
            json.dump(archived, temp, indent=2)
            temp.close()
            Path(temp.name).replace(ARCHIVED_CHATS_FILE)
        finally:
            Path(temp.name).unlink(missing_ok=True)


@app.get("/api/chats/archived")
async def api_chats_archived():
    histories = ConversationHistoryStore(CHAT_HISTORY_FILE).read_all()
    return JSONResponse(chat_list(histories, archived_chats(strict=True), limit=50, closed=True),
                        headers={"Cache-Control": "no-store"})


@app.post("/api/chats/restore")
async def api_chats_restore(body: dict):
    item_id = str(body.get("item_id") or "").strip()
    if not is_chat_id(item_id):
        return JSONResponse({"error": "need a chat id"}, status_code=400)
    archived = archived_chats(strict=True)
    if item_id not in archived or not ConversationHistoryStore(CHAT_HISTORY_FILE).read(item_id):
        return JSONResponse({"error": "Chat is unavailable."}, status_code=404)
    save_chat_state(archived, item_id, {"restored_at": datetime.now(timezone.utc).isoformat()})
    return JSONResponse({"restored": True})


@app.post("/api/board/chat/{run_id}/approve")
async def api_board_approve(run_id: str, body: dict):
    if chat_router is None and not await ensure_chat_router():
        return chat_unavailable()
    approved = bool(body.get("approved")) if isinstance(body, dict) else False
    edit = body.get("edit") if isinstance(body, dict) else None
    result = await chat_router.approve(run_id, approved, edit)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.get("/api/vault-document")
async def api_vault_document(path: str = ""):
    """Return one validated vault document (Markdown, or plain text as source)."""
    try:
        document = resolve_vault_text(path)
    except ValueError:
        return JSONResponse({"error": "invalid document path"}, status_code=400)
    except FileNotFoundError:
        return JSONResponse({"error": "document not found"}, status_code=404)
    if document.stat().st_size > 2 * 1024 * 1024:
        return JSONResponse({"error": "document is too large"}, status_code=413)
    try:
        content = document.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return JSONResponse({"error": "document is not UTF-8"}, status_code=415)
    relative = document.relative_to(paths.WORKSPACE.resolve()).as_posix()
    if document.suffix.lower() in VAULT_SOURCE_SUFFIXES:
        return JSONResponse({
            "path": relative, "title": document.name,
            "content": source_as_markdown(content, document.suffix), "properties": [],
        })
    title = markdown_title(content, document.stem)
    body, properties = split_front_matter(content)
    return JSONResponse({
        "path": relative, "title": title, "content": body, "properties": properties,
    })


def split_front_matter(content: str) -> tuple[str, list[list[str]]]:
    """Separate YAML front matter from a Markdown body as display-ready pairs.

    Marked would otherwise render the block as a rule plus a setext heading.
    """
    match = re.match(r"\A---\s*\n(.*?)\n---[ \t]*(?:\n|\Z)", content, re.DOTALL)
    if not match:
        return content, []
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return content, []
    if not isinstance(metadata, dict):
        return content, []
    properties = []
    for key, value in metadata.items():
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if not isinstance(v, (dict, list)))
        elif isinstance(value, dict) or value is None:
            continue
        if str(value).strip():
            properties.append([str(key), str(value)])
    return content[match.end():].lstrip("\n"), properties


def changelog_version(text: str) -> str:
    """The version is the first `## x.y.z` heading in CHANGELOG.md."""
    match = re.search(r"^## (\d+\.\d+\.\d+)\b", text, re.M)
    return match.group(1) if match else "0.0.0"


@app.get("/api/changelog")
async def api_changelog():
    try:
        text = (DASHBOARD_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        text = ""
    return {"version": changelog_version(text), "content": text}


_news_cache: dict = {"at": 0.0, "data": None}
_bamboozle_lock = asyncio.Lock()


@app.get("/api/news")
async def api_news():
    """Public BBC headlines for the Office lounge TV (Ceefax style), cached for 15 minutes."""
    if _news_cache["data"] is None or time.time() - _news_cache["at"] > teletext.NEWS_TTL:
        data = await asyncio.to_thread(teletext.fetch_news)
        if any(data["sections"].values()) or _news_cache["data"] is None:
            _news_cache.update(at=time.time(), data=data)
    return _news_cache["data"]


@app.get("/api/bamboozle")
async def api_bamboozle():
    """Today's Bamboozle! quiz for the Office lounge TV."""
    async with _bamboozle_lock:  # one fetch per day even if several tabs ask at once
        quiz = await asyncio.to_thread(teletext.daily_quiz, datetime.now().date().isoformat())
    if not quiz:
        return JSONResponse({"error": "not in transmission"}, status_code=503)
    return quiz


@app.get("/changelog")
async def changelog_page():
    return FileResponse(pages.page_file("changelog"))


@app.get("/settings")
async def settings_page():
    return FileResponse(pages.page_file("settings"))


@app.get("/document")
async def document_page():
    return FileResponse(pages.page_file("document"))


@app.get("/workspace")
async def workspace_page():
    return FileResponse(pages.page_file("workspace"))


@app.get("/api/workspace")
async def api_workspace():
    return JSONResponse(await asyncio.to_thread(build_catalogue, paths.WORKSPACE),
                        headers={"Cache-Control": "no-store"})


def file_browser_command(folder: Path) -> list[str] | None:
    if sys.platform == "darwin":
        return ["open", str(folder)]
    if sys.platform == "win32":
        return ["explorer", str(folder)]
    return ["xdg-open", str(folder)] if shutil.which("xdg-open") else None


def launch_detached(command: list[str]) -> None:
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


@app.post("/api/workspace/reveal", dependencies=[Depends(local_ai_settings)])
async def api_workspace_reveal():
    """Open the active workspace in this computer's file browser."""
    command = file_browser_command(paths.WORKSPACE)
    if not command:
        return JSONResponse({"error": "No file browser is available on this computer."}, 400)
    # SECURITY-REVIEW: fixed binary and the runner's own workspace path; no request input.
    try:
        launch_detached(command)
    except OSError:
        return JSONResponse({"error": "Roosta could not open the workspace folder."}, 500)
    return {"opened": str(paths.WORKSPACE)}


@app.get("/assistant")
async def assistant_page():
    return FileResponse(pages.page_file("assistant"))


@app.get("/api/pulse")
async def api_pulse():
    """Live vault telemetry, AI activity and board mood for the Pulse page."""
    states = runner.get_states()
    health = board_health(states)
    handled = chat_router.handled() if chat_router else {}
    state = runner.get_state("assistant")
    doc = normalise_board_doc((state or {}).get("last_output", {}).get("details", {}))
    doc["items"] = merge_board_feed_items(doc["items"], states, board_merges(states, chat_router))
    doc["items"] = merge_pushed_notifications(doc["items"])
    reminders = chat_router.reminders() if chat_router else []
    due_reminders, later_reminders = split_due_reminders(reminders)
    have = {item["id"] for item in doc["items"]}
    doc["items"] = [item for item in due_reminders if item["id"] not in have] + doc["items"]
    current_items = [item for item in doc["items"] if item["id"] not in handled]
    snoozed = chat_router.snoozed() if chat_router else {}
    active_items, later_items = split_snoozed_items(current_items, snoozed)
    parked = {item["id"] for item in later_items}
    later_items = later_items + [
        item for item in later_reminders
        if item["id"] not in parked and item["id"] not in handled
    ]
    task_states = runner.get_states()
    chat_items = []
    if chat_router:
        for item_id in chat_router.active_items():
            known = chat_router.known_item(item_id)
            chat_items.append(known or {"id": item_id, "title": "Conversation"})
    return JSONResponse(build_pulse(
        paths.WORKSPACE,
        activity.recent(200),
        handled,
        len(active_items),
        len(later_items),
        health,
        task_states=task_states,
        running_activity=activity.running(),
        chat_items=chat_items,
        active_project_items=[
            {"id": item["id"], "title": item.get("title", ""), "project_ref": item["project_ref"]}
            for item in active_items if item.get("project_ref")
        ],
    ))


@app.get("/api/constellation/{slug}")
async def api_constellation_project(slug: str):
    """Briefing for one project star: README excerpts, provenance, links, recent files."""
    try:
        return JSONResponse(await asyncio.to_thread(project_brief, paths.WORKSPACE, slug),
                            headers={"Cache-Control": "no-store"})
    except ValueError:
        return JSONResponse({"error": "invalid project"}, status_code=400)
    except FileNotFoundError:
        return JSONResponse({"error": "project not found"}, status_code=404)


@app.post("/api/constellation/{slug}/review")
async def api_constellation_review(slug: str, body: dict):
    """Weekly-review decision: change status, or record the user's confirmation.

    A local vault write the user makes by clicking; it touches only the README
    frontmatter keys `status`, `last_updated`, `verified` and `stale_after`.
    """
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid request"}, status_code=400)
    try:
        brief = await asyncio.to_thread(
            review_project, paths.WORKSPACE, slug,
            str(body.get("action", "")), str(body.get("status", "")),
            reviewer=profile.load().reviewer,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except FileNotFoundError:
        return JSONResponse({"error": "project not found"}, status_code=404)
    return JSONResponse(brief)


@app.get("/office")
async def office_page():
    return FileResponse(pages.page_file("office"))


@app.get("/pulse")
async def pulse_page():
    return FileResponse(pages.page_file("pulse"))


@app.get("/constellation")
async def constellation_page():
    # Same page in full-screen mode; pulse.html switches layout on the path.
    return FileResponse(pages.page_file("pulse"))


# Mount static after routes so / doesn't get overridden
static_dir = DASHBOARD_ROOT / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


if __name__ == "__main__":
    from roosta.cli import main

    raise SystemExit(main(["start"]))
