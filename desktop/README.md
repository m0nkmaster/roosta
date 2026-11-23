# Roosta for macOS

Roosta gives your AI workers a shared workspace and an Assistant board. The recommended way to get started is [Python in your browser](../README.md#run-in-the-browser-with-python).

This directory contains the optional Electron shell for macOS. It adds a Dock icon, menu bar controls and native notifications. [Download the macOS app](../README.md#download-the-macos-app).

Release builds bundle Python and the Roosta backend. They can initialise a workspace without a separate Git or Python installation. Development builds use the installed `roosta` command.

## Behaviour

- Starts and supervises the FastAPI skills runner
- Opens `/assistant` as the main window
- Finds text in the current window with **View → Find in Page** or **Command+F** (**Ctrl+F** on Windows or Linux). Press **Enter** for the next match, **Shift+Enter** for the previous match and **Escape** to return to the page.
- Continues running in the menu bar after the window closes
- Sends native notifications once per confirmed new Assistant item and authentication failure
  episode, even while the window is focused; failed deliveries remain eligible for retry
- Opens notification clicks at the relevant Assistant item or runner task
- Shows the active Assistant count on the Dock icon
- Offers Restart Roosta from both the macOS app menu and menu-bar icon
- Shows latest skill output and recent run history in View Logs; runner diagnostics stay secondary
- Restarts a crashed runner twice, then stops the crash loop and reports it
- Reports a missing saved workspace and lets you choose another existing Roosta workspace
- Reuses a healthy runner already listening on `127.0.0.1:7667`

The app does not launch at login. Quitting it stops only a runner process that it started.

## Development

Install the checkout as the `roosta` command first (`uv tool install --editable .` from the repo
root), so the app runs your working copy rather than a released Roosta.

```bash
cd desktop
npm install
npm start
```

`npm start` uses `ROOSTA_WORKSPACE` if set, else the workspace `roosta init` last recorded in
`~/.config/roosta/config.json`, else `~/workspace`.

On packaged first launch, a non-empty folder without `.roosta` prompts for confirmation.
A compatible hidden setup folder offers **Migrate workspace**, carrying over workers, connections
and history; an ordinary folder offers **Adopt folder**, adding Roosta while keeping existing
documents and skills. Cancel makes no changes. Missing or empty folders initialise automatically.
Existing Roosta workspaces open directly. The CLI setup remains explicit during development.

## Build and install

With Node 22.12+ and a project Python environment installed, on a Mac of the target
architecture, from the repository root:

```bash
uv pip install -e '.[dev]' 'pyinstaller==6.22.3'
.venv/bin/python desktop/scripts/build-backend.py
cd desktop
npm ci
npm run setup:signing             # once, creates a local self-signed identity
npm run dmg                       # app, DMG and SHA-256 checksum under dist/
```

`npm run install:mac` instead builds and replaces `/Applications/Roosta.app`, removing `dist/`
after installation to avoid duplicate notification registrations. Run the backend build again
before packaging Python changes. Build arm64 on Apple Silicon and x64 on Intel; cross-compiling
the Python bundle is not supported. App and DMG versions come from `src/roosta/__init__.py`.
The bundle id is `com.m0nkmaster.roosta`.

`ASSISTANT_CODESIGN_IDENTITY` overrides the default `Assistant Local Notifications` identity.
Self-signing does not satisfy Gatekeeper: see [installation instructions](INSTALL.txt).
Python, static assets, policy templates and core skills ship inside the app. Settings installs verified standalone AI runtimes. Git, accounts and local-model downloads are separate. Workspace data never lives inside the app.

## GitHub Releases

From a clean `main` checkout, with your feature changes already committed:

```bash
python3 scripts/release.py ship 0.4.2 --note "Describe the user-visible change"
```

Run this from the repository root. It prepares the version/changelog, creates the release commit,
pushes `main` and the tag atomically, watches CI and prints the published release URL. If the
version and changelog are already committed, use `python3 scripts/release.py ship`.

The workflow tests and builds native Apple Silicon and Intel apps plus the Python wheel/source
archive. It verifies DMGs and packaged backends, publishes PyPI, then publishes the GitHub release
with matching downloads and changelog notes. A failed check prevents publication. Published files
are never replaced. **Run workflow** on `main` builds downloadable test artefacts without publishing.
See [release setup and recovery](../docs/development/releases.md), including the one-time PyPI
trusted-publisher setup; no PyPI API token is required.

No Apple account or signing secrets are needed. By default each CI build generates a disposable
self-signed identity. To preserve signing identity across releases (recommended for notification
continuity), export the existing `Assistant Local Notifications` certificate **and private key**
as a password-protected `.p12`, then set repository Actions secrets `ROOSTA_SIGNING_P12` (base64
of that file) and `ROOSTA_SIGNING_PASSWORD`. Never commit the certificate or password. CI imports
it into a temporary keychain and deletes that keychain after the build. A certificate created
this way is still self-signed; it does not enable notarisation.

For changes affecting first launch or sign-in, use a non-publishing workflow run to check the
artefacts on a clean Mac before tagging. CI validates the backend and bundle signature; it cannot
validate Gatekeeper interaction, notification delivery or real enterprise account access.
To update the bundled app, quit Roosta and replace it in Applications. Your workspace stays in its own folder.

`npm run icons` resizes `../assets/roosta-app.png` into every macOS Dock icon size
up to 1024px using macOS `sips`, then compiles the `.icns` with `iconutil`. It also copies
`../assets/roosta-pixel.png` to the dashboard logo/favicon and generates monochrome menu-bar icons.

## Notifications troubleshooting

Open **Apple menu → System Settings → Notifications → Roosta**. Turn on **Allow notifications** and choose your banner and sound preferences. If Roosta is missing, choose **Send Test Notification** from Roosta’s menu-bar icon, then check the list again.

The local self-signed identity is sufficient for banner + sound notifications; notarisation is
**not** required. If notifications go silently to Notification Centre with no banner or sound,
the cause is almost always one of these, in order of likelihood:

- **Duplicate Launch Services registration.** If both `/Applications/Roosta.app` and the
  `dist/…/Roosta.app` build output are registered under `com.m0nkmaster.roosta`,
  macOS can't decide which app owns the notification identity and downgrades delivery to
  Notification Centre only. `install:mac` removes the `dist` copy and re-registers the installed
  app as the sole owner. To check by hand: `lsregister -dump | grep -i Roosta.app` should show a
  single `/Applications` path. (`lsregister` lives under
  `CoreServices.framework/…/LaunchServices.framework/…/Support/`.)
- **Alert volume at zero.** Notification sounds use the *alert* volume, which is separate from
  output volume. `osascript -e 'get volume settings'` reports it; `set volume alert volume 75` fixes
  a silent-but-visible notification. `usernoted` caches the value, so bounce it (`killall usernoted`)
  after changing it.
- **Multiple displays.** Banners appear on one display only; on a multi-monitor setup they may be
  landing on a screen you aren't looking at.
- After any of the above, restart Roosta so it reconnects to `usernoted`, then use
  "Send Test Notification" from the menu-bar icon to confirm.

## Tests

```bash
npm test
```

The frozen backend collects keyring and its macOS backend for Keychain API-key storage. The
packaging smoke test checks the AI setup API and Settings with an empty home and restricted PATH.
