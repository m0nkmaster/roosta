# Consolidation playbook - templates and refactor mechanics

Depth for the gardener's Phase 2 (digest) and Phase 5 (consolidate). The SKILL
routes here when actually writing PRIORITIES.md or executing a structural refactor.

## PRIORITIES.md structure

`PRIORITIES.md` is the current answer to "what matters now?", not a record of
what mattered on previous runs. Rewrite it in place. Remove superseded statuses,
completed work outside the recent-outcomes window, expired dates, old sprints and
duplicate descriptions. Git and `notes/garden-log.md` already preserve history.

```markdown
# Priorities

**Last refreshed:** YYYY-MM-DD HH:MM

## My priorities
<!-- Owned by the user. Never reword, reorder or remove; only tick off or add status links -->

## This week's focus
<!-- At most 3 outcomes, each with its immediate next action -->

## Active work
<!-- At most 6 rows: work, current state, next action -->

## Watching
<!-- At most 8 items, one line each, linking the project/incident/ticket for depth -->

## Standing focus areas
<!-- Durable responsibilities from AGENTS.md -->

## Recent outcomes
<!-- At most 5 outcomes from the last 14 days -->
```

Keep a small durable terminology section only when another canonical workspace
document explicitly routes readers to it.

### Rewrite rules

1. Put the refreshed timestamp directly below the title. There is exactly one.
2. Never add dated digest paragraphs, update blocks or a "shifts since last
   refresh" history section.
3. Mention each subject once. Choose the section based on whether it is a focus,
   active project, concrete task or watch item.
4. Link to project and incident files for depth instead of copying their
   chronology.
5. No task list: the user's to-dos live in their task tool. Do not mirror task, ticket or chat backlogs. Promote only work that requires
   the user's attention or materially shapes their priorities.
6. Remove stale and completed entries rather than annotating them as stale or
   superseded.
7. Leave `## My priorities` exactly as the user wrote it; derive the agent-written
   sections from it, not the other way round.
8. Keep the complete file under 120 lines. If it exceeds the limit, consolidate
   before finishing.

### Final check

Before committing, verify:

- no expired "today", "tomorrow" or sprint labels remain
- current live state does not coexist with an older contradictory state
- no completed checkbox appears under active tasks
- no subject appears in more than one operational section
- the file still reads clearly without the garden log or previous git version

## Phase 5 refactor mechanics

### 5a. Detect duplication

Clusters where 2+ files cover the same domain:

```bash
# Illustrative - adapt to what you find
rg -l "data flow|warehouse|connections" projects/ notes/ .agents/skills/ AGENTS.md
```

Signs of duplication:
- Same mental model in a project README and a notes doc
- AGENTS.md listing three docs that all say "start here"
- A skill that only links outward to workspace files with no bundled content
- Narrative prose inside what should be an ops runbook
- Empty or stub project folders after content moved elsewhere

### 5b. Plan the refactor (before deleting anything)

Write the plan in scratch notes:

| Current (remove/gut) | Canonical home | Action |
|----------------------|----------------|--------|
| `projects/foo/onboarding.md` | `.agents/skills/foo-expert/SKILL.md` | Migrate narrative, delete source |
| `notes/dated-connections.md` narrative | skill `references/connections-runbook.md` | Split ops from architecture |
| `projects/foo/README.md` overview | Thin index only | Gut duplicate prose |

Get the end state clear before moving files.

### 5c. Execute consolidation

1. **Create or extend the canonical skill** - mental model, decision tree, agent instructions, bundled `references/`
2. **Migrate content** - move reference material into `references/`, not duplicated
Preserve user-curated collection and topic overviews, membership, order and prose throughout this procedure.

3. **Slim what remains** - runbooks to commands only, READMEs to indexes
4. **Delete legacy** - remove superseded files; no stubs
5. **Update AGENTS.md** - single pointer per domain (root and project-level as needed)
6. **Fix all inbound links** - grep for old paths across the workspace

For skill-authoring conventions, read `write-a-skill/SKILL.md` if present.

**Commit:** `garden: consolidate [domain]` (one per domain; can be multiple)

### 5d. Light structural fixes

Only after consolidation, or when trivial:
- Missing README.md in an active project folder - create a thin index
- Obviously dead content with no value - move to `archive/` or delete
- Broken internal links - fix
- Formatting that actively harms readability

Don't go hunting for format violations. Fix what the consolidation sweep surfaced.

**Commit:** `garden: tidy [what]`

## Exemplar: what "proper gardening" looks like

Picture a long AI session that produced scattered knowledge about a data platform
across onboarding docs, project READMEs, connection notes and AGENTS.md pointers.
The right outcome:

- **One canonical skill** (`.agents/skills/<domain>-data-expert/`) with mental model, decision tree, and bundled `references/` - portable, self-contained, transferable
- **Legacy removed** - duplicate onboarding doc, redundant project folder content, narrative duplicated in runbooks
- **Runbook slimmed** to ops only (credentials, commands, troubleshooting) - no "how data works" prose
- **AGENTS.md updated** to a single pointer, not five
- **No backwards compatibility** - no stubs, no "see also the old doc", no parallel copies

That is the remit. Not small formatting fixes. Not missing README stubs.
**Structural refactors that make the brain simpler and more powerful.**
