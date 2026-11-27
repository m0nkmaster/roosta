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
remain usable. Discovery skips known cmux terminal-specific shims and Claude wrappers (including symlink targets), then considers the first ordinary executable on PATH, the standard user install and managed copies. This keeps unattended runs and Open in Terminal off cmux session wrappers without rejecting other user wrappers. Version probes are cached against resolved path, modification time and size so external
CLI updates are recognised without restarting. No network lookup happens during discovery: downloads
are explicit Settings actions and wait for active turns. `describe()` reports the selected version and
whether Roosta or the user installed it. Downloads use the default SSL context with a fallback to
`/etc/ssl/cert.pem` when the frozen backend's bundled OpenSSL paths don't exist. The frozen
backend includes keyring's native backend, so installation needs neither Node nor system Python.
Updating stages and verifies the download before replacing the managed copy. New harness releases do not require a Roosta update.

Claude, Pi and Cursor runs prepend the package's `worker-bin` directory to their child PATH.
Its `roosta` command re-enters the serving interpreter and package, or relaunches the frozen
backend with a fresh PyInstaller environment. Runs inherit the serving workspace and port,
including when a task has a different working directory.

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
re-creates it. An explicit **Add and use as default** submits `default_if_unset: true` on account creation. The account and default are saved together, preserving any default chosen in another window. Detection alone leaves the choice open. Choose any connected account as default with `POST /api/ai/default {connection}`. This does not list models or run a test. The first successful test sets the default only if none has been chosen.

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
is still valid for the new provider. Workers use their `model` when valid for the provider,
otherwise the default; the worker form saves it through `connection_model`. Cursor model ids get a
format check only, because listing them needs the account's key.
`GET /api/ai/models?connection=<id>&general=0|1` lists the default and choices (`?provider=` also works).

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
approved sender or an existing privileged task uses the unrestricted profile.

Named Claude and Pi connections deny file-tool reads and writes in the connection and
managed-runtime directories under every profile. File tools can read installed skills, their
references and the operating model under `paths.APP_ROOT`. Edits and writes to that package
are denied unless its resolved path is inside the selected workspace (an editable checkout).
Pi also blocks shell commands that mention an absolute private root or the external package
root. With the external package, Pi accepts a standalone `python3` invocation of the literal
absolute path to `skills/workspace-learner/sessions.py` for `status`, `list` and `transcript`.
The helper command also accepts the literal prefix `PYTHONDONTWRITEBYTECODE=1`.
Use the workspace as the working directory and quote paths containing spaces. For source inspection
use the read tool, `cat FILE`, or `grep -F -- PATTERN FILE` with one absolute package file.
These shell reads accept literal arguments only. Redirection and chained commands remain blocked.
A product engineering worker can use the ordinary profile with a separate Git worktree
and launch from the workspace to discover its custom skill. Ordinary Claude runs use `dontAsk`.

`SessionMap` reads old string values and writes `{session_id, connection}` records. New chats bind the connected default once.
An actor turn holding the item lock also binds that default when the chat has no named account
or its account was deleted. It discards the old provider session and unverified model pick, keeps
the visible transcript, and passes the topic summary into the fresh session. With an incomplete
summary it includes recent messages from the current conversation segment. Reading Settings or
the board does not rebind chats. A missing or disconnected default leaves an orphan untouched.
Existing named accounts stay pinned, including on disconnect or authentication failure. A pending
approval or sender in flight blocks recovery. The sender always uses the account that drafted the action.
Explicit chat migration retains rendered history and topic summary,
rotates execution context, and is rejected during a live turn or pending approval. Worker YAML omits
`connection` to follow the current default and stores a stable id only for an explicit account pin. The
runner resolves the default once after waiting for its writer slot and stores the concrete connection
id on activity. An old `connection: default` is read as omitted. Disconnected accounts fail on their original binding. Untested accounts and accounts with a failed check can run.

The local-only `POST /api/ai/operations/{key}/cancel` accepts the running test’s `run_id`. Cancellation targets that test alone and waits for its process group cleanup before publishing `interrupted` and allowing retry. It preserves the previous test metadata.

The disclosed setup probe uses a temporary file with a random value and requires both a successful
read-tool result and an assistant response containing it. It does not load workspace MCP or skills.
Automated tests cover routing, account/session isolation, approvals, request-origin checks, timeouts,
checksums and policies. Verify live OpenAI and Anthropic sign-in, enterprise account access and
OpenRouter acceptance on a clean packaged machine to confirm provider access and billing eligibility.

## Runtime details

Every chat, worker and approved send runs on a named AI connection: Anthropic through Claude Code,
OpenAI, OpenRouter and Ollama through Pi, and Cursor through the Cursor Agent CLI (`agent`). The old
engine picker, per-task `harness:`/`claude_model:` keys and the OpenCode runtime are retired.

- **Claude prompts go on stdin, never argv.** Endpoint security on some managed Macs SIGKILLs (exit 137,
  before any output) any process whose command line contains certain words, e.g. "openclaw" in any
  case. Cursor takes its prompt as the last argument and is exposed to the same risk; a run killed
  by a signal before any output reports that cause rather than a generic failure.

- **Claude permissions.** Claude runs `claude --print --output-format stream-json --verbose
  --permission-mode dontAsk --settings <profile>`: `dontAsk` refuses anything not on the allow list,
  so no bypass mode is involved. The `safe` settings are generated from `cursor-permissions.json`
  (Shell rules become `Bash(... :*)` denials, Write rules become Edit and Write denials), and the
  `Mcp(*:*keyword*)` denials become a `claude_guard.py` hook, because Claude permission rules cannot
  wildcard inside MCP tool names. The guard ignores case, so it is stricter than Cursor
  (`get_comments` is blocked too). The `unrestricted` profile, used by the approved sender and by
  tasks marked `unrestricted: true`, has no denials. `curl` and `wget` stay denied in `safe`;
  workers read the local board and task status with `roosta snapshot board|tasks`. Local commands
  such as `rm`, `git reset` and `git clean` are not denied in any profile.

- **Claude models.** `is_claude_model` is an argv-safety format check only; a new choice is
  validated against Claude Code's own list (`validate_model`) and an already stored value stays
  accepted. A model id may end in `@<effort>`; `claude_args` splits it into `--model` and
  `--effort`. Claude has no create-chat call, so Roosta mints a UUID and the first turn passes
  `--session-id`, later ones `--resume`. The child sets `MCP_CONNECTION_NONBLOCKING=false`, because
  otherwise print mode starts the model before MCP servers connect.

- **Unattended Claude runs never background a command.** Print mode ends when the turn ends, so a
  model that backgrounds a command and "waits for the notification" loses the run. Connections set
  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, and worker runs set `BASH_MAX_TIMEOUT_MS` to the task's
  `max_timeout` minus two minutes so a long script such as a chat archive fits in one foreground call.

- **Cursor connections.** Roosta strips inherited `CURSOR_API_KEY` from connection environments.
  A Cursor run receives only its selected account’s key from the OS credential store. Each turn
  writes its permissions and MCP servers to a private temporary `cursor/run-*/` directory and
  uses it as `CURSOR_CONFIG_DIR`. Concurrent runs on the same account cannot overwrite each
  other’s settings. Each directory links to the account’s persistent `cursor/chats/` store so
  sessions can resume after the temporary config is removed.
  The `safe` profile is `cursor-permissions.json` plus connector denials; `unrestricted` allows
  everything. Both deny the connection and managed-runtime roots, and writes to an installed
  package outside the workspace. Turns run `agent --print --trust --force --approve-mcps
  --output-format stream-json --stream-partial-output`; Cursor's own default model applies when
  none is chosen. Roosta does not install or update the CLI; Settings links to cursor.com/cli.

- **`agent create-chat` must use the default CLI config.** With `CURSOR_CONFIG_DIR` pointed at a
  permission profile, Cursor prints a valid chat id but keeps the process alive, so `create_chat`
  drops that variable. New chats create their Cursor chat before the first turn
  (`ai_backend.new_session`); a worker run without a session creates one at the start of the turn.

## Chat tool availability

- **Tool parity.** Every connection receives the MCP servers the user already configured
  (`~/.cursor/mcp.json`, `~/.claude.json`, Pi's and the workspace's `.mcp.json`), and `CHAT_PROMPT`
  points the actor at AGENTS.md, workspace skills and `TOOLS.md`. The `safe` profile still blocks
  external writes until the approved sender path. OAuth-backed MCP servers may report `needsAuth`
  in a board turn; say so and ask for the content rather than reporting it missing.

## Session store retention

- **Cursor CLI session stores are pruned at server start; transcript trees never are.** The Cursor
  CLI writes a per-run SQLite store under each connection's `cursor/chats/<hash>/<uuid>/`. No
  dashboard code reads them - history is rendered from `~/.cursor/projects` and `~/.claude/projects`
  - so `prune_cursor_session_stores` runs beside `activity.compact` and deletes stores older than
  `SESSION_STORE_RETENTION_DAYS` (30) that no activity row still references. The transcript trees
  are left alone: they back the activity drill-down and mingle with the user's own CLI history.

Packaged desktop builds invoke the frozen backend with `--claude-guard` for the Claude hook.
Development invokes Python and `claude_guard.py`; both commands quote paths and keywords for
the hook shell, including app paths containing spaces. No system Python is needed in a release.

Manual chat context refresh preserves the account and model binding. The next turn
allocates a new provider session under the per-item turn lock, even when the old
session id is still on disk. Only an accepted handoff supplies prior conversation
context. See the [conversation segment contract](assistant.md#starting-a-new-conversation-segment).

Roosta adds exact skill and extension paths plus the installed operating model to each worker, actor and approved sender prompt. The same routing applies to secondary skills and resumed sessions. Native skill discovery is for additional custom skills.
