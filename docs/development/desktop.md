# macOS shell engineering notes

[Agent guide](../../AGENTS.md). Read before changing `desktop/`. Installation, signing and notification troubleshooting
live in [desktop/README.md](../../desktop/README.md).

`desktop/` is the preferred launcher on macOS. Release builds run the bundled `roosta-backend start`; development uses the installed
`roosta start`. Both run against the
workspace (`ROOSTA_WORKSPACE`, else the one `roosta init` recorded, else `~/workspace`), launches the command without a shell and adds the GUI-only
paths needed for local CLIs and Cursor Agent. A healthy process already on `127.0.0.1:7667` is reused and
never stopped by the app on normal launch. **Restart Roosta** also kills any external listener
on that port before relaunching, so dashboard HTML/API changes load without manually hunting stray
`uvicorn` processes. HTML routes send `Cache-Control: no-store` so the Electron shell does not
keep stale nav.

- The window opens on `/assistant`; closing it leaves the app and runner in the menu bar. Explicit
  Quit stops a runner the app owns after the window accepts closing. A renderer with unsaved
  document edits can request a native discard confirmation during navigation or quit.
- **View → Find in Page** targets the focused dashboard, recovery or logs window. `find.js`
  searches its WebContents and accepts commands only from the separate local find bar.
  Keep the controls outside the searched document and keep Find IPC out of the dashboard preload.
  Closing the bar clears highlights and returns focus to the page. Navigation, hiding or closing
  the window discards its search.
- Both the macOS application menu and menu-bar icon expose Restart Roosta.
- View Logs leads with each task's latest skill output plus recent run history. Raw Python/uvicorn
  output is secondary under a collapsed Runner diagnostics section.
- The app retries a crashed runner twice with backoff, then stops the crash loop and reports it.
- A missing saved workspace is reported before launch; recovery can choose and remember another existing Roosta workspace, then retry automatically.
- **Never enable a dev reloader without `reload_excludes` for runtime state.** Tasks write
  `.roosta/state/cache/*.json` and `.roosta/state/assistant/*.json`; watching those outputs can
  create a restart loop. The current `roosta start` and supervised desktop launch do not enable
  reload. Preserve that behaviour unless a development launcher explicitly excludes runtime files.
- **Check login shell startup if both Cursor and the runner fail to open.** Cursor gives an
  interactive login shell about 10 seconds to resolve `PATH`. The supervisor allows 30 seconds
  for the runner health check. Time `zsh -i -l -c exit` and check the Roosta port for a stale
  runner before relaunching.
- Native notifications are owned solely by the Electron main process. New board items from the
  conductor or a scheduled sensor feed notify once per id across restarts, including while the
  window is focused. An item is recorded as seen only after Electron emits `show`; failed or
  unconfirmed deliveries are released for retry. A sign-in wait notifies once per
  distinct reason and resets once no task is waiting on it. The tray menu reports notification health.
- Settings → Notifications writes `"notifications": false` to `~/.config/roosta/config.json`
  (absent means on). `deliverNotices` reads it before every delivery and, while off, confirms notices
  without showing them so re-enabling does not replay a backlog. The first-run prompt is skipped and
  the tray says "off in Settings"; **Send Test Notification** still works. Settings gives Mac users manual instructions.
  External links remain limited to HTTP and HTTPS.
- The local self-signed identity supports notifications without notarisation. If a notification
  reaches Notification Centre without a banner or sound, check for duplicate Launch Services
  registrations, a muted macOS alert volume and banners on a second display. See
  [Notifications troubleshooting](../../desktop/README.md#notifications-troubleshooting).
- Notification clicks deep-link to `/assistant?item=<id>` or `/?task=<id>` via `openNoticeTarget`;
  macOS `activate` must not reset that navigation to the generic Assistant home. The static pages must
  preserve those query-string entry points. Each notification's macOS `id` is its notice key
  (`item:<id>`), because clicks usually land in a later process (the runner restarts often):
  startup re-attaches handlers via `Notification.getHistory()` and a cold launch reads the key from
  the `ready` event's `launchInfo`. Without the key, a click just opens the default item.
- Renderer code has no Node integration. External links open in the default browser; only the
  localhost dashboard remains in the app window.
- **Keep the bundle id stable at `com.m0nkmaster.roosta`.** macOS associates notification
  permissions with this identity. The board page inside the app is called Assistant (Open Assistant,
  Refresh Assistant Now).
- The app does not launch at login and has no auto-updater. Electron's macOS notification API
  requires a stable code signature: run `npm run setup:signing` once to create the local
  `Assistant Local Notifications` identity, then `npm run install:mac` rebuilds and replaces
  `/Applications/Roosta.app`; release builds need a backend rebuild for Python/dashboard changes. Development still reads the installed checkout.
- The Dock icon uses `assets/roosta-app.png`. `desktop/scripts/create-icons.js` resizes
  this master with macOS `sips` into each icon size through 1024px, then compiles the `.icns`
  with `iconutil`. Do not redraw the approved artwork. The dashboard logo/favicon uses
  `assets/roosta-pixel.png`, copied to `static/favicon.png`; the tray stays monochrome for
  macOS template rendering.

## Release packaging

`desktop/scripts/build-backend.py` freezes the installed checkout using PyInstaller on the native
architecture. Data and dynamic imports must include the static UI, skeleton (including `.roosta`),
core skills, policy templates and uvicorn. The backend lives outside ASAR in
`Contents/Resources/roosta-backend/`; packaged launches and Repair never select or upgrade a
separate `uv tool` installation. First launch runs `init --skip-checks --no-git` only when `.roosta`
is absent. A non-empty folder requires a native confirmation via `confirmWorkspaceSetup`, shared
by launch, Retry, Restart and Repair. Detection is structural: one immediate hidden directory with
regular `tasks.yaml`, `connectors.yaml` and `skills.lock.json` files offers migration, without any
product-name checks or wording. Symlinked sources/markers are excluded; multiple candidates stop
without changes. After confirmation, recheck the source and destination, rename the source to
`.roosta`, and leave a relative compatibility symlink so existing skills and documents still work.
If creating that link fails, restore the original directory. Then run `init --adopt` to finish
setup and remember the workspace. With no compatible setup, offer adoption before `init --adopt`;
cancellation makes no changes and Retry asks again. Empty/missing folders initialise automatically;
existing `.roosta` workspaces need no prompt. A conflicting `.roosta` file is reported rather than
overwritten. Development keeps the CLI's explicit adoption requirement. Git is optional for boot;
AI runtimes are installed and repaired from Settings; standalone downloads need no system Node or Python. The frozen executable also dispatches `--claude-guard`
so Claude's external-write hook does not depend on system Python.

`npm run dmg` signs the app, verifies its signature and creates a compressed disk image with an
Applications shortcut, installation notes and SHA-256 checksum. The tag workflow builds arm64
and x64 independently, smoke-tests the packaged backend, then publishes PyPI and GitHub together
after validation. See [release automation](releases.md) for the single-command flow, trusted
publishing setup and failure recovery, and the desktop README for signing and clean-Mac checks. Self-signed
builds require a Gatekeeper override; no notarisation or automatic updates are implied.

Copy the frozen backend with `verbatimSymlinks: true`: Packager extraResource copying
rewrites framework links to absolute build-machine paths, which invalidates the signed app.

The frozen backend collects keyring and its macOS backend for Keychain API-key storage. The
packaging smoke test checks the AI setup API and Settings with an empty home and restricted PATH.

The dashboard's shared release notice and Settings check use the serving backend for
version and installation guidance. A frozen Mac backend links its architecture's DMG.
A shell attached to a Python runner shows that runner's instructions instead.
