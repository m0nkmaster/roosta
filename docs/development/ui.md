# Shared UI, workspace and Pulse

[Agent guide](../../AGENTS.md). Read before changing any page. Paths beginning `static/` are under `src/roosta/`.
See [Assistant contracts](assistant.md) and [Office rendering](office.md) for page-specific details.

## Shared shell and components

- **Worker AI selection** uses the connected default when `connection` is absent. The Workers page shows one default choice that writes nothing to `tasks.yaml`; only choosing a named account persists a connection id.

- **Workers drawer.** An expanded worker shows its description and 1:1/Office links, any error or blocked message, then its last run (summary, time and duration, with details folded). Settings sit in a closed `<details>` grouped into Schedule, AI and Name; `openSettings` keeps it open across re-renders. Don't repeat row facts (schedule, runs, skill, status) in the drawer.

- **`static/nav-count.js`** - The one shared header. Every page, shipped or custom, carries an empty
  `<header class="workspace-header navbar" aria-label="Workspace"></header>` and loads this script, which
  renders the brand, the nav (shipped pages, then custom pages), the Assistant count and, top right, the
  version and a Settings cog. Settings is never a nav link; the macOS app menu also offers it (Cmd+,).
  Add or rename a nav link in the script's `NAV` list only, never in a page

- **`static/changelog.html`** - `/changelog`, renders `CHANGELOG.md` via `/api/changelog`, which
  also returns the version (the top `## x.y.z` heading). `nav-count.js` adds that version, linked
  here, to the top right of every page's header

- **`static/settings.html` / `ai-settings.js` / `theme.js`** - `/settings` leads with the default AI account and names the software it runs through. Existing Claude Code connections explicitly explain that Roosta reuses the login on this computer; a detected login can be selected immediately. Model and reasoning controls live in a disclosure, with a model dropdown grouped by connected account and an Effort dropdown when the selected model supports it. Supported effort levels load from the runtime and persist with the model choice. Choosing a model saves the default account and provider-scoped model together. Account setup lives under the collapsed Change AI or manage accounts disclosure (opened automatically on first load when no default exists). Account management and usage sit in per-account disclosures (usage lists at most the 10 most recently active chats per account; `chat_count` carries the total); missing software has an inline install action on the account; AI software also offers installation, Open in Terminal on macOS, and Update to latest under a closed Updates disclosure, preserving other installations. Terminal sessions use the CLI’s own login and settings, as explained beside the controls. Service names use Claude and ChatGPT / OpenAI; account names are optional. Add/edit forms have Cancel, clear credentials on exit and stay open across job polling; expanded account and software details also survive polling. Settings refreshes when the window regains focus and retries interrupted status reads after a setup action. The connections endpoint snapshots job statuses before discovering accounts and software so a completion during discovery gets one final poll. Model and effort requests run independently of job polling. Running tests show Cancel test, while Use as default remains available. Provider/billing guidance, official sign-in and the optional tool-use test remain part of setup. Settings shows a Continue workspace setup notice above Your AI only while setup is unhandled and a concrete output is missing (name, priorities or starter schedule), naming what is missing; chat history alone never shows it. A Workspace and runner card (`workspace-settings.js`) follows the account setup: active workspace and a Change workspace disclosure (select, create or adopt, with a Git option), the address `roosta start` will use (hidden for the desktop app; a non-loopback host needs an explicit confirmation), background-service status and install, and current core skills, workspace extensions and fork status. Review customisations opens a new chat with a draft naming the installed review procedure, active forks and archived alternatives. Nothing there switches or restarts the running runner; the Assistant’s preceding Connect your AI card links here without starting an AI turn. Appearance is a per-browser preference in `localStorage`. Every page loads `theme.js` undeferred
  right after `shell.css`, so appearance is set before first paint; the `storage` event keeps open
  pages in step. Appearance offers Purple (default), Slate, Midnight, Forest, Charcoal and Light,
  saved under `roosta-theme`. `theme.js` sets `data-roosta-scheme` plus Tabler's `data-bs-theme` mode.
  Saved `light` remains Light; legacy `dark` selects Slate. `roostaTheme.get()` and the theme event's
  detail remain `light`/`dark`; `roostaTheme.scheme()` returns the selected scheme. The light palette
  is one `[data-bs-theme="light"]` block in `shell.css` that redefines
  the `--console-*` and `--signal-*` tokens (signals darken to stay legible on white). Pages use those
  tokens (`--console-rail`, `--console-selected`, `--console-tint`, ...) rather than hardcoded dark hexes,
  or light mode leaves dark patches. The Pulse and full-screen constellation inherit the shell palette. Their canvas renderer
  reads the colour tokens on load and on `roosta-theme`, including changes from another tab.
  The existing animation loop paints the new colours with the current view and project positions.
  The Office canvas and Ceefax TV retain their artwork palettes.

- **Settings → Notifications** shows Mac users the manual path to Roosta’s notification preferences and points them to the menu-bar test notification if Roosta is missing.

- **Recently closed chats** in Settings shows the newest 10 threads on load and on return from the back/forward cache. With more than 10 available, Show more reveals up to 50 and Show less returns to 10. Restore opens the original conversation in Assistant. The Chats rail also offers a ten-second Undo toast. See the [chat archive contract](assistant.md).

- **Folder browsing** (`GET /api/settings/folders`) keeps listing readable folders when a child's
  `.roosta` marker cannot be inspected; that child has no workspace badge. An unreadable selected
  folder still returns an error. The endpoint remains restricted to local Settings requests.

- **`static/shell.css`** - Shared Tabler theme tokens, local Inter font, top navigation, page headers and focus
  styles; the default dark scheme uses deep purple surfaces, lilac highlights and warm amber accents beside the orange logo.
  Keep page-to-page shell geometry and palette here so switching views feels continuous

- **`static/column-resize.js`** - Resizable page columns. A page places an empty divider element on a
  column edge (styled by `.column-divider` in `shell.css`) and calls `roostaColumns.attach(divider, {id,
  label, target, container, variable, min, max, grow})`. The divider becomes a focusable vertical
  `separator` with `aria-value*`; dragging, the arrow keys (Shift for four times the step), Home/End and
  Enter or a double-click (restore the default) set one CSS width variable on the container, which the
  page's grid or flex rule reads with its default as the fallback. Widths persist per `page.column` id in
  `localStorage` under `roosta-columns` (the desktop origin is fixed, so they survive restarts), are
  re-fitted to `max` on window resize without being forgotten, and follow other windows via `storage`.
  The divider emits `roosta-columns-change` so canvases can redraw. Columns: Assistant inbox and
  document pane, Workspace Explore and results, Workers AI Activity, Pulse and full-screen constellation
  project details. Keep a minimum for the remaining flexible column in each `max`, keep each page's
  wiring in one script block (`test_columns.py` runs it against real CSS), and hide dividers in media
  queries where the layout stacks.

- **Responsive layout.** Settings fills the available window width. On narrow screens the Assistant's
  stacked inbox and conversation scroll within the main panel, with a minimum conversation height
  so short windows keep the chat and composer reachable. `test_layout.py` renders the real page CSS
  in Chrome without live APIs or polling to guard width and bottom-of-page access.

- **`static/vendor/tabler/`** - Pinned Tabler 1.7.3 core CSS and MIT licence; no build step or plugin JS

- **Brand artwork.** The shared header and browser tabs use `static/favicon.png`, copied from
  `assets/roosta-pixel.png` by `desktop/scripts/create-icons.js`.

- **Visual identity is a professional Tabler workspace.** Use the locally vendored Tabler core CSS,
  Inter and the shared theme in `shell.css`. A minimal horizontal bar carries navigation
  at the top; each page has a clear header. Assistant separates the inbox, conversation and optional
  document pane without an enclosing card or nested navigation frame. Keep full-width content with a fixed speaker
  column. Action types keep stable, restrained colours in tags and selection rules; statuses remain
  legible text with a dot. Avoid decorative metric rainbows, default blue branding, brown tones,
  narrow centred chats, pill-heavy controls and bespoke display typography.

- **Tabler owns components.** Use `.btn`, `.btn-primary`, `.btn-danger`, `.btn-outline-danger`,
  `.btn-ghost-secondary` and `.btn-sm`; inputs/selects use `.form-control`/`.form-select`, and panels
  use `.card`/`.card-header`. Do not rebuild a parallel control family in page CSS. Primary actions
  are violet, external approvals use danger, dismissive actions use ghost. Keep tags flat and
  smaller than buttons; status labels must never look clickable. `.task-status` is the runner's
  status hook, distinct from Tabler's category `.badge`.

- **Load locally, in order.** Every page loads `vendor/tabler/tabler.min.css` before `shell.css`.
  Tabler 1.7.3 was extracted from its integrity-verified npm archive; provenance and update guidance
  are in `static/vendor/tabler/README.md`. Keep the licence beside it. Existing JavaScript handles
  interactions, so neither Tabler nor Bootstrap JavaScript is needed. Inter is in `static/fonts/`.
  Page-local CSS describes workflow geometry, prose and state; shared branding and component tokens
  belong in `shell.css`. Navigation labels stay visible in smaller windows; only the brand text hides.
  Use native card bodies/headers, list groups, badges, alerts and dropdown items; do not repaint
  their borders, fills or padding locally. Grid rows may set their signal edge with a scoped selector
  (`.task-list .task-row`, `.item-list .item-row`) so Tabler's flush-list rule retains it.

- **No special-effect button variants.** Say what an action does; AI ornament adds no information
  when nearly everything is AI. Keep a clear distinction between saturated action buttons, tinted
  category tags and status text. External approvals must remain separate from ordinary chat sends.

- **CSS freshness.** `/static/*.css` is served `Cache-Control: no-cache`. Reloading picks up HTML/CSS
  changes without a runner restart or Electron rebuild. Electron's logs and recovery windows retain
  their separate styles.

## Custom pages

- **Custom pages** - static HTML/JS in the workspace's `.roosta/pages/<name>/`, served at
  `/pages/<name>/` and added to every page's nav by `nav-count.js` (from `/api/pages`, cached in
  `localStorage` so the link paints at once; folders that override a shipped page are not listed). They read
  only `/api/workspace/files?glob=` (frontmatter, no bodies), `/api/workspace/document`, `/api/tasks`,
  `/api/board`, `/api/profile` and `/api/pages/<name>/data/<file>.json`, which serves JSON skills
  write to `.roosta/state/pages/<name>/`. A page folder named like a shipped page replaces it
  (`pages.page_file`). There are no Python plug-ins: a missing capability becomes a generic API here.

## Workspace and documents

- **`static/document.html`** - Markdown viewer and source editor for validated workspace documents linked
  from Assistant items

- **`static/workspace.html` / `workspace.js`** - Fluid Tabler document navigator; in-memory literal
  search over `/api/workspace`, ordered Markdown collections, topics and decision/plan sections, highlighted previews and
  up to eight selected files; collection names, descriptions and membership come from workspace metadata.
  Open folder posts to local-only `/api/workspace/reveal`, which opens the active workspace (never a
  request-supplied path) in the OS file browser

- **Manual document editing** uses `static/document-editor.js` in Workspace, the standalone viewer and
  the Assistant document pane. Each document header groups Edit and Copy. In edit mode, Copy draft replaces the reader copy action. Icon controls have accessible names and hover titles. The editor loads raw UTF-8 from local-only
  `GET /api/workspace/document-source?path=…`. Save sends the source as UTF-8 plain text to
  the same URL with PUT and a quoted revision in If-Match. The 2 MB limit applies in both
  directions. Only visible Markdown files on macOS or Linux filesystems with atomic exchange qualify. Paths containing
  symlinks, multiply linked files and read-only files stay view-only. Saves lock the parent
  directory against other editor saves, stage in that directory, and recheck the live directory,
  file identity and bytes. Atomic exchange requires both names to exist and retains the displaced file
  for verification. A racing change rolls back. If another writer also interrupts rollback, the error
  identifies the retained file for recovery. The lock is advisory for external writers.
  Drafts live in the page until Save or confirmed discard. Copy draft includes frontmatter.

- **`static/safe-markdown.js`** - Shared sanitised Markdown renderer for document and Workspace previews

- **`static/markdown-copy.js`** - Copy-as-Markdown for the document page, Workspace preview and
  the whole Assistant board (items, chats, document pane; text fields keep native copy): `watch(selector)` makes highlighting (or Cmd+C) copy the selection via
  Turndown (CDN, GFM plugin); `copyMarkdown(text)` backs each Copy button. Copies use
  `execCommand('copy')` because the desktop app denies every permission, async clipboard included. Assistant chat and item code blocks have a keyboard-accessible Copy code
  button added after sanitisation. It copies the rendered code verbatim. Selections inside a block
  copy plain code, and selections spanning prose and code retain Markdown formatting.

- **Workspace search never runs AI.** `/api/workspace` returns visible Markdown contents with
  `no-store`; literal matching and highlighting stay in browser memory. Selected paths persist per
  chat, and `api_board_chat` reads full contents afresh (eight files / 192 KB total, no truncation).
  Queued turns retain their own item/context snapshot. Navigator links prefill, never auto-send.
  Collections use README titles/overviews/status, shared tags (inherited by supporting project
  documents), and optional topic reading lists.

## Pulse and constellation

Pulse counts the same installed and workspace skill names as Workers, once per name.

- **`static/pulse.html`** - Pulse telemetry page (workspace constellation first, then
  AI activity, live workspace stats and hot files); polls `/api/pulse`. `/constellation` serves the same file, which hides
  everything but the constellation when it sees that path

- **Workspace and Constellation share selected pages.** See the [portable index examples and fallback rules](../../README.md#choose-your-workspace-collections).
  `workspace.selected_collections` operates on the bounded visible catalogue. Workspace keeps
  source paths for search, previews and attachments. Constellation keeps legacy project slugs and
  uses a URL-safe encoding of the complete path for other stars. A review resolves the id against
  current membership. Topics and Decisions & plans are independent views onto the same sources.
- **Distance measures attention.** The drawer names its date source. Use the latest valid
  substantive update or verification date, falling back to that page's mtime. Rings, search,
  status, verification due, board links, related links and zoomed supporting pages share these
  signals. A board item can flag a selected source through its document links or its existing project reference.
  Review prioritises board attention, drift and verification. Confirmation records
  the profile reviewer and renews the verification window. Status changes date the update.
  The drawer, `?focus=` and the detail/review API all use the same star id. A review reads and
  saves through `document_editor.edit_document`, so it applies only to the revision it read and has
  the same [manual editing](#workspace-and-documents) save guarantees and refusals.

- **Ring radii scale with occupancy, and labels are rationed.** A busy "today" would otherwise
  collapse into a few pixels at the centre, so band edges are part evenly spaced and part
  weighted by how many projects sit in each; angles then relax apart, pushing harder on inner
  orbits where a radian covers less ground. Only the most notable few projects carry a resting
  label - the rest appear on hover - and labels are dropped where they would collide with
  another label or a board-flagged star.

- **Pulse is fluid.** Its `container-fluid` fills the window; do not cap `.pulse-main` or hide
  horizontal overflow to conceal layout errors. Verify at 1920px and 2560px as well as smaller sizes.

## Screenshotting a page

Never point a headless browser at `/`, `/assistant`, `/pulse` or `/office`. They hold an open SSE
connection and polling intervals, so the page never reaches a quiet network state,
`--virtual-time-budget` never settles and the capture hangs until killed - leaving orphaned Chrome
processes and a temporary profile directory behind. Build a throwaway static harness that imports
the real `shell.css` and the page's own styles, screenshot that, then delete it.

For collection QA run the static interaction probes from the checkout on a host with Chrome:

```sh
.venv/bin/python -m pytest -q tests/test_collection_ui.py --basetemp=/tmp/roosta-collection-qa
```

Use a fresh temporary directory for each run. Pytest replaces its base directory.
The probes use the shipped page, styles and scripts, a synthetic Markdown workspace, and
in-memory API responses. Set `ROOSTA_QA_MARKED` to a trusted local copy of
`marked/lib/marked.umd.js` for visual QA. Each fixture copies it alongside its HTML.
Without the variable, the interaction probe uses a text-only parser. The fixture
removes remote scripts and turns off intervals and animation scheduling. At 1440 and 480 pixels they click
through collections, section previews, attachments, star search, filters and review.
Each case leaves a standalone `workspace.html` or `pulse.html` beside its mock workspace.
For a screenshot, open that generated file at its test width or pass its file URL
to Chrome with `--headless=new --allow-file-access-from-files --window-size=1440,900
--screenshot=/tmp/roosta-collection.png`.

The Assistant **More** menu opens a local handoff preview or a Start fresh confirmation.
Cancel and Escape dismiss the preview. After acceptance, each previous segment is
readable through a collapsed, dated **Previous conversation** disclosure. Automatic
24-turn rotation displays a small context refresh indicator in the conversation header.

## Release notices

The shared header checks the cached release status on page load and once a minute.
A newer release gets a dismissible notice once per release per tab session, with release
notes and a link to Settings. Settings reads the running backend version and can request a
fresh check through the existing loopback and same-origin guard.
