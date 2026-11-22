# Roosta — agent guide

Roosta is your agentic office: a desktop app for a team of AI workers with shared knowledge and skills.
Application code lives in `src/roosta/`; the shell lives in `desktop/`. A user's workspace
owns its profile, skills, schedule and runtime state. Edit the app in this checkout,
never inside a user's workspace.

## Working rules

- Keep API routes and the shared runner, chat router and activity instances in `app.py`; put
  subsystem logic in its own module, as with `scheduler.py`, `board.py` and `task_config.py`. Do not introduce a framework layer. Pages are static HTML + fetch, with no Jinja or build step.
- Use `paths.py` for `APP_ROOT` versus `WORKSPACE`; never hardcode a home directory.
  Use `profile.load().user` and `{user}` in prompts, and the profile's `reviewer` for provenance.
- Preserve other sessions' uncommitted work. Stage by path and commit only your own hunks;
  never `git add -A` or stash the tree. Live runtime files can change underneath a stash.
- Every shipped dashboard change needs a dated `CHANGELOG.md` entry and version bump.
  Follow the rules at the top of that file; check for concurrent edits before writing.
- Keep external writes behind the board's explicit draft/approval/sender flow. Scheduled
  skills report findings as board items. The runner may apply scoped issue comments and the `in review` label under an explicit
  per-worker repository grant (see Runner). A task with explicit
  `allow_git_push` approval may run exactly `git push origin main` in its named repository;
  timer pushes also require `push_on_schedule`. Unrestricted tools do not grant permission.
- Treat workspace paths and model output as untrusted. Preserve resolved-symlink validation,
  attachment limits, Markdown sanitisation and sender-action validation.
- A worker is a skill on a schedule: UI says **worker** and always names the skill;
  code, API and YAML say **task**. Schedules belong only in `.roosta/tasks.yaml`, never in skills.
- Use the same full status labels everywhere: `idle`, `queued`, `running`, `success`,
  `error`, `blocked`, `auth failed`, `interrupted`. `kind` describes what ran, not its verdict.
- Chats are keyed by stable item id, never by project. Closing an item or losing its board
  source must not erase its conversation. Browser disconnects must not cancel a live turn.
- Read the relevant references below before changing a subsystem. Preserve the documented
  safeguards, and update the owning reference when a contract changes.

## Read for the task

| Working on | Reference |
| --- | --- |
| Scheduling, task settings, connectors, activity, task YAML | [Runner](docs/development/runner.md) |
| Claude/Cursor/Ollama commands, models, policies, sessions | [AI harnesses](docs/development/harnesses.md) |
| Board feeds, chats, markers, approvals, reminders | [Assistant](docs/development/assistant.md) |
| Any page, shared components, themes, custom pages, Workspace, Pulse | [UI](docs/development/ui.md) |
| Office simulation, sprites, casting, visual checks | [Office](docs/development/office.md) |
| Electron supervision, notifications, deep links | [Desktop notes](docs/development/desktop.md) and [desktop README](desktop/README.md) |

[README.md](README.md) covers installation and use. Track work in
[GitHub Issues](https://github.com/m0nkmaster/roosta/issues). The roosta-engineer's feedback and delivery log
belong in the maintainer's workspace `.roosta/engineer/`, never this repo.

## Code map

Paths below are relative to `src/roosta/` unless stated otherwise.

| File or directory | Responsibility |
| --- | --- |
| `paths.py`, `profile.py` | App/workspace roots; user identity and preferences |
| `cli.py`, `skeleton/` | Init/adopt, start, service install, workspace scaffolding |
| `skills.py`, `skills/`, `operating-model.md` | Shipped skills and workspace sync |
| `app.py` | FastAPI routes, lifespan and the shared runner, chat router and activity instances |
| `scheduler.py` | `TaskRunner` loop, writer serialisation, prompts and one harness run per task |
| `task_config.py` | Task model, `tasks.yaml` loading and comment-preserving edits, skill lookup |
| `chat.py` | `ChatRouter`, markers, approvals, conversation stores |
| `board.py` | Board card normalisation, feed merging, reminders, setup card and board health |
| `chat_items.py` | Open, document, worker 1:1 and new-worker chat items |
| `ai_backend.py`, `ai_connections.py`, `ai_runtime.py` | AI dispatch, named accounts, credential references and managed runtimes |
| `ai_settings.py` | Worker runtime checks and options, model lists and validation, Settings setup jobs |
| `workspace_settings.py` | How Roosta is run, skill ownership and the workspace folder browser |
| `pi_agent.py`, `pi_guard.mjs` | Pi RPC transport and permission hook |
| `cursor_agent.py`, `cursor_sessions.py` | Cursor invocation, environment, transcript reading |
| `claude_code.py`, `claude_guard.py` | Claude invocation, stream parsing, permission settings/hook |
| `opencode_ollama.py` | Local model invocation, environment, compatibility |
| `connectors.py` | Generic sign-in probes and external-write denials |
| `workspace.py` | Read-only document catalogue, vault path validation and bounded attachments |
| `attachments.py` | Chat upload storage, limits and validation |
| `pulse.py`, `usage.py` | Vault telemetry and privacy-preserving interaction signals |
| `pages.py` | Custom pages and workspace overrides of shipped pages |
| `teletext.py` | Office lounge TV feeds: BBC headlines and the daily quiz |
| `activity_log.py` | AI activity feed: every spawn, its `activity.jsonl` history and live subscribers |
| `static/` | Pages; shared `nav-count.js`, `shell.css`, `theme.js`, `column-resize.js`, Markdown helpers |
| `desktop/` (repo root) | Native macOS shell and runner supervision |

Workspace configuration lives in `.roosta/tasks.yaml` and `.roosta/connectors.yaml`.
Runtime data is gitignored under `.roosta/state/`: task outputs in `cache/{id}.json`,
chat/board stores in `assistant/`, custom-page data in `pages/<name>/`.

`roosta init` copies the skeleton without overwriting and links `CLAUDE.md` to `AGENTS.md`
and `.claude/skills` to `.agents/skills` (independent folders when links are unavailable). It records the workspace in
`~/.config/roosta/config.json` for the desktop app and bare `roosta start`. Core skills and the operating model run directly from the package.
Startup migrates legacy trees before workers and chats start. Workspace additions and pinned forks
live under `.roosta/skill-extensions/` and `.roosta/skill-forks/` (see README).

## Regression traps

- Clear a task's trigger on every `_poll_loop` gate that manual runs cannot bypass.
  A leaked trigger makes `_wait_or_trigger` spin without yielding and freezes the dashboard.
- Serialise writers against other writers only. Non-writer tasks may run concurrently.
- Send Claude prompts on stdin, never argv. Unattended Claude commands stay in the foreground.
- Allow an immediate transport retry only before model/tool progress; otherwise local work
  may run twice. Preserve inactivity timeouts, stderr draining and process-group cleanup.
- Carried-forward task output must drop stale `details.error` values.
- Use Tabler components and shared theme tokens. Navigation belongs only in `nav-count.js`.
  Load Tabler CSS, then `shell.css`, then undeferred `theme.js` before first paint.
- Never screenshot live polling/SSE pages with headless virtual time. Use a disposable static
  harness with real styles and mocked API data; see the UI and Office references.
- Never run the dev reloader without `reload_excludes` for runtime output.

## Validation and reloads

For implementation changes, establish the test baseline before building and run the suite after:

```sh
uv venv                              # once, if .venv is absent
uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

For Electron changes also run `node --test` from `desktop/`. Trust the test process's own
exit code, never a pipeline such as `pytest | tail`. Documentation-only edits need link
and diff checks; no app build is needed.

`tests/conftest.py` isolates `ROOSTA_WORKSPACE` and activity storage before imports. Keep that
isolation: importing the runner against the real workspace can seed configs containing MCP
tokens. Runner tests fake task loading, auth, execution and cache paths; never invoke real
harnesses, external tools or the live vault. Pulse tests use relative instants, not fixed dates.

Tests are grouped by subsystem: `test_runner.py`, `test_board.py`, `test_claude_code.py`,
`test_sessions.py`, `test_pulse.py`, `test_office.py`, `test_usage.py`, `test_uploads.py`, `test_changelog.py`.
Board and Office tests also run extracted JavaScript helpers under Node.

HTML/CSS changes load on refresh; Python changes need a runner restart; core skill edits apply on the next turn; only `desktop/` changes need an Electron rebuild. Task YAML reloads
without a restart.

## Keeping this guide useful

Keep this file around 150 lines or fewer: shared rules, a code map and links. Put subsystem
contracts and debugging recipes in their reference; user instructions in the README;
release history in the changelog. Update an existing rule instead of appending feature prose.
