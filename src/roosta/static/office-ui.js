// Office page. The page around the scene: HUD, roster, dossier, ticker, employee of the week and input.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// ================================================================ HUD, roster, dossier, ticker
const fmtAgo = (iso) => {
    if (!iso) return "never";
    const d = (Date.now() - new Date(iso).getTime()) / 1000;
    if (isNaN(d)) return "—";
    if (d < 0) return "soon";
    if (d < 90) return "just now";
    if (d < 3600) return Math.round(d / 60) + "m ago";
    if (d < 86400) return Math.round(d / 3600) + "h ago";
    return Math.round(d / 86400) + "d ago";
};
const fmtDur = (s) => {
    if (!s && s !== 0) return "—";
    s = Math.round(s);
    if (s < 90) return s + "s";
    if (s < 5400) return Math.round(s / 60) + "m";
    if (s < 172800) return Math.round(s / 3600) + "h";
    return Math.round(s / 86400) + "d";
};
function nextDue(t) {
    const at = dueAt(t, Date.now());
    if (at === null) return t.interval || t.run_at ? "not today" : "—";
    const due = at - Date.now();
    return (due <= 0 ? "due now" : "in " + fmtDur(due / 1000)) + (t.retry_at ? " (retry)" : "");
}
const countsOf = (list) => {
    const c = { working: 0, queued: 0, locked: 0, hurt: 0, resting: 0 };
    for (const t of list) c[behaviour(t)]++;
    return c;
};
let counts = countsOf([]);
// Runs started since local midnight. /api/activity returns at most 200 rows, newest first; if the oldest
// row is still today the log was truncated, so the count is a floor ("200+").
function runsToday(rows, midnight) {
    let n = 0,
        oldest = Infinity;
    for (const r of rows) {
        const t = Date.parse(r.started);
        if (isNaN(t)) continue;
        oldest = Math.min(oldest, t);
        if (t >= midnight) n++;
    }
    return { n, floor: rows.length >= 200 && oldest >= midnight };
}
// Consecutive failed runs per task, newest run backwards (a success ends the streak; live runs are skipped).
function errorStreaks(rows) {
    const out = {},
        done = new Set();
    const sorted = rows
        .filter((r) => r.task_id && r.status !== "running")
        .sort((a, b) => Date.parse(b.started) - Date.parse(a.started));
    for (const r of sorted) {
        if (done.has(r.task_id)) continue;
        if (r.status === "error" || r.status === "interrupted") out[r.task_id] = (out[r.task_id] || 0) + 1;
        else done.add(r.task_id);
    }
    return out;
}

// ================================================================ employee of the week
// The frame by the front door holds the week's best clean-run record: success rate, then successful runs, with at least
// EOTW_MIN finished runs. It is crowned on Friday at 16:00 (a ceremony if the Office is open then) and held until the next.
// /api/activity only reaches back 200 runs (about a day), so the week's tally is folded together in localStorage
// (office-eotw-v1), keyed by run id, from every poll; a week the Office started watching late says "since <day>".
// shortcut: a gap of more than a day with the page closed loses those runs; take a since= activity param if it matters.
const EOTW_KEY = "office-eotw-v1",
    EOTW_MIN = 3;
const EOTW_SAVE = !DEMO && HOUR_OVERRIDE == null && DAY_OVERRIDE == null && !params.has("warp");
function weekStartOf(ms) {
    // Monday 00:00 local time
    const d = new Date(ms);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime();
}
function eotwRank(store, ids) {
    const by = {};
    for (const k in (store && store.runs) || {}) {
        const [id, ok] = store.runs[k];
        const b = by[id] || (by[id] = { id, ok: 0, n: 0 });
        b.n++;
        b.ok += ok;
    }
    return Object.values(by)
        .filter((b) => b.n >= EOTW_MIN && (!ids || ids.includes(b.id)))
        .sort((a, b) => b.ok / b.n - a.ok / a.n || b.ok - a.ok || (a.id < b.id ? -1 : 1));
}
// Fold activity rows into the week's tally; a new week starts afresh, crowning last week's best first if Friday was missed.
function eotwTally(store, rows, wk, now) {
    let s = store;
    if (!s || s.week !== wk) {
        let holder = s ? s.holder || null : null;
        if (s && s.week < wk && s.awarded !== s.week) {
            const top = eotwRank(s)[0];
            if (top) holder = { ...top, week: s.week };
        }
        let since = wk; // a full 200-row window that starts after Monday means the Office missed the start of the week
        if (rows && rows.length >= 200) {
            let o = Infinity;
            for (const r of rows) {
                const t = Date.parse(r.started);
                if (t < o) o = t;
            }
            if (o > wk && o < Infinity) since = o;
        }
        s = { week: wk, since: Math.min(since, now), runs: {}, holder, awarded: null };
    } else s = { ...s, runs: { ...s.runs } };
    for (const r of rows || []) {
        if (!r || !r.id || !r.task_id || !["success", "error", "interrupted"].includes(r.status)) continue;
        if (!(Date.parse(r.started) >= wk)) continue;
        s.runs[r.id] = [r.task_id, r.status === "success" ? 1 : 0];
    }
    return s;
}
function eotwDue(day, t) {
    return (day === 5 && t >= 16) || day === 6 || day === 0;
}
function eotwAward(store, day, t, ids) {
    if (!store || store.awarded === store.week || !eotwDue(day, t)) return null;
    const top = eotwRank(store, ids)[0];
    return top ? { holder: { ...top, week: store.week }, ceremony: day === 5 && t < 19 } : null;
}
let eotw = null,
    eotwView = null,
    frameFlashUntil = 0;
try {
    eotw = JSON.parse(localStorage.getItem(EOTW_KEY) || "null");
} catch (e) {
    eotw = null;
}
function eotwShown(store, ids, has) {
    // the crowned holder, else this week's leader so far
    if (store && store.holder && has(store.holder.id))
        return { ...store.holder, kind: "holder", lead: eotwRank(store, ids)[0] || null };
    const top = store && eotwRank(store, ids)[0];
    return top ? { ...top, kind: "leader", lead: top } : null;
}
function eotwUpdate(rows) {
    const now = Date.now(),
        T = clock(),
        ids = tasks.map((t) => t.id);
    eotw = eotwTally(eotw, rows, weekStartOf(now), now);
    const aw = eotwAward(eotw, T.day, T.t, ids);
    if (aw) {
        eotw.holder = aw.holder;
        eotw.awarded = eotw.week;
    }
    eotwView = eotwShown(eotw, ids, (id) => workers.has(id));
    if (aw && aw.ceremony) eotwCeremony(tnow());
    if (EOTW_SAVE)
        try {
            localStorage.setItem(EOTW_KEY, JSON.stringify(eotw));
        } catch (e) {
            /* storage full: the tally restarts */
        }
}
const dayMonth = (ms) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
function eotwText(v) {
    const who = (id) => nickOf(tasks.find((t) => t.id === id) || { id }),
        rec = (b) => `${b.ok}/${b.n} clean runs`;
    if (!v) return "Employee of the week · crowned Fri 16:00 · best clean-run record wins";
    if (v.kind === "holder")
        return (
            `Employee of the week: ${who(v.id)} · ${rec(v)} (w/c ${dayMonth(v.week)})` +
            (v.lead && eotw.awarded !== eotw.week ? ` · this week ${who(v.lead.id)} leads, ${rec(v.lead)}` : "")
        );
    const late =
        eotw && eotw.since > eotw.week + 3600e3
            ? " since " + new Date(eotw.since).toLocaleDateString("en-GB", { weekday: "short" })
            : " this week";
    return `Employee of the week race: ${who(v.id)} leads · ${rec(v)}${late} · crowned Fri 16:00`;
}
// Friday 16:00: the frame lights up, the winner (if off shift) steps up under it, and the nearest colleagues cheer.
function eotwCeremony(now) {
    const w = eotw && eotw.holder && workers.get(eotw.holder.id);
    if (!w) return;
    frameFlashUntil = now + 6000;
    starBurst(FRAME.x + 14, FRAME.y + 18);
    floatText(FRAME.x + 14, FRAME.y + 52, "EMPLOYEE OF THE WEEK!", "#ffd166");
    w.emote = "star";
    w.emoteUntil = now + 3000;
    if (w.state === "resting" && !w.errand && !FRAME_POI.taken) {
        leaveSpot(w);
        w.carry = null;
        sendTo(w, FRAME_POI);
        say(w, pick(QUIPS.eotwWho, Math.random()), now);
    } else {
        say(w, pick(QUIPS.eotwBusy, Math.random()), now);
        eotwCheer(w, now, 1400);
    }
}
function eotwPose(w, now) {
    frameFlashUntil = Math.max(frameFlashUntil, now + 4000);
    w.celebrateUntil = now + 1800;
    w.celebrateStart = now;
    w.emote = "star";
    w.emoteUntil = now + 3000;
    confetti(w.x, w.y - 40);
    starBurst(w.x, w.y - 30);
    say(w, pick(QUIPS.eotwSpeech, Math.random()), now);
    eotwCheer(w, now, 900);
}
function eotwCheer(w, now, delay) {
    // up to three free colleagues nearby turn to the winner and cheer
    const near = [...workers.values()]
        .filter(
            (o) =>
                o !== w &&
                o.state === "resting" &&
                !o.path.length &&
                o.act !== "nap" &&
                Math.hypot(o.x - w.x, o.y - w.y) < 320,
        )
        .sort((a, b) => Math.hypot(a.x - w.x, a.y - w.y) - Math.hypot(b.x - w.x, b.y - w.y))
        .slice(0, 3);
    near.forEach((o, i) => {
        o.lookDir = dirTo(o, w.x, w.y);
        o.lookUntil = now + delay + 4000;
        o.emote = "star";
        o.emoteUntil = now + delay + 3000;
        o.quip = pick(QUIPS.eotwCheer, Math.random());
        o.quipStart = now + delay + i * 900;
        o.quipUntil = o.quipStart + 3000;
    });
}
let activityAt = 0,
    streaks = {};
async function pollActivity() {
    if (Date.now() - activityAt < 60e3) return;
    activityAt = Date.now();
    const el = document.getElementById("hud-today");
    try {
        const r = await fetch("/api/activity?limit=200", { cache: "no-store" });
        if (!r.ok) throw new Error(r.status);
        const rows = await r.json();
        const { n, floor } = runsToday(rows, new Date().setHours(0, 0, 0, 0));
        streaks = errorStreaks(rows);
        eotwUpdate(rows);
        for (const w of workers.values())
            if ((w.state === "hurt" || w.state === "working" || w.state === "queued") && streaks[w.id])
                w.streak = Math.max(w.streak || 0, streaks[w.id]);
        if (counts.hurt) {
            assign(tasks);
            events(tasks);
        }
        el.textContent = n.toLocaleString() + (floor ? "+" : "");
    } catch (e) {
        el.textContent = "—";
    }
}
function updateHud() {
    counts = countsOf(tasks);
    const T = clock();
    document.getElementById("hud-clock").textContent =
        String(T.h).padStart(2, "0") + ":" + String(T.m).padStart(2, "0");
    const totalRuns = tasks.reduce((a, t) => a + (t.run_count || 0), 0);
    document.getElementById("hud-score").textContent = totalRuns.toLocaleString();
    const chips = [
        ["working", "on shift"],
        ["queued", "queued"],
        ["locked", "signed out"],
        ["hurt", "sick"],
        ["resting", "roaming"],
    ];
    document.getElementById("hud-chips").innerHTML = chips
        .map(
            ([k, l]) =>
                `<span class="badge state-badge${counts[k] ? "" : " zero"}" style="--c:${UI_COL[k]}"><i class="dot"></i><b>${counts[k]}</b>${l}</span>`,
        )
        .join("");
    let head, sub, col;
    const night = nightShift(T),
        late = lateNote([...workers.values()], whoOf, fmtDur);
    if (counts.locked) {
        const signIn = tasks.some((t) => t.status === "blocked");
        const sickSub = counts.hurt ? ` · ${counts.hurt} in the sick bay` : "";
        head = "Signed out";
        // the action leads, so a narrow window's ellipsis cuts the detail, not what to do
        sub =
            (signIn ? "A sign-in needs you" : "An AI engine is unavailable") +
            ` · ${counts.locked} stuck on a frozen call in the meeting room` +
            sickSub;
        col = UI_COL.locked;
    } else if (counts.hurt) {
        head = "Sick bay";
        sub = `${counts.hurt} worker${counts.hurt > 1 ? "s" : ""} hit an error on the last run`;
        col = UI_COL.hurt;
    } else if (counts.working >= 3) {
        head = "Office humming";
        sub = `${counts.working} desks busy${counts.queued ? `, ${counts.queued} waiting their turn` : ""}`;
        col = UI_COL.working;
    } else if (counts.working) {
        head = "Shift moving";
        sub = `${counts.working} at a desk${counts.queued ? `, ${counts.queued} queued` : ""}`;
        col = UI_COL.working;
    } else if (counts.queued) {
        head = "Waiting their turn";
        sub = `${counts.queued} gaming or gazing until the writer lock frees`;
        col = UI_COL.queued;
    } else {
        const wk = T.day === 0 || T.day === 6,
            ph = dayPhase(T.day, T.t),
            dusk = !night && darkness(T) > 0.25;
        head = night
            ? wk
                ? "Weekend night shift"
                : "Night shift"
            : wk
              ? (T.day ? "Saturday" : "Sunday") + " skeleton crew"
              : ph === "lunch"
                ? "Lunch hour"
                : ph === "evening"
                  ? "Evening wind-down"
                  : dusk
                    ? "Lamps on"
                    : "All quiet";
        sub = wk
            ? "Weekend: the crew lounges between runs"
            : ph === "lunch"
              ? "Lunch hour: the crew is in the kitchen between runs"
              : ph === "morning"
                ? "Morning: coffee and stand-up around the board between runs"
                : ph === "evening"
                  ? "Evening: the crew winds down in the lounge and games room between runs"
                  : dusk
                    ? "Dark outside, lamps on inside while the crew works on between runs"
                    : "Crew busy with off-shift life between runs";
        col = UI_COL.resting;
        if (late) {
            head = "Running late";
            sub = `${late}, not started yet: has the runner nodded off?`;
        }
    }
    if (late && head !== "Running late") sub += ` · ${late}`;
    const st = document.getElementById("hud-status");
    st.textContent = head;
    st.style.color = col;
    const subEl = document.getElementById("hud-sub");
    subEl.textContent = sub;
    subEl.title = sub;
}
const rosterEls = new Map();
function updateRoster() {
    const box = document.getElementById("roster");
    const order = { locked: 0, hurt: 1, working: 2, queued: 3, resting: 4 };
    const sorted = [...tasks].sort(
        (a, b) =>
            order[behaviour(a)] - order[behaviour(b)] ||
            (b.status === "auth-failed") - (a.status === "auth-failed") ||
            (b.run_count || 0) - (a.run_count || 0),
    );
    for (const t of sorted) {
        let el = rosterEls.get(t.id);
        const st = behaviour(t),
            look = lookOf(t),
            lk = lookKey(look);
        if (!el) {
            el = document.createElement("button");
            el.className = "crew";
            el.type = "button";
            el.addEventListener("click", () => select(t.id, true));
            el.addEventListener("mouseenter", () => {
                hovered = t.id;
            });
            el.addEventListener("mouseleave", () => {
                if (hovered === t.id) hovered = null;
            });
            rosterEls.set(t.id, el);
        }
        if (el.dataset.look !== lk) {
            el.innerHTML = "";
            el.appendChild(portrait(look, 32));
            el.insertAdjacentHTML(
                "beforeend",
                '<span class="lv"></span><span class="nm"></span><span class="dot"></span>',
            );
            el.dataset.look = lk;
        }
        el.querySelector(".lv").textContent = "LV" + levelOf(t.run_count);
        el.querySelector(".nm").textContent = nickOf(t);
        el.className = "crew " + st + (selected === t.id ? " sel" : "");
        el.style.setProperty("--sc", UI_COL[st]);
        el.title = `${nickOf(t)} · ${ROLES[roleOf(t)].name} · ${STATE_LABEL[st]} · last run ${fmtAgo(t.last_run)}`;
        box.appendChild(el);
    }
    for (const [id, el] of rosterEls)
        if (!tasks.some((t) => t.id === id)) {
            el.remove();
            rosterEls.delete(id);
        }
    balanceRoster();
}
// Fewest rows that fit, spread evenly, so one tile never sits alone on the last row.
function balancedCols(n, fit) {
    fit = Math.max(1, fit);
    return Math.ceil(n / Math.ceil(Math.max(1, n) / fit));
}
function balanceRoster() {
    const box = document.getElementById("roster"),
        n = box.children.length;
    const gap = parseFloat(getComputedStyle(box).columnGap) || 0,
        tile = 52,
        w =
            box.parentElement.clientWidth -
            parseFloat(getComputedStyle(box.parentElement).paddingLeft) -
            parseFloat(getComputedStyle(box.parentElement).paddingRight);
    const cols = balancedCols(n, Math.floor((w + gap) / (tile + gap)));
    box.style.maxWidth = n ? cols * tile + (cols - 1) * gap + "px" : "";
}
function updateTicker() {
    const done = tasks
        .filter((t) => t.last_run && (t.status === "success" || t.status === "error"))
        .sort((a, b) => new Date(b.last_run) - new Date(a.last_run))
        .slice(0, 8);
    const bits = done.map((t) => {
        const r = ROLES[roleOf(t)];
        const bad = t.status === "error";
        return `<span class="${bad ? "bad" : ""}">${r.icon} ${esc(nickOf(t))} ${bad ? "hit a snag" : "finished"} ${fmtAgo(t.last_run)}</span>`;
    });
    const html = (bits.join('<span class="sep">·</span>') || "No completed runs yet") + '<span class="sep">·</span>';
    const el = document.getElementById("ticker");
    if (el.dataset.html !== html) {
        el.dataset.html = html;
        el.innerHTML = html + html;
        el.style.setProperty("--dur", Math.max(30, bits.length * 7) + "s");
    }
}
const WHERE = {
    fire: "at the fireplace",
    chat: "chatting",
    sofa: "on the sofa",
    tv: "watching TV",
    window: "at the window",
    books: "browsing the shelves",
    coffee: "at the coffee machine",
    cooler: "at the water cooler",
    vending: "at the vending machine",
    fridge: "raiding the fridge",
    plant: "tending a plant",
    door: "guarding the door",
    art: "admiring the art",
    meeting: "in a meeting",
    post: "at the pigeonholes",
    board: "at the whiteboard",
    copier: "loitering by the copier",
    roam: "wandering",
    read: "reading in the lounge",
    peek: "looking over a shoulder",
    bedside: "visiting the sick bay",
    pong: "at the table tennis table",
    arcade: "on the arcade machine",
    console: "on the games console",
    foos: "at the foosball table",
    darts: "at the dartboard",
    frame: "at the employee-of-the-week frame",
    visit: "in " + officeName().replace(/^Your/, "your"),
    sink: "at the kitchen sink",
    table: "in the kitchen",
    phone: "on their phone",
};
const ITEM_NAME = { mug: "a coffee", water: "some water", snack: "a snack", sandwich: "a sandwich", book: "a book" };
const ACT_LABEL = {
    warm: () => "warming up by the fire",
    tv: () => "watching TV",
    read: () => "reading",
    eat: (w) => (w.poi.tag === "table" && phaseNow() === "lunch" ? "having lunch" : "having a snack"),
    sip: (w) => "having " + (ITEM_NAME[w.carry] || "a cuppa"),
    fetch: (w) => "grabbing " + (ITEM_NAME[KITCHEN[w.poi.tag]] || "something"),
    browse: () => "picking a book",
    phone: () => "scrolling their phone",
    gaze: () => "taking in the view",
    water: () => "watering the plants",
    write: () => "sketching on the whiteboard",
    meet: () => "in a meeting",
    papers: () => "sorting papers by the copier",
    post: (w) => (w.item ? "reading the post" : "checking the pigeonholes"),
    talk: () => "chatting",
    guard: () => "guarding the door",
    nap: () => "napping",
    peek: (w) => {
        const o = w.poi && w.poi.desk && workers.get(w.poi.desk.owner);
        return o ? "looking over " + whoOf(o) + "'s shoulder" : "looking over a shoulder";
    },
    bedside: (w) => {
        const so = w && w.sendOffFor && w.sendOffUntil > tnow() && workers.get(w.sendOffFor);
        if (so) return "wishing " + whoOf(so) + " luck from the sick bay";
        const o = [...workers.values()].find((p) => p.state === "hurt" && !p.path.length);
        return o ? "visiting " + whoOf(o) + " in the sick bay" : "visiting the sick bay";
    },
    pong: () => "playing table tennis",
    arcade: () => "on the arcade machine",
    foos: () => "playing foosball",
    darts: () => "throwing darts",
    wash: () => "washing up",
    pose: () => "posing under their employee-of-the-week portrait",
    visit: () => "dropping in on " + officeName().replace(/^Your/, "your"),
};
const dossier = document.getElementById("dossier");
// real runner action the dossier offers for a worker's state (lifted into tests/test_office.py)
// A scheduled writer waiting on _writer_lock (waiting_behind set, queued false) cannot be cancelled via /cancel.
function actionFor(id, st, canCancel = true) {
    const base = "/api/tasks/" + encodeURIComponent(id);
    if (st === "working") return null;
    if (st === "queued")
        return canCancel
            ? { kind: "cancel", label: "Cancel queued run", url: base + "/cancel", ask: "Drop the queued run of" }
            : null;
    return { kind: "run", label: "Send to desk · run now", url: base + "/run", ask: "Run now:" };
}
// When a writer task is waiting on the writer lock, resolve the lock holder's id and Office nickname.
function waitingForOf(t, list) {
    if (!t || !t.waiting_behind) return null;
    const h = (list || []).find((x) => x.id === t.waiting_behind);
    return { id: t.waiting_behind, nick: nickOf(h || { id: t.waiting_behind }) };
}
// Clicking a cancellable queued worker (or an auth-failed worker at the call screen) opens its card straight on the confirm step.
function shouldArmClick(st, status, demo, canCancel = true) {
    if (demo) return false;
    return (st === "queued" && canCancel) || (st === "locked" && status === "auth-failed");
}
// Clicking the call screen inspects/arms the front locked-out worker while a sign-in is down, or plays a world-only check when clear.
function fixtureAction(kind, list, demo) {
    if (kind === "call") {
        const l = lockOrder((list || []).filter((t) => behaviour(t) === "locked"))[0];
        return l ? { mode: "locked", id: l.id, arm: !demo } : { mode: "clear", id: null, arm: false };
    }
    return null;
}
// a standing 1:1 thread on the Assistant board; the opening question is prefilled, never sent
function oneToOneHref(id) {
    return `/assistant?item=${encodeURIComponent("worker:" + id)}&ask=${encodeURIComponent("How are you finding your role?")}`;
}
let armed = null;
const actMsg = new Map(); // armed = task id whose confirm step is showing
function actionHtml(t, st) {
    if (DEMO) return `<div class="d-act"><div class="d-msg">Runner actions are off in demo mode.</div></div>`;
    const a = actionFor(t.id, st, !!t.queued),
        m = actMsg.get(t.id),
        msg = m ? `<div class="d-msg${m.bad ? " bad" : ""}">${esc(m.text)}</div>` : "";
    const wf = waitingForOf(t, tasks);
    const holderBtn = wf
        ? `<button class="btn btn-sm btn-outline-secondary" type="button" data-act="holder">⏳ Waiting for ${esc(wf.nick)} · view desk</button>`
        : "";
    if (!a) {
        if (armed === t.id) armed = null;
        return holderBtn || msg ? `<div class="d-act">${holderBtn}${msg}</div>` : "";
    }
    if (armed !== t.id)
        return `<div class="d-act"><button class="btn btn-sm btn-outline-secondary" type="button" data-act="arm">${a.label}</button>${holderBtn}${msg}</div>`;
    const note = a.kind === "run" ? " Counts as your approval: a writer task may commit or push." : "";
    return `<div class="d-act"><p class="d-ask">${a.ask} <b>${esc(nickOf(t))}</b>${nickOf(t) !== t.id ? ` (${esc(t.id)})` : ""}?${note}</p><div class="d-act-row">
        <button class="btn btn-sm btn-primary" type="button" data-act="go">Confirm</button><button class="btn btn-sm btn-ghost-secondary" type="button" data-act="back">Not now</button></div></div>`;
}
async function runAction(t, st) {
    const a = actionFor(t.id, st, !!t.queued),
        w = workers.get(t.id);
    armed = null;
    if (!a || DEMO) return renderDossier();
    actMsg.set(t.id, { text: "Asking the runner…" });
    renderDossier();
    let res = null,
        body = {};
    try {
        res = await fetch(a.url, { method: "POST" });
        body = await res.json().catch(() => ({}));
    } catch (e) {
        res = null;
    }
    const now = last || tnow();
    if (res && res.ok) {
        actMsg.set(t.id, {
            text: a.kind === "run" ? "Runner accepted. The scene follows its next poll." : "Queued run dropped.",
        });
        if (w) {
            say(
                w,
                a.kind === "run" ? pick(["on it!", "heading in", "right away"], Math.random()) : "never mind, then",
                now,
            );
        }
    } else {
        const why = res ? `${res.status} ${body.error || res.statusText || "failed"}` : "runner unreachable";
        actMsg.set(t.id, { text: "Runner said no: " + why, bad: true });
        if (w) floatText(w.x, w.y - 52, "✕ " + (body.error || "no"), "#ff6b6b");
    }
    await poll();
}
dossier.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]"),
        t = b && tasks.find((x) => x.id === selected);
    if (!t) return;
    const act = b.dataset.act;
    if (act === "arm") {
        armed = t.id;
        actMsg.delete(t.id);
        renderDossier();
    } else if (act === "back") {
        armed = null;
        renderDossier();
    } else if (act === "holder") {
        const wf = waitingForOf(t, tasks);
        if (wf && workers.has(wf.id)) select(wf.id, true, false);
    } else if (act === "go" && armed === t.id) {
        b.disabled = true;
        runAction(t, behaviour(t));
    }
});
function renderDossier() {
    const t = tasks.find((x) => x.id === selected),
        w = workers.get(selected);
    if (!t || !w) {
        dossier.hidden = true;
        return;
    }
    const st = behaviour(t),
        r = ROLES[roleOf(t)],
        lv = levelOf(t.run_count),
        xp = ((t.run_count || 0) - lv * lv) / ((lv + 1) ** 2 - lv * lv);
    const ew = w.errand && workers.get(w.errand),
        rw =
            (w.reliefWith && w.reliefUntil > tnow() && workers.get(w.reliefWith)) ||
            (w.greetPeer && w.greetUntil > tnow() && workers.get(w.greetPeer)),
        rk = w.reliefKind || w.greetKind,
        rd = w.reliefDesk || w.greetDesk,
        wf = waitingForOf(t, tasks);
    const mentee = st === "resting" ? menteeOf(w) : null,
        mentorOf = st === "working" ? [...workers.values()].find((o) => menteeOf(o) === w) : null;
    const where =
        {
            working: w.desk
                ? `desk ${DESKS.indexOf(w.desk) + 1}${cat.onDesk === w.id ? " · cat on the keyboard" : ""}${mentorOf ? ` · learning the ropes from ${whoOf(mentorOf)}` : ""}`
                : "hot-desking",
            queued:
                (w.desk ? `gaming at desk ${DESKS.indexOf(w.desk) + 1}` : "staring out the window") +
                (wf ? ` · waiting for ${wf.nick}` : " · waiting for the writer lock"),
            locked:
                t.status === "auth-failed"
                    ? "meeting room · redialling the call"
                    : "meeting room · waiting on a sign-in",
            hurt:
                "sick bay" +
                (w.streak >= 2 ? ` · ${w.streak} failed runs in a row` : "") +
                (cat.onBed === w.id ? " · cat on the bed" : "") +
                (w.hasTea ? " · nursing a cuppa" : ""),
            resting: rw
                ? `celebrating ${rk === "welcome" ? "probation " : rk === "comeback" ? "recovery " : ""}with ${whoOf(rw)}${rd ? ` at desk ${rd}` : ""}${rk === "welcome" && (w.proudUntil > tnow() || rw.proudUntil > tnow()) ? (w.proudUntil > tnow() ? " · proud mentor" : " · their mentor") : ""}`
                : ew
                  ? w.errandKind === "welcome"
                      ? `walking over to congratulate ${whoOf(ew)}${w.proudUntil > tnow() ? " · proud mentor" : ""}`
                      : w.errandKind === "comeback"
                        ? `walking over to welcome ${whoOf(ew)} back`
                        : w.errandKind === "peek"
                          ? `checking on ${whoOf(ew)}`
                          : w.errandKind === "mentor"
                            ? `going to show ${whoOf(ew)} the ropes`
                            : w.errandKind === "tea"
                              ? `bringing a cuppa to ${whoOf(ew)} in the sick bay`
                              : `fetching a coffee for ${whoOf(ew)}`
                  : mentee
                    ? `showing ${whoOf(mentee)} the ropes at desk ${DESKS.indexOf(mentee.desk) + 1}`
                    : w.poi
                      ? w.act && ACT_LABEL[w.act] && !w.path.length
                          ? ACT_LABEL[w.act](w)
                          : w.path.length
                            ? "on the way to " + (WHERE[w.poi.tag] || "roaming").replace(/^(at|on|in) /, "")
                            : WHERE[w.poi.tag] || "roaming"
                      : "roaming",
        }[st] +
        (st === "resting" && !rw && !ew
            ? shiftNote((dueAt(t, Date.now()) ?? Infinity) - Date.now(), w.path.length > 0)
            : "") +
        (w.late && st !== "working" ? ` · ${fmtDur(w.late / 1000)} overdue, not started yet` : "");
    let prog = "";
    if (st === "working") {
        const p = progressOf(t),
            s = runStart.get(t.id);
        const txt =
            p == null
                ? t.last_duration
                    ? "running…"
                    : "first run"
                : p < 1
                  ? `${Math.round(p * 100)}% · ~${fmtDur(t.last_duration * (1 - p))} left`
                  : `overtime +${fmtDur((Date.now() - s) / 1000 - t.last_duration)}`;
        prog = `<div class="d-prog"><div class="progress progress-sm"><div class="progress-bar${p == null ? " progress-bar-indeterminate" : ""}" style="width:${p == null ? 100 : Math.round(Math.min(1, p) * 100)}%;background:${p != null && p >= 1 ? "var(--signal-coral)" : "var(--st-working)"}"></div></div><div class="d-prog-txt">${esc(txt)}</div></div>`;
    }
    const errTxt = cleanError(t.last_error);
    dossier.innerHTML = `<div class="card-body"><button class="btn-close" type="button" aria-label="Close"></button>
        <div class="d-head"><canvas width="32" height="32"></canvas><div>
            <div class="d-role">${r.icon} ${r.name}</div><div class="d-id">${esc(nickOf(t))}${nickOf(t) !== t.id ? ` <span class="d-task">${esc(t.id)}</span>` : ""}</div>
            <div class="d-lv">Lv ${lv} · ${(t.run_count || 0).toLocaleString()} runs${starter(null, t.run_count).isNew ? ` · <span style="color:#7ee0b5">new starter</span>` : ""}<div class="progress progress-sm"><div class="progress-bar" style="width:${Math.round(xp * 100)}%;background:var(--st-resting)"></div></div></div></div></div>
        <div class="mb-2"><span class="badge state-badge" style="--c:${UI_COL[st]}"><i class="dot"></i>${STATE_LABEL[st]}</span><span class="d-where">${esc(where)}</span></div>
        ${eotwView && eotwView.id === t.id ? `<p class="d-ask">🏆 ${eotwView.kind === "holder" ? `Employee of the week (w/c ${dayMonth(eotwView.week)})` : "Leading the employee-of-the-week race"} · ${eotwView.ok}/${eotwView.n} clean runs</p>` : ""}
        ${prog}
        ${t.description ? `<p class="d-desc">${esc(t.description.slice(0, 90))}${t.description.length > 90 ? "…" : ""}</p>` : ""}
        <dl><dt>Last run</dt><dd>${fmtAgo(t.last_run)}${t.last_duration ? " · " + fmtDur(t.last_duration) : ""}</dd>
        <dt>Next</dt><dd>${st === "working" ? "now" : nextDue(t)} · ${t.run_at ? "daily" : t.interval ? "every " + fmtDur(t.interval) : "—"}</dd></dl>
        ${errTxt && st !== "resting" && st !== "working" ? `<div class="d-err">${esc(errTxt.slice(0, 120))}</div>` : ""}
        ${actionHtml(t, st)}
        ${DEMO ? "" : `<div class="d-act"><a class="btn btn-sm btn-outline-secondary" href="${oneToOneHref(t.id)}" title="Talk through the role with this worker and refine its skill">💬 1:1 chat</a></div>`}
        <a class="d-link" href="/runner?task=${encodeURIComponent(t.id)}">Open in Workers →</a></div>`;
    const pc = dossier.querySelector("canvas");
    pc.getContext("2d").drawImage(portrait(w.look, 32), 0, 0);
    dossier.querySelector(".btn-close").onclick = () => select(null);
    dossier.hidden = false;
    placeDossier();
}
function placeDossier() {
    const w = workers.get(selected);
    if (!w || dossier.hidden) return;
    // viewport coords (position:fixed) so the card is always fully on screen, whatever the scroll
    const r = stage.getBoundingClientRect(),
        k = r.width / W,
        cw = dossier.offsetWidth,
        ch = dossier.offsetHeight,
        vw = innerWidth,
        vh = innerHeight;
    const wx = r.left + w.x * k,
        wy = r.top + (w.y - 25) * k;
    let x = wx + 24;
    if (x + cw > vw - 8) x = wx - cw - 24;
    dossier.style.left = Math.max(8, Math.min(vw - cw - 8, x)) + "px";
    dossier.style.top = Math.max(8, Math.min(vh - ch - 8, wy - ch / 2)) + "px";
}
function select(id, keepOpen, armNow) {
    const wantArm = !!(armNow && id && !DEMO);
    if (id && selected === id && !keepOpen && armed === (wantArm ? id : null)) selected = null;
    else selected = id || null;
    armed = wantArm && selected ? selected : null;
    if (armed) actMsg.delete(selected);
    for (const [k, el] of rosterEls) el.classList.toggle("sel", k === selected);
    renderDossier();
}

// ================================================================ input
function worldPoint(e) {
    const r = view.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
}
function hit(p) {
    let best = null;
    for (const w of workers.values())
        if (p.x > w.x - 10 && p.x < w.x + 10 && p.y > w.y - 50 && p.y < w.y + 3 && (!best || w.y > best.y)) best = w;
    return best;
}
const hitCat = (p) => p.x > cat.x - 9 && p.x < cat.x + 9 && p.y > cat.y - 14 - (cat.ride ? 5 : 0) && p.y < cat.y + 3;
const hitCopier = (p) => p.x >= COPIER.x && p.x <= COPIER.x + 53 && p.y >= COPIER.y && p.y <= COPIER.y + 45;
const hitDoor = (p) => p.x >= DOOR.x - 4 && p.x <= DOOR.x + 45 && p.y >= DOOR.y - 4 && p.y <= WALL + 10;
const hitCall = (p) => p.x >= CALL.x - 2 && p.x <= CALL.x + 32 && p.y >= CALL.y - 2 && p.y <= CALL.y + 50;
const hitUserDesk = (p) =>
    p.x >= USER_DESK.x && p.x <= USER_DESK.x + 58 && p.y >= USER_DESK.y - 20 && p.y <= USER_DESK.y + 35;
const hitPost = (p) =>
    p.x >= PIGEON.x - 1 && p.x <= PIGEON.x + PIGEON.w + 1 && p.y >= PIGEON.y - 1 && p.y <= PIGEON.y + PIGEON.h + 1;
const hitFrame = (p) =>
    p.x >= FRAME.x - 1 && p.x <= FRAME.x + FRAME.w + 1 && p.y >= FRAME.y - 3 && p.y <= FRAME.y + FRAME.h + 1;
const hitEgg = (p) =>
    eggs.find((e) => !e.found && p.x >= e.x - 7 && p.x <= e.x + 7 && p.y >= e.y - 14 && p.y <= e.y + 2) || null;
let hoverEgg = null;
function clickFrame(now) {
    const v = eotwView,
        w = v && workers.get(v.id);
    frameFlashUntil = now + 1500;
    if (!w) {
        floatText(FRAME.x + 14, FRAME.y + 52, "vacancy: crowned Fri 16:00", "#cfc8e8");
        return;
    }
    select(w.id, true);
    if (w.state === "resting" && !w.path.length && now >= w.quipUntil) {
        w.emote = "star";
        w.emoteUntil = now + 2000;
        say(w, pick(QUIPS.eotwMe, Math.random()), now);
    }
}
function clickEgg(e, now) {
    e.found = true;
    try {
        localStorage.setItem(EGG_KEY, JSON.stringify(eggs.filter((x) => x.found).map((x) => x.x + "," + x.y)));
    } catch (err) {
        /* ignore */
    }
    const n = eggs.filter((x) => x.found).length,
        all = n === eggs.length;
    starBurst(e.x, e.y - 6);
    if (all) confetti(e.x, e.y - 10);
    floatText(e.x, e.y - 16, all ? "EGG HUNT CHAMPION!" : `egg ${n} of ${eggs.length}`, "#ffd166");
    const o = cheerer({ x: e.x, y: e.y }, workers.values(), 220);
    if (o && now >= o.quipUntil) {
        o.lookDir = dirTo(o, e.x, e.y);
        o.lookUntil = now + 2200;
        o.emote = "heart";
        o.emoteUntil = now + 2000;
        say(o, pick(all ? QUIPS.eggAll : QUIPS.egg, Math.random()), now);
    }
}
let copierFlashUntil = 0,
    copierClicks = 0,
    doorFlashUntil = 0;
function clickCopier(now) {
    copierFlashUntil = now + 900;
    copierClicks++;
    const jam = copierClicks % 4 === 0;
    if (jam) {
        for (let i = 0; i < 6; i++)
            spawn({
                type: "spark",
                x: COPIER.x + 40,
                y: COPIER.y + 22,
                vx: rnd(-24, 24),
                vy: rnd(-24, 8),
                life: 0.5,
                max: 0.5,
                c: i % 2 ? "#ffd166" : "#ff6b6b",
            });
        floatText(COPIER.x + 26, COPIER.y - 6, "PC LOAD LETTER", "#ffd166");
    } else {
        for (let i = 0; i < 3; i++)
            spawn({
                type: "paper",
                x: COPIER.x + 44,
                y: COPIER.y + 24 + i * 2,
                vx: 16 + i * 5,
                vy: -3 + i * 2,
                life: 1.1,
                max: 1.1,
            });
        floatText(COPIER.x + 26, COPIER.y - 6, "test page", "#b79bff");
    }
    const near =
        [...workers.values()].find((w) => w.act === "papers" && !w.path.length) ||
        cheerer({ x: COPIER.x + 26, y: COPIER.y + 36 }, workers.values(), 180);
    if (near && now >= near.quipUntil) {
        near.lookDir = dirTo(near, COPIER.x + 26, COPIER.y + 24);
        near.lookUntil = now + 2200;
        near.emote = jam ? "bang" : "book";
        near.emoteUntil = now + 2000;
        say(
            near,
            pick(
                jam
                    ? ["PC LOAD LETTER?!", "what does that even mean?", "kick Tray 2!"]
                    : ["who's printing memes?", "warm off the rollers!", "is that my payslip?"],
                Math.random(),
            ),
            now,
        );
    }
}
function clickCall(now) {
    const act = fixtureAction("call", tasks, DEMO);
    callFlashUntil = now + 900;
    if (act.mode === "locked") {
        const w = workers.get(act.id);
        spawn({ type: "knock", x: CALL.x + 15, y: CALL.y + 11, vx: 0, vy: 0, life: 0.25, max: 0.25 });
        select(act.id, true, act.arm);
        if (w) {
            w.emote = "lock";
            w.emoteUntil = now + 2200;
            say(w, pick(DEMO ? QUIPS.locked : QUIPS.callCheck, Math.random()), now);
        }
        return;
    }
    for (let i = 0; i < 6; i++)
        spawn({
            type: "spark",
            x: CALL.x + 15,
            y: CALL.y + 11,
            vx: rnd(-18, 18),
            vy: rnd(-18, 12),
            life: 0.5,
            max: 0.5,
            c: i % 2 ? "#7ee0b5" : "#b79bff",
        });
    floatText(CALL.x + 15, CALL.y - 6, "call: connected", "#7ee0b5");
}
function clickDoor(now) {
    doorFlashUntil = now + 900;
    for (let i = 0; i < 6; i++)
        spawn({
            type: "spark",
            x: DOOR.x + 41,
            y: DOOR.y + 26,
            vx: rnd(-18, 18),
            vy: rnd(-18, 12),
            life: 0.5,
            max: 0.5,
            c: i % 2 ? "#7ee0b5" : "#fffaf0",
        });
    floatText(DOOR.x + 20, DOOR.y - 4, "badge reader: all green", "#7ee0b5");
    const guard =
        [...workers.values()].find((w) => w.act === "guard" && !w.path.length) ||
        [...workers.values()].find((w) => w.act === "guard");
    if (
        guard &&
        guard.state === "resting" &&
        !guard.path.length &&
        Math.hypot(guard.x - DOOR.front.x, guard.y - DOOR.front.y) < 220 &&
        now >= guard.quipUntil
    ) {
        guard.lookDir = dirTo(guard, DOOR.x + 20, DOOR.y + 30);
        guard.lookUntil = now + 2200;
        guard.emote = "wave";
        guard.emoteUntil = now + 2000;
        say(guard, pick(["all clear, boss!", "sign-in is green!", "gate's holding steady!"], Math.random()), now);
    }
}
// what a click on the hovered thing does, for first-time viewers (lifted into tests/test_office.py)
function hintFor(kind, st, demo, canCancel = true) {
    if (kind === "worker") {
        const a = demo ? null : actionFor("", st, canCancel);
        if (!a) return "click: dossier";
        return a.kind === "cancel"
            ? "click: cancel queued run · or drag off the floor"
            : "click: dossier · drag to a desk to run";
    }
    if (kind === "call")
        return st === "locked"
            ? demo
                ? "click: inspect the frozen call"
                : "click: re-check sign-in"
            : "click: test the video call";
    if (kind === "copier") return "click: print a test page";
    if (kind === "door") return "click: check badge reader";
    return (
        {
            cat: "click: pet the cat",
            darts: "click: throw a dart",
            console: "click: swap game and call players",
            arcade: "click: insert a coin",
            pong: "click: call the rally",
            foos: "click: call a game or spin the rods",
            coffee: "click: brew a fresh pot",
            fridge: "click: open the fridge",
            fire: "click: poke the fire",
            clock: "click: strike the hour",
            tv: "click: Ceefax",
            board: "click: open the Assistant board",
            frame: "click: employee of the week",
            post: "click: check your pigeonhole",
            egg: "click: pick up the egg",
        }[kind] || null
    );
}
// drag a worker onto the ops floor to arm its Run now confirm, or a queued worker off it to arm Cancel; never fires itself (lifted into tests/test_office.py)
function dropAction(st, room, demo, canCancel = true) {
    if (demo) return { ok: false, kind: null, text: "demo: runner actions are off" };
    if (st === "working") return { ok: false, kind: null, text: "already at a desk" };
    if (st === "queued") {
        if (!canCancel)
            return { ok: false, kind: null, text: "waiting for the writer lock · scheduled runs can't be cancelled" };
        return room !== "office"
            ? { ok: true, kind: "cancel", text: "let go: cancel queued run? (you confirm next)" }
            : { ok: false, kind: "cancel", text: "drag off the ops floor to leave the queue" };
    }
    if (room !== "office") return { ok: false, kind: "run", text: "drop on the ops floor to run" };
    return { ok: true, kind: "run", text: "let go: run now? (you confirm next)" };
}
const drag = { id: null, sx: 0, sy: 0, x: 0, y: 0, moved: false, face: null };
let dragClick = false;
const hint = { kind: null, id: null, x: 0, y: 0, since: 0 },
    HINT_DWELL = 350,
    HINT_LEARNT = 3;
const hintCount = {}; // cached so the render loop never touches localStorage
const hintUses = (kind) => {
    if (!(kind in hintCount)) {
        try {
            hintCount[kind] = Number(localStorage.getItem("office-hint-" + kind)) || 0;
        } catch (e) {
            hintCount[kind] = HINT_LEARNT;
        }
    }
    return hintCount[kind];
};
function hintUsed(kind) {
    if (kind) {
        hintCount[kind] = hintUses(kind) + 1;
        try {
            localStorage.setItem("office-hint-" + kind, hintCount[kind]);
        } catch (e) {
            /* ignore */
        }
    }
    hint.since = Infinity;
}
function hintKind(p, w, c) {
    return c
        ? "cat"
        : w
          ? "worker"
          : hitEgg(p)
            ? "egg"
            : hitFrame(p)
              ? "frame"
              : hitPost(p)
                ? "post"
                : hitCall(p)
                  ? "call"
                  : hitCopier(p)
                    ? "copier"
                    : hitDoor(p)
                      ? "door"
                      : hitDartboard(p)
                        ? "darts"
                        : hitConsole(p)
                          ? "console"
                          : hitArcade(p)
                            ? "arcade"
                            : hitPong(p)
                              ? "pong"
                              : hitFoos(p)
                                ? "foos"
                                : hitCoffee(p)
                                  ? "coffee"
                                  : hitFridge(p)
                                    ? "fridge"
                                    : hitFire(p)
                                      ? "fire"
                                      : hitClock(p)
                                        ? "clock"
                                        : hitTV(p)
                                          ? "tv"
                                          : hitBoard(p)
                                            ? "board"
                                            : null;
}
view.addEventListener("mousemove", (e) => {
    const p = worldPoint(e),
        c = hitCat(p),
        w = c ? null : hit(p),
        cl = !c && !w && hitCall(p),
        cp = !c && !w && !cl && hitCopier(p),
        dr = !c && !w && !cl && !cp && hitDoor(p),
        cn = !c && !w && !cl && !cp && !dr && hitConsole(p);
    hoverEgg = !c && !w ? hitEgg(p) : null;
    const fr = !c && !w && !hoverEgg && hitFrame(p),
        rd = !c && !w && !hoverEgg && !fr && hitUserDesk(p);
    hovered = c
        ? "cat"
        : w
          ? w.id
          : hoverEgg
            ? "egg"
            : fr
              ? "frame"
              : rd
                ? "userDesk"
                : !c && !w && hitPost(p)
                  ? "post"
                  : cl
                    ? "call"
                    : cp
                      ? "copier"
                      : dr
                        ? "door"
                        : cn
                          ? "console"
                          : null;
    const bn = w || c ? null : hitBoardNote(p);
    boardHover = bn ? bn.title : null;
    const kind = hintKind(p, w, c),
        id = w ? w.id : null;
    if (kind !== hint.kind || id !== hint.id) {
        hint.kind = kind;
        hint.id = id;
        hint.since = performance.now();
    }
    hint.x = p.x;
    hint.y = p.y;
    view.classList.toggle("hovering", !!kind);
});
view.addEventListener("mouseleave", () => {
    hovered = null;
    hint.kind = null;
});
function startDrag(p) {
    const w = hitCat(p) ? null : hit(p);
    if (!w) return;
    Object.assign(drag, { id: w.id, sx: p.x, sy: p.y, x: p.x, y: p.y, moved: false, face: portrait(w.look, 32) });
}
function moveDrag(p) {
    if (!drag.id) return;
    drag.x = clamp(p.x, 8, W - 8);
    drag.y = clamp(p.y, 8, H - 8);
    if (!drag.moved && Math.hypot(p.x - drag.sx, p.y - drag.sy) > 8) {
        drag.moved = true;
        hint.kind = null;
        view.classList.add("dragging");
    }
}
function endDrag() {
    if (!drag.id) return;
    const id = drag.id,
        moved = drag.moved,
        t = tasks.find((x) => x.id === id),
        w = workers.get(id);
    drag.id = null;
    drag.face = null;
    view.classList.remove("dragging");
    if (!moved || !t || !w) return;
    dragClick = true; // swallow the click that follows this mouseup
    const d = dropAction(behaviour(t), roomAt(drag.x, drag.y), DEMO, !!t.queued);
    if (!d.ok) {
        floatText(drag.x, drag.y - 8, d.text, "#cfc8e8");
        return;
    }
    select(id, true, true); // the confirm step names the task; nothing is sent yet
    say(
        w,
        pick(
            d.kind === "cancel" ? QUIPS.queueCancel : ["you want me in?", "desk time?", "say the word"],
            Math.random(),
        ),
        last || tnow(),
    );
}
view.addEventListener("mousedown", (e) => {
    if (e.button === 0) startDrag(worldPoint(e));
});
addEventListener("mousemove", (e) => moveDrag(worldPoint(e)));
addEventListener("mouseup", endDrag);
view.addEventListener(
    "touchstart",
    (e) => {
        if (e.touches.length === 1) startDrag(worldPoint(e.touches[0]));
    },
    { passive: true },
);
addEventListener(
    "touchmove",
    (e) => {
        if (!drag.id || !e.touches.length) return;
        moveDrag(worldPoint(e.touches[0]));
        if (drag.moved) e.preventDefault();
    },
    { passive: false },
);
addEventListener("touchend", endDrag);
addEventListener("touchcancel", () => {
    drag.id = null;
    drag.face = null;
    view.classList.remove("dragging");
});
view.addEventListener("click", (e) => {
    if (dragClick) {
        dragClick = false;
        return;
    }
    const p = worldPoint(e),
        now = last || tnow();
    {
        const c = hitCat(p);
        hintUsed(hintKind(p, c ? null : hit(p), c));
    }
    if (hitCat(p)) {
        catHearts();
        catSay(pick(["mrrp?", "meow", "prrrr", "mew!", "…"], Math.random()), now);
        if (cat.mode === "sleep") {
            cat.mode = "sit";
            cat.until = now + 4000;
        }
        return;
    }
    const w = hit(p);
    if (w) {
        const arm = shouldArmClick(w.state, w.task && w.task.status, DEMO, !!(w.task && w.task.queued));
        select(w.id, false, arm);
        const wf = w.state === "queued" && waitingForOf(w.task, tasks);
        if (arm && selected === w.id && armed === w.id)
            say(w, pick(w.state === "queued" ? QUIPS.queueCancel : QUIPS.callCheck, Math.random()), now);
        else if (wf && selected === w.id)
            say(
                w,
                pick([`waiting on ${wf.nick}`, `after you, ${wf.nick}`, `${wf.nick}'s got the lock`], Math.random()),
                now,
            );
        return;
    }
    {
        const e = hitEgg(p);
        if (e) {
            clickEgg(e, now);
            return;
        }
    }
    if (hitFrame(p)) {
        clickFrame(now);
        return;
    }
    if (hitPost(p)) {
        checkPost(now);
        return;
    }
    if (hitCall(p)) {
        clickCall(now);
        return;
    }
    if (hitCopier(p)) {
        clickCopier(now);
        return;
    }
    if (hitDoor(p)) {
        clickDoor(now);
        return;
    }
    if (hitDartboard(p)) {
        throwDart(now);
        return;
    }
    if (hitConsole(p)) {
        swapConsole(now);
        return;
    }
    {
        const a = hitArcade(p);
        if (a) {
            insertCoin(a, now);
            return;
        }
    }
    if (hitPong(p)) {
        clickPong(now);
        return;
    }
    if (hitFoos(p)) {
        clickFoos(now);
        return;
    }
    if (hitCoffee(p)) {
        brewCoffee(now);
        return;
    }
    if (hitFridge(p)) {
        openFridge(now);
        return;
    }
    if (hitFire(p)) {
        pokeFire(now);
        return;
    }
    if (hitClock(p)) {
        strikeClock();
        return;
    }
    if (hitTV(p)) {
        openCeefax(!ceefax.open);
        return;
    }
    if (hitBoard(p)) {
        location.href = "/assistant";
        return;
    }
    select(null);
});
const namesBtn = document.getElementById("names-btn");
const toggleNames = () => {
    showNames = !showNames;
    namesBtn.setAttribute("aria-pressed", showNames);
};
namesBtn.addEventListener("click", toggleNames);
document.addEventListener("keydown", (e) => {
    if (e.target.closest("input,textarea") || e.metaKey || e.ctrlKey) return;
    if (onQuizPage() && /^[1-4]$/.test(e.key)) {
        bamboozleAct("pick", Number(e.key) - 1);
        return;
    }
    if (onQuizPage() && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        bamboozleAct("go");
        return;
    }
    if (e.key === "n" || e.key === "N") toggleNames();
    else if (e.key === "Escape") {
        if (ceefax.open) openCeefax(false);
        else select(null);
    }
});
