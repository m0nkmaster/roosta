# Audit dimensions

Every pass, weigh the set against **both** blocks. The first is mechanical hygiene -
the floor. The second is where opinion earns its keep; a skill can pass every hygiene
check and still fail these.

## Hygiene (the floor)

| Dimension | Smell | Fix |
|-----------|-------|-----|
| **Bloat** | Body repeats itself; > ~250 lines of prose; a 500-line catalogue inline | Tighten; move depth into `references/`; the SKILL routes, references hold detail |
| **Description & triggers** | Won't fire when it should; vague; overlaps another skill's triggers | Sharpen the frontmatter `description` and trigger phrases |
| **Overlap / duplication** | Two skills cover the same ground | Merge into one canonical skill; delete the loser; fix inbound links |
| **Portability** | Depends on a workspace-only path or `[[wikilink]]` prerequisite (but see the workspace-management carve-out in SKILL.md - don't re-flag those) | Bundle the reference inside the skill; make paths relative |
| **Dead references** | Links, paths or bundled files that no longer exist | Repoint or remove |
| **Staleness** | Example or fact contradicted by current reality | Correct against ground truth |

## Opinion (where you go far-reaching)

| Dimension | Smell | Fix |
|-----------|-------|-----|
| **Wrong approach** | Skill works but tackles the problem in a clumsy or dated way; you'd design it differently from scratch today | Redesign it - don't just tidy the edges |
| **Timid** | Skill under-reaches: does half of what it obviously should, hedges where it should be decisive, or defers work back to the user it could own | Make it bolder and more complete |
| **Missing (ambitious)** | The single most valuable skill the user *doesn't* have, given how they actually work | Propose it forcefully - create it if clear-cut, else log it as a lead |
| **Better idea** | A different structure, split or shared reference would make a whole family sharper | Pursue it if confident; otherwise log a concrete proposal |
