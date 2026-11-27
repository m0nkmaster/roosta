# Assistant board and conversations

[Agent guide](../../AGENTS.md). Read before changing board feeds, chat identity, markers, reminders or approvals.
Implementation: `src/roosta/chat.py`, `board.py` (card normalisation, feed merging, reminders,
setup and health), `chat_items.py` (open, document, worker and new-worker chats), `app.py`
(routes) and `static/assistant.html`. Store paths
starting `assistant/` are under the workspace's `.roosta/state/`. Also see
[harnesses](harnesses.md) and [shared UI rules](ui.md).

## Board and document contracts

`/assistant` is a chat-app **board**. Left rail = the things that genuinely need the user now; right pane = a live conversation about the selected one. The spirit: **awareness in, judgement-ranked attention out, chat to resolve, vault for memory.** Per-item compact conversation continuity persists locally; durable business outcomes still belong in the vault (`projects/`, `PRIORITIES.md`, `notes/`).


- **Conductor** (`assistant` skill, run as the `assistant` task in `tasks.yaml`): periodically reads the vault + connected tools, judges what needs the user, and emits a minimal ranked `items` doc (`{id,project_ref,title,why,situation,opening_move,action_owner,action_label,action_type,links,documents,new}` + `done_today`). `id` identifies one distinct attention item and stays stable while that reason remains open. `project_ref` optionally names the single canonical vault project directory, after the conductor verifies its README, but is context only: several items from the same project always retain separate conversations. Lifecycle state is unified under the gitignored `.roosta/state/assistant/` directory (`seen.json`, `handled.json`, `snoozed.json`). `action_type` is an optional visual category (`chat`, `ticket`, `email`, `standup`, `meeting`, `document`, `review`, `decision`, `task`); `normalise_board_doc` infers it from the proposed opening move when absent, so old cached items also get a clear badge. `action_owner` says whether the Assistant can handle the next move or the user must act; `action_label` supplies the specific button wording, with safe category-based fallbacks for older cached items. `links` is a short list of `{label,url}` direct CTAs (Teams permalink, Jira/PR URL, calendar/doc) - `_normalise_links` drops any non-http(s) link and caps at 4, so a fabricated or unsafe URL cannot render as a CTA. It also repairs group-chat links whose conversation id ends in `@thread.v2` by replacing channel-only query fields with `context={"contextType":"chat"}`; channel `@thread.tacv2` links remain unchanged. `documents` is a separate list of `{label,path}` CTAs for relative Markdown files inside the vault and outside `dashboard/`. `/document?path=...` renders them inside the app through the path-validated, read-only `/api/vault-document` endpoint. A scheduled feed's top-level `details.draft` is attached as `Open draft` to its matching item, including legacy rolling-comms output. The board **re-verifies live state each pass** and drops items resolved out-of-band rather than nagging from memory; it caps at ~5-7 items.

- **Vault documents stay one click away.** The chat prompt tells the actor to return created or
  referenced Markdown documents as relative Markdown links. As a backstop, the sanitised reply
  renderer turns an inline-code relative `.md` path into an in-app document link. Absolute paths,
  traversal, URLs and dashboard internals are never linked; the document endpoint still performs
  authoritative server-side path validation.

- **Documents can open their own chat.** The viewer's *Chat about this* opens
  `/assistant?item=doc:<vault path>`, a persistent standing thread like `person:` (no Close or
  Not now). `document_chat_item` resolves it through `resolve_vault_markdown`, so an invented or
  escaping path 404s, and sets `project_ref` when the document sits under `projects/<slug>/`.

- **The chat shows its document alongside.** `showDocPane` in `static/assistant.html` renders the
  first linked vault document (a `doc:` thread's own path, or an item's first `documents` entry) in a
  right-hand pane via `/api/vault-document`; hidden under 1100px, ✕ hides it until the next item opens. The pane shares the [manual Markdown editor](ui.md#workspace-and-documents). Editing works independently of the chat and its history.

- **The rail has two tabs: Inbox and Chats.** Inbox is what the assistant raises; Chats is what the user
  starts. `/api/board` returns `chats` (`chat_list`): every `chat:`, `worker:`, `hire:` and `doc:` thread with
  history, newest activity first, capped at 100. Opening a chat switches to its tab. The page names
  the chats it has opened in `/api/board?thread=` (`standing_thread_ids`, capped at 20) so only
  their transcripts come back with the board. The page sends one query parameter per id so document paths containing commas stay intact. The API also accepts legacy comma-separated `threads`.

- **✕ archives a chat, never deletes it.** `POST /api/chats/archive` records the close time and displayed
  title in `assistant/archived-chats.json` for chats with history. The Chats tab offers Undo for
  ten seconds. Settings previews the newest 10 still-closed chats and can expand to the latest 50 by close time
  (`GET /api/chats/archived`), including legacy timestamp-only records. A newer message brings
  a chat back automatically. Undo and Settings both call `POST /api/chats/restore {item_id}` and
  open the original thread. Its restore time ranks it among recent chats even if its last message
  predates the 100-row rail. Closing and restoring leave transcripts and running turns intact.

- **First conductor pass.** A successful `roosta snapshot board` with empty active and deferred
  card lists allows the conductor to start from an empty board before a cache exists. If the
  snapshot fails and the prior cards cannot be recovered from cache, the conductor reports an
  error without items so the runner carries its previous cards forward.
- **Scheduled sensor feeds.** Every scheduled task may return board-shaped items in
  `details.items`; there is no allowlist. `/api/board` merges each task's latest findings into the
  conductor snapshot by stable id (`merge_board_feed_items`). A repeated id **refines** the
  existing card: tasks apply oldest `last_run` first, supplied fields replace older wording (the
  conductor's included), omitted fields stay, links and documents combine, and an untitled update
  for an unknown id is dropped. Skills avoid duplicates by reading the board and reusing an
  existing card's id - see [board contract](../../src/roosta/skills/assistant/references/board-contract.md). Duplicates
  under different ids are resolved by the conductor's `details.merges` map, persisted by
  `ChatRouter.record_merges` in `assistant/merged.json` and applied via `resolve_alias` before
  merging; the card the user has a conversation on always keeps its id. A folded duplicate only fills
  blank fields and adds links and documents: the kept card is the conductor's synthesis, so it
  never takes the duplicate's title or wording.

- **Executive brief, not wall of text.** Each item answers what changed, why it matters now, and
  what happens next. Headlines carry outcomes rather than ticket lists; context is at most two
  short sentences; the recommendation is visually separated, names its owner, and uses a specific
  action button instead of a generic "Go". The card body fields (`why`, `situation`,
  `opening_move`) render Markdown via the same `md()`/`marked` path as chat - bullets, tables and
  inline links display in both streamed and restored replies. Rendered Markdown is reduced to an
  allowlist of structural tags and safe HTTP(S) links; `title` and labels stay plain escaped text.

- **Personal ordering stays local.** The rail can retain the conductor's recommended order or sort
  by newest, action type, or a visible 1-5 importance score calculated from urgency language,
  ownership, newness and decision work. Pinned items always stay above the selected order. Sort and
  pin preferences live in browser storage because they are presentation choices, not shared work
  state.

- **User-owned recommendations are display-only.** Only `action_owner: assistant` renders an action
  button that starts an empty-message AI turn. Items owned by the user (`action_owner: user`) show their full context and
  recommendation without triggering AI; direct destinations belong in `links`.

- **Model choice lives in Settings.** The chat rail has no account, model, effort or refresh controls. Settings applies its chosen model to subsequent turns on that provider; existing chats retain their account and conversation.

- **Composer hierarchy.** The paperclip menu (upload from this computer, or add from Workspace),
  textarea and Send share one compact row; upload and context-file tags sit above only when
  selected. Paste and drag-and-drop also upload. Group Not now and Close in the conversation header. Textarea growth never
  stretches adjacent buttons. The attachment SVG is inline: a cached external sprite can leave a
  newly added symbol blank even when the page HTML is fresh.

- **Uploads.** Files from the computer are stored under `assistant/uploads/<hashed item id>/`
  (item ids are untrusted, so never used in a path), at most 20 MB each, 8 per message and 200 MB
  per conversation. Image types are sniffed from magic bytes; everything else, including HTML and
  SVG, is served as a download with `nosniff`. The upload POST is a raw body and refuses
  cross-origin requests. A send carries `uploads: [id]`; the turn's item gains `uploaded_files`
  with workspace-relative paths the model opens with its own read tool, never inlined, so non-image
  formats depend on the harness. History stores `{id, name, size, image}` only. Archiving keeps
  files; firing a worker removes them.

- **Close feedback uses Tabler.** Show a dismissible native toast for a closed action and a native
  success alert with Undo in the completed conversation. Page JavaScript manages visibility and
  expiry; preserve the standard component appearance and reduced-motion accessibility.

## First-run AI prerequisite

`setup_item()` offers the deterministic `roosta-ai-setup` card whenever no AI connection can run,
including in an established workspace, because every chat and worker needs one; otherwise it
checks whether workspace setup is pending (an empty profile or an existing setup conversation).
The AI card stays until the default named account is connected and has installed software and a model when its provider requires one. The card points to the outstanding step for a saved account, including default selection, runtime installation, browser sign-in when Pi reports it missing, or model choice. A detected system Claude Code account explains login reuse. Its fixed Settings link needs
no model, and the page hides its composer and Close/Not now controls. The disclosed connection check
is optional. `/api/ai/connections.workspace_setup_ready` lets Settings show Continue workspace setup, a page-level notice above Your AI, only when the prerequisite
is satisfied, `roosta-setup` is not yet handled and `workspace_setup_missing` lists a concrete gap (name in PROFILE.md, an item under `## My priorities`, or no tasks; see `setup_gaps()`), which the notice names; the board then replaces the AI card with `roosta-setup`. Only this prerequisite pane
auto-advances when its source disappears. Cached/model items cannot replace either reserved setup id.
New first-run chats and stale setup requests return a Settings destination before creating a session
or invoking a harness. Existing conversations keep their history.

## Conversation lifecycle

- **Queued messages.** While a turn is in progress, further sends for the same item are queued
  server-side and run automatically when the current reply finishes. The UI shows a dashed
  "Queued…" bubble immediately; background turns rely on `/api/board` polling for the current reply’s progress.

- **Chat** (`chat.py`, `ChatRouter` + the `actor` skill): each turn runs on the chat's AI
  connection through `ai_backend.prepare` and `stream`, resuming that connection's session
  (Claude `--resume`, Pi `--session-id`, Cursor `--resume <chat-id>`).
  `start_turn` owns the run in a background task and puts events on a queue consumed by SSE, so
  changing page or losing the browser stream cannot cancel the model process. `GET /api/board`
  exposes active item ids and `chat_progress`, keyed by item id with the current `run_id` and
  display `label`. SSE events carry both ids. A transient `progress` event reports running
  status, tool activity or an explicit harness tool summary. Streamed and polled generic progress
  displays as “Thinking” with decorative dots that stay still under reduced motion. Specific
  labels such as tool activity and “Writing reply” stay static. Tool inputs, results and reasoning
  stay out of progress. Terminal events clear it, and history stores only the conversation.
  `SessionMap` (`assistant/sessions.json`), `TopicStore` (`assistant/topics.json`) and
  `ConversationHistoryStore` (`assistant/chat-history.json`) are keyed only by stable item id.
  History mutations require a readable store and atomically replace the file after writing.
  The handled, snoozed, reminders, raised and merged stores are `JsonFile`s, written through
  `paths.write_json` like every other state file, so a crash never leaves half a file.
  Non-UUID session ids are discarded. The history store
  preserves the visible transcript when the user switches tabs or reloads the app; the topic store
  keeps a compact rolling summary and verified `project_ref`, then rotates the raw model session
  every 24 turns. Project or topic metadata must never group chats because one project can have
  several unrelated live items. The actor reads a referenced project's README before acting and
  writes durable outcomes into that project unless a more specific linked note is the proper home.
  Live turns use the restrictive dashboard permission profile, so local outcome writes work while
  external actions remain blocked until the separate approved sender invocation.
  A live conversation must outlive the item leaving the board: the conductor drops items it
  considers resolved, capped out or aged off, so `api_board_chat` falls back to
  `ChatRouter.known_item` (topic record / transcript / handled note / live session) to keep
  answering instead of 404ing a thread the user is mid-conversation on; only a truly unseen id 404s.
  For the same reason `mark_handled` records the outcome but never wipes the session, topic
  summary or transcript - resolving an item still hides it from the rail, but a follow-up keeps its
  context. `ChatRouter.handled()` normalises an accidental `{"items": [...]}` wrapper (written by
  a misbehaving local-model pass) before board code reads it. Malformed values must never take
  down `/api/board`.
  `CHAT_PROMPT` tells the model to keep skill loading and tool use invisible before asking it to
  load `actor`; this ordering is deliberate because otherwise the model narrates the load before
  it has read the skill's output-discipline rules. Board replies must begin with the answer and
  default to 1-3 short sentences, under 80 words unless asked for detail. Factual synthesis from
  the vault or enterprise systems includes its strongest direct source links in the first reply
  and labels inference rather than making the user ask where it came from. `VisibleReplyFilter` is the
  hard backstop: it strips first-person preambles and opening progress narration such as
  "Investigating..." or "Updating the project README", including across streamed chunks. On
  Claude, `ToolRoundHold` drops any message text under 160 characters that is followed by a tool
  call, so progress lines go whatever their wording.
  A failed turn is never retried automatically, because local actions may already have occurred.

- **Every question is its own chat.** The Chats tab's *Ask anything…* box (or `?item=new`, which
  Workspace links use) mints `chat:<12 hex>` in the page; the server learns of it with the first
  message and titles it from that message. A chat uses the same actor and approval boundary as item
  chats, but has no Close or Not now controls and is never marked handled after acting. People ask
  roughly two messages per chat, so there is no single permanent General thread to reset.
  `hire:<12 hex>` (New worker) chats work the same way, listed in Chats and titled from the first message.

- **A new chat opens on ideas, and Chats always starts with one.** The Chats tab's first row is
  always *New chat* (an open, unsent chat takes that row rather than appearing twice), and switching
  to Chats while an inbox item is showing opens a new chat. Its greeting shows a grid of ideas;
  clicking one fills the composer, never sends. The ideas come from `GET /api/chat-ideas`
  (`load_chat_ideas`), which validates `.roosta/state/assistant/chat-ideas.json` - written weekly
  by the `chat-ideas` core skill (a starter task) from the workspace's priorities, projects and
  tools, kept to durable ideas that still hold a week later - and drops anything malformed; with none, the page's built-in
  `EXAMPLES` show. `idea_used` usage events record only whether a workspace or starter idea was picked.

## Endpoints

`GET /api/board` (rail + done-today + current chat histories + active chat ids +
`agent_up` + `health`), `POST /api/board/refresh` (trigger a conductor pass),
`GET /document?path=<relative-md>` + `GET /api/vault-document?path=<relative-md>` (read-only,
in-app vault Markdown; a chat-reply link to a vault `.html/.txt/.json/.yaml/.csv` file outside
dot-folders opens there too, shown as fenced read-only source with no doc chat; `.roosta/` config
is the one dot-folder exception (`is_workspace_config`), never `.roosta/state/`, even via a symlink;
a Markdown path must still be a visible Markdown path, outside `private/`, after symlinks resolve),
`POST /api/board/chat {item_id, message, context_paths?, uploads?}` (starts a detached turn and streams its queued events;
returns `202 {queued, position}` when a turn for that item is already running), `POST /api/chats/archive {item_id}`,
`POST /api/board/chat/upload?item_id=&name=` (raw file body) and `GET /api/board/chat/upload/{id}?item_id=`,
`POST /api/board/chat/{run_id}/approve {approved, edit?}`,
`POST /api/notify {title, body?, id?, url?, due?}` (any skill/script can push a notification straight
onto the board with one `curl "127.0.0.1:${ROOSTA_PORT:-7667}/api/notify"`; it becomes a `new` item held in
`_pushed_notifications` and merged into `/api/board`, so the desktop notifier fires it deduped by
`id` and closing it on the board clears it). Both the desktop app and the web board poll
`/api/board` every 5s, so a pushed item notifies and appears within a few seconds without any SSE.
With a future timezone-aware `due`, `/api/notify` instead persists a **file-backed reminder**
(see below) rather than an in-memory ping, so it survives a restart and surfaces only when due.
Endpoints acting on visible cards must resolve them through `collect_board_items`, which includes
conductor, sensor, pushed-notification and reminder sources.

## Recently closed + revive

`mark_handled` stores a compact `item` snapshot (title, why,
situation, action fields, links, documents, project_ref via `_closed_snapshot`) alongside the
`{result, at}` outcome so a closed item can be reviewed and revived with its original context;
`api_board_close` resolves the full visible item before closing. `/api/board` returns
`document.closed` (newest-first, capped 15) via `recently_closed`, each `{id, title, result, at,
action_type}` with title falling back to `known_item` for pre-snapshot records. `POST
/api/board/reopen {item_id}` calls `ChatRouter.unhandle` (drops it from `handled.json`, returns the
snapshot) and re-pushes it to `_pushed_notifications` under its **original id**, so the conversation
thread is preserved and no duplicate appears if the conductor still produces it. Revival is
in-memory: an item the conductor no longer knows about is lost on restart if not actioned. The rail
shows a collapsible "Recently closed" section with a Reopen button; a header search box (top right)
filters the rail client-side.

## Reminders (file-backed board cards)

A board chat can create a *new* standalone card - not
reschedule the current item - when the user says "remind me about X" / "put X on my board". The actor
emits `<<<REMIND>>>{title,body,due}` (validated in `chat.py`, `due` null = now, else a bounded
future tz-aware instant); `ChatRouter.add_reminder` persists it to the gitignored
`assistant/reminders.json` (`[{id,title,body,due,created}]`). This is deliberately distinct from
snooze: a reminder has no live conductor source, so it can't rely on conductor re-validation to
resurface - it must persist. Assistant, the Office count and Pulse share the active and later lanes: due reminders become
`new` rail items (notified, deduped by id); future ones join the `later` lane by `snoozed_until`
and auto-promote when due. Closing a reminder card runs `mark_handled`, which calls
`remove_reminder` so the store entry is dropped rather than leaking. `/api/notify` with a `due`
writes to the same store, so external scripts get scheduled reminders too.

## Board health (honest all-clear)

`board_health(states)` reports failed or stale
`BOARD_SENSOR_IDS` in `degraded`, plus failed non-sensor tasks in `automation_failures`.
`ok` remains the sensor-trust verdict used by Pulse. The Assistant status strip warns when its
picture may be incomplete or any scheduled automation has failed, and links to the Skill runner
for details. It informs, never blocks. `health.restart_pending` (`restart_pending()`) is true when
any `*.py` under `APP_ROOT` changed on disk after the server started (an editable install or an
upgrade under a running runner), and the strip then says "Restart Roosta to load the latest update".

## Turn protocol

the actor streams plain assistant prose (rendered as markdown via `marked`) and ends with one trailing marker carrying a compact `thread_summary`: `<<<STATE>>>{json}` (discussion), `<<<DEFER>>>{json}` (schedule a revisit of THIS item), `<<<REMIND>>>{json}` (create a NEW durable board card/reminder, optionally scheduled), `<<<PAUSE>>>{json}` (external send drafted - the chat stops, the UI shows inline Send/Cancel, and only on Send does the privileged `sender` skill perform it), `<<<DONE>>>{json}` (acted - UI auto-advances), or `<<<ERROR>>>{json}`. Markers are parsed in `chat.py` and never shown to the user. Optional `learned: [{path,fact}]` on `STATE`/`DONE` surfaces inline vault captures in the chat UI; the actor writes the canonical doc and appends `notes/assistant-captures.jsonl` in the same turn (see the actor skill). Deferral timestamps must include a timezone, be in the future and be no more than 366 days away.
The parser and UI also strip an accidental trailing `>>>` after marker JSON because models sometimes close the delimiter.
Before invoking `sender`, `normalise_sender_action` validates the actor's untrusted pause payload and maps its generic `{draft,target}` fields to the sender contract: `{text,target}` for messages, `{status,ticket}` for Jira changes, or `{project,ticket}` for new Jira tickets (target must be a bare project key such as `PROJ`). Unknown or incomplete action shapes are rejected.
Chat drafts and sends end with `[AI]`; the actor includes it in the
approval text and the sender adds it if absent as a final backstop. Email is unchanged.

**Attention scheduling:** "Not now" is a first-class outcome, separate from resolving an item. The
board offers allowlisted presets (one hour, tomorrow morning, next Monday) and stores the choice in
`assistant/snoozed.json` through `ChatRouter`. `GET /api/board` partitions the conductor's current
items into active `items` and a visible `later` lane. An expired item only resurfaces if the latest
conductor pass still says it needs the user, so the board never revives stale work from its own memory.
The user can use "Bring back" at any point. Marking an item handled clears any snooze for the same id.
The API accepts preset names rather than arbitrary timestamps, keeping the scheduling surface small
and validated. Conversational requests such as "bring this back in a few days" use the actor's
validated `DEFER` marker; the conductor reads the same snooze store and preserves a live episode
while it is parked.

## Approval lifetime

The approval endpoint requires a JSON boolean in `approved`. Invalid input leaves the draft pending.
Approval cards survive a dropped stream, not a restart. `/api/board` re-offers
`pending_approvals` until the user acts, so a queued turn or reload never loses a Send/Cancel card.
Held cards live in memory (`ChatRouter._paused`), so a runner restart drops them.

`teams`/`teams_message` and `jira`/`jira_ticket` remain accepted aliases for the generic `chat`
and `ticket` visual categories. Service-specific permalink and content repair stay URL/CLI matched.
A chat with a missing account recovers on its next turn. Pending approvals and approved sends stay tied to the drafting account. See [AI harnesses](harnesses.md).

## Starting a new conversation segment

The **More** menu offers **Start fresh** and **Continue with a summary** on inbox items,
general chats, worker 1:1s and document chats. Both keep the item id, subject, account,
model and visible transcript. Archive, Restore and inbox handling are independent.

`POST /api/chats/context` with `item_id` and `mode: preview` returns a local editable
handoff and a revision of this item's transcript, topic and session binding. A preview
does not write or contact a provider. Accept with that revision and mode `fresh` or
`summary`. Only the latter carries the supplied `handoff`. A changed revision, live or
queued turn, pending approval, or approved sender in flight returns 409.

Acceptance atomically replaces the topic record with a dated transcript boundary,
a reset turn count, the chosen summary and a flag requiring a new session. Session
allocation waits until the next turn owns the item lock. Board responses expose the
boundaries as message offsets for rendering. Legacy transcripts start at offset zero.
When a turn omits its summary or fails, any retained summary is labelled potentially
outdated in subsequent prompts. Legacy summaries have the same uncertain freshness.
