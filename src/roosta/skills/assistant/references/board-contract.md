# Assistant board contract

The shape every scheduled skill uses to put cards on the Assistant board. The `assistant` conductor owns judgement; this file owns the **shape**, so sensors do not drift.

## Envelope

Finish with exactly one parseable line, no fenced wrapper:

```text
<task-output>{"summary":"<one line>","status":"success"|"error","details":{...}}</task-output>
```

- `status: "error"` only when the pass itself failed (auth, unreadable workspace).
- A quiet run with nothing for the user is `status: "success"` with `details.items: []`.

## `details.items`

Any scheduled skill may return board-shaped dicts in `details.items`; the board merges every task's latest output by exact `id`. Two skills land on one card only with the **same** id, so read the board first (see **Updating an existing card**).

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | Stable slug while the same reason for attention stays open. For a chat thread: `<source-prefix>-<threadRootId>`, no topic words, so every skill that sees the thread lands on one card. Other sources use their own stable key (`incident-<slug>`, `proj-1234-<topic>`). |
| `project_ref` | yes | Canonical `projects/<slug>` after reading that README, or `null`. |
| `title` | yes | Outcome, risk or decision in at most eight words. Plain text. |
| `why` | yes | One short sentence on urgency or impact. Markdown OK. |
| `situation` | yes | At most two short decision-relevant sentences. Markdown OK. |
| `opening_move` | yes | One direct recommendation. Markdown OK. |
| `action_owner` | yes | `assistant` when the board can prepare, draft or investigate; `user` when the user must decide, approve or send. |
| `action_label` | yes | Specific two-to-four-word imperative. Never "Go" or "Open". |
| `action_type` | yes | One of `chat` (any chat message), `ticket` (any ticket), `email`, `standup`, `meeting`, `document`, `review`, `decision`, `task`. |
| `links` | yes | 0-3 http(s) CTAs from tool responses or workspace docs read this pass. Never invent or hand-build URLs. |
| `documents` | optional | Workspace Markdown read or written this pass: `[{"label":"Open draft","path":"drafts/foo.md"}]`. |
| `new` | yes | `true` if materially new this pass. |

### Links

- Every chat-sourced item carries the thread link returned by the read that surfaced it. Prefer the thread root over a reply deep link.
- Copy permalinks verbatim; never assemble one from ids.
- Labels stay short: "Open thread", "PROJ-8769", "Open board".

## Channel ownership

Give each chat source one owning sensor and one id prefix, and record the table in `TOOLS.md`. Any skill may add or refine a card for a thread, but it uses the owning prefix so it lands on the same card. Within one skill, keep one id per open thread; when the situation sharpens, set `new: true` and update the copy instead of minting a new id.

## Still the user's?

Before returning a new card, or re-returning an open one, check the live source this pass. Drop the item if it is handled:

| Source | Handled when |
|--------|--------------|
| Chat thread | the user replied substantively after the ask, or a colleague answered and they were not mentioned again |
| Ticket | reassigned away from them, resolved, or past the state that needed them |
| PR | merged, closed or already approved by them |
| Deadline or meeting | passed |

When unsure, drop it. `handled.json` removes dismissed episodes; it does not replace the live check.

## Updating an existing card

Read what is already on the board before minting:

```bash
roosta snapshot board
```

It prints the board JSON; the cards are in `.document.items`.

A successful snapshot with empty `document.items` and `document.later` confirms an empty board, including before any worker has written a cache. If the snapshot fails, read `last_output.details.items` from the conductor and sensor caches in `.roosta/state/cache/`. If the prior cards cannot be recovered, report the read failure with `status: "error"` and omit `details.items` so the runner preserves the previous cards.

- **Same subject already on the board:** return an item with that card's `id` and only the fields you improve, each rewritten in full. Links and documents you add are combined with the card's.
- **The newest run wins per field.** Fields you omit stay as they are. `new: true` only for a material update.
- **A refinement needs a live card.** An item without a `title` whose id is not on the board is dropped.
- **Different reason, different card:** a win on a thread that also carries an action is its own episode.

Different ids for the same topic are caught by the conductor, which folds them and returns `details.merges`. Keep returning your id; it refines the kept card from then on.

## Extra `details` keys

A skill may add top-level `details` keys next to `items`, for example `draft` (a workspace path the board offers as "Open draft"). The conductor adds `done_today` and `merges`.

## Tool parity

Scheduled and chat runs are headless. OAuth-backed MCP servers may report `needsAuth` there even when they work interactively. Say the server needs sign-in in this runtime and ask the user for the content; never report the page as missing.
