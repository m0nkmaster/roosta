<!-- Read from the installed Roosta package. Put your own rules in AGENTS.md. -->

# The Roosta operating model

This workspace is a thinking space for AI-assisted knowledge work, not a codebase. Markdown is the default format; clear prose beats code. Any agent (Claude Code, Codex, Cursor, pi) follows these rules; the workspace `AGENTS.md` adds the owner's own rules on top, including team conventions. Roosta’s tool permissions, external approvals and output protocols always apply.

## Start here

1. `PROFILE.md` - who you work for: name, role, tone, language, hours.
2. `AGENTS.md` - the owner's rules and one-line routes to everything else.
3. `PRIORITIES.md` - what matters now. It is not a task list.
4. `CONTEXT.md` - the domain: teams, systems, vocabulary.
5. `TOOLS.md` - every connected tool: how to reach it, auth, known failure modes.

## Capture learnings (always)

Whenever you learn something durable - a correction, a gotcha, a tool quirk, "it works like X not Y" - write it down before the session ends. Nothing is remembered unless it lands in a file.

- **Where:** the canonical home for the topic: a project README, `CONTEXT.md`, `TOOLS.md`, a note or a skill. `AGENTS.md` holds rules and one-line routes, not reference detail.
- **How:** one sharp line, deduped against what is already there. Prune vague or stale entries rather than piling on.

## Provenance

Docs go stale silently, so record when a doc was last **checked against its source of truth**, not just edited. Any doc may carry:

```yaml
verified:                        # newest first
  - { by: human:<owner-slug>, at: 2026-11-05 }
  - { by: workspace-gardener/<model-id>, at: 2026-10-20 }
stale_after: 2026-12-05          # re-verify on or after this date
```

- `last_updated` dates the last substantive update; `verified` says someone checked what it claims and found it current. Never add a `verified` entry for an edit alone.
- Actors follow the [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) v0.2: `human:<owner-slug>` only when the owner says in the session that they have read the doc and it is right; `<skill>/<model-id>` when an agent checked it; `process:<name>` for model-free automation.
- Set `stale_after` with every `verified` entry: 30 days for active projects, 90 for paused or blocked ones, none for completed projects and timeless notes.
- Treat an unverified or expired doc as a lead to check, not as fact.

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

## Projects

Every project is a kebab-case folder under `projects/` with a `README.md` entry point. No per-project `AGENTS.md`; agent reading order goes in the README's `## For AI agents` section.

```yaml
---
title: Project title
status: active        # active | blocked | paused | completed
last_updated: 2026-11-12
owner: <owner name>
tags: []              # optional; also people, repos, links
---
```

Required sections: `## Overview`, `## Current state` (keep it fresh and bump `last_updated`), `## Key people`, `## Links`. Optional: `## Key decisions`, `## History`, `## Related`, `## For AI agents`. Supporting files (`notes/YYYY-MM-DD-topic.md`, `decisions.md`, `plan.md`, `assets/`) appear only when there is real content. The `workspace-new-project` skill scaffolds a compliant folder.

## Linking

Docs connect deliberately through a `## Related` table:

```markdown
## Related

| Link | Relationship |
|------|--------------|
| [[other-project]] | Shares the same launch date |
```

Link projects by bare slug, keep links two-way (the gardener maintains this), and add real connections only. A skill's `## Related` links only to other skills, so skills stay portable.

## Folders

Flat, descriptive, one purpose each: `projects/`, `notes/`, `drafts/`, `analysis/`, `templates/`, `.agents/skills/`. Files are kebab-case Markdown; date-sensitive files carry the date (`2026-02-09-weekly-plan.md`). Don't assume structure exists: suggest a home before creating a new folder.

## Safety

- **No external side effects without the owner's explicit approval.** Never post messages, create or change tickets, edit wiki pages, send email, trigger jobs or deploy unless the owner says yes to that exact action. In the Assistant, drafts pause for Send/Cancel.
- **Never print a process environment.** `env`, `printenv`, `ps eww` and dumping `.env` put every secret into the transcript. Test a variable with `[ -n "$VAR" ]` instead.
- **Attribute AI-written posts.** Every message the assistant sends on the owner's behalf ends with the visible footer `[AI]`.
- **Install on approval.** Find and install a CLI or MCP server when a task needs it, but only after the owner approves that install.

## Working style

- Be concise. Docs are for the owner's own use: no boilerplate or filler.
- Write in the language variant `PROFILE.md` names.
- Bias towards skills and conventions over code. Before adding bespoke code, check whether clearer skill guidance, an existing tool or a simple data convention does the job.
- Fix skills at the model, not the question: when a real question exposes a skill gap, revise the section whose framing caused it.
- Corrections leave no trace: rewrite the final version as if the mistake never happened.
- The owner may dictate. Odd words are usually speech-to-text errors; read them phonetically first.
- Conventional commits, one short line. Stage files by path, never `git add -A`.

## The Assistant

Roosta's app is one interface onto this workspace, not a requirement. Its config is `.roosta/`: `tasks.yaml` (the schedule), `connectors.yaml` (tool sign-in checks and write denials), `pages/` (custom pages), `office-cast.yaml` (how Office workers look). Runtime state lives in the gitignored `.roosta/state/`. Ask the `page-builder` skill for a new page and the `connectors` skill to connect a tool.

## Things to ask

When someone asks what the assistant can do, answer with examples that fit their `PROFILE.md`, `PRIORITIES.md` and connected tools, drawn from:

- **Focus:** "What should I focus on this week?", "What's slipping?", "Prep me for my 1:1 with Sam."
- **Projects:** "Start a project for the launch", "What's the current state of X?", "Who's involved in Y?"
- **Memory:** "Remember that we decided Z", "Remind me on Friday to chase the review", "What did we decide about X?"
- **Drafting:** "Draft a reply to that thread" (it waits for your Send), "Turn these notes into a weekly update."
- **Tools:** "Connect GitHub", "What tools are connected?", "Why is the Jira check failing?"
- **Roosta itself:** "Build me a page that shows X", "Write a skill that does Y every Monday", "Run the gardener now."

