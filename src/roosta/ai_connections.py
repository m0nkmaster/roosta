"""Named AI connections: non-secret metadata in the workspace, keys in the OS vault."""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path

from roosta import ai_runtime, paths

CONNECTIONS_FILE = paths.STATE_DIR / "ai-connections.json"
CONNECTIONS_DIR = paths.STATE_DIR / "ai-connections"
PROVIDERS = {
    "openai": {"label": "OpenAI", "billing": "OpenAI API (separate from ChatGPT subscriptions)",
               "key_url": "https://platform.openai.com/api-keys"},
    "anthropic": {"label": "Anthropic", "billing": "Anthropic API (separate from Claude subscriptions)",
                  "key_url": "https://platform.claude.com/settings/keys"},
    "openrouter": {"label": "OpenRouter", "billing": "OpenRouter API",
                   "key_url": "https://openrouter.ai/settings/keys"},
    "ollama": {"label": "Local (Ollama)", "billing": "Local inference · no API billing",
               "key_url": "https://ollama.com/download"},
    "cursor": {"label": "Cursor", "billing": "Your Cursor plan, through a Cursor API key",
               "key_url": "https://cursor.com/dashboard?tab=integrations"},
}


def engine(provider: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError("Invalid provider")
    return {"anthropic": "claude", "cursor": "cursor"}.get(provider, "pi")


def selected_model(provider: str) -> str:
    choice = load().get("model_choice", {})
    return choice.get("model", "") if choice.get("provider") == provider else ""


def selected_effort(provider: str, model: str) -> str:
    choice = load().get("model_choice", {})
    return choice.get("effort", "") if (choice.get("provider"), choice.get("model")) == (provider, model) else ""


def default_model(provider: str, *, general: bool = False) -> str:
    """The user's configured default, else the harness's own; "" means none is known."""
    chosen = selected_model(provider)
    if chosen:
        return chosen
    if provider == "anthropic":
        from roosta import claude_code
        return claude_code.claude_general_chat_model() if general else claude_code.claude_model()
    return ai_runtime.default_model(provider)


def load() -> dict:
    try:
        data = json.loads(CONNECTIONS_FILE.read_text())
    except FileNotFoundError:
        return {"default": "", "connections": []}
    except (OSError, ValueError) as exc:
        raise ValueError("AI connection settings cannot be read; restore the file before changing accounts") from exc
    if not isinstance(data, dict) or not isinstance(data.get("connections"), list):
        raise ValueError("Invalid AI connection settings")
    for connection in data["connections"]:
        if isinstance(connection, dict):
            connection.pop("model", None)
    return data


def save(data: dict) -> None:
    CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = CONNECTIONS_FILE.with_suffix(f".{uuid.uuid4().hex}.tmp")
    with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(data, output, indent=2)
    temporary.replace(CONNECTIONS_FILE)


def directory(connection_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", connection_id):
        raise ValueError("Invalid connection id")
    root = CONNECTIONS_DIR.resolve()
    destination = root / connection_id
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise ValueError("Invalid connection directory")
    return destination


def get(connection_id: str = "", *, connected: bool = True) -> dict:
    data = load()
    selected = data.get("default", "") if connection_id in ("", "default") else connection_id
    connection = next((c for c in data["connections"] if c.get("id") == selected), None)
    if connection is None:
        raise ValueError("Choose an AI connection in Settings")
    directory(connection["id"])
    if connected and not connection.get("connected"):
        raise ValueError(f"{connection['label']} is disconnected; reconnect it or choose a replacement in Settings")
    engine(connection["provider"])
    return dict(connection)


def runtime(provider: str, model: str) -> str:
    """Format and policy checks for one model id; membership in the harness's own list is checked separately."""
    if provider not in PROVIDERS or not isinstance(model, str):
        raise ValueError("Invalid provider or model")
    if provider == "anthropic":
        from roosta.claude_code import is_claude_effort_only, is_claude_model
        if not (is_claude_model(model) or is_claude_effort_only(model)):
            raise ValueError("Choose a model supported by Claude Code")
        return "claude"
    if provider == "cursor":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model):
            raise ValueError("Choose a model Cursor offers")
        return "cursor"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,119}", model):
        raise ValueError("Invalid provider or model")
    lower = model.lower()
    if provider == "openrouter":
        if lower.split("/", 1)[0].lstrip("~") == "anthropic":
            raise ValueError("Anthropic models require an Anthropic connection through Claude Code; choose that connection explicitly")
        if lower.startswith("openrouter/"):
            raise ValueError("Choose an explicit model on OpenRouter; automatic model routing is not supported")
    return "pi"


def _vault():
    import keyring
    vault = keyring.get_keyring()
    # Refuse plaintext and null/fail fallbacks, including chained backends.
    if type(vault).__module__ not in {"keyring.backends.macOS", "keyring.backends.Windows",
                                     "keyring.backends.SecretService", "keyring.backends.kwallet"}:
        raise ValueError("An OS credential store is required (Keychain, Windows Credential Manager or Secret Service)")
    return vault


def credential(connection: dict) -> str:
    if connection["auth"] != "api_key":
        return ""
    secret = _vault().get_password("Roosta AI", connection["credential_ref"])
    if not secret:
        raise ValueError(f"{connection['label']} needs its API key; reconnect it in Settings")
    return secret


def create(body: dict) -> dict:
    provider = body.get("provider")
    if provider not in PROVIDERS:
        raise ValueError("Choose OpenAI, Anthropic, OpenRouter, Cursor or local Ollama")
    label = body.get("label") or PROVIDERS[provider]["label"]
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        raise ValueError("Connection name must be 1–80 characters")
    auth = body.get("auth", "local" if provider == "ollama" else "api_key")
    allowed = ({"cli", "api_key", "system"} if provider == "anthropic" else
               {"cli", "api_key"} if provider == "openai" else
               {"local"} if provider == "ollama" else {"api_key"})
    if auth not in allowed:
        raise ValueError("Unsupported authentication method")
    key = body.get("api_key", "")
    if auth == "api_key" and (not isinstance(key, str) or not 1 <= len(key.strip()) <= 4096 or any(c.isspace() for c in key.strip())):
        raise ValueError("Enter a valid API key")
    data = load()
    connection_id = uuid.uuid4().hex
    billing = PROVIDERS[provider]["billing"]
    if auth == "cli":
        billing = f"{'ChatGPT' if provider == 'openai' else 'Claude'} account · your organisation or subscription plan"
    elif auth == "system":
        billing = "Your Claude Code sign-in · your Claude plan"
    connection = {"id": connection_id, "label": label.strip(), "provider": provider,
                  "auth": auth, "credential_ref": uuid.uuid4().hex,
                  "billing": billing,
                  "connected": True, "tested": False}
    if auth == "api_key":
        _vault().set_password("Roosta AI", connection["credential_ref"], key.strip())
    data["connections"].append(connection)
    try:
        save(data)
    except Exception:
        if auth == "api_key":
            _vault().delete_password("Roosta AI", connection["credential_ref"])
        raise
    return connection


async def offer_system() -> dict | None:
    """Offer the user's own Claude Code sign-in once, when a compatible Claude is installed."""
    data = load()
    if data.get("system_offered") or any(c.get("auth") == "system" for c in data["connections"]):
        return None
    if not await asyncio.to_thread(ai_runtime.find, "claude"):
        return None
    # Detection can overlap an explicit account choice or another Settings request.
    data = load()
    if data.get("system_offered") or any(c.get("auth") == "system" for c in data["connections"]):
        return None
    connection = {"id": uuid.uuid4().hex, "label": "Claude Code", "provider": "anthropic",
                  "auth": "system", "credential_ref": uuid.uuid4().hex,
                  "billing": "Your Claude Code sign-in · your Claude plan",
                  "connected": True, "tested": False}
    data["system_offered"] = True
    data["connections"].append(connection)
    save(data)
    return connection


def update(connection_id: str, **changes) -> dict:
    data = load()
    connection = next((c for c in data["connections"] if c["id"] == connection_id), None)
    if connection is None:
        raise ValueError("Unknown connection")
    connection.update(changes)
    connection.pop("model", None)
    save(data)
    return dict(connection)


def set_default(connection_id: str, model: str | None = None, effort: str = "") -> None:
    connection = get(connection_id)
    data = load()
    data["default"] = connection["id"]
    if model is not None:
        data["model_choice"] = {"provider": connection["provider"], "model": model, "effort": effort}
    save(data)


def change(connection_id: str, body: dict) -> dict:
    connection = get(connection_id, connected=False)
    label = body.get("label", connection["label"])
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        raise ValueError("Connection name must be 1–80 characters")
    key = body.get("api_key", "")
    if not isinstance(key, str) or len(key) > 4096 or any(c.isspace() for c in key.strip()):
        raise ValueError("Enter a valid API key")
    if connection["auth"] == "api_key" and not connection["connected"] and not key.strip():
        raise ValueError("Enter an API key to reconnect this account")
    # Invalidate before replacing a credential, so a failed save cannot leave a tested flag.
    update(connection_id, tested=False)
    if key.strip():
        if connection["auth"] != "api_key":
            raise ValueError("This connection uses official account sign-in")
        _vault().set_password("Roosta AI", connection["credential_ref"], key.strip())
    return update(connection_id, label=label.strip(), connected=True)
