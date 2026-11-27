---
name: setup
description: First-run and re-runnable setup for a Roosta workspace - interviews the user for their profile, priorities and tools, connects the tools they use (each install approved), turns on the starter schedule, creates a first real board card, trims parts of the operating model they don't want, and reviews legacy skill customisations. Use when the board's "Set up your workspace" card is opened, when the user says "set up Roosta", "redo my setup", "update my profile", or to review workspace forks.
---

# Setup

You are setting up Roosta with the user: a workspace (this folder) run by the installed operating model, with the Assistant board as its main interface. Aim to finish in about ten minutes. Be warm and brisk: ask a few questions at a time, offer sensible defaults, and write as you go so nothing is lost if the user stops halfway.

Setup can run in a board chat or in `claude` in this folder. In a board chat, ask one short batch of questions per turn and end each turn as the `actor` skill says; installs and sign-ins still need the user's explicit yes.

## 1. Profile

Ask for: full name and what to call them, role and team, the assistant's name if they want one, tone (default "concise and direct"), language variant (e.g. British English), timezone and working hours. Write the frontmatter of `PROFILE.md` and a few lines under **About me** and **How I like to work**. A filled-in `name` is what retires the setup card.

## 2. Priorities and context

Before suggesting projects or collections, take a quick, read-only look at the workspace. Start with the top-level folders and loose files. Read any existing `WORKSPACE.md`, README and a few representative Markdown headings in likely work folders. For mixed files such as PDFs, spreadsheets and images, use names and location as clues. Stay within the workspace and skip hidden, private, symlinked and generated content. If you find only starter files, go straight to priorities.

For a populated folder, describe the pattern you see in a sentence or two, using actual paths. Ask one focused question about anything that would change your suggestion. For example, “I found `Clients/Acme/brief.md` and several loose Acme spreadsheets. Is the brief where you start client work?” If the layout is ambiguous, ask which file they usually open first.

If moving files would help the user find related work, offer a small batch of moves. Show each current path and proposed destination relative to the workspace, and ask which moves they want. Move only the files they select. Check that both paths stay inside the workspace without crossing symlinks, and skip any occupied destination. Update affected workspace links, including relative links inside moved notes, then verify they resolve and report which files moved.

Ask what matters most over the next month or quarter: three to five things, in their words. Write them under `## My priorities` in `PRIORITIES.md`, exactly as said. Ask who they work with most and which systems or products their work touches; seed `CONTEXT.md` with short entries. Reuse an existing project page wherever it lives. Offer `workspace-new-project` when a priority needs a new project.

Use the user's groupings and vocabulary to suggest a small set of collection links, with the actual Markdown pages each would open. If a useful group has no overview, offer to write one. With their agreement, add the chosen links to `WORKSPACE.md` following the operating model. Preserve existing prose, link order and deliberate omissions. A workspace without an index already has a read-only fallback.


## 3. Tools

Ask which tools they use day to day: chat (Teams, Slack), tickets (Jira, Linear, GitHub Issues), docs (Confluence, Google Docs, Notion), email and calendar, code (GitHub), data. For each, follow the `connectors` skill: check what is installed, propose the install with its exact command, **wait for approval**, have them sign in, add the connector with its check and write denials, and write the `TOOLS.md` entry. Skip any they don't want now; setup can be re-run. When naming tools you can already see, count only MCP tools callable in this session or CLIs whose check passes; tools listed only in subagent definitions are not connected.

Where they keep their task list (Notion, Things, Jira) goes in `AGENTS.md` as a one-line rule: the workspace never mirrors a task list.

## 4. Starter schedule

Copy the tasks in [references/starter-tasks.yaml](references/starter-tasks.yaml) into `.roosta/tasks.yaml`: the assistant worker (every 15 minutes), the workspace gardener, chat ideas (weekly, the ideas a new chat offers) and the workspace learner. Explain each in one line. If they connected a chat tool, offer a watcher skill for it (written with `write-a-skill`, returning board cards per the board contract, `sensor: true` and `requires: [<connector>]`). New workers omit `connection` and follow the selected default in Settings → AI connections. Add a connected named connection id only when the user explicitly pins that worker to an account.

## 5. A first real card

From their priorities, pick the one with the clearest next step and create a board card for it: in a board chat end with `<<<REMIND>>>` (title, one-line body, `due: null`); from the terminal, `curl -s -X POST "127.0.0.1:${ROOSTA_PORT:-7667}/api/notify" -H 'content-type: application/json' -d '{"title":"...","body":"..."}'`. Tell them the assistant worker will start raising cards on its own within the hour.

## 6. Trim what they don't want

The operating model ships whole; setup removes rather than adds. Ask whether any part doesn't fit (provenance stamps, `## Related` tables, the dated-file convention). Record each opt-out as a one-line rule in their `AGENTS.md`, which records workspace preferences. Approval and tool protocols always apply.

## 7. Finish

Commit what you wrote (`chore: set up Roosta`), staging files by path. Summarise in three lines: who Roosta thinks they are, what is connected, what runs when.

Then give **three to five things to try next**, each a sentence they could send as-is, built from what they just told you: one about a named priority ("What's the next step on the Q3 launch?"), one using a tool they connected ("Tell me which pull requests need me"), one that saves something ("Remember that…" or "Remind me on Friday to…"), and one that grows Roosta ("Build me a page that shows my projects by status" or "Write a skill that drafts my weekly update"). Say every new chat offers more ideas, rewritten from their workspace weekly by the chat-ideas worker, and that setup can be re-run any time. In a board chat, end with `<<<DONE>>>` and `acted: true`.

## Re-running setup

Read the current `PROFILE.md`, `PRIORITIES.md`, `TOOLS.md` and `.roosta/connectors.yaml` first and ask only about what is missing or changed. Never overwrite the user's own words; update in place.

## Reviewing workspace forks

Run `roosta skills status` in the workspace. Compare the installed skill, active fork and every archived alternative listed under `review`, including helper scripts and references. If a fork is retired, explain which workers still use it and offer to retain it or archive it with `roosta skills use-core NAME`. A retired skill has no installed version for an extension to follow. Explain which local behaviour would change. With the user's agreement, capture additive preferences in the file printed by `roosta skills extend NAME`. Check those rules against the installed version before running `roosta skills use-core NAME`. With Roosta open, the switch takes effect on restart so active runs can finish. The archive keeps the full tree. Keep the fork active if the user still needs replacement behaviour.

## Related

| Link | Relationship |
|------|--------------|
| [[connectors]] | Connects each tool the user names |
| [[workspace-new-project]] | Turns priorities into projects |
| [[write-a-skill]] | Writes watcher skills for connected tools |
