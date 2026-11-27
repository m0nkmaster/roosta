# Runner, workers and connectors

[Agent guide](../../AGENTS.md). Read before changing scheduling, task configuration, connector checks or activity.
Code lives in `src/roosta/scheduler.py` (the runner loop and harness runs), `task_config.py` (the task model and
`tasks.yaml` loading and edits), `connectors.py` and `app.py` (routes); runtime paths such as `cache/`
are relative to the workspace's `.roosta/state/`. See [harnesses](harnesses.md) for CLI details.

## Scheduling and execution

Desktop first launch uses `roosta init --skip-checks --no-git` so opening the bundled app
does not require Git or trigger macOS developer-tool installation. CLI init retains its
Git setup by default; `--no-git` only skips repository creation and its initial commit.

`roosta init` installs empty `tasks.yaml` and `connectors.yaml` from the packaged skeleton's
`.roosta/` directory. Setup then adds the chosen workers and connectors. Keep repository runtime
ignore rules root-anchored so these starter files ship in wheels. Rerunning init restores missing
files without replacing existing configuration.

- **Writer-locked concurrency, not global serialisation.** Tasks run in parallel by default. A task
  flagged `writer: true` in `tasks.yaml` (may rewrite vault docs or auto-commit) is serialised against
  *other writers* via `TaskRunner._writer_lock`, so two doc-rewriting passes can never race on
  the same files/git index.
  Read/fetch-only tasks (watchers, the assistant conductor, briefs) carry no lock
  and can run whenever their own schedule fires, including alongside a writer. `is_queued()`
  reports true for a task whose trigger fired but is still waiting on the writer lock.

- **Every worker runs on an AI connection.** A task's `connection:` names one; unset follows the
  default chosen in Settings, bound once after the writer queue. On upgrade, check each worker’s
  connection before enabling its schedule. Pin local-only Ollama workers to Local (Ollama) and
  choose an installed model. The auth check before each run
  confirms that connection's software is installed. With no connection the run fails with "Choose
  an AI connection in Settings" and the board shows the AI setup card, even after workspace setup.

- **Tasks wait for their connectors.** A task with `requires: [...]` stays `blocked` while any of
  those connectors' probes is `auth-failed`, without spawning a harness or advancing its schedule,
  and runs when the probe recovers. Probe errors do not block. **Any early-`continue` gate in
  `_poll_loop` that a manual run cannot bypass must clear that task's trigger.**
  `_wait_or_trigger` returns without ever awaiting when the trigger is already set, so a leaked
  trigger turns the loop into a tight non-yielding spin that re-reads `tasks.yaml` and every
  `SKILL.md`, monopolises the event loop and freezes the entire dashboard.

- **A pre-check can skip an unchanged run.** A task's `precheck:` command (no shell, 30s) runs
  before a scheduled run; exit 1 means nothing changed, so the schedule advances and the last
  output carries forward without a model run. Any other outcome runs the skill. Manual runs always
  bypass it.

- **Idle timeout, not wall-clock.** `run_task` reaps a skill run on *inactivity*, not total elapsed
  time: 300s of silence by default. `TASK_MAX_TIMEOUT` (3600s) remains the absolute backstop. Stderr is drained
  concurrently so a full pipe cannot masquerade as an idle run. Both limits are overridable per
  task via `idle_timeout:`/`max_timeout:` in `tasks.yaml`. Silence is measured on the awake
  (monotonic) clock, so a Mac that sleeps mid-run does not kill it on wake. When judging a
  "presumed hung" error, compare its `duration` with wall time before blaming the skill.

- **Task loops are supervised.** `_supervised_loop` records an error and restarts the task's poll
  loop after an unexpected exception. If a task looks stuck, check `runner.log` for "poll loop crashed".

- **Missed weekly slots catch up once.** Daily `run_at` tasks already run later the same day. A
  `days_of_week` task whose latest scheduled slot passed while the runner was down runs once on the
  next day the runner is up (`missed_weekly_slot`); on its scheduled day the normal time gate
  decides, and a task that has never run is not caught up.

- **Runs lost to the network retry in 15 minutes.** A failed run whose error matches
  `OFFLINE_FAILURES` (Claude "Can't reach the API server", "computer went to sleep", Cursor "Failed
  to reach the Cursor API", ECONNRESET, DNS) sets `retry_at`; once due it bypasses the time and
  interval gate (not the day gate), so a daily task does not lose its slot. Any other outcome
  clears it. The Skill runner row reads "offline · retrying HH:MM".

- **`<task-output>` tags** for structured output parsing from the JSON stream.
  Every runtime must return a valid envelope; progress-only or non-JSON results are errors.
  Cursor result extraction prefers a completed streamed envelope over a stale terminal result.
  `parse_task_output` tolerates one missing or extra closing brace, and `TASK_STATUS_ALIASES`
  maps `ok`/`complete` and similar to `success` and `partial`/`incomplete` to `error`. A
  model-reported failure keeps its own `summary` as `last_error`, so the board shows why it
  failed; still fix a skill's contract wording when it drifts.

- **Carried-forward output must not carry stale errors.** Fast paths that copy `last_output`
  forward (an unchanged pre-check) drop any old `details.error`, because the conductor reads
  every sensor cache and would re-raise it as a board card.

- **A failed run keeps its last cards.** When an `error` run omits `details.items` or returns an empty list, the
  runner keeps the previous items (not the old `details.error`), so one AI failure cannot empty
  the Assistant board or blind the conductor's next pass. A failed conductor pass also keeps its
  previous cards when the model returns a partial list.

- **Skill descriptions stay canonical.** The runner reads each task skill's `description` from
  `SKILL.md` frontmatter, using the same resolved file as the actual prompt, and shows it as
  one truncated line with the full text on hover.

## Host check

Every request must name an IP literal, `localhost` or the saved `ROOSTA_HOST` in its `Host`
header (`trusted_host` in `app.py`). This blocks DNS rebinding, where a web page points its own
domain at 127.0.0.1 and then calls the API as if it were same-origin. A machine name such as
`studio.local` works only when it is the saved host.

## Settings endpoints for the CLI

`/api/settings/workspace` (GET, POST select/create/adopt), `/api/settings/address`,
`/api/settings/service` reuse `cli.py`. They are
local-only and same-origin like `/api/ai/*` (`local_ai_settings`), return `Cache-Control: no-store`,
and never restart or switch workspace in-process: they record `workspace`, `host` and `port` in
`~/.config/roosta/config.json` for the next `roosta start`, which uses flags first, then config,
then `127.0.0.1:7667`. The service endpoint only writes the unit file, like `roosta service install`,
and is refused when `ASSISTANT_DESKTOP=1` (the desktop app always passes both address flags and
supervises its own runner). Tests monkeypatch `cli.CONFIG_FILE`, `Path.home`, `platform.system` and
`cli._probe`; never run these against a real home directory.

## Connectors and external writes

The runner knows no specific tool. `.roosta/connectors.yaml` lists connectors, re-read whenever it
changes. Each may declare a read-only `check` command (no shell), how to read it (`expect`/`reject`
dotted JSON paths, else the exit code), the user's `login` command, and `deny` - write-command
prefixes enforced by the default profile. Unrestricted runs omit Roosta's connector denials. Named connections retain their
[protected paths](harnesses.md) under every profile. A connector with no `check` only contributes denials.

- There are no standing health workers. A task with `requires: [<id>]` runs those checks just
  before it starts; a confirmed `auth-failed` holds it `blocked` with "Waiting for sign-in: <label>
  (run `<login>`)", without spawning a model run. Checks are shared for `CHECK_CACHE_SECONDS` so
  tasks starting together run each one once.
- `verdict` is pure: `success`, `auth-failed` (the check ran and says signed out) or `error` (it
  could not run or its output made no sense). `error` never blocks.
- The desktop app notifies once per distinct sign-in reason while any task waits on it.
- The `connectors` core skill holds a catalogue of common tools. Organisation-specific recipes live in
  `examples/organisation-pack/` and are not shipped; a workspace adds them through TOOLS.md.

By default workers return board-shaped `details.items`, `/api/board`
merges those feeds with the conductor snapshot, and the Electron main process owns native
notifications. Assistant drafts use the board's Send/Cancel flow.
The default worker profile permits local deletion, `git reset` and `git clean`. Workers already
marked `unrestricted: true` have broader standing approval in 0.21.0, covering local and external
actions on manual and scheduled runs. Both profiles retain Roosta’s protected paths. Blockers
still go to the board in the task output. Legacy push flags and per-connection GitHub issue
grants are ignored and never turn on Unrestricted. The loader and `roosta doctor` warn about
enabled `allow_git_push` and `push_on_schedule` fields in `tasks.yaml`. Doctor does not inspect
per-connection `issue-grants.json` files.

## Adding a task

Add to the workspace's `.roosta/tasks.yaml`:
```yaml
  - id: my-task
    skill: skill-name       # installed, forked or custom skill name
    name: My task           # optional: Skill runner display name (default: id)
    nickname: Dwight        # optional: what The Office calls this worker (default: id)
    description: Does X     # optional: overrides the skill's description
    interval: 3600          # seconds between runs (ignored when run_at is set)
    run_at: "09:00"         # optional: HH:MM local time; run once per day at this time
    weekdays_only: true     # optional: skip Saturday and Sunday (default false)
    days_of_week: [monday]  # optional: run only on these lowercase day names
    writer: true            # optional: rewrites vault docs/auto-commits (default false, see Scheduling and execution)
    requires: [github]       # optional: wait while these connectors are signed out
    precheck: scripts/new.sh # optional: exit 1 = nothing new, skip the scheduled model run
    sensor: true             # optional: feeds the board; board health warns when it fails
    unrestricted: true       # optional: standing approval for any action; nothing is off limits
    idle_timeout: 300       # optional: silence limit (default 300s)
    max_timeout: 3600       # optional: absolute runtime ceiling (default TASK_MAX_TIMEOUT)
    connection: account-id  # optional: pin a connected named connection; omitted follows the default
    model: opus             # optional: model for that connection; otherwise its default
    dir: /path/to/run/in    # the run's workspace and working directory
```

Use `interval` for polling tasks (teams-actions-watch, assistant). Use `run_at` for
once-daily tasks at a specific time (standup briefs, daily reports). `run_at` and `interval`
are mutually exclusive - when `run_at` is set, interval is ignored. Flags accept only
real YAML booleans; anything else fails closed with a warning. Retired `harness:` and
`claude_model:` keys are ignored; only `model:` sets a worker's model.
`last_run` is stamped when a run **finishes**, so an interval counts from the end of the last run
(drifting by run time) and a Run now resets it; a Run now after today's `run_at` counts as today's run.
`tasks.yaml` is the only home for a task's schedule: never state a run time or frequency in a skill, because the user changes them here.

No restart is needed: the runner watches `tasks.yaml` (and re-reads it every 30 seconds in case a file event is missed; a failed watcher restarts itself), spawns a loop for a new task id, and each
loop re-reads its own config every cycle. Code changes to the runner do need a restart.

## Prompt template

`task_prompt` in `scheduler.py` selects the unattended instructions. The default prompt forbids
external writes and returns findings as Assistant board items, optionally linking workspace Markdown
through `documents`. The unrestricted prompt authorises any local or external action the work
needs, asks the model to keep credentials out of output, and returns blockers to the board. Both
return `<task-output>` JSON with `summary`, `status` and `details`.

## Workers page

- **`static/index.html`** - Workers at `/runner` (rows show the task's `name`, else its id, and always the skill it runs) (`/` redirects to `/assistant`, the landing page; `/?task=` deep links forward to `/runner`). Single-page status UI (vanilla JS, polls `/api/tasks`); dense
  one-line-per-task list with an expanding detail drawer, plus name/skill search, a status filter
  and a sort (default alphabetical). Sort and filter persist in browser storage. **A worker is a
  skill on a schedule**: the UI says worker, never hides the skill, and code, `tasks.yaml` and the
  API keep saying task. Each row has a 1:1 chat button (the same `worker:<task id>` thread the Office
  dossier opens, question prefilled, never sent); **New worker** opens `/assistant?item=hire`, which
  mints a `hire:<12 hex>` chat where `hire_chat_item`'s `voice` has the actor follow `write-a-skill`
  and its scheduled-worker reference, writing the SKILL.md and then the `tasks.yaml` entry only after
  the user agrees to each

- **Tasks are configured from the Workers page.** Each task's drawer holds one settings form - name,
  Office nickname, description, schedule (every N minutes/hours/days or daily at HH:MM; every
  day, weekdays or specific days), and AI connection - saved with `POST /api/tasks/{id}/settings`.
  The Unrestricted checkbox sends `unrestricted` only when changed. Like connection changes,
  this write requires a local, same-origin request. JSON `true` enables the grant, `false`
  removes it, and omission preserves it. The poll loop reads the grant before waiting for the writer lock, so a run already waiting there or executing keeps its original permissions.
  `update_task_fields` rewrites only those keys in `tasks.yaml`, keeping other lines and comments;
  a trailing comment survives only while its value is unchanged, so `interval: 3600  # 1 hour`
  does not keep a wrong note. Empty name, nickname or description removes the key (fallback: id,
  id, the skill's own description). Connection changes are sent only when changed and refused while
  the task is running or queued; identity and schedule edits are not. While a form is focused or
  has unsaved edits the 5s poll does not re-render the list. Removing a worker uses YAML source
  positions and checks the whole remaining schedule before saving, including an empty task list.

- **Skill names open a read-only preview on the Workers page.** `GET /api/tasks/{id}/skill`
  follows the runner's skill lookup order for a configured task, with the document reader's
  resolved-symlink, UTF-8 and 2 MB checks within the selected skill root. The native dialog
  renders sanitised Markdown, including frontmatter as YAML code, and closes with Close or Escape.

- **Unscheduled skills sit below the workers.** `GET /api/skills/unscheduled` lists skills in the
  installed package, workspace forks and the workspace’s `.agents`, `.claude` and `.cursor` roots that no task names, with
  their descriptions. Global-only skills are excluded, as are the dashboard-invoked `actor`
  and `sender`. `GET /api/skills/{name}/skill` previews only those workspace skills, with the same
  document checks and any additive workspace instructions. **Schedule** opens the hire chat with the request prefilled, never sent. The
  page reloads the list when the set of scheduled skills changes and every 30s.

## AI activity feed

`ActivityLog` in `activity_log.py` (the `app.activity` instance) records every scheduled or manual skill run the dashboard spawns:
`start("skill", skill, source, task_id=, backend=)`, then
`set_session(id, session_id)` and `finish(id, status, summary)`. Board chat turns are not logged
here.

- **kind:** `skill`; `chat`, `action` and `send` are reserved for board spawns, which are not
  logged. **source:** `scheduled` or `manual` (Run now).
- **Storage:** last 200 entries in memory; each start+finish also appends to `cache/activity.jsonl`
  (gitignored, trimmed at server start - see retention below).
- **The feed survives a restart.** `ActivityLog.hydrate()` rebuilds history from the tail of
  `activity.jsonl`, collapsing each id to its last write. An entry still marked `running` belonged
  to the previous process, whose harness child died with it, so it is recorded as `interrupted`.
- **Session drill-down.** Each run records its model session id; clicking a feed row loads the
  transcript and a resume command (`GET /api/activity/{id}/transcript`, Cursor transcripts via
  `cursor_sessions.py`).
- **Endpoints:** `GET /api/activity?limit=` is a snapshot; `GET /api/activity/stream` is live SSE;
  `GET /api/activity/{id}` is one entry.
- **Queued runs can be cancelled.** `POST /api/tasks/{id}/cancel` clears a trigger, including one
  already waiting on the writer lock.
- **The runner panel pins in-flight work.** `AI Activity` on `/runner` opens with a Running now block
  built from the union of running activity entries *and* the runner's own `/api/tasks` state
  (running plus writer-lock queued), with a per-second elapsed timer. Either source alone can miss
  a live skill - the activity log loses its entry across a restart, and a task state has no start
  time - so keep both.

- **The activity log is trimmed at server start.** `cache/activity.jsonl` is append-only;
  `ActivityLog.compact` keeps its newest 4 MB of whole lines (about two months) when the server
  starts, never on import. Tests write to a throwaway log via `tests/conftest.py`, so a live row
  whose session id matches a fixture means isolation has broken.

## Product usage and engineering runs

- Workers can run `roosta snapshot board` or `roosta snapshot tasks` for the live JSON. Both issue a loopback GET on the runner port with proxies and redirects disabled.
- **Dashboard evolution uses real product behaviour.** `/api/usage` accepts only allowlisted,
  coarse interaction metadata and stores it in gitignored `cache/product-usage.jsonl`; it rejects
  item ids, titles and message text. `roosta usage --days 14` gives the roosta-engineer a
  compact evidence summary. Its deliveries and failures become Assistant board items, while
  no-change passes stay quiet. The shipped skill edits workspace customisations and drafts product feedback for review.

Workers with no `connection` resolve the default once at execution, after the writer queue, and bind activity
to that connection id. Missing or disconnected connections wait with a Settings repair message;
manual triggers are cleared on the same auth gate as legacy tasks. See [AI harnesses](harnesses.md).

Startup migrates legacy skill copies before starting workers or chats. Skills resolve to an active workspace fork, then installed core, then custom task/workspace/global skills. See [skill ownership and recovery](../skills.md) for CLI commands.
