---
name: workspace-new-project
description: Scaffolds a new project under projects/ - a kebab-case folder with a README.md carrying the required frontmatter and sections. Use when starting a new project, creating a project folder, or scaffolding workspace docs for ongoing work.
---

# New project

Every project is a folder under `projects/` with a `README.md` entry point. The canonical rules are in the Projects section of `.roosta/operating-model.md`.

## 1. Pick a slug

Kebab-case, descriptive, no date prefix (`documentation-rewrite`, `q3-launch`). Match the name people actually use; if the user gave a working title, derive the slug from it. Check `projects/` first: if a project already covers this, offer to extend it instead.

## 2. Create the README

Create `projects/<slug>/README.md`. Do not pre-create empty `notes.md`, `decisions.md` or `plan.md`; add them when there is content.

```markdown
---
title: Project title
status: active
last_updated: YYYY-MM-DD
owner: <name from PROFILE.md>
---

# Project title

## Overview
<!-- One paragraph: what this is and why it exists -->

## Current state
<!-- Where things stand right now -->

## Key people

| Person | Role | Notes |
|--------|------|-------|
| <name from PROFILE.md> | <role from PROFILE.md> | Owner |

## Links

| Resource | URL / reference |
|----------|-----------------|
|  |  |
```

- Required frontmatter: `title`, `status` (`active | blocked | paused | completed`, default `active`), `last_updated` (today), `owner`. Optional: `tags`, `people`, `repos`, `links`, and any keys the user's `AGENTS.md` adds.
- Sentence-case headings. All four sections present, even as stubs.
- If the user mentions related projects, add a `## Related` table and the reverse row in each related README.

## 3. Supporting files, when content arrives

- `notes/YYYY-MM-DD-topic.md` for dated notes; `decisions.md` for a decision log; `plan.md` for a brief or phased plan; `assets/` for binaries; free-form topic files when content earns its own page.

## 4. Conventions

- Write in the language `PROFILE.md` names. Wikilinks and Markdown links are both fine.
- No external side effects (messages, tickets) unless the user approves.

## 5. Finish

If the user wants it on their radar, add a row to **Active work** in `PRIORITIES.md`; otherwise mention it once as an option. Offer to list the new README in a chosen collection when the workspace uses `WORKSPACE.md`. Append the relative Markdown link if the user wants it included. Tell them the path you created and the first useful edit ("fill in Overview").
