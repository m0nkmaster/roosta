# Pass phases - digest, clarify, connect and consolidate

Phase 2-5 detail for the dreaming pass. Phase 1 intake lives in
`intake-sources.md`; PRIORITIES rewrite rules and Phase 5 refactor mechanics live
in `consolidation-playbook.md`.

## Phase 2: Digest - synthesise into understanding

Take everything you've absorbed and process it:

**Update `PRIORITIES.md`:**
Re-evaluate rather than accumulate. What shifted, what is more urgent, and what
can leave? Rewrite the current entry for a subject and delete its superseded
wording. Apply the hard limits and checks in `consolidation-playbook.md`. A pass
that adds a dated header or increases duplication has failed even if the new
facts are accurate.

**Update project `## Current state` sections:**
For any project with meaningful activity, refresh its current state. Carry forward
decisions, rationale, or caveats the user wrote there. Update `last_updated` for substantive changes to the page. Link and formatting maintenance preserve its attention dates.

**Commit:** `garden: digest [date]`

## Phase 3: Clarify - sharpen the thinking

Read through active project READMEs and recent notes. Clarify durable documents by
**adding** synthesis, not overwriting the user's voice - unless consolidating duplicates
(see Phase 5). This additive rule does not apply to current-state indexes such as
`PRIORITIES.md`; those must be rewritten in place.

**Start from the provenance queue.** Run the two commands under *Provenance* in
the installed operating model and work expired docs first, then `active` projects with no
`verified` entry. Each doc you check gets a new
`{ by: workspace-gardener/<your model ID>, at: <today> }` entry at the top of `verified`
and a fresh `stale_after`. Fix or flag any claim that failed the check; never
re-stamp a doc you only skimmed. Leave `human:` entries untouched. Log the count
checked under **Verified**.

For active projects and recently touched docs, **sample-check claims** against
code, tickets or docs before treating them as current. Prioritise:

- Architecture and data-flow descriptions (grep the relevant repo)
- Ticket references and status ("In Progress" in a README vs Done in the tracker)
- Service names, endpoints, table/view names, ownership
- Anything a future agent would rely on to act correctly

- Vague language you can now make specific - add dated updates, don't delete originals
- Contradictions between files - surface explicitly; check which matches ground truth
- Half-formed ideas - add synthesis beneath under `Synthesis (gardener):`
- Outdated framing - add current framing, note what it supersedes and what you verified

**Commit:** `garden: clarify [what]`

## Phase 4: Connect - strengthen the web

This is where the vault's "web of mind" gets built, not just implied. See
Linking in the installed operating model for the
full convention - the summary for gardener purposes:

- For every project, note, or analysis doc you touched this pass, ask: does this
  genuinely relate to something else in the vault (shared owner, same initiative,
  blocks/depends on, supersedes, same underlying system, related thought space)? If
  yes, it needs a `## Related` entry - a stray mid-prose mention isn't enough.
- **Add or extend `## Related`** as a table: `| [[target]] | relationship |`. Use
  `[[wikilinks]]` for in-vault targets.
- **Always make it bidirectional.** Adding A → B means adding B → A in the same
  pass, worded from B's perspective (the relationship label doesn't have to be
  identical wording, just consistent in meaning). If B has no `## Related` section
  yet, create one; if it exists, append a row rather than rewriting it.
- **Skills stay portable.** A skill's own `## Related` section (if any) only links
  to other skills - never to vault-only project files as a prerequisite. Vault docs
  linking *to* a skill (the existing AGENTS.md pattern) is fine and unaffected.
- **Quality over coverage.** Don't manufacture a relationship to fill the section.
  A project with nothing genuinely connected simply has no `## Related` section
  this pass.
- Update `CONTEXT.md` with new names, services and initiatives.
- **After consolidation (Phase 5),** ensure all links (including `## Related` rows)
  point at canonical homes - not deleted duplicates. Deleting or renaming a file
  means fixing every `## Related` row that pointed at it, on both sides.

**Commit:** `garden: connect [what]`

## Phase 5: Consolidate - refactor knowledge architecture

**This is not optional light tidying.** Every pass audits for structural mess. If
a deep session (Cursor export, long analysis, repeated agent Q&A) produced
knowledge now spread across multiple files, consolidate it here.

The full mechanics - duplication detection, planning the refactor before deleting,
executing consolidation, and the light structural fixes that follow - live in
**`consolidation-playbook.md`**. The shape:

- **5a. Detect** clusters where 2+ files cover the same domain (`rg -l` across
  `projects/ notes/ .agents/skills/ AGENTS.md`).
- **5b. Plan** the end state in scratch notes before moving anything - a table of
  current -> canonical home -> action.
- **5c. Execute** - create/extend the canonical skill, migrate content into
  `references/`, slim what remains, delete legacy (no stubs), fix all inbound links.
- **5d. Light fixes** only after consolidation or when trivial.

**Commit:** `garden: consolidate [domain]` (one per domain; can be multiple), then
`garden: tidy [what]` for light fixes.

For skill-authoring conventions, read `write-a-skill/SKILL.md` if present.
