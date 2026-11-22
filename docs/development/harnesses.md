# AI harnesses

[Agent guide](../../AGENTS.md). Read before changing CLI invocation, model selection, permissions or sessions.
Paths such as `cache/` are under the workspace's `.roosta/state/`; Python modules are in `src/roosta/`.

## Named AI connections

`ai_backend.py` owns dispatch for named connections. `ai_settings.py` lists runtime options and
models, validates model choices and runs Settings' install, test and sign-in jobs.
`ai_connections.py` stores only metadata in
`.roosta/state/ai-connections.json`; API keys go through `keyring` to an allowlisted native OS backend.
A missing/locked vault fails closed. `ai_runtime.py` downloads the latest published standalone
Pi and unmodified Claude Code binaries into versioned workspace cache directories. Install/update
resolves Pi's GitHub latest-release asset digest or Claude's latest channel and release manifest,
validates version/checksum metadata, then verifies SHA-256 and the downloaded binary's version before
replacing a managed copy. No versions or hashes are pinned in Roosta. `find()` chooses the newest
working managed or user-installed binary, preferring the user's copy on a tie; old managed directories
remain usable. Version probes are cached against resolved path, modification time and size so external
CLI updates are recognised without restarting. No network lookup happens during discovery: downloads
are explicit Settings actions and wait for active turns. `describe()` reports the selected version and
whether Roosta or the user installed it. Downloads use the default SSL context with a fallback to
`/etc/ssl/cert.pem` when the frozen backend's bundled OpenSSL paths don't exist. The frozen
backend includes keyring's native backend, so installation needs neither Node nor system Python.
Updating stages and verifies the download before replacing the managed copy. New harness releases do not require a Roosta update.

Settings uses one provider/account flow. AI software reports installation status; installed binaries offer Update to latest under Updates, which does not imply a detected failure. On macOS, Open in Terminal starts the exact installed Claude Code or Pi binary in `paths.WORKSPACE` as a standalone interactive session using the CLI’s own login/settings, not a Roosta connection. The local-only `POST /api/ai/terminal` accepts only the two runtime ids, refuses missing/installing binaries, shell-quotes both paths, and passes the command as an argument to a fixed AppleScript. It never exports Roosta connection credentials or submits a prompt. The `local_ai_settings` dependency
requires a loopback client, a local Host, and a same-origin browser request for credential/setup APIs.
Tests and installs run as supervised setup jobs; status contains no credentials or authentication output.
Claude enterprise sign-in invokes the official `auth login --sso` browser flow under a unique
`CLAUDE_CONFIG_DIR`. No subscription token field or app-owned OAuth flow exists. Organisation access
still needs a real sign-in test. OpenAI account connections invoke Pi’s `auth login openai`
Sign in with ChatGPT browser flow (including enterprise accounts subject to organisation policy);
API-key connections remain a separate billing choice. Pi 1.5.2 requires a terminal for this command,
so the backend supplies a private PTY and discards authentication output. The browser must run on
the same computer; competing OpenAI sign-ins are rejected and login times out after five minutes.
Pi owns OAuth storage and refresh: each connection has one private `pi/auth.json`, linked into its
workspace-specific Pi directories. Pi locks the resolved file so concurrent refreshes share a lock;
foreign links and replacement auth files fail closed. Logout removes that connection’s credential.
See Pi’s [OpenAI provider](https://github.com/earendil-works/pi/blob/v1.5.2/packages/ai/src/providers/openai.ts)
and [auth commands](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/cli.md#auth), and the official [authentication contract](https://code.claude.com/docs/en/authentication)
and [redistribution terms](https://code.claude.com/docs/en/legal-and-compliance).

Anthropic connections may instead use auth `system`: the user's own Claude Code sign-in. These runs
get no `CLAUDE_CONFIG_DIR` and no `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`, so Claude reads `~/.claude`
and the user's existing login; session-resume detection looks under `~/.claude/projects`. No
sign-in/logout subprocess ever runs for them — disconnect only marks the record disconnected, and
the login operation is rejected. At server startup (before workers start), and when `/api/ai/connections` is loaded, if no `system` connection
exists, one is auto-provisioned ("Claude Code") if `find("claude")` succeeds; a top-level
`system_offered` flag in the connections file makes this happen once, so deleting it never
re-creates it. The first connection whose test succeeds becomes the default automatically.

A connection is an account (provider plus sign-in or key) and carries no model; any legacy `model`
key in the file is ignored on load. Settings stores a top-level `model_choice: {provider, model, effort}` alongside the default account via
`POST /api/ai/default {connection, model, effort}` after catalogue validation. This choice overrides old
per-chat model picks for that provider on subsequent turns, without migrating accounts or interrupting
live turns. Effort applies only to the chosen provider/model: Claude receives `--effort`, Pi receives
`--thinking`. `/api/ai/efforts` returns Claude's `supportedEffortLevels` or Pi's offline
`get_available_thinking_levels` RPC response, cached per model; unsupported choices are rejected
before saving. Pi confirms the requested thinking level in `get_state` before receiving a prompt. Workers with explicit models retain them. The old per-chat APIs remain for compatibility.
`ai_connections.default_model()` uses this choice for the matching provider, then resolves the fallback: Anthropic honours the user's `CLAUDE_MODEL` (and `CLAUDE_GENERAL_CHAT_MODEL` for
general chats), else `""`, meaning Claude Code's own default (no `--model`); OpenAI and OpenRouter use
the model Pi itself selects when only that provider is configured (`ai_runtime.default_model`, a `get_state`
RPC against Pi with a placeholder key); Ollama has no default, so a run without a model fails with
"Choose a model in Settings" (workers: "...for this worker in its settings").
Nothing model-related is hardcoded: `PROVIDERS` has no models. `prepare(..., model=)` validates format
and policy with `runtime()` (OpenRouter rejects `anthropic/` makers and `openrouter/*` routing).
Claude's list comes from the SDK `initialize` control request (`ai_backend.claude_models`): Claude
Code run with the connection environment (minus `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, which
also hides most of the account's models) and `--setting-sources ""`, cached per connection for an hour and
cleared on install, a connection test, or `?refresh=1`. Its `default` entry shows as "Default · <name>"
and maps to `""`; `@<effort>` must be in that entry's `supportedEffortLevels`. If the handshake fails
the list is `claude_code.CLAUDE_FALLBACK_ALIASES` (`fable`, `opus`, `sonnet`, `haiku`), the one permitted
hardcode, with an error shown beside the picker; an already-stored valid model stays accepted.
Pi providers validate by membership in Pi's catalogue (`model_catalog`) and Ollama by `ollama list`. `ConnectionRun.model` feeds Claude's `--model`, Pi's `--model`, the Ollama `models.json`
entry and the exact-model check on Pi's `get_state`. `SessionMap` records are
`{session_id, connection, model}` (model optional); `POST /api/ai/chat-model` changes it without rotating
the session and is refused during a live turn; changing a chat's connection keeps the model only if it
is still valid for the new provider. Connection-backed workers use `claude_model` (Anthropic) or `model`
(Pi providers) when valid for the provider, otherwise the default; the worker form saves it through
`connection_model`. `GET /api/ai/models?connection=<id|legacy:claude>&general=0|1` lists the default and
choices (`?provider=` also works).

Each connection has a stable id, provider, billing route and credential reference. The child
environment removes inherited model credentials and routing settings before adding only this account's
key. Claude's host-managed routing prevents settings from silently changing that route, while managed
permission policies still apply. Pi has isolated state per connection and workspace, explicit provider
and model arguments, disabled discovery of arbitrary extensions, and Roosta's policy extension.
RPC holds the prompt until the extension acknowledges its policy through a notification and
`get_state` confirms the exact provider/model; a missing hook or fuzzy model match fails closed.
Anthropic names (including aliases) and OpenRouter automatic routing never reach Pi. OpenRouter only
accepts explicit non-Anthropic makers. Local Ollama uses Pi's standard OpenAI-compatible provider.

The runtimes own the model/tool loop and context. Prompts use stdin. Named runs drain stderr,
observe idle/absolute deadlines and reap their process group, including cancellation. Pi's error
messages are checked even on exit 0. The Pi extension translates the existing permission profile
and connector denials; these shell/MCP rules are guardrails, not an OS sandbox. Only an explicitly
approved sender or an existing privileged task uses the unrestricted profile. Named Claude connections
also protect connection state, the managed runtime directory and the running application package
(`paths.APP_ROOT`) under every profile. With an editable install the package is inside the source
checkout. Give a product engineering worker a separate Git worktree and point its skill there.
It can keep the ordinary profile and launch from the workspace to discover its custom skill. Ordinary Claude runs
use `dontAsk`, including the legacy path.

`SessionMap` reads old string values and writes `{session_id, connection}` records. Existing legacy
sessions retain their engine; new chats bind the connected default once. Changing the default never
moves an existing chat or approval. Explicit chat migration retains rendered history and topic summary,
rotates execution context, and is rejected during a live turn or pending approval. Worker YAML omits
`connection` to follow the current default and stores a stable id only for an explicit account pin. The
runner resolves the default once after waiting for its writer slot and stores the concrete connection
id on activity. An old `connection: default` is read as omitted. Disconnected or untested accounts do
not fall back to another account.

The disclosed setup probe uses a temporary file with a random value and requires both a successful
read-tool result and an assistant response containing it. It does not load workspace MCP or skills.
Automated tests cover routing, account/session isolation, approvals, request-origin checks, timeouts,
checksums and policies. Verify live OpenAI and Anthropic sign-in, enterprise account access and
OpenRouter acceptance on a clean packaged machine to confirm provider access and billing eligibility.

## Legacy configurations

The details below apply to preserved Cursor, Claude and OpenCode schedules and sessions. The old
backend API and saved selection remain for compatibility; new selections use named connections.

### Invocation, models and permission profiles

- **Claude prompts go on stdin, never argv.** Endpoint security on some managed Macs SIGKILLs (exit 137,
  before any output) any process whose command line contains certain words, e.g. "openclaw" in any
  case. Every caller of `claude_args` writes the prompt to the child's stdin. Cursor and
  OpenCode pass prompts in argv and are exposed to the same risk.

- **Legacy tasks pick one of three harnesses: Claude Code, Cursor or Ollama.** `harness:` in
  `tasks.yaml` is `claude`, `cursor` or `opencode-ollama`; unset follows the
  chat engine (`resolve_harness`). Cursor runs `agent --print --force --trust --approve-mcps`; local runs use
  `ollama launch opencode --model <model> -- run --standalone --format json --auto`. OpenCode's
  `--standalone` starts a private server that reads the run's `OPENCODE_CONFIG_DIR`.
  `opencode_ollama_env` sets `PWD` to the task's `dir` so OpenCode finds the workspace skill. The wrapper supplies
  the Ollama provider inline without changing OpenCode's user config. The tracked
  `opencode-runner.json` policy is seeded into a gitignored, highest-precedence config directory
  with the dashboard's secret, destructive-git and external-write denials, plus the selected
  workspace skill directory so OpenCode can discover it. OpenCode is not available for
  `allow_git_push` tasks. The child PATH puts `~/.opencode/bin` first when present;
  An older Homebrew OpenCode's legacy unattended flag is incompatible with the current `--auto`
  invocation.

- **Ollama model availability does not imply agent compatibility.** A model must reliably emit
  OpenCode tool calls. Qwen 2.5 Coder advertises `tools` but prints the call as JSON instead, so it
  is excluded from runtime choices and rejected during preflight. OpenCode output without the
  required `<task-output>` envelope is an error, with a specific error for unexecuted calls. Qwen
  3.5 runs with OpenCode's `none` reasoning variant (`--model ollama/<model>#none`) because its default variant can put the final
  task output in a reasoning event and emit no assistant text. Timed-out harnesses run in their own
  process group so their OpenCode children are killed with the Ollama wrapper.

- **The legacy backend API** (`POST /api/ai-backend`) applies only when no named default is configured. It retains the old Cursor/Claude default for unbound legacy chats and tasks without an explicit `harness:`; explicit legacy harnesses ignore it. It is persisted in gitignored `cache/ai-backend.json`,
  with `AI_BACKEND` (process environment, then workspace `.env`) as the fallback, and is read at
  the start of each run, so no restart is needed. Claude
  runs `claude --print --output-format stream-json --verbose --permission-mode dontAsk --settings
  <profile>`: `dontAsk` refuses anything not on the allow list, so no bypass mode is involved.
  The settings are generated from the Cursor profiles below (Shell rules become `Bash(... :*)`
  denials, Write rules become Edit and Write denials), and the `Mcp(*:*keyword*)` denials become
  a `claude_guard.py` hook, because Claude permission rules cannot wildcard inside MCP tool names.
  The guard ignores case, so it is stricter than Cursor (`get_comments` is blocked too). The
  approved sender uses the `unrestricted` profile, as does any task marked `unrestricted: true`
  (check the workspace schedule): no local deny rules, but the prompt still forbids external
  writes. `is_claude_model` is an argv-safety format check only (no family or effort names); a new
  Claude choice is validated against Claude Code's own list (`validate_model`, including the
  `/runtime` and `/settings` task endpoints), so Cursor model names never reach Claude; an already
  stored value stays accepted:
  tasks and item chats use `CLAUDE_MODEL` (unset means Claude Code's own default, so no `--model`) unless a task sets `claude_model`.
  A Claude model id may end in `@<effort>` (low, medium, high, xhigh, max); `claude_args` splits it
  into `--model` and `--effort`; `@<effort>` alone sets only `--effort`. Bare aliases (`opus`, `sonnet`,
  `haiku`) resolve in Claude Code to the latest of each tier at the CLI's default effort
  (kept separately from the Cursor `model`, so switching harness never clobbers either pick),
  and chats (`chat:` ids) use `CLAUDE_GENERAL_CHAT_MODEL` (unset: Claude Code's default). Claude has no create-chat
  call, so the dashboard mints a UUID and the first turn passes `--session-id`, later ones
  `--resume`, decided by whether `~/.claude/projects/*/<id>.jsonl` exists; a stored Cursor chat id
  therefore starts a fresh Claude session, and the topic summary carries continuity. The child
  sets `MCP_CONNECTION_NONBLOCKING=false`, because otherwise print mode starts the model before
  MCP servers connect and the first tool search reports MCP servers as still connecting.
  Claude authenticates with the user's own Claude login, which the availability check does not probe;
  a run that fails on an expired login records `CLAUDE_SIGNIN_MESSAGE`, and board health names it
  once instead of showing N separate failures.

- **Unattended Claude runs never background a command.** Print mode ends when the turn ends, so a
  model that backgrounds a command and "waits for the notification" loses the run. Task runs set
  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, and `BASH_MAX_TIMEOUT_MS` follows the task's
  `max_timeout` (minus two minutes) so a long script such as a chat archive fits in one
  foreground call.

- **Under Cursor, live board turns run with**
  the tracked `cursor-permissions.json` policy. `cursor_agent.py` seeds it into gitignored
  `cache/cursor-agent-config/` because the CLI adds account/runtime state to its config file. The
  profile allows local reads/writes but denies secret access, destructive git, git push, known
  external-write CLI commands and write-shaped MCP tools. A task with `allow_git_push: true` uses
  `cursor-permissions-git-push.json`, which permits only `git push origin main`; its prompt must
  confine that standing approval to one named repository. The approved sender path deliberately
  omits these profiles only after the user confirms the external action. Named connections also
  protect their credential and managed-runtime directories. They protect the installed application
  package unless it is inside the selected workspace, so a worker can develop Roosta from its own
  source checkout without gaining access to connection state.

- **Chats have their own model.** `GENERAL_CHAT_MODEL` (process environment, then workspace
  `.env`) sets the model for `chat:` ids; unset, Cursor uses its own default. Item chats, person and document
  chats, approved sends and task defaults continue to use `CURSOR_MODEL`, so changing it does not
  move scheduled work.

- **`agent create-chat` must use the default CLI config.** With `CURSOR_CONFIG_DIR` pointed at the
  dashboard permission profile, Cursor prints a valid chat UUID but keeps the process alive,
  causing the 20-second session-creation timeout. Empty chat creation runs no tools, so
  `CursorAgent.create_session()` passes `safe_config=False`; actual turns still use the profile.
  - **Cursor scopes chat history to `CURSOR_CONFIG_DIR`, not just the account.** A dashboard chat
    id (from `assistant/sessions.json`) will *not* resume under a plain interactive `agent` login,
    even as the same email - it returns an empty/new chat. To open one manually, mirror the runner's
    env: `CURSOR_API_KEY` from the root `.env` and `CURSOR_CONFIG_DIR=.roosta/state/cache/cursor-agent-config`,
    then `agent --resume <id>` (that dir carries the restrictive permission profile).

- **Harness and model are per task.** The Cursor/Ollama `model` defaults to `CURSOR_MODEL`
  (process environment, then workspace `.env`; unset, no `--model` is passed and Cursor picks its own); `claude_model` defaults to
  `CLAUDE_MODEL`. `/api/runtime-options` always lists all three harnesses, each with its models
  (Claude Code's handshake list, `agent models`, `ollama list`) and an `available` flag shown as
  "(unavailable)" in the dropdown.

## Chat tool availability

- **Tool parity with Cursor IDE.** Live turns inherit the user's MCP config from `~/.cursor/mcp.json`
  (mirrored into the dashboard agent config dir), prepend local bins to `PATH` in
  `cursor_env()`, and instruct the actor via `CHAT_PROMPT` to use AGENTS.md, workspace skills
  and the tools `TOOLS.md` lists. The restrictive permission profile still blocks external
  writes until the approved sender path. Parity is not complete for **OAuth-backed MCP servers**:
  Notion reports `needsAuth` in a board turn and exposes only `mcp_auth`, so an actor cannot read a
  Notion page that the same model reads fine from the Cursor IDE. Say so and ask for the content
  rather than reporting the page as missing.

- **Agent runtime** (`ai_backend.AIAgent`): one headless CLI process per turn on the bound connection or preserved legacy engine. Under Cursor (`CursorAgent`) the dashboard checks the CLI and API key at
  startup and creates empty chats with `agent create-chat`; under Claude it mints a session UUID
  as described above. Chats are disabled with 503 when the local prerequisites are
  missing.

## Session store retention

- **Cursor CLI session stores are pruned at server start; transcript trees never are.** The Cursor
  agent CLI writes a per-run SQLite store under `cache/cursor-agent-config/chats/<hash>/<uuid>/`
  (and the git-push config's equivalent). No dashboard code reads them - history is rendered from
  `~/.cursor/projects` and `~/.claude/projects` - so they are unbounded scratch, one store per run
  plus orphaned `-wal` files. `prune_cursor_session_stores` runs beside `activity.compact` and
  deletes stores older than `SESSION_STORE_RETENTION_DAYS` (30) that no activity row still
  references, so a resumable chat is never pulled out from under the CLI. The `~/.cursor` and
  `~/.claude` transcript trees are deliberately left alone: they back the activity drill-down and
  mingle with the user's own CLI history, so pruning them would be real context loss.

Packaged desktop builds invoke the frozen backend with `--claude-guard` for the Claude hook.
Development invokes Python and `claude_guard.py`; both commands quote paths and keywords for
the hook shell, including app paths containing spaces. No system Python is needed in a release.

Manual chat context refresh preserves the account and model binding. The next turn
allocates a new provider session under the per-item turn lock, even when the old
session id is still on disk. Only an accepted handoff supplies prior conversation
context. See the [conversation segment contract](assistant.md#starting-a-new-conversation-segment).
