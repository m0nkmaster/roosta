---
name: page-builder
description: Build a custom page for the Roosta Assistant - static HTML and JS in .roosta/pages/<name>/ that reads Roosta's read-only APIs and JSON written by a scheduled skill. Use when the user asks for a new page, view, dashboard, tracker, board or screen in Roosta, or wants to change or replace a shipped page.
---

# Page builder

A custom page is a folder `.roosta/pages/<name>/` holding `index.html` and any JS, CSS or images it needs. Roosta serves it at `/pages/<name>/` and adds it to the top navigation on every page, titled from its `<title>`. There is no build step and no server code: a page only reads.

## Decide the data first

A page shows one of three things:

| Data | Source |
|------|--------|
| Workspace documents | `GET /api/workspace/files?glob=<glob>`: path, title, frontmatter and modified time per Markdown file (no bodies). `GET /api/workspace/document?path=<path>` for one document's full text |
| Scheduled work | `GET /api/tasks`: every task's status and `last_output` |
| Anything else | JSON a scheduled skill writes to `.roosta/state/pages/<name>/<file>.json`, read with `GET /api/pages/<name>/data/<file>.json` |

If the page needs data from a tool (tickets, calendar, a database), write or extend a **skill** that fetches it and writes the JSON file, and schedule it in `.roosta/tasks.yaml`. Never fetch from a tool in the page, never call a write endpoint, and never put credentials in a page. If a page needs a capability no API offers, say so: it becomes an upstream request for Roosta (the `roosta-engineer` drafts it), not a workaround.

Other read-only endpoints pages may use: `/api/board` (the Assistant board), `/api/activity` (recent runs), `/api/pulse` (workspace telemetry), `/api/profile` (the user's name).

## Build it

```html
<!doctype html>
<html lang="en" data-bs-theme="dark">
<head>
  <meta charset="utf-8">
  <title>Reading list</title>
  <link rel="icon" href="/static/favicon.png" type="image/png">
  <link rel="stylesheet" href="/static/vendor/tabler/tabler.min.css">
  <link rel="stylesheet" href="/static/shell.css">
  <script src="/static/nav-count.js" defer></script>
</head>
<body>
  <header class="workspace-header navbar" aria-label="Workspace"></header>
  <main class="container-fluid py-3" id="app"></main>
  <script type="module" src="./app.js"></script>
</body>
</html>
```

- Leave the header empty: `nav-count.js` renders the shared brand and navigation into it, including this page. Never hard-code nav links.
- Use Tabler classes (`card`, `table`, `badge`, `btn`) and the shell's theme tokens; don't build a parallel style system.
- Escape everything you render from data (`textContent`, not `innerHTML`, unless you sanitise).
- Poll gently (30-60 seconds) or not at all. Link workspace documents to `/document?path=<path>`; a chat about one opens at `/assistant?item=doc:<path>`.
- Keep it small: one HTML file and one JS file is usually enough.

## Replacing a shipped page

A folder named like a shipped page (`assistant`, `pulse`, `office`, `workspace`, `index` for the runner, `document`, `changelog`) replaces it. Start from a copy of `/static/<name>.html` and say clearly that Roosta updates to that page will no longer reach the user.

## Check it

1. Open `http://127.0.0.1:${ROOSTA_PORT:-7667}/pages/<name>/` and confirm it renders with real data.
2. For a headless check, never point a browser at a live page that polls; build a throwaway static copy that loads the page with a saved JSON response, screenshot that, then delete it.
3. If a skill feeds it, Run now on the skill and confirm the JSON file appears and the page reads it.

Commit the page folder (and any skill and task you added) with a short `feat(roosta): <name> page` message.

## Related

| Link | Relationship |
|------|--------------|
| [[roosta-engineer]] | Evolves pages from usage over time |
| [[write-a-skill]] | For the skill that feeds a page |
