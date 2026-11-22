---
name: setup
description: First-run and re-runnable setup for a Roosta workspace - interviews the user for their profile, priorities and tools, connects the tools they use (each install approved), turns on the starter schedule, creates a first real board card, trims parts of the operating model they don't want, and merges Roosta updates into skills they have edited. Use when the board's "Set up your workspace" card is opened, when the user says "set up Roosta", "redo my setup", "update my profile", or after a Roosta upgrade reports edited skills.
---

# Setup

You are setting up Roosta with the user: a workspace (this folder) run by an operating model (`.roosta/operating-model.md`), with the Assistant board as its main interface. Aim to finish in about ten minutes. Be warm and brisk: ask a few questions at a time, offer sensible defaults, and write as you go so nothing is lost if the user stops halfway.

Setup can run in a board chat or in `claude` in this folder. In a board chat, ask one short batch of questions per turn and end each turn as the `actor` skill says; installs and sign-ins still need the user's explicit yes.

## 1. Profile

Ask for: full name and what to call them, role and team, the assistant's name if they want one, tone (default "concise and direct"), language variant (e.g. British English), timezone and working hours. Write the frontmatter of `PROFILE.md` and a few lines under **About me** and **How I like to work**. A filled-in `name` is what retires the setup card.

## 2. Priorities and context

Ask what matters most over the next month or quarter: three to five things, in their words. Write them under `## My priorities` in `PRIORITIES.md`, exactly as said. Ask who they work with most and which systems or products their work touches; seed `CONTEXT.md` with short entries. Offer to create a project for each priority that is really a project (the `workspace-new-project` skill).

Ask how the user groups their knowledge. Offer to adopt the Markdown index convention
in the operating model using their existing pages. With their agreement, add
`WORKSPACE.md` and ordered links to collection overviews. Keep existing prose, link
order and omissions. A workspace without an index already has a read-only fallback.


## 3. Tools

Ask which tools they use day to day: chat (Teams, Slack), tickets (Jira, Linear, GitHub Issues), docs (Confluence, Google Docs, Notion), email and calendar, code (GitHub), data. For each, follow the `connectors` skill: check what is installed, propose the install with its exact command, **wait for approval**, have them sign in, add the connector with its check and write denials, and write the `TOOLS.md` entry. Skip any they don't want now; setup can be re-run.

Where they keep their task list (Notion, Things, Jira) goes in `AGENTS.md` as a one-line rule: the workspace never mirrors a task list.

## 4. Starter schedule

Copy the tasks in [references/starter-tasks.yaml](references/starter-tasks.yaml) into `.roosta/tasks.yaml`: the assistant conductor (every 15 minutes), the workspace gardener, chat ideas (weekly, the ideas a new chat offers) and the workspace learner. Explain each in one line. If they connected a chat tool, offer a watcher skill for it (written with `write-a-skill`, returning board cards per the board contract, `sensor: true` and `requires: [<connector>]`). New workers omit `connection` and follow the selected default in Settings → AI connections. Add a connected named connection id only when the user explicitly pins that worker to an account.

## 5. A first real card

From their priorities, pick the one with the clearest next step and create a board card for it: in a board chat end with `<<<REMIND>>>` (title, one-line body, `due: null`); from the terminal, `curl -s -X POST "127.0.0.1:${ROOSTA_PORT:-7667}/api/notify" -H 'content-type: application/json' -d '{"title":"...","body":"..."}'`. Tell them the conductor will start raising cards on its own within the hour.

## 6. Trim what they don't want

The operating model ships whole; setup removes rather than adds. Ask whether any part doesn't fit (provenance stamps, `## Related` tables, the dated-file convention, the `[AI]` footer on posts). Record each opt-out as a one-line rule in their `AGENTS.md`, which overrides the operating model. Never edit `.roosta/operating-model.md`; Roosta replaces it on update.

## 7. Finish

Commit what you wrote (`chore: set up Roosta`), staging files by path. Summarise in three lines: who Roosta thinks they are, what is connected, what runs when.

Then give **three to five things to try next**, each a sentence they could send as-is, built from what they just told you: one about a named priority ("What's the next step on the Q3 launch?"), one using a tool they connected ("Tell me which pull requests need me"), one that saves something ("Remember that…" or "Remind me on Friday to…"), and one that grows Roosta ("Build me a page that shows my projects by status" or "Write a skill that drafts my weekly update"). Say every new chat offers more ideas, rewritten from their workspace weekly by the chat-ideas worker, and that setup can be re-run any time. In a board chat, end with `<<<DONE>>>` and `acted: true`.

## Re-running setup

Read the current `PROFILE.md`, `PRIORITIES.md`, `TOOLS.md` and `.roosta/connectors.yaml` first and ask only about what is missing or changed. Never overwrite the user's own words; update in place.

## Merging Roosta skill updates

`roosta skills sync` updates core skills the user never edited and leaves edited ones alone. `.roosta/skills.lock.json` marks those `"modified": true` with `available` set when a newer version shipped. For each:

1. Find the shipped version: `roosta skills path` prints the folder holding Roosta's core skills.
2. Diff it against the user's copy in `.agents/skills/<name>/`, and explain in a few lines what Roosta changed and what the user changed.
3. Propose a merged version that keeps the user's intent and takes Roosta's fixes. Apply it only when they agree, then run `roosta skills sync` again so the lock records the new base.

## Related

| Link | Relationship |
|------|--------------|
| [[connectors]] | Connects each tool the user names |
| [[workspace-new-project]] | Turns priorities into projects |
| [[write-a-skill]] | Writes watcher skills for connected tools |
