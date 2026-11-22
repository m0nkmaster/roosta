# Making a scheduled skill a worker

A scheduled skill is only finished when it has a task and an Office look. Do all three.

## 1. Task

Add an entry to `.roosta/tasks.yaml`: `id` (= skill name), `skill`, a `nickname` (a human first name, unique in the file), a cadence (`run_at: "HH:MM"` or `interval` seconds, plus `weekdays_only` / `days_of_week`), `writer: true` if it commits to the vault, `requires: [<connector>]` for each live tool it needs, and `dir`. Omit `connection` to follow the default; add a connected named connection id only when the user asks to pin this worker to that account. Copy the shape of a neighbouring task. The runner reloads the file itself and runs a new task once straight away.

## 2. Office look

Add one line to `.roosta/office-cast.yaml`, keyed by the lower-case nickname:

```yaml
dwight: { body: m, tone: Tan, hair: parted/Charcoal, glasses: halfmoon }  # my-task, the example worker
```

- **Body and head match the nickname:** `body: f` for a conventionally female name, `m` for a male one; `head: old` (optional) for a senior or veteran character. A unisex name: choose one and say which in the comment.
- **Tone** (skin): `Brown Coffee Honey Peach Porcelain Tan`. Vary it across the cast rather than repeating the most common one.
- **Hair** is `style/Colour`, and only these combinations exist: balding Ash|Brown; bob Chestnut|Orange; bob-bangs Raven; bun Silver; buzzcut Black|Silver; cowlick Black|Blonde; curly Blonde|Red; curly-short Black|Red; dreadlocks Black; flattop Black; flattop-fade Brown; idol Violet; natural Black|Green; page Blonde|Raven; parted Black|Charcoal|Silver; twists Brown; twists-fade Black.
- **Beard** (optional, `body: m`): beard Brown|Green, beard-trimmed Red|Silver, tache-handlebar Charcoal, tache-horseshoe Ash|Brown.
- **Glasses** (optional): `halfmoon` or `round`.
- **Fit the job:** let the look say what the worker does. Reviewers, archivists and auditors get glasses; a senior or long-running job gets silver hair or `head: old`; a fast watcher gets something short and practical (buzzcut, bob); a creative job can get bold colour (idol Violet, natural Green). Comment each line `# <task id>, the <one-word job>`.
- **Shirt is automatic:** the Office picks it from the role in the task id or skill name (`watch`/`support` Lookout, `tracker`/`incident` Detective, `gardener`, `learner`, `auditor`, `engineer`, digest/brief/review/triage Clerk, otherwise Worker). Choose a name with the right word so the role, and so the shirt and desk habits, fit.

Use the listed sprite combinations. The Office falls back to its default look when a layer is missing.

## 3. Check

The task appears on the Workers page and its first run lands in `.roosta/state/cache/<id>.json`. The worker in `/office` wears its look.
