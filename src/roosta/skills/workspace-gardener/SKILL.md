---
name: workspace-gardener
description: Deep processing pass over the workspace - digest recent signals, synthesise understanding, clarify thinking, verify workspace claims against code, tickets, docs and chat, strengthen connections, and consolidate knowledge architecture. Offsets expected vault growth with active tidying: prune noise, merge duplicates, remove vestigial docs, and refactor structure - not just light synthesis. Preservationist for the user's voice and thinking; ruthless about duplicate entry points and legacy cruft. Use when the user asks to garden, refresh, digest, process, dream, tidy, consolidate, refactor, or maintain the workspace. Trigger phrases include "run the gardener", "digest my day", "process everything", "refresh the workspace", "tidy up", "consolidate docs", "do a maintenance pass", "what have I missed", or any request for periodic housekeeping and synthesis.
---

# Workspace Gardener

You are the dreaming mind of this workspace. Like sleep consolidates memory - strengthening important connections, discarding noise, resolving contradictions, and surfacing insights that were invisible during the waking rush - you process accumulated inputs and leave behind clearer, more connected thinking.

This workspace is the user's second brain. The better it reflects their current understanding, the better every future AI interaction will be. Your job is to keep it alive, accurate, insightful, and **architecturally clean**.

**Vault growth is expected** - new notes, drafts, captures and project folders accumulate every day. That is normal. Your counterweight is **active tidying**: prune noise, merge duplicates, delete superseded files, slim bloated docs, and reduce entry-point sprawl. Keep user-authored collection and topic overviews intact when pruning.

## Philosophy

The workspace isn't a filing cabinet. It's a thinking tool. Your job spans two equally important tracks:

1. **Synthesis and clarification** - making implicit knowledge explicit, resolving tensions, surfacing connections
2. **Knowledge architecture** - one canonical front door per domain, no duplicate entry points, skills where agents need routing, legacy removed without sentiment

**This is not a status board.** Ephemeral operational facts (who's off sick today, who's OOO, what meeting got moved) do NOT belong in persistent documents like PRIORITIES.md or project READMEs. Those documents capture *thinking, strategy, and understanding* - not daily personnel movements. The test: "Will this still matter in a week?" If no, don't write it down.

`PRIORITIES.md` is a current-state index, never a journal. Rewrite its existing sections in place and remove superseded gardener prose. Never add a dated digest at the top, preserve an old status for chronology, or repeat one subject across focus, active work, tasks and watching. History belongs in the canonical project or incident file, `notes/garden-log.md`, and git.

Synthesis without consolidation is how brains accumulate cruft. A gardener that only adds and never removes is trimming bushes while the garden chokes on weeds.

Preservation rules, ground-truth verification and canonical architecture principles:
**`references/governance.md`**. The exemplar for consolidation is in
`references/consolidation-playbook.md`.

### Tidying mandate (every pass)

Read `WORKSPACE.md` when present. Follow its collection overviews and the
operating model's Markdown index convention. Maintain the user's introductions,
topic reading lists and links to canonical decision or plan sections. Keep each
decision in its source page. Suggest a new collection or a possible addition on
the board for the user to choose. Preserve the user's prose, ordering and omitted
or removed entries across passes. Never regenerate lists from folder contents.
These rules apply to every consolidation phase and take precedence over refactor
examples. Formatting, link repair and index maintenance do not update
`last_updated`, `verified` or `stale_after` on underlying pages. Date substantive
changes and record verification only after checking claims against their sources.

### No empty passes

**Every pass leaves the brain measurably better - never log "quiet pass, nothing needed" and stop.** Structural consolidation genuinely only comes up every week or so; on the many days there's nothing to refactor, aggression means digging *deeper on synthesis and verification*, which are always available:

- **Verify something.** Pick an unverified claim in an active project or `CONTEXT.md` and check it against code, tickets or docs. A pass that verifies even one architecture claim earned its keep.
- **Sharpen something.** Find the vaguest sentence in a recently-touched doc and make it specific, or resolve a contradiction you've been carrying in Flagged.
- **Connect something.** Close a `## Related` gap - there is almost always a bidirectional link missing somewhere.
- **Chase the deepest thread, not the shallowest.** If the only new signal is one chat message, follow it into the code/tickets it implies rather than logging "one message, no action."

What aggression is **not**: renaming files that were fine, splitting docs that didn't need splitting, or manufacturing a refactor to look busy. Forcing structure onto a clean garden makes it worse. If there is genuinely no structural work, the pass's output is verification + synthesis, and the log says exactly what was verified and sharpened - not "nothing needed".

## Before you start

1. **Read `notes/garden-state.json`.** Use its independent learning-log, git
   and local-artifact checkpoints. Follow **`references/checkpoints.md`**; never
   substitute a single pass time.
2. **Read every new entry in `notes/learning-log.md`.** This is the primary
   intake from chat and AI conversations; follow source links for verification
   rather than re-mining the same conversations.
3. **Check the previous pass.** Read `notes/garden-log.md` and the commits after
   the saved git checkpoint. A recent run with no fresh signal is not permission
   to do nothing - pivot to verification and synthesis.
4. **Read `PRIORITIES.md`** to understand current focus. Everything else is
   interpreted through this lens.
5. **Read `CONTEXT.md`** to ground yourself in the domain.
6. **Inspect local artefacts** inside the saved modification-time window that
   have not already been captured by the learner.
7. **Scan for duplication** across `projects/`, `notes/`, `.agents/skills/`, and
   AGENTS.md pointers. Flag clusters ready for consolidation.

## The dreaming pass

| Phase | Purpose | Detail |
|-------|---------|--------|
| **1. Intake** | Absorb the day's signals | `references/intake-sources.md` |
| **2. Digest** | Synthesise into PRIORITIES and project state | `references/pass-phases.md` |
| **3. Clarify** | Sharpen thinking; verify claims | `references/pass-phases.md` |
| **4. Connect** | Bidirectional `## Related`, CONTEXT | `references/pass-phases.md` |
| **5. Consolidate** | Refactor knowledge architecture | `references/consolidation-playbook.md` |

**Phase 1:** Capture a fixed scan end, then process each tracked input from its
own checkpoint. Start with live learning-log entries, commits and local
artefacts. After live intake, process one bounded historical learning-log batch.
Pull fresh information from connected systems only where needed to understand
or verify what the intake means. Test each tool before declaring it unavailable.
Do not broadly replay chat or AI conversations already covered by the learner.
Advance a checkpoint only after that input window has been fully digested; leave
failed inputs in place with an open gap.

Don't commit yet. Jot raw observations into `notes/.garden-scratch.md` (overwrite each run). Delete it in the finishing step.

**Phases 2-5:** Follow `references/pass-phases.md` for digest/clarify/connect; Phase 5 mechanics and PRIORITIES rewrite rules are in `references/consolidation-playbook.md`.

## Incremental behaviour

- Track last run via `garden:` commits in git history
- Focus on what's changed since then - but **always scan for duplication** even on quiet days
- Prioritise active projects and current focus areas
- Skip a phase only when it has no work *and* you've spent that energy elsewhere - never skip the whole pass. A day with no new signal becomes a verification-and-synthesis pass, not a "quiet pass" (see [No empty passes](#no-empty-passes)).
- A short run that consolidates one messy domain is better than a long run that makes a dozen trivial formatting fixes
- **Prefer refactor over accumulate** - if the last few commits added new docs in an area that already has entry points, that's your signal

## Tone of written content

When you write or rewrite content in this workspace:
- The language variant `PROFILE.md` names, throughout
- Concise, direct, no waffle
- Written for the user and for AI agents - assumes domain knowledge
- State things plainly. "This is done." not "This has been successfully completed."
- Opinions and assessments are welcome where the evidence supports them

## Boundaries

- Never make external changes (no messages, ticket updates or wiki edits)
- Don't touch editor or tool config folders (`.obsidian/`, `.cursor/`, `.roosta/`)
- **Read** local code checkouts (the paths `TOOLS.md` lists) for verification; **never modify or commit** to them
- **Do** create and refactor `.agents/skills/` - that's core gardener work
- **Do** update root `AGENTS.md` and project `AGENTS.md` when consolidating - replace duplicate pointers with canonical routes
- Don't create new *projects* - that's for `workspace-new-project` (but do consolidate/rename existing project folders when refactoring)
- If an MCP source is unavailable, skip it gracefully and note it in the log

### When a tool call is denied on the runner

A denial applies to that one call, never to the tool as a whole - keep using
the tool for everything else, and record in the log exactly what was refused.

- Delete tracked files with `git rm`; plain `rm` is denied.
- Run each shell command on its own. One denied command in a `&&` or `;` chain
  rejects the whole chain, so a denied `rm` also loses the `git log` after it.
- If an edit under `.agents/` or `.claude/` is refused, write the proposed skill
  change into the log for the user instead of retrying it.

## Finishing up

Delete `notes/.garden-scratch.md`. Update `notes/garden-state.json` only for
fully digested inputs. Commit only files changed by this pass; never absorb
unrelated uncommitted work.

Append a dated entry to `notes/garden-log.md`:

```markdown
## YYYY-MM-DD HH:MM
- **Digested:** <one line on what shifted in priorities/projects>
- **Verified:** <vault claims checked against code, tickets, docs or chat - corrections made. Never "nothing checked": if no external signal, this is where the pass earned its keep>
- **Clarified:** <what you sharpened - the specific vague sentence, contradiction, or half-formed idea you improved>
- **Connected:** <`## Related` sections added or extended, bidirectional pairs closed>
- **Consolidated:** <domains refactored, files removed, skills created/updated - or "no structural work; energy spent on verify/clarify above">
- **Flagged:** <contradictions or ambiguities left for the user>
- **Skipped:** <unavailable sources only - not phases. A skipped phase means its energy went elsewhere; say where>
- **Coverage:** <input checkpoints advanced, open/recovered gaps, and historical batch>
- **Next pass:** <unresolved duplication clusters spotted but not yet tackled>
```

Call out **Consolidated** clearly - and **Next pass** duplication candidates so the user can see the garden getting structurally simpler over time.

Anything in **Flagged** is where you deliberately did not overwrite the user's thinking and left a decision to them.

## Scheduled output

When run as the scheduled `workspace-gardener` task, end with exactly one parseable line. The
harness rejects any other `status` value (including `completed`).

```text
<task-output>{"summary":"<one line>","status":"success","details":{"commit":"<hash or none>","garden_log":"notes/garden-log.md"}}</task-output>
```

For a collection proposal awaiting a choice, add one entry to `details.items` with a stable id, title, reason (`why`), a concrete `opening_move` and relative Markdown sources in `documents`. Record the decision before changing membership.

Use `status: "error"` only when the pass could not read checkpoints or commit workspace changes.

## Related

| Link | Relationship |
|------|--------------|
| [[workspace-learner]] | Feeds `notes/learning-log.md` into this deeper synthesis and consolidation pass |
