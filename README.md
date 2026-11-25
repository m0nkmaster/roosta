# Roosta

<img src="assets/roosta-pixel.png" alt="Roosta, an orange-hooded pixel character with glowing eyes and goggles" width="160" align="right">

**Your agentic office. Tiny desks. Proper work.**

Give your AI team jobs: research a topic, organise project notes, build something useful or keep an eye on what matters. Workers share knowledge of your priorities, learn from your feedback and bring findings and decisions to your Assistant board.

Your office runs on your computer, with its knowledge in readable Markdown files. Chat with the team, shape their jobs and watch them at work in the pixel-art Office. You set the direction. Roosta keeps the desks busy.

![Roosta's pixel-art Office, with AI workers at desks, in meeting rooms and around shared spaces](assets/office.png)

## Get started

Choose how to open your office. [Python in your browser](#run-in-the-browser-with-python) is the quickest way in. The [macOS app](#download-the-macos-app) gives you the same office with a Dock icon, menu bar controls and native notifications.

<a id="altenatively-run-in-the-browser-with-python"></a>

### Run in the browser with Python

On macOS or Linux, you'll need [Git](https://git-scm.com/downloads) and either [uv](https://docs.astral.sh/uv/getting-started/installation/) or [pipx](https://pipx.pypa.io/stable/installation/). Roosta needs Python 3.11 or newer. If you have **uv**, it can download Python for you:

```sh
uv tool install --python 3.11 roosta
```

If you use **pipx** instead, install a compatible Python first and select it by name (here, Python 3.11):

```sh
pipx install --python python3.11 roosta
```

Create your workspace and start Roosta. To use an existing folder of notes, substitute `roosta init --adopt <folder>` for the first command.

```sh
roosta init ~/workspace
roosta start
```

Leave that terminal open and visit [your Assistant board](http://127.0.0.1:7667/assistant). The default port is 7667, or ROOS on a phone keypad.

### Download the macOS app

Download the DMG for your Mac from [GitHub Releases](https://github.com/m0nkmaster/roosta/releases). Choose **arm64** for Apple Silicon (M-series) or **x64** for Intel. Drag Roosta into Applications, eject the disk image and open Roosta from Applications. Python comes bundled.

Releases are **self-signed and not notarised by Apple**. If macOS blocks a download you trust, go to **System Settings → Privacy & Security → Open Anyway** for Roosta and confirm.

On first launch, Roosta uses your configured workspace or creates `~/workspace`. If it finds an existing folder of documents or a compatible older setup there, it asks before adopting or migrating it. To update, quit Roosta and replace the app in Applications with the new copy. Your workspace lives outside the app.

### Set up your office

1. **Connect your AI.** On a fresh workspace, the board offers **Connect your AI**, or **Choose your Claude Code account** if Claude Code is already installed. Open AI settings to select **Use as default** on that account, or choose **Add and use as default** when adding your account. Install its software and complete any requested sign-in or model choice. The connection test is optional.
2. **Tell Roosta about your work.** Choose **Continue workspace setup**, then open **Set up your workspace** on the board. Roosta helps you describe your priorities, projects and tools, sets up a starter schedule and creates your first board card.
3. **Build your team.** Open Workers and choose **New worker** to describe a job. Each worker runs a named skill on a schedule. Visit the Office to find its desk and chat about the job.

Bring your own AI accounts. Use an OpenAI or Anthropic subscription, or pay separately for API usage. OpenAI, OpenRouter and local Ollama models run through the [Pi](https://pi.dev/) agent harness. A Cursor account runs through the [Cursor Agent CLI](https://cursor.com/cli) with a Cursor API key.

### Updating and diagnosing Python installations

Let active workers and chats finish, then run `roosta update` from the installation serving your workspace. Restart the runner (Ctrl+C and `roosta start` for the foreground setup above) or restart its existing service, then reload the dashboard. To preview the upgrade, use `roosta update --check`.

For a read-only health report, run `roosta doctor`.

To run Roosta in the background, open **Settings → Workspace and runner**. From a terminal, stop the foreground runner, run `roosta service install --workspace ~/workspace` with your workspace path, then follow the printed activation command for launchd on macOS or systemd on Linux.

<details>
<summary>Upgrade compatibility and diagnostic options</summary>

The updater looks for the latest stable GitHub release and a compatible, non-yanked wheel on PyPI. It keeps a current or newer version. It uses the original uv or pipx tool installation, or pip or uv in a standalone virtual environment. Source checkouts, bundled apps and installations with an unknown owner receive manual instructions.

Doctor checks the installation, runtimes, configuration, worker skills and directories, changes to core skills, and the local runner. It uses the workspace from `--workspace <folder>`, then `ROOSTA_WORKSPACE`, saved configuration or the current directory, in that order. Use `--offline` to skip release and local runner requests and `--json` for structured results. A blocking failure returns 1. Warnings and skipped optional features leave the exit status at zero.

Account and connector checks inspect configuration. To verify sign-in, use AI Settings or the connector's own login check.

</details>

## Inside your office

The Assistant board brings together what needs you now. Workers handle recurring jobs; the Office shows the team at work. Ask Roosta to build custom pages when you need another view of your work.

| Page | What you can do |
|------|----------------|
| Assistant (`/assistant`) | Review findings, make decisions and continue your chats |
| Office (`/office`) | See your scheduled workers in a pixel-art office |
| Workers (`/runner`) | Give workers jobs, set schedules, check run history and chat to refine their skills |
| Workspace (`/workspace`) | Search your shared knowledge and choose files as chat context |
| Pulse (`/pulse`) | Explore workspace activity and review pages that need attention |
| Custom pages (`/pages/<name>/`) | Use views Roosta builds for you with the `page-builder` skill |

### Skills give your workers their jobs

A skill is a set of instructions for one job. Roosta has built-in skills for keeping knowledge current, learning from feedback, improving the office and handling work that needs your approval. Add your own as your team grows.

| Skill | Job |
|-------|-----|
| `assistant` | Ranks findings and turns them into board cards |
| `chat-ideas` | Suggests useful new chats from your priorities, projects and tools |
| `actor` | Handles the chat on a card and drafts actions for approval |
| `sender` | Performs one action you approved |
| `workspace-gardener` | Digests, verifies, connects and tidies the workspace |
| `workspace-learner` | Learns from your AI chats and connected tools |
| `skill-auditor` | Reviews and improves the skill set |
| `workspace-new-project` | Scaffolds a project |
| `setup` | First-run setup and guided fork review |
| `connectors` | Connects a tool safely, with a catalogue of common ones |
| `page-builder` | Builds custom pages |
| `write-a-skill` | Writes and sharpens skills |
| `roosta-engineer` | Evolves your pages, tasks and skills from how you use them |

Workers and chats read core skills, their scripts and references, and the operating model directly from the installed package. In Settings → Workspace and runner, **Review customisations** opens an unsent chat draft comparing your local behaviour with installed core. You choose which preferences to keep. For terminal use, run the following commands from your workspace (or pass `--workspace <folder>` to workspace commands).

- **Add a preference.** `roosta skills extend NAME` prints the editable file at `.roosta/skill-extensions/NAME.md`. Roosta reads it after the skill on each turn. The installed instructions keep improving on upgrade. Additions cannot change approval, tool or output protocols.
- **Replace a skill.** `roosta skills fork NAME` pins a complete editable tree under `.roosta/skill-forks/NAME/`. Settings and `roosta skills status` identify forks and flag when the installed tree has changed since the fork was created.
- **Return to core.** Compare the fork with `NAME/` under the folder printed by `roosta skills path`. Move the preferences you want into an extension, then run `roosta skills use-core NAME`. With the runner open, the switch takes effect on restart so active turns can finish. The complete fork moves into `.roosta/skill-archive/forks/` for recovery. The same command archives a retired skill under `retired/`. Setup can help review scripts, references and behavioural differences before you switch.

**Upgrading an older workspace.** Run `roosta skills sync` to see pending changes. Let active runs finish, then restart to apply them.

- Roosta archives verified generated copies in `.roosta/skill-archive/`. Clean or missing copies use installed core. Edited or unverifiable trees become active forks for review.
- Roosta checks independent Claude and Agents copies separately. A clean Agents copy follows core even if the Claude copy differs. If both have edits, the Agents copy stays active and the Claude copy goes into the archive's `review-claude/` folder for review.
- Retired skills in the old lock survive as workspace forks. Other custom skills stay in place. Linked or incomplete trees remain available for review in Settings while other skills migrate.
- Roosta keeps the old lock and archives recognised generated operating models before installing a small pointer. Edited operating models and workspace instructions stay in place.

For standalone agent sessions, run `roosta skills instructions [NAME]` in the workspace. It prints the same operating model and effective file routes as dashboard turns. A same-named project or global skill cannot shadow installed core.

### Shared knowledge you own

Your office's knowledge lives in a local folder of Markdown files: your profile, priorities, project notes and skills. You can read and edit them yourself, or work with them directly from Claude Code, Codex, Cursor or Pi. The operating model is the set of conventions that helps agents use that knowledge consistently.

```
~/workspace/
  AGENTS.md            # your rules and standalone skill routing (CLAUDE.md points here)
  PROFILE.md           # who you are and how the assistant should sound
  PRIORITIES.md        # what matters now
  CONTEXT.md TOOLS.md  # your domain and your tools
  projects/ notes/ drafts/ analysis/ templates/
  .agents/skills/      # your custom skills (.claude/skills points here)
  .roosta/
    skill-extensions/  # additive instructions for installed skills
    skill-forks/       # explicitly pinned skill trees
    tasks.yaml         # the schedule
    connectors.yaml    # tool sign-in checks and write denials
    pages/             # your custom pages
    state/             # runtime state (gitignored)
```

### Choose your Workspace collections

In `WORKSPACE.md`, list the collection overviews you want to browse.

```markdown
# Workspace

- [Clients](Clients/README.md)
- [Projects](projects/README.md)
```

In `Clients/README.md`, explain the collection and list its members.

```markdown
# Clients

Current engagements, in review order.

- [North Coast](North%20Coast.md)
- [Acme](Enterprise/Acme.md)
```

Use the first inline Markdown link on each top-level list item. Paths are relative
to that index and case-sensitive. Encode spaces as `%20` or enclose the destination
in angle brackets. Headings and paragraphs are yours. The first occurrence sets the
order. Hidden, private, symlinked, external and missing targets are ignored.
Only collection members become stars, once per source path. A README's supporting
folder documents and a single page's list of linked documents can appear as moons.

Without `WORKSPACE.md`, Roosta shows existing `projects/*/README.md` overviews,
or the existing priorities and context pages if there are no projects. Creating an
empty index clears that selection. All knowledge still searches visible Markdown.

Use `topics/<tag>.md` for an introduction and a reading list alongside shared tag
discovery. Decisions and plans surface matching level-two sections from the source.
Optionally list sources in `Decisions.md` or `Plans.md`, for example
`- [Delivery sequence](Clients/Enterprise/Acme.md#delivery-sequence)` for a
`## Delivery sequence` section. Open source reads the whole document.

Constellation rings use the later of the page's valid `last_updated` and dated
`verified` entries. With neither, the page's own modification time is an estimate
and formatting that page can move its star. Editing a collection index or a supporting
file leaves its members' attention dates alone. Active or blocked pages drift after
30 days. An expired `stale_after` or missing verification brings an unfinished page
into review. Confirming records your profile reviewer and today's date.

## Safety

- By default, external writes (messages, tickets, pages, email) pause for **Send/Cancel** on the board. Only then does the `sender` skill run.
- In **Workers**, expand a worker and open **Settings → Unrestricted** to grant standing approval for any action, local or external; nothing is off limits. Clear the checkbox to revoke approval. Choose **Save** to apply the change to future runs. A worker already executing or waiting for another writer keeps its current permissions.
- Standard runs use permission guardrails that allow any local change but block secret access, external writes (git push, GitHub creates, curl/wget), write-shaped MCP tools and configured connector write commands. These are tool policies, not an OS sandbox; explicitly unrestricted tasks bypass them.
- Tasks marked as writers run one at a time; other tasks may run concurrently.
- Posts the assistant sends end with `[AI]`.

Connector write denials can be loosened per connector, never globally.

## AI connections

Settings → **Your AI** shows the account Roosta uses. Open **Model and reasoning** to choose a
model and its supported reasoning effort, or **Change AI or manage accounts** to connect another
account. Each account records its provider and billing route; model choice is saved separately.
API keys live in the OS credential store (Keychain on macOS). Account sign-in credentials stay in
Claude Code's or Pi's authentication storage; Roosta can also use your existing Claude Code login.
Choose **Use as default** on any connected account. The optional connection test makes one small
billable request to check that the model can read a temporary file. Choose **Cancel test** to stop it.

Anthropic models run through the unmodified Claude Code runtime. OpenAI, non-Anthropic OpenRouter
models and local Ollama models run through Pi. Anthropic models on OpenRouter are rejected: choose
an Anthropic connection explicitly. Roosta never automatically changes an account or billing route.

Chats retain their account when the default changes. Model changes in Settings apply to subsequent
turns on that provider; account and model controls live in Settings. Workers follow the connected
default when `connection` is omitted; choosing a named connection pins only that worker.
Disconnect lists affected chats, approvals and workers.
**Install / Update to latest** downloads the publisher's latest release and verifies its checksum,
preserving other CLI installs. Roosta runs the newest installed copy of Claude Code or Pi, preferring
your own installation when versions match. Updates are explicit and wait for active AI turns to finish;
there are no Roosta version pins or background downloads. Managed downloads support macOS and glibc
Linux on Apple/ARM64 and x64; Windows runtime installation is not implemented yet.

## Develop

**From a local checkout**, to work on Roosta:

```bash
git clone https://github.com/m0nkmaster/roosta.git && cd roosta
uv tool install --editable .      # `roosta` now runs this checkout
roosta init ~/workspace
roosta start
```

With an editable install, refresh the dashboard for HTML and CSS changes, restart the runner for Python changes, and start a new turn for core skill changes. For the optional macOS shell, including how to run it from source, build it, sign it and troubleshoot notifications, see the [desktop README](desktop/README.md).

Run checks from the repository root:

```bash
uv venv && uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
cd desktop && node --test
```

Architecture, decisions and gotchas: [AGENTS.md](AGENTS.md). Release notes: [CHANGELOG.md](CHANGELOG.md).

## Licence

Apache-2.0. The Office uses the [LPC Revised](https://github.com/ElizaWy/LPC) sprites (OGA-BY 3.0) and OFL fonts; Tabler is MIT. Credits are beside each vendored asset.
