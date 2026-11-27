# Classification and promotion pipelines

## Read conversations safely

Apply both guards to every candidate:

1. **Read the complete exchange.** A correction, retraction or decision may appear
   later. Never extract from a partial thread.
2. **Separate testimony from system behaviour.** Someone describing their own
   setup, plan or opinion is not proof that the platform generally works that way.

Also distinguish an agent mistake from the user changing direction or thinking aloud.
The latter is not something to "fix".

## Classification

Classify each useful candidate into exactly one primary outcome:

| Outcome | Meaning | Action |
|---------|---------|--------|
| **Correction** | The user corrected the agent, the agent repeated a known error, or a tool/path/query failed because guidance was wrong or missing | Trace and fix the root cause if durable and verified |
| **Learning** | New durable context was settled in the conversation and is missing from the workspace | Run the promotion pipeline |
| **Open** | Unresolved, ambiguous, unverifiable or a single-person data point | Log and flag; never promote |
| **Transient** | Operational noise or unlikely to matter in a week | Log one short line or omit if valueless |
| **Already handled** | The conversation itself made the correct canonical edit | Note only when useful; do not duplicate it |

A single conversation may contain several candidates, but do not record the same
fact as both a correction and a learning.

## Correction pipeline

Typical correction signals:

- "No", "that's wrong", "actually", "I meant" or repeated clarification
- wrong table, column, identifier, repository, file path or command
- empty or misleading results that the documented workflow should have prevented
- stale claims about ownership, architecture, terminology or status
- the same drafting or reasoning failure recurring across sessions

For each candidate:

1. Identify the actual failure, not merely the visible symptom.
2. Locate the guidance or knowledge that should have prevented it.
3. Verify the correction against code, a runbook, a ticket, a live tool or the user's
   explicit statement.
4. Fix the canonical source:

| Root cause | Canonical target |
|------------|------------------|
| Domain fact | `CONTEXT.md`, `PRIORITIES.md` or the relevant project README |
| Data or query behaviour | The owning domain skill or its references |
| Skill wording, trigger or example | The owning skill |
| Workspace path or convention | Root/project `AGENTS.md` or relevant README |
| No durable canonical home | Learning log only |

An in-session self-correction needs no further edit if the canonical source is
already right.

## Learning promotion pipeline

Only promote when every check passes:

1. **Settled** - the complete conversation resolves the point without a later
   contradiction.
2. **Verified** - check the obvious ground truth:
   - code or local development behaviour: checked-out repository, read only
   - ticket status or ownership: the ticket tracker
   - live product or configuration: the product's own tools
   - process or runbook: the wiki
3. **Durable** - useful beyond today's transient state.
4. **Generalising** - useful to a future reader who was not in the conversation.
5. **Canonical home** - one existing document clearly owns the fact.
6. **No anecdote** - write a concise reference fact, not who said it or how it was
   discovered.

Fail any check and keep the item `Open` rather than manufacturing certainty.
