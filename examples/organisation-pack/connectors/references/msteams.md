# Microsoft Teams via `msteams` (organisation-specific)

Offer this only when `command -v msteams` succeeds: the CLI is distributed inside some organisations and rides the user's own browser session, so it cannot run unattended on a server.

- **Access:** `msteams <tool> ... --json` prints the payload directly; redirect it to a file, because piped output can be cut off at 64 KB. Parameters are camelCase; `msteams help <command>` lists flags.
- **Sign-in:** `msteams login` (interactive). `teams_get_me` answers from a cached profile, so it is not a sign-in check. The messaging token lapses on its own while the session is still good, and the CLI usually recovers it with a headless re-login. Leave `messaging.available` out of `expect`, and have each Teams skill run `msteams login` once and retry when a read fails on sign-in, asking the user only if that fails. A `fetch failed` from search is a search outage, not a sign-in failure: fall back to thread reads.

```yaml
- id: teams
  name: Microsoft Teams
  check: msteams teams_status --json
  # messaging.available is left out on purpose: see Sign-in
  expect: {success: true, directApi.available: true}
  reject: {session.likelyExpired: true}
  login: msteams login
  deny:
    - msteams send
    - msteams teams_send_message
    - msteams teams_edit_message
    - msteams teams_delete_message
    - msteams teams_add_reaction
    - msteams teams_remove_reaction
    - msteams teams_create_group_chat
```

- **Quirks:** copy `messageLink` verbatim; channel and chat permalinks differ and a hand-built one does not open. Thread reads use `--limit` and `--since`; search pages use `--from` and `--size`; results are newest first. Markdown tables do not render in Teams chats; send `--contentType html` with a `<table>` instead. Do not copy message bodies into tracked workspace docs: record what was learned, with the `messageLink`.
- **Pre-check for a self-chat watcher:** a task polling the user's note-to-self chat can skip unchanged polls with `precheck:` set to a small script that compares the newest message id with the skill's watermark and exits 1 when nothing is new.
