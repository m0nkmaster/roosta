# Governance - preservation, ground truth and canonical architecture

Depth for the gardener's judgement calls. The SKILL routes here when deciding what
to edit, what to verify, and how to structure the vault.

## Ground truth: the vault is understanding, not gospel

The user's notes capture *how they think things work* - priorities, rationale, mental
models, half-formed hypotheses. That is valuable and mostly sacred. It is **not
always accurate**. Architecture drifts, services get renamed, decisions get
superseded in tickets, and code does what code does regardless of what a README says.

Spot-check claims against reality when you touch a topic - not every sentence every
pass, but do not treat vault prose as verified fact either.

| Source | Use for |
|--------|---------|
| **Local code** (the checkouts `TOOLS.md` lists) | Implementation truth - names, event shapes, state logic, config, API contracts |
| **Tickets** | Current status, ownership, what's actually shipped vs planned |
| **Wiki and docs** | Canonical runbooks, access patterns, team-owned process docs |
| **Chat** | Recent decisions, corrections, "actually we changed that" moments |
| **Product tools** | Live product state |

When vault prose and ground truth disagree:

- **Verifiable fact** (wrong service name, stale status, incorrect SQL, code moved) - correct the vault directly and note what you checked
- **Strategic opinion or decision** the user recorded - leave their words; add a dated correction beneath (`Verified YYYY-MM-DD: code shows X`)
- **Ambiguous or unresolved** - flag in garden-log; don't guess

Read code repos freely for search and verification. **Never commit to or modify**
checked-out repos - that is not gardener territory.

## The first law: preserve the user's thinking, not duplication

This skill runs unattended. Nobody reviews your changes before they land. That
makes preservation rules precise:

### Sacred (never overwrite)

- The user's decisions, opinions, judgements, rationale, half-formed ideas
- Their exact wording where it carries nuance
- Contradictions between files (surface them; don't pick a winner silently)

### Freely editable (yours or structural)

- Gardener-authored synthesis from prior passes
- Project `## Current state` snapshots the gardener maintains
- **Duplicate content** that says the same thing in two places - consolidate, don't preserve twice
- Index pages, README overviews, AGENTS.md routing pointers
- Legacy docs superseded by a canonical skill or note

### The test for any write

| Question | Action |
|----------|--------|
| Does this deepen understanding? | Write it |
| Does this remove a duplicate entry point? | Do it |
| Am I updating a current-state index such as `PRIORITIES.md`? | Replace the old state; do not append history |
| Am I rewording the user's durable thinking to "improve" it? | Stop - add clearly attributed synthesis in its canonical home |
| Am I deleting the only copy of a decision? | Stop - migrate the content first |
| Am I leaving a stub "for backwards compatibility"? | Don't - the user wants iteration, not vestigial crap |

**Reconcile by surfacing, not by deciding** - when two files *disagree* on facts or
direction, note the tension and leave both until the user resolves it. When two files
*repeat* the same narrative, that's not a contradiction to preserve - it's
duplication to kill.

Correct unambiguous factual errors directly (wrong dates, dead links, renamed
services) - but only after checking ground truth. A confident wrong correction is
worse than a stale note.

## Canonical architecture principles

Apply these whenever you audit structure (every pass should at least scan for
violations):

### One front door per domain

Multiple entry points saying the same thing guarantees drift. Typical offenders:

- A project README + a notes doc + a skill + AGENTS.md links all covering the same narrative
- An onboarding doc and a "start here" README with overlapping prose
- Runbooks that mix "how it works" with "how to connect"

**Fix:** Pick one canonical home. Route everything else there. Delete or gut the rest.

### Skills vs vault docs vs notes

| Artifact | When to use | Contents |
|----------|-------------|----------|
| **Skill** (`.agents/skills/`) | Agents need domain routing, mental models, "which tool when" | ~150-250 lines: decision tree, key concepts, links to bundled `references/` and `scripts/` |
| **Vault reference** (`projects/`, long docs) | Living catalogues, deep dives, worked examples that change often | Full inventories, E2E traces, mapping tables - too big for SKILL.md |
| **Notes** (`notes/`) | Personal ops, dated one-offs, secrets-adjacent runbooks | CLI commands, `.env` patterns, troubleshooting - not architecture narrative |
| **AGENTS.md** | Agent bootstrap only | One-line pointers to skills and key docs - not duplicate prose |

**Skill decision checklist** - promote to (or create) a skill when:

- Agents repeatedly need to choose between tools/stores/sources
- Knowledge spans multiple files and agents won't find the right one
- The content is domain expertise, not a transient task
- It would benefit teammates if made portable (bundled references, relative paths, no workspace-only wikilinks)

**Do not** create a skill that only points at personal vault files - that's an index,
not a transferable skill. Bundle references inside the skill folder.

**Do not** put 500-line catalogues into SKILL.md - that's a context bomb. The skill
routes; references hold depth.

### Transferable skills

Skills the user might share must be self-contained:

```
skill-name/
  SKILL.md
  references/
    deep-dive-one.md
    deep-dive-two.md
  scripts/
    example.sh
```

Paths in SKILL.md are relative to the skill folder. No "read `projects/foo/bar.md`"
as a prerequisite - this includes `## Related` sections: a skill may link to other
skills, never to vault-only project files. Personal secrets stay in `notes/` or
`.env`, never in the skill.

### Remove, don't stub

When consolidating:

- Delete superseded files (git remembers)
- Preserve user-curated overviews, including their prose and chosen links. Consolidate duplicate technical instructions in the canonical skill.
- Update all inbound links in one pass
- No "deprecated - see X" stubs unless the user explicitly asked for a transition period

The user's rule: **skill is canonical, never duplicate, forget backwards compatibility.**
