# Changelog

Record each release newest first. Bump minor for features and visible behaviour, patch for fixes and polish.

## 0.23.2 - 2026-11-27

- A worker that follows your default AI account now only accepts a model that account offers, as pinned workers already did, instead of saving one it cannot run.
- Clearing the description of a worker added since Roosta started shows its skill's own description straight away.

## 0.23.1 - 2026-11-27

- Worker runs on your own Claude Code sign-in show their transcript again when you open them in AI Activity, and Cursor worker runs in another folder find theirs.
- Workers that fail because the network dropped or the computer slept retry in 15 minutes again, as the Skill runner's "offline · retrying" label promises. Workers and chats that lose the network now say the AI provider couldn't be reached.
- An offline retry that finds nothing new returns the worker to its normal schedule. Failed Cursor worker runs keep their session ID for AI Activity.

## 0.23.0 - 2026-11-27

- Roosta now says "workspace" everywhere it used to say "vault". Custom pages read documents from `/api/workspace/files` and `/api/workspace/document` instead of the `/api/vault/...` routes, the desktop menu's Vault Pulse is now Pulse, and the document page is titled Workspace document.
- The worker that keeps your Assistant board is called the Assistant (not the conductor) in the starter schedule, skills and docs.
- Pulse loads project briefs and saves weekly reviews through `/api/projects/<name>` instead of `/api/constellation/<name>`.
- Closing, reopening and snoozing board items and creating reminders now work even when no AI connection is ready.
- The Office page's code moved into separate, readable scripts, one per part of the office. The office looks and behaves the same.

## 0.22.5 - 2026-11-27

- Roosta refuses requests addressed to any host other than an IP address, localhost or your saved host, so a web page can no longer reach your workspace or start a chat through DNS rebinding.
- The document viewer and document chats no longer follow a link in your workspace into .roosta/state, a private/ folder or a non-Markdown file.
- Closed items, snoozes, reminders, worker state and Roosta's own settings save atomically, so a crash or force-quit can no longer leave a half-written file that empties them.
- Changing a chat's model before AI is connected now explains what to do instead of failing.
- Retired harness: and claude_model: keys in tasks.yaml are now ignored; set model: instead.
- Chats from before named AI accounts continue on your default account with a fresh session, keeping their history and summary. Settings no longer shows the Continue older chats card.

## 0.22.4 - 2026-11-27

- Assistant links to workspace skill files now open in the document viewer and jump to a matching section heading.
- Pi workers can read chat history when they run the bundled helper with Python bytecode writes disabled through `PYTHONDONTWRITEBYTECODE=1`.

## 0.22.3 - 2026-11-26

- `roosta usage` reads the workspace a worker is running in, not an older workspace saved in your config, so the engineer sees your real Assistant usage.

## 0.22.2 - 2026-11-26

- Removing a worker preserves neighbouring workers and leaves a valid schedule when the last worker is removed.
- Chat history saves atomically. A damaged transcript file is preserved for recovery. Send and Cancel require an explicit boolean approval.
- Desktop restart checks which process owns the dashboard port before stopping an external Roosta runner.
- Assistant, Office and Pulse agree on active and later board items. Pulse includes installed core skills and workspace forks in its skill count.

## 0.22.1 - 2026-11-26

- When you revise a ticket or other item it already drafted, the Assistant first checks whether you approved and created it, then drafts an edit instead of a duplicate. It also reads reminders from Roosta's state file directly, so it can confirm reminders that workspace search misses.

## 0.22.0 - 2026-11-26

- Collections can maintain themselves. Add `collect_tag`, `collect_path`, `collect_order` or `exclude` to a collection index's frontmatter and the workspace gardener adds matching pages on every pass, without removing or reordering your own entries.

## 0.21.4 - 2026-11-26

- A chat reply or worker run that starts while Settings is repairing its AI software now waits up to 10 minutes for the repair to finish, instead of failing straight away and needing a resend.

## 0.21.3 - 2026-11-26

- Continuing a chat whose AI account is missing starts a fresh session on your connected default account and keeps the conversation history and topic. Disconnected accounts stay pinned.

## 0.21.2 - 2026-11-25

- Workers use the running Roosta installation for board snapshots, including on a fresh Mac or with an older CLI installed. The Assistant can start from a confirmed empty board and preserves unresolved cards when it cannot read their prior state.

## 0.21.1 - 2026-11-25

- Settings refreshes when AI setup finishes or you return from sign-in. Add and use as default saves the first account choice so the board can continue workspace setup after a restart, without a connection test.

## 0.21.0 - 2026-11-25

- A failed worker run keeps its last board cards instead of clearing them, so one AI error no longer empties the Assistant board.
- Workers can change anything in the workspace: deleting files, `git reset` and `git clean` no longer need approval. External writes stay blocked.
- Workers already marked Unrestricted now have standing approval for any action, local or external. Roosta's own AI account credentials and package folder stay protected.
- The Assistant reads the live board with `roosta snapshot board`, which every worker may run.
- Setup counts a tool as connected only when it is callable in the session or its check passes.
- Cursor accounts use the Agent CLI and a Cursor API key. Concurrent turns have separate permissions and MCP settings. Each run uses its account’s key and discards any inherited Cursor API key.
- Existing named accounts are retained. If you used only the old CLI picker, configure or select an account in Settings. Check each worker’s connection before enabling its schedule. To keep Ollama work local, select Local (Ollama) and an installed model to run through Pi.
- Existing legacy conversations require an explicit account choice in Settings before any context is sent. Visible history and topic summaries survive, and the next turn starts a fresh provider session.
- Worker migration backs up `tasks.yaml` to `tasks.yaml.pre-0.21.0` and keeps the model used by the previous account or CLI. Custom YAML layouts stay intact and load in place.
- Worker permissions have two levels: the default, and Unrestricted. Legacy push flags and GitHub issue grants are ignored and never enable Unrestricted. `roosta doctor` flags enabled `allow_git_push` and `push_on_schedule` fields in `tasks.yaml`. Per-connection `issue-grants.json` files are outside that check.
- The board shows Connect your AI whenever no AI connection is ready, not only before workspace setup.

## 0.19.4 - 2026-11-24

- History listings provide the full transcript ID workers need. Workers can read the live board and task status with a local snapshot command.

## 0.19.3 - 2026-11-24

- Pi workers and Assistant chats can scan history with the bundled Workspace Learner helper and inspect individual installed source files while package writes remain blocked.

## 0.19.2 - 2026-11-24

- Document toolbars in Workspace, Assistant and the vault viewer group Edit and Copy together and use compact icons for saving, copying a draft and cancelling edits. Open full document stays in the current window.

## 0.19.1 - 2026-11-24

- Workspace Learner now retains queued human messages from Claude Code, preserving their order without counting duplicate representations.

## 0.19.0 - 2026-11-24

- Edit Markdown source in Workspace, the document page and the Assistant document pane. Preview changes before saving and keep your draft if the file changes elsewhere.
- Zoom the macOS dashboard from the View menu or with Command and the plus, minus or zero key. The zoom level follows you between dashboard pages.

## 0.18.1 - 2026-11-23

- Settings now shows `roosta update` for supported Python installations.
- Getting-started and release instructions lead with Python in the browser, with the macOS app alongside it as the second option.

## 0.18.0 - 2026-11-23

- Workers settings now let you grant or revoke Unrestricted standing approval from the next run.

## 0.17.3 - 2026-11-23

- Workers configured with `unrestricted: true` can carry out external actions explicitly directed by their instructions on both Run now and scheduled runs.

## 0.17.2 - 2026-11-23

- Active chats show “Thinking” with cycling dots until more specific progress is available. The dots stay still when reduced motion is enabled.

## 0.17.1 - 2026-11-22

- Fix file access for chats and workers using named AI connections. Review customisations can now read installed core skills, their references and the operating model.

## 0.17.0 - 2026-11-22

- Workers and chats use the installed core skills and operating model. Workspace extensions follow core improvements on every upgrade.
- Preserve legacy edits as reviewable forks. Settings and `roosta skills status` show pinned skills, available core updates and recovery copies.

## 0.16.0 - 2026-11-22

- Choose Workspace collections and Constellation stars through ordered Markdown links in WORKSPACE.md and collection overviews.
- Browse topic reading lists and source-linked decisions and plans. Review stars by their last substantive update or verification date.

## 0.15.0 - 2026-11-22

- Use roosta update to check for and install a compatible stable release in the current Python installation.
- Use roosta doctor to diagnose installation, workspace and runner issues with offline and JSON reporting options.
- Skip cmux terminal-specific Claude wrappers when finding AI software, so Roosta uses a direct Claude installation instead.
- Choose a connected AI account as default immediately, including while its optional connection test runs. Settings lets you cancel the test and keeps account controls available while model choices load.
- Workspace Learner reports actions queued for the workspace user under `queued_for_user`.

## 0.14.0 - 2026-11-22

- Code blocks in chats and item discussions have a Copy code button that copies the code with its spacing and line breaks.
- The Pulse and full-screen constellations follow all six appearance schemes. Switching schemes keeps your position, zoom, filters and selected project.

## 0.13.0 - 2026-11-22

- Settings shows the 10 most recently closed chats first. Use Show more to see up to 50 or Show less to return to 10.

## 0.12.0 - 2026-11-21

- Assistant chats show live reply status and available tool activity, including when you reopen a running chat. Progress clears when the reply ends.
- Roosta checks for stable releases in the background. Settings shows the running version and manual update instructions for the installation serving your workspace.
- Settings now shows Mac users how to enable banners and sounds manually and where to send a test notification if Roosta is missing from the list.

## 0.11.0 - 2026-11-20

- Office gains a fireplace and stockings, fridge and clock interactions, a second café table, dart challenges, on-demand foosball and console players, and scored table tennis.
- Office workers head back before their next shift and flag overdue starts; the lounge TV filters distressing headlines, and the click guide lists each room’s interactions.

## 0.10.2 - 2026-11-19

- Chat actions now end with a compact More button for Start fresh and Continue with a summary.

## 0.10.1 - 2026-11-19

- Make macOS release checks tolerate Chrome hanging after a complete layout-test result, while retaining all layout assertions and rejecting incomplete or failed output.
- Includes the latest chat improvements: Start fresh, editable summary handoffs, Undo and restore for closed chats, and desktop Find in Page.
- Also includes notification controls, resizable page columns, clearer worker settings and unscheduled skills, and workspace and named-connection improvements.

## 0.10.0 - 2026-11-19

- Use the Chat menu to start fresh or review and edit a summary before continuing. Earlier messages stay in the same chat behind a dated Previous conversation divider. The chat also shows when its model context refreshes automatically.

## 0.9.0 - 2026-11-19

- Closing a chat now offers Undo for 10 seconds. In Settings → Recently closed chats, restore any of the 50 most recently closed conversations and continue where you left off.

## 0.8.0 - 2026-11-19

- Press Command+F (Ctrl+F on Windows or Linux) to find text in the current desktop window, including chats, inbox items and runner logs. Enter and Shift+Enter move between matches, and Escape closes Find.

## 0.7.1 - 2026-11-19

- An expanded worker on the Workers page is easier to read. It opens with what the worker does and what its last run reported, including when it ran and how long it took, with the run's details folded away. Its settings now sit under a closed **Settings** section, grouped into Schedule, AI and Name. The details the row already shows are no longer repeated.

## 0.7.0 - 2026-11-19

- Turn the Roosta app's notifications on or off under **Settings → Notifications**. While they are off, new board items and sign-in waits still appear on the board but no longer pop up, and turning them back on does not replay what arrived in between. On a Mac, a link opens System Settings for banners, sounds and Focus.

## 0.6.0 - 2026-11-18

- The Workers page lists your workspace’s skills that no worker runs yet, under **Not on a schedule**. Click a skill’s name to read its SKILL.md, or **Schedule** to ask the Assistant to make it a worker; the request is filled in for you to edit before sending.

## 0.5.0 - 2026-11-18

- Workers using named connections can edit Roosta’s source when its checkout is the selected workspace. Connection credentials and managed runtime directories remain protected.

## 0.4.0 - 2026-11-18

- If the saved workspace has moved or been deleted, Roosta now says **Workspace not found** and lets you choose another workspace instead of reporting runner exit code `-2`.
- Workers now follow the connected default without writing a `connection` setting. Choosing a named account is the only action that pins a worker, and the ambiguous previous-setup choices are gone.

## 0.3.1 - 2026-11-18

- **Back to Pulse** on the full-screen constellation now returns to the Pulse page straight away, instead of doing nothing until you had selected a project.

- The Roosta worker now wears the mascot’s orange hood and purple goggles in the Office and crew portraits.

## 0.3.0 - 2026-11-18

- Grant a named worker standing approval to comment on open ready issues and add the in review label in one GitHub repository.

## 0.2.0 - 2026-11-18

- Resize the side-by-side columns on the Assistant, Workspace, Workers and Pulse pages by dragging the divider between them, or by focusing it and using the arrow keys. Double-click the divider or press Enter to restore the default. Each page remembers your widths, including after you restart the app.
- Roosta Engineer now improves your workspace exclusively. It drafts feedback for your review when a change belongs in the app.

## 0.1.3 - 2026-11-17

- The Assistant chat no longer asks permission again and again for workspace changes you asked for, and it points at the approval button instead of asking "Approve?" as a question. Typing "go" while a card waits gets a one-line pointer to the button, not a fresh draft.
- Workspace and Pulse now show only what a standard workspace holds: the People collection, the `people` front-matter attribution, and the constellation's People, Incidents and Notes layers are gone.
- The learner's chat helper dates each Assistant chat by its own latest message, so a scheduled pass reads only chats that really changed instead of every chat each time the history file is saved.
- The Workspace page has an **Open folder** button that opens your workspace in Finder (Explorer on Windows, your file manager on Linux). It works only on the computer running Roosta.

## 0.1.2 - 2026-11-17

- Fix macOS first launch in an existing folder: ask to migrate a compatible workspace setup or adopt the folder, preserving documents and skills.
- Brand the desktop loading screen with the Roosta character instead of generative art, and use it as the dock icon in development.

## 0.1.0 - 2026-11-17

- Initial release of Roosta, your agentic office.
