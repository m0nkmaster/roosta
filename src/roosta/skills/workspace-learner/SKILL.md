---
name: workspace-learner
description: The workspace's continuous learning loop. Mines the user's AI conversations and any connected chat for agent mistakes, corrections, newly surfaced context and recurring problems; fixes verified root causes in skills or canonical vault docs, promotes settled facts, and logs unresolved points without turning them into claims. Use when the user asks to "learn from my conversations", "review recent chats", "capture what we learned", "fix what agents keep getting wrong", "update the brain from chat", or on the scheduled workspace-learner cadence. Distinct from workspace-gardener (deep synthesis and consolidation) and skill-auditor (structural review of the skill set).
---

# Workspace Learner

You are the workspace's continuous learning and self-healing loop. Read the
conversations the user actually has, then make the smallest durable change that helps
future agents understand their world or avoid repeating a mistake.

This is one pass with two equally important outcomes:

1. **Correction** - an agent got something wrong, used a tool badly, followed the
   wrong path or repeatedly needed clarification. Verify why, then fix the root
   cause.
2. **Learning** - a conversation surfaced durable context that the vault does not
   yet carry. Verify it, then add it to its canonical home.

Do not run separate transcript passes for these outcomes. Every conversation is
read once and classified once.

## Boundaries with sibling loops

- **You** capture and correct from conversations. Your writes are atomic facts,
  instructions and small root-cause fixes.
- **Workspace gardener** consumes `notes/learning-log.md` and performs deeper
  synthesis, priority refreshes, contradiction resolution and structural
  consolidation. Do not duplicate that work.
- **Skill auditor** reviews the skill collection as a system. It may consume your
  log, but it does not independently re-mine transcripts.

## Hard rules

- Write in the language `PROFILE.md` names.
- Local edits only. Read connected tools and checked-out code for evidence, but
  never change them.
- Never modify checked-out code (the paths `TOOLS.md` lists).
- Preserve the user's voice, opinions, decisions and half-formed ideas. Correct facts
  and mechanics; do not rewrite their thinking.
- Verify before writing. An uncertain observation stays in the log.
- Prefer an existing canonical home. Never create a document merely to house one
  anecdote.
- Make the smallest change that prevents recurrence or fills the knowledge gap.
- A failed or partial source scan never advances that source's checkpoint.
- Do not touch editor or tool config (`.obsidian/`, `.cursor/`, `.roosta/`).
- Commit only files changed by this pass. Never use `git add -A`.
- A denied tool call applies to that one call, never to the tool as a whole.
  Carry on writing everything else, and record what was refused.
- If an edit under `.agents/` or `.claude/` is refused, `notes/` is still
  writable, so a skill fix you cannot apply goes
  into `notes/learning-log.md` as a proposed change for the user, and the pass still
  records everything else it learned.

## One pass

1. Read `notes/learning-state.json`. It holds an independent live checkpoint,
   backfill cursor and open gap for every source. Follow
   **`references/checkpoints.md`**. Never use one global watermark.
2. Capture `scan_end_ms`, check each source explicitly, then pull AI and chat
   activity from that source's own checkpoint - **`references/sources.md`**.
3. Read each relevant thread or transcript completely; classify and run the
   appropriate pipeline - **`references/pipelines.md`**.
4. Complete at least one bounded historical-backfill batch from an incomplete
   source after the live scans. Live capture takes priority if time is tight.
5. Write only verified, durable changes.
6. Update only checkpoints whose scans completed. Leave failed checkpoints in
   place and record their open gaps.
7. Prepend a dated entry to the learning log and set its pass watermark to the
   current epoch milliseconds at finish:

   ```bash
   echo $(($(date +%s)*1000))
   ```

   Do not hand-convert displayed UTC timestamps.
8. Commit the state, learning log and files changed by this pass:

   ```bash
   git add notes/learning-state.json notes/learning-log.md <each changed file>
   git commit -m "learn: <short summary>"
   ```

If no candidate warrants a canonical change, still record the pass and update
only the source checkpoints that were fully scanned.

## Learning log

Prepend entries to `notes/learning-log.md`:

```markdown
## YYYY-MM-DD HH:MM
- **Reviewed:** <sessions and chat scope>
- **Corrections:** <root-cause fixes, or "none">
- **Learned:** <promoted facts and targets, or "none">
- **Open:** <unresolved or unverifiable points, or "none">
- **Transient:** <brief summary, or "none">
- **Queued for the user:** <external actions not taken, or "none">
- **Coverage:** <checkpoints advanced, recovered gaps, unavailable sources, and backfill batch>
- **Watermark:** <epoch-ms>
```

Keep the log useful but compact. It is evidence and an intake queue for the
gardener, not a second canonical knowledge base. `Watermark` dates the pass;
`notes/learning-state.json` is authoritative for source coverage.

## Board output

**Chat threads: refine, never mint a parallel card.** The board merges on exact
`id`, so a new slug for a thread the user already has becomes a duplicate. If the thread
has a card, return that card's `id` with the sharper context you found (see
**Updating an existing card** in
[`../assistant/references/board-contract.md`](../assistant/references/board-contract.md)).
If it has none, record the action in `Queued for the user` and let the owning sensor raise it.

Keep `details.items` as `[]` unless a non-chat finding of this pass genuinely
has no owning sensor. Never add an item for an unverified observation, a
historical fact or a task already resolved in the same conversation.

End with `<task-output>` JSON:

```json
{
  "summary": "<one line: reviewed N, corrected C, learned L, flagged F>",
  "status": "success",
  "details": {
    "reviewed": 0,
    "corrections": [ { "file": "", "what": "", "source": "" } ],
    "learned": [ { "fact": "", "target": "", "source": "" } ],
    "open": [ "" ],
    "queued_for_user": [ "" ],
    "items": []
  }
}
```

If one source is unavailable, continue with the others and note the gap. Report
`status: "error"` only when no source can be read or the local vault cannot be
updated safely.
