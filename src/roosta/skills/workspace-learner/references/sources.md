# Sources - AI conversations and connected chat

Use the independent cursors and gap rules in `checkpoints.md`. Never infer that a source was covered from the pass watermark in the learning log.

## AI conversations (the baseline, always available)

The bundled helper reads genuine interactive sessions from OpenCode, Cursor, Claude Code and the Assistant's `.roosta/state/assistant/chat-history.json`, while excluding subagents, scheduled Roosta runs (matched by `BG_PHRASES` in `sessions.py`) and trivial sessions:

```bash
# Set helper to the absolute path of sessions.py beside this skill’s SKILL.md.
# Run from the workspace.
python3 "$helper" status
python3 "$helper" list [SINCE] --source SOURCE --before TIME --json
python3 "$helper" transcript SOURCE:ID
python3 "$helper" transcript SOURCE:ID --tools
```

Each list row contains `SOURCE:ID`; pass that full token to `transcript`. Add `--tools` when a session suggests a query, path or tool failure.

The Assistant history has no per-message timestamps, so the helper treats every conversation as updated when the file's modification time crosses its checkpoint. Read each returned conversation completely and deduplicate already handled facts.

**Inline Assistant captures:** when the `actor` skill already promoted a correction in a board chat, it wrote the canonical doc and appended a line to `notes/assistant-captures.jsonl`. Treat matching facts from that conversation as **Already handled**.

## Connected chat and email

Learn from whatever chat or email connectors the workspace has (`.roosta/connectors.yaml`, `TOOLS.md`). Skip this section entirely when there are none: AI conversations alone are a complete pass.

For each connected source:

- Read the channels and tracked DMs `TOOLS.md` names as mattering, plus the user's activity feed if the tool has one. Follow that tool's paging and timestamp rules in `TOOLS.md` before any read; a wrong field name looks like an empty source.
- Sort by timestamp before reading; many tools return newest first. Keep each message's permalink.
- An activity feed also surfaces replies outside the named channels. When one names a thread the user is personally driving, read that single thread rather than adopting the whole channel.
- Track each channel separately and chat discovery separately from each DM, so one inaccessible conversation cannot hide or advance the others. A newly relevant DM gets its own state key, its live checkpoint set to the discovery window's start and backfill marked incomplete.
