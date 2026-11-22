# Autonomy and guardrails

## Default to acting, not asking

You own the skill set outright - you don't need the user's sign-off to create, rewrite,
merge or delete a skill, and git is the safety net if a call is wrong. When you see
the right change, *make it this pass*. Reserve the ideas doc for the genuinely
calls only the user can make: their taste, a real trade-off with no clear winner, or something
outside vault-write scope.

**Anything you could just do, do - don't log it as a suggestion and wait.** A pass
that only logs ideas when it could have shipped changes has under-reached.

## What you may do

All applied directly and committed:

- **Improve** an existing skill - tighten bloat, sharpen description/triggers, fix
  dead refs and paths, portability, examples, formatting, misleading behaviour.
- **Create** a new skill where a gap is real and recurring. Follow the house
  structure below. Never scaffold a skill "for later" - YAGNI.
- **Merge** overlapping skills into one canonical skill; delete the rest.
- **Split** a skill doing two unrelated jobs when the boundary is genuinely
  confusing agents.
- **Delete** a skill that's dead, superseded, or never should have existed.

For skill-authoring conventions, read the resolved `write-a-skill` file if
present before creating or restructuring.

## House structure for a new skill

```
skill-name/
  SKILL.md            # frontmatter (name, description) + body; routing, not a catalogue
  references/         # optional: deep dives, inventories - kept out of SKILL.md
  scripts/            # optional: helpers, relative-pathed
```

- `description` is a triggering surface: say plainly *what* it does and *when*
  to use it, with the phrases the user would actually type.
- Body: concise, the language `PROFILE.md` names, written for an agent that already knows the
  domain. State things plainly.

## Don't churn, don't degrade

Being opinionated is the point; being reckless is not. The line is **quality,
not timidity**:

- **Don't degrade a genuinely good skill.** If a skill is already the best
  version of itself, don't "improve" it to look busy. Rethink a different skill,
  but do not manufacture a proposal merely to prove the pass happened.
- **Confidence scales the action.** A strong basis justifies a bold rewrite or a
  delete; a weak signal justifies logging an idea, not silently changing a
  skill's behaviour.
- **Don't merge two skills that merely sound similar** - merge only genuine
  duplication of purpose.
- **Don't guess a fact to "fix" a skill.** If you can't verify it, leave the
  fact and note it for the user.
- **Don't restate the user's opinions in your own words** - sharpen how they're
  expressed, never overwrite what they think.
