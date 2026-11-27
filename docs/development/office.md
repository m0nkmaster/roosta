# Office simulation and artwork

[Agent guide](../../AGENTS.md). Read before changing `src/roosta/static/office.html`, its `office-*.js` scripts or its assets.
The page chrome follows the [shared UI rules](ui.md); simulation and art details follow.

## Scene and interactions

- **Code layout.** `office.html` is the page chrome and styles. The scene is plain classic scripts that
  share one global scope, loaded in this order (each file opens with its job; `// ===` headers mark sections):
  `office-world.js` (canvas setup, art, cast, roles, seasons, rooms, A* grid, clock and weather),
  `office-people.js` (workers, off-shift activities, emotes and quips, simulation, overtime errands),
  `office-games.js` (table tennis, foosball, darts, console TV), `office-ambient.js` (Ceefax, the cat,
  the robot vacuum), `office-render.js` (static background and frame drawing), `office-ui.js` (HUD,
  roster, dossier, ticker, employee of the week, input), `office-data.js` (polling and saved scene) and
  `office.js` (main loop and boot, always last). Top-level code may only use names from its own file or
  an earlier one; functions are free to call anything at run time. Format with Prettier
  (`--print-width 120 --tab-width 4`). Tests lift top-level `function`s and `const`s from the scripts
  in load order (`_lift`, `_const` in `tests/test_office.py`).
- **`static/office.html`** - Office page: a top-down pixel-art office (2D canvas, LPC Revised
  sprites) where each scheduled task is a worker placed by its live `/api/tasks` status - at a desk
  with a lit laptop and a progress bar (elapsed against `last_duration`; the start time is only
  knowable client-side, so it is recorded in `localStorage` when the page sees the run begin),
  waiting for the writer lock (queued: playing a game on a desk laptop under a gamepad bubble, or staring
  out of a window when no desk is free; a running task outranks them for desks), round the meeting table
  facing a frozen video-call screen (auth-failed stands at the screen, blocked tasks sit), in the sick
  bay (error/interrupted), or roaming between runs across seven walled rooms in two rows joined by
  doorways - top: ops floor (server rack LEDs follow runner load), meeting room (whiteboard shows a
  live sticky-note kanban by state) and kitchen (fitted units, breakfast bar, dining table); bottom:
  first aid (the sick bay), lounge (sofas round a wall TV showing BBC headlines as Ceefax pages from
  `/api/news`, cached 15 min; click it for the full page, a fixed 4:3 screen whose type scales with its width, where page 152 is a playable Bamboozle! quiz:
  hosted by a Teletext-mosaic Bamber Boozler, ten questions a day from `/api/bamboozle`, fetched once daily from The Trivia API, falling back to Open Trivia DB,
  cached in `cache/bamboozle.json`) and games room (arcades, a console den whose TV rotates retro game demos, table tennis,
  foosball, darts) and the user's office (a dead-end room off the games room, named from `PROFILE.md`, where
  off-shift workers drop in during working hours; the user's chair stays empty). Off shift, every spot has a visible activity with a
  held prop - watching TV, reading, eating at café tables, sipping, phones, watering plants,
  sketching on the whiteboard, meetings - and a kitchen trip hands the worker a drink or snack
  they carry to a seat. A* pathing to nearby, role-weighted spots, with eased walking, avoidance,
  turn-taking chat with gestures, shop talk (a chat pair trades what their last runs produced:
  `gist()` trims each task's `last_output.summary` to one speech-bubble clause and drops anything
  path-, URL- or secret-shaped, a good/quiet/bad tone picks the reply, one scripted conversation
  runs at a time, each run's news is retold at most twice, with occasional gossip about a third
  worker's run), waves in passing, desk visits and ping-pong rallies. A finished run earns a victory hop and a trip to the coffee machine; a failure
  is a slow walk to the sick bay; level-ups burst. An office cat (wanders, naps in sunbeams or by
  the warm rack, follows people, gets petted, meows when clicked) and a night-time robot vacuum
  it sometimes rides. Speech quips type out. Day/night
  follows local time: live sky (clouds, birds, stars, plane, city lights), real-time wall clock,
  dust in the sunbeams, golden-hour grade, darkness with lamp/screen light pools. Seasonal themes follow the UK
  calendar (`seasonFor`; `?season=` overrides): Christmas, New Year, Easter egg hunt, Valentine's, Pride, Halloween,
  bonfire-week fireworks and Friday the 13th (a black cat), decor from `vendor/lpc/seasonal/`. An employee-of-the-week frame by the front door shows the
  best clean-run record, folded from `/api/activity` into `localStorage` (`office-eotw-v1`) and crowned Fri 16:00. The chrome around the scene
  is standard shell and Tabler (page header, stat cards for lifetime runs, runs today counted from
  `/api/activity` since midnight, and clock, status badges, a Crew card with portrait roster) and a
  dossier card (level = √runs, cadence, next due, last error). Role and layout derive
  client-side from skill name and task id. The look comes from the nickname: `CAST`
  maps each one to a body, skin tone, hair, beard and glasses that suit the name (the shirt stays the
  role's colour), and an unlisted nickname gets a hashed masculine look. `tests/test_office.py` fails
  until every starter-schedule nickname is cast and every layer it needs is vendored. Workers go by their `tasks.yaml`
  `nickname` (else the task id) on name tags, the roster, dossier, ticker, confirms and gossip. Interactive as well as watchable: it
  drives the runner from the dossier (Send to desk = `POST /run`, Cancel queued run = `POST /cancel`;
  **1:1 chat** opens the standing `worker:<task id>` thread on the Assistant board, where `worker_chat_item`
  hands the model a `voice` to speak as that worker and refine its SKILL.md with the user's agreement)
  behind a deliberate click and confirm naming the task, off in `?demo`, never from the simulation, a
  timer or a URL param; pure helpers are lifted and tested under Node in `tests/test_office.py`. The office
  keeps going between visits: the scene (workers, cat, vacuum, ping-pong, conversations) is saved to
  `localStorage` (`office-state-v1`, furniture stored by index) on leaving and every 10s, then restored on
  return with `clockSkew` re-based to the saved instant, the latest statuses applied, and the time away
  replayed (`catchUp`: at most the last 5 minutes are simulated, any longer gap just expires timers; a hidden
  tab replays its gap the same way). Nobody teleports: only off-shift workers on a cold start are placed
  directly; a new worker enters through the front door and everyone walks to desks, windows, the meeting room or sick bay.
  `?demo` and `?warp` neither read nor write the saved state. URL params: `?demo` fakes every state, `?hour=HH` previews time of day, `?worker=<id>`
  opens a dossier, `?names` shows all name tags, `?warp=N` fast-forwards the simulation N seconds

## Rendering and visual checks

- **Office interactions.** The kitchen has two café tables and a clickable fridge
  (lit interior and night light, snack trips and missing-yoghurt reactions). The lounge fireplace
  follows `fireState`: daytime fires in cold months, embers in the evening, out overnight;
  workers visit the hearth while it burns. Clicking pokes it, with flares, sparks or smoke.
  The vendored fireplace accessories include tools and Christmas stockings. The grandfather
  clock strikes on click and at daytime hour changes (visual speech, no audio); automatic
  chimes and dart challenges are suppressed during initial warp/catch-up.
- **Games stay ambient.** Clicking table tennis or foosball calls two distinct free off-shift
  colleagues, or cheers an existing game; console clicks swap games and call up to two players.
  Table tennis uses `pongPoint` (first to eleven, win by two), a flip counter and a maximum
  four-minute stay; clicking a long rally jinxes the point. Real runs always take priority.
  A colleague at the dartboard may challenge the user's next three darts to beat their best
  (or 60). These interactions never start runner work or make API writes.
- **Schedule cues.** `shiftPull` biases off-shift workers towards the ops floor within three
  minutes of their next slot; `shiftNote` explains it on the dossier. `overdueBy` marks starts
  over ten minutes late only after the open Office watches for another two minutes, excluding
  running, queued and sign-in-blocked tasks. These cues do not change the schedule. `grimNews`
  filters news/sport titles and summaries before building Ceefax pages. The roster footer lists
  clickable toys by room. Saved scenes with an old furniture count restart the scene; task,
  chat and worker records are unaffected.

- **The Office page uses real pixel art on a plain 2D canvas, no build step.** Game-grade looks
  need real art, so it composites vendored LPC Revised sheets rather than hand-drawn shapes. The
  scene renders at a fixed 1280x720 logical resolution (roughly one art pixel per CSS pixel at
  full width), every sprite at 1x, then is upscaled nearest-neighbour to fill the cabinet width on
  a device-pixel canvas; text is drawn after the upscale so it stays crisp.
  Sprite crops (`C` in `office-world.js`) were measured from the sheets' alpha bounding boxes - re-measure
  rather than guess when adding art. Headless visual check: `Google Chrome --headless=new
  --force-device-scale-factor=2 --virtual-time-budget=6000 --screenshot` against a
  `python3 -m http.server` root holding a `static` symlink and a mock `api/tasks` file, with
  `?demo&hour=23&warp=90` to see every state at night. Add `warp`: headless virtual time barely
  ticks `requestAnimationFrame`, so without it you only see the first few frames. Use a fresh
  `--user-data-dir` per shot or Chrome serves the cached page.

## Assets and attribution

- **`static/vendor/lpc/`** - Unmodified sheets from the [LPC Revised](https://github.com/ElizaWy/LPC)
  pack (OGA-BY 3.0, attribution in `Credits.txt` and the page legend), renamed into a flat layout.
  Characters are layered 64px frames (rows up/left/down/right), stacked by `layersOf`:
  `hair-behind` (long styles only), `body`, `legs`, `feet`, `shirt`, `head`, beard, `hair`, `glasses`.
  Feminine sets carry a `-f` suffix and `head-old` is the elderly head; hair and beards are
  `hair/<style>/<colour>`. The body sheet has no head, so both layers are needed. Only the
  combinations in use are vendored: fetch another from the LPC repo's `Characters/` tree into the
  same layout when casting someone new

- **`static/fonts/PressStart2P-*` and `PixelifySans*`** - OFL pixel fonts for text drawn inside the Office canvas; the page chrome uses Inter
