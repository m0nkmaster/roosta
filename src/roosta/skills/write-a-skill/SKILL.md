---
name: write-a-skill
description: Create or revise an agent skill in this workspace - a folder under .agents/skills/ with a SKILL.md whose description makes it fire at the right time, plus bundled references and scripts. Use when the user wants to create, write, build, split or sharpen a skill, or when a repeated task deserves one.
---

# Writing a skill

For an installed skill, write workspace-specific additions in `.roosta/skill-extensions/<name>.md`. Use a full fork only when the user explicitly wants to maintain a replacement. Never edit the package.

A custom skill is a folder under `.agents/skills/<name>/` that teaches an agent one job. Claude Code, Codex, Cursor and pi all discover it there (`.claude/skills` points to the same folder).

## 1. Decide it deserves to exist

Make a skill when agents repeatedly need the same domain routing or procedure, the knowledge spans several files, or a recurring task keeps being explained from scratch. Don't make one for a one-off task, or one that only points at workspace notes: that is an index, not a skill. Check `.agents/skills/` first and extend an existing skill rather than overlap it.

Ask the user only what you cannot infer: what the task is, when it should fire, what good output looks like, and whether a script would make it deterministic.

## 2. Layout

```
<name>/
  SKILL.md          # the routing brain: 150-250 lines at most
  references/       # depth the agent reads only when needed
  scripts/          # deterministic helpers the skill runs
```

## 3. SKILL.md

```markdown
---
name: <name>            # matches the folder; kebab-case
description: <what it does>. Use when <the situations and phrases that should trigger it>.
---

# Title

<The mental model in a paragraph: what this job is and what good looks like.>

## <Procedure or decision tree>

## Output

## Related
| Link | Relationship |
|------|--------------|
| [[other-skill]] | ... |
```

- **The description is the trigger.** Agents choose skills from it alone, so name the task, the domain words and the phrases a user would say. Say what it is distinct from when a sibling skill is close.
- **Route, don't dump.** Keep the decision tree and key concepts in `SKILL.md`; put catalogues, examples and long procedures in `references/` and link them with relative paths.
- **Portable.** Relative paths only. A skill may link to other skills but never depends on a workspace project file; secrets stay in `.env`, never in the skill.
- **Schedules live in `.roosta/tasks.yaml`**, never in the skill: say what one run does, not when it runs.
- **Scheduled skills** end with one `<task-output>` JSON line (`summary`, `status`, `details`) and return board cards in `details.items` using the shape in the `assistant` skill's board contract. Each one also needs a task in `.roosta/tasks.yaml` and an Office look in `.roosta/office-cast.yaml` (named worker, body to match the name, hair and props to fit the job): follow [references/scheduled-worker.md](references/scheduled-worker.md).
- Write in the language `PROFILE.md` names: plain, direct, no filler.

## 4. Check it

Read the description cold: would an agent pick this skill for the user's last three requests of this kind, and not for the neighbouring ones? Run the skill once on a real case. For a scheduled skill, confirm the task shows on the Workers page and the worker wears its look in the Office. Fix what it got wrong in the section whose framing caused it, rather than adding a special case.

## Related

| Link | Relationship |
|------|--------------|
| [[skill-auditor]] | Reviews the whole skill set on a schedule |
