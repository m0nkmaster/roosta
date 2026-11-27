# Managing workspace skills

For an overview and the built-in catalogue, see [Skills give your workers their jobs](../README.md#skills-give-your-workers-their-jobs).

In Settings → Workspace and runner, **Review customisations** opens an unsent chat draft comparing your local behaviour with installed core. You choose which preferences to keep. For terminal use, run the following commands from your workspace (or pass `--workspace <folder>` to workspace commands).

- **Add a preference.** `roosta skills extend NAME` prints the editable file at `.roosta/skill-extensions/NAME.md`. Roosta reads it after the skill on each turn. The installed instructions keep improving on upgrade. Additions cannot change approval, tool or output protocols.
- **Replace a skill.** `roosta skills fork NAME` pins a complete editable tree under `.roosta/skill-forks/NAME/`. Settings and `roosta skills status` identify forks and flag when the installed tree has changed since the fork was created.
- **Return to core.** Compare the fork with `NAME/` under the folder printed by `roosta skills path`. Move the preferences you want into an extension, then run `roosta skills use-core NAME`. With the runner open, the switch takes effect on restart so active turns can finish. The complete fork moves into `.roosta/skill-archive/forks/` for recovery. The same command archives a retired skill under `retired/`. Setup can help review scripts, references and behavioural differences before you switch.

**Upgrading an older workspace.** Run `roosta skills sync` to see pending changes. Let active runs finish, then restart to apply them.

- Roosta archives verified generated copies in `.roosta/skill-archive/`. Clean or missing copies use installed core. Edited or unverifiable trees become active forks for review.
- Roosta checks independent Claude and Agents copies separately. A clean Agents copy follows core even if the Claude copy differs. If both have edits, the Agents copy stays active and the Claude copy goes into the archive's `review-claude/` folder for review.
- Retired skills in the old lock survive as workspace forks. Other custom skills stay in place. Linked or incomplete trees remain available for review in Settings while other skills migrate.
- Roosta keeps the old lock and archives recognised generated operating models before installing a small pointer. Edited operating models and workspace instructions stay in place.

For standalone agent sessions, run `roosta skills instructions [NAME]` in the workspace. It prints the same operating model and effective file routes as dashboard turns. A same-named project or global skill cannot shadow installed core.
