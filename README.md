# Roosta

<img src="assets/roosta-pixel.png" alt="Roosta, an orange-hooded pixel character with glowing eyes and goggles" width="160" align="right">

**Your agentic office.**

Hi, I'm Roosta - I help you run a team of AI workers that get to know your work and then get on with it - all on your computer.

Give your workers jobs. They research, organise, build and keep your projects moving, drawing on shared knowledge of your priorities, projects and preferences stored in simple, readable, markdown files. Your team learn from your feedback, improve their skills and bring you the decisions that need your attention.

Watch them work in your pixel-art office, talk to them directly, and shape the team around what you need. You set the direction, hire and fire. Your agents get to work.

- **A team that knows your work.** Workers share a workspace of project knowledge, priorities and preferences, so each job can build on what came before.
- **Work that keeps moving.** Give recurring jobs to workers that run on a schedule, from researching a topic to keeping project notes current.
- **An office that gets better.** Workers maintain shared knowledge, learn from your conversations, refine skills and improve your setup.
- **Stay connected.** Roosta manages your AI connections and the tools your workers use, helping you connect the services you work with and keep sign-ins working.
- **You stay in charge.** Review findings, guide workers and approve messages or other external actions before they happen.

Named after a resourceful, unconventional problem-solver, Roosta is about taking initiative and finding a way through the chaos. 

![Roosta's pixel-art Office, with AI workers at desks, in meeting rooms and around shared spaces](assets/office.png)

## Get started

### Download the macOS app

Download the dmg for your Mac from [GitHub Releases](https://github.com/m0nkmaster/roosta/releases):
**arm64** for Apple Silicon, **x64** for Intel. Drag Roosta into Applications, eject the disk
image, then open it.

Roosta releases are **self-signed and not notarised**. If macOS blocks the first launch, use
**System Settings → Privacy & Security → Open Anyway** for Roosta and confirm.
The first launch creates `~/workspace` (or uses your previously configured workspace).
If the folder already contains files, Roosta asks before changing it: migrate a compatible
workspace setup, or adopt a folder of documents. Cancelling leaves the folder untouched.

### Set up your office

1. **Connect your AI.** On a fresh workspace, the board offers **Connect your AI**, or **Choose your Claude Code account** if Claude Code is already installed. Open AI settings to select **Use as default** on that account, or connect another account and install its software.
2. **Tell Roosta about your work.** Choose **Continue workspace setup**, then open **Set up your workspace** on the board. Roosta helps you describe your priorities, projects and tools, sets up a starter schedule and creates your first board card.
3. **Build your team.** Open Workers and choose **New worker** to describe a job. Each worker runs a named skill on a schedule; chat with it to refine the job, and see it in the Office.

Bring your own AI accounts. Use an OpenAI or Anthropic subscription, or pay separately for API usage. OpenAI models run through the [Pi](https://pi.dev/) agent harness.

### Altenatively, run in the browser with Python

You can also run Roosta in a browser on macOS or Linux. Python installs need Python 3.11+ and git; no separately installed agent CLI is required.

```bash
uv tool install roosta            # or: pipx install roosta
roosta init ~/workspace
roosta start                      # http://127.0.0.1:7667/assistant (7667: R-O-O-S on a phone keypad)
```

Connect your AI and follow the setup steps above. Run Roosta in the background with `roosta service install` (launchd on macOS, systemd on Linux). Settings also covers the workspace, address, background service and core skill ownership, without a terminal. Converting a folder of notes you already have? `roosta init --adopt <folder>` adds Roosta without touching your files.

### Updating and diagnosing Python installations

Run `roosta update --check` to preview the latest stable GitHub release. Run `roosta update` to install it in the environment that supplied this CLI. Python upgrades require a matching, non-yanked wheel on PyPI for your Python version. A current or newer CLI stays in place. Roosta uses the owning uv tool or pipx installation, or the original pip or uv installer in a standalone virtual environment. Source checkouts, bundled apps and installations whose owner cannot be identified receive manual update instructions. After an upgrade, restart the runner serving your workspace to use the new core skills.

Run `roosta doctor` for a read-only report. Workspace selection follows `--workspace <folder>`, `ROOSTA_WORKSPACE`, the saved configuration, then the current directory. Use `--offline` to skip the public release and local runner requests, and `--json` for structured checks and counts.

```sh
roosta doctor --workspace ~/workspace --offline --json
```

Doctor checks installation and runtime availability, configuration, worker skills and directories, core skill drift, and the local runner. Account and connector checks inspect configuration only. To verify sign-in, use AI Settings or the connector's own login check. Warnings and skipped optional features leave the exit status at zero. A blocking failure returns 1.

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

A skill is the backbone of Roosta's workers, there are a set of instructions for a job. Roosta has built-in skills for keeping knowledge current, learning from feedback, improving the office and handling work that needs your approval. Add your own as your team grows.

| Skill | Job |
|-------|-----|
| `assistant` | Conductor: ranks what needs you into board cards |
| `chat-ideas` | Suggests useful new chats from your priorities, projects and tools |
| `actor` | The live chat on a card; drafts actions, never sends them |
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

On startup, Roosta moves verified generated copies into `.roosta/skill-archive/` and uses installed core. A missing copy also uses installed core. An edited or unverifiable tree becomes an active fork for review. An independent Claude copy is checked separately. A verified clean Agents copy continues to follow core even if the Claude copy differs. When both contain changes, the Agents copy stays active and the Claude copy is archived under `review-claude/` inside the archive and listed for review. Retired skills present in the old lock survive as workspace forks. Other custom skills remain in place. The compatibility command `roosta skills sync` reports pending changes. Restart after active runs finish to apply migration. Roosta keeps the old lock and archives recognised generated operating models before installing a small pointer. Edited operating models and workspace instructions stay in place. Linked or incomplete skill trees stay available for review in Settings while other skills migrate.

For standalone agent sessions, run `roosta skills instructions [NAME]` in the workspace. It prints the same operating model and effective file routes as dashboard turns. A same-named project or global skill cannot shadow installed core.

### Shared knowledge you own

Your office's knowledge lives in a local folder of Markdown files: your profile, priorities, project notes and skills. You can read and edit them yourself, or work with them directly from Claude Code, Codex, Cursor or pi. The operating model is the set of conventions that helps agents use that knowledge consistently.

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

- External writes (messages, tickets, pages, email) pause for **Send/Cancel** on the board. Only then does the `sender` skill run. A worker can have standing approval to comment on open `ready` issues and add `in review` in one repository. See [worker grants](docs/development/runner.md#standing-approval-for-issue-updates). A separately approved task may run exactly `git push origin main` in one named repository; scheduled pushes also require `push_on_schedule`.
- In **Workers**, expand a worker and open **Settings → Unrestricted** to grant standing approval for external actions explicitly directed by its instructions, subject to user and workspace restrictions. Clear the checkbox to revoke approval. Choose **Save** to apply the change to future runs. A worker already executing or waiting for another writer keeps its current permissions.
- Standard runs use permission guardrails that block secret access, destructive git, write-shaped MCP tools and configured connector write commands. These are tool policies, not an OS sandbox; explicitly unrestricted tasks bypass them.
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
cd desktop && npm install
npm start                         # run the app from source, no install
npm run setup:signing && npm run install:mac   # or install it into /Applications
```

With the editable install, dashboard HTML and CSS changes show on reload, Python changes after **Restart Roosta**, and core skill changes on the next turn; none needs a rebuild. Only changes under `desktop/` need `npm start` again or a fresh `npm run install:mac`. Notifications, signing and troubleshooting: [desktop/README.md](desktop/README.md).

Run checks from the repository root:

```bash
uv venv && uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
cd desktop && node --test
```

Architecture, decisions and gotchas: [AGENTS.md](AGENTS.md). Release notes: [CHANGELOG.md](CHANGELOG.md).

## Licence

Apache-2.0. The Office uses the [LPC Revised](https://github.com/ElizaWy/LPC) sprites (OGA-BY 3.0) and OFL fonts; Tabler is MIT. Credits are beside each vendored asset.
