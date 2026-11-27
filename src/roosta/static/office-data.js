// Office page. Reading the runner (tasks, activity) and saving the scene between visits.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// ================================================================ data
const prevRuns = new Map(),
    prevState = new Map();
let tvFlashUntil = 0;
const startKey = (id) => "office-start-" + id;
function trackRunStart(t, st) {
    if (st !== "working") {
        if (runStart.has(t.id)) {
            runStart.delete(t.id);
            try {
                localStorage.removeItem(startKey(t.id));
            } catch (e) {
                /* ignore */
            }
        }
        return;
    }
    if (runStart.has(t.id) && runStart.get(t.id)) return;
    let saved = null;
    try {
        saved = JSON.parse(localStorage.getItem(startKey(t.id)) || "null");
    } catch (e) {
        saved = null;
    }
    if (saved && saved.rc === (t.run_count || 0)) {
        runStart.set(t.id, saved.t);
        return;
    }
    const seenStart = prevState.has(t.id) && prevState.get(t.id) !== "working";
    const s = t._demoStart || (seenStart ? Date.now() : null);
    runStart.set(t.id, s);
    if (s && !t._demoStart)
        try {
            localStorage.setItem(startKey(t.id), JSON.stringify({ rc: t.run_count || 0, t: s }));
        } catch (e) {
            /* ignore */
        }
}
// When a well-over (tier 2, >=150%) or way-over (tier 3, >=250%) run finally succeeds,
// the worker gets a relief moment and any colleague rubber-ducking at their desk celebrates with them (lifted into tests/test_office.py).
function overrunRelief(tier, ws, workerId, desk) {
    if (!tier || tier < 2 || !desk) return null;
    let peer = null,
        atDesk = false;
    for (const o of ws || []) {
        if (!o || o.id === workerId || o.state !== "resting") continue;
        if (o.poi && o.poi.tag === "peek" && o.poi.desk === desk && (!o.path || !o.path.length)) {
            peer = o;
            atDesk = true;
            break;
        }
        if (!peer && (o.errand === workerId || (o.poi && o.poi.tag === "peek" && o.poi.desk === desk))) peer = o;
    }
    return { tier, float: tier >= 3 ? "FINALLY! +1 run" : "PHEW! +1 run", peer: peer ? peer.id : null, atDesk };
}
// When a worker passes probation (10th run) or recovers from a failure streak (2+ errors in a row),
// a colleague at their desk celebrates immediately or the nearest free off-shift colleague walks over to high-five them.
// A probation pass goes to the new starter's mentor of record first, if they are free (`proud` marks it).
function milestoneGreet(passed, streak, ws, worker, desk, peekTaken, mentor) {
    const kind = passed ? "welcome" : (streak || 0) >= 2 ? "comeback" : null;
    if (!kind || !worker) return null;
    const list = [...(ws || [])];
    const badge = kind === "welcome" ? "PROBATION PASSED!" : "BACK ON MY FEET!";
    const line =
        kind === "welcome" ? "I'm staying!" : streak >= 5 ? `${streak} failures, then this. phew.` : "back on my feet!";
    const mine = kind === "welcome" && mentor && mentor.id !== worker.id ? mentor : null;
    const tag = (o) => (mine && o === mine ? { proud: true } : {});
    if (desk) {
        for (const o of list) {
            if (!o || o.id === worker.id || o.state !== "resting") continue;
            if (o.poi && o.poi.tag === "peek" && o.poi.desk === desk && (!o.path || !o.path.length))
                return { kind, badge, line, peer: o.id, mode: "atDesk", ...tag(o) };
        }
        if (!peekTaken) {
            const r = (mine && mentorFree(mine) && mine) || coffeeRunner(worker, list);
            if (r) return { kind, badge, line, peer: r.id, mode: "walk", ...tag(r) };
        }
    }
    return { kind, badge, line, peer: null, mode: "call" };
}
function events(list) {
    const now = tnow();
    for (const t of list) {
        const prev = prevRuns.get(t.id),
            w = workers.get(t.id),
            st = behaviour(t);
        trackRunStart(t, st);
        const sb = starter(prev, t.run_count);
        if (w) w.newStarter = sb.isNew;
        if (w && st === "hurt") w.streak = Math.max(1, streaks[t.id] || t._demoStreak || 0);
        else if (w && (st === "working" || st === "queued") && (streaks[t.id] || t._demoStreak))
            w.streak = Math.max(w.streak || 0, streaks[t.id] || t._demoStreak || 0);
        if (prev !== undefined && (t.run_count || 0) > prev && w) {
            if (st === "hurt") {
                w.lastDesk = null;
                w.lastTension = 0;
                floatText(w.x, w.y - 52, "✕ error", "#ff6b6b");
                say(w, pick(QUIPS.fail, Math.random()), now);
                react(w, "sympathy", 1600);
            } else {
                const desk = w.lastDesk,
                    deskNo = desk ? DESKS.indexOf(desk) + 1 : 0;
                const pk = desk && POIS.find((q) => q.tag === "peek" && q.desk === desk);
                const relief = overrunRelief(w.lastTension || 0, workers.values(), w.id, desk);
                const ms = milestoneGreet(
                    sb.passed,
                    w.streak || 0,
                    workers.values(),
                    w,
                    desk,
                    !!(pk && pk.taken),
                    sb.passed ? mentorOfRecord(mentorTally, t.id, workers.values()) : null,
                );
                const peer =
                    (ms && ms.peer && workers.get(ms.peer)) || (relief && relief.peer && workers.get(relief.peer));
                w.lastDesk = null;
                w.lastTension = 0;
                w.streak = 0;
                if (ms) {
                    floatText(w.x, w.y - 68, ms.badge, "#7ee0b5");
                    starBurst(w.x, w.y - 30);
                    if (ms.mode === "call" && !peer) react(w, ms.kind, 1200);
                } else if (!peer) react(w, "cheer", 1400);
                confetti(w.x, w.y - 40);
                if (relief) starBurst(w.x, w.y - 30);
                floatText(w.x, w.y - 52, relief ? relief.float : "+1 run", "#ffd166");
                say(w, ms ? ms.line : pick(relief ? QUIPS.relief : QUIPS.done, Math.random()), now);
                tvFlashUntil = now + 400;
                if (levelOf(t.run_count) > levelOf(prev)) {
                    setTimeout(() => {
                        floatText(w.x, w.y - 66, "LEVEL UP! LV" + levelOf(t.run_count), "#7ee0b5");
                        starBurst(w.x, w.y - 30);
                    }, 700);
                }
                if (w.state === "resting") {
                    // victory hop, then off for a reward
                    const atDesk = (ms && ms.mode === "atDesk") || (relief && relief.atDesk);
                    const walkGreet = ms && ms.mode === "walk" && peer && pk;
                    const hopMs = atDesk ? 2200 : walkGreet ? 1600 : 1300;
                    w.celebrateUntil = now + hopMs;
                    w.celebrateStart = now;
                    w.dir = atDesk || walkGreet ? "right" : "down";
                    if (relief || ms) {
                        w.emote = "star";
                        w.emoteUntil = now + hopMs;
                    }
                    if (walkGreet) {
                        w.greetPeer = peer.id;
                        w.greetKind = ms.kind;
                        w.greetDesk = deskNo;
                        w.greetUntil = now + 16000;
                        leaveSpot(peer);
                        peer.errand = w.id;
                        peer.errandKind = ms.kind;
                        peer.carry = null;
                        sendTo(peer, pk);
                        peer.emote = "star";
                        peer.emoteUntil = now + 2400;
                        peer.proudUntil = ms.proud ? now + 20000 : 0;
                        say(peer, pick(QUIPS[ms.proud ? "proudGo" : ms.kind], Math.random()), now);
                    } else if (peer && atDesk) {
                        const rKind = ms ? ms.kind : null;
                        w.reliefWith = peer.id;
                        w.reliefKind = rKind;
                        w.reliefDesk = deskNo;
                        w.reliefUntil = now + hopMs;
                        peer.celebrateUntil = now + hopMs;
                        peer.celebrateStart = now;
                        peer.dir = "left";
                        peer.reliefWith = w.id;
                        peer.reliefKind = rKind;
                        peer.reliefDesk = deskNo;
                        peer.reliefUntil = now + 3200;
                        peer.dwellUntil = Math.max(peer.dwellUntil || 0, now + 3200);
                        peer.emote = "star";
                        peer.emoteUntil = now + 3000;
                        peer.proudUntil = ms && ms.proud ? now + 3200 : 0;
                        peer.quip = pick(
                            QUIPS[
                                ms
                                    ? ms.proud
                                        ? "proudHi"
                                        : ms.kind === "welcome"
                                          ? "welcomeHi"
                                          : "comebackHi"
                                    : "reliefPeer"
                            ],
                            Math.random(),
                        );
                        peer.quipStart = now + 700;
                        peer.quipUntil = now + 3700;
                        if (ms && ms.proud) {
                            w.quip = pick(QUIPS.proudThanks, Math.random());
                            w.quipStart = now + 1600;
                            w.quipUntil = now + 4600;
                        }
                    } else if (peer) {
                        peer.errand = null;
                        peer.errandKind = null;
                        peer.path = [];
                        peer.lookDir = dirTo(peer, w.x, w.y);
                        peer.lookUntil = now + 2600;
                        peer.emote = "star";
                        peer.emoteUntil = now + 2400;
                        peer.quip = pick(QUIPS.reliefPeer, Math.random());
                        peer.quipStart = now + 700;
                        peer.quipUntil = now + 3500;
                    }
                    const reward = POIS.filter(
                        (p) => !p.taken && ["coffee", "vending", "cooler", "fridge"].includes(p.tag),
                    ).sort((a, b) => Math.hypot(a.x - w.x, a.y - w.y) - Math.hypot(b.x - w.x, b.y - w.y))[0];
                    if (reward) {
                        sendTo(w, reward);
                        w.rewardRun = true;
                    }
                }
            }
        }
        if (!sb.isNew && t.run_count != null && mentorTally[t.id]) {
            delete mentorTally[t.id];
            saveMentors();
        }
        prevRuns.set(t.id, t.run_count || 0);
        prevState.set(t.id, st);
    }
}
function demoize(list) {
    const out = list.map((t) => ({ ...t, status: "success", queued: false, waiting_behind: "", last_error: "" }));
    [0, 3, 6].forEach((i) => {
        if (out[i]) {
            out[i].status = "running";
            out[i].last_duration = out[i].last_duration || 300;
            out[i]._demoStart = Date.now() - out[i].last_duration * 1000 * [0.35, 1.6, 2.6][i / 3];
        }
    });
    if (out[8]) out[8].queued = true;
    if (out[9]) out[9].waiting_behind = out[0] ? out[0].id : "office-director";
    if (out[11]) {
        out[11].status = "error";
        out[11].last_error = "Task produced no output for 600s - presumed hung";
        out[11]._demoStreak = 4;
    }
    if (out[12]) {
        out[12].status = "blocked";
        out[12].last_error = "Waiting for sign-in: Teams (run `msteams login`)";
    }
    if (out[13]) {
        out[13].status = "auth-failed";
        out[13].last_error = "Claude Code CLI unavailable";
    }
    return out;
}
let demoCache = null;
async function poll() {
    try {
        const res = await fetch("/api/tasks", { cache: "no-store" });
        let list = await res.json();
        if (DEMO) {
            if (!demoCache) demoCache = demoize(list);
            list = demoCache;
        }
        tasks = list;
        assign(list);
        events(list);
        updateHud();
        updateRoster();
        updateTicker();
        pollActivity();
        pollKanban();
        if (selected) renderDossier();
    } catch (err) {
        document.getElementById("hud-sub").textContent = "lost contact with the runner — retrying";
    }
}

// ================================================================ persistence
// The office keeps going while the user is on another page: the scene is saved on leaving and, on return,
// restored and fast-forwarded by the time away. Simulation timestamps live on the tnow() clock, so
// restoring re-bases clockSkew to the saved instant rather than rewriting every timer.
const STATE_KEY = "office-state-v1",
    STATE_MAX_AGE = 24 * 3600e3,
    CATCHUP_MS = 300e3,
    STEP_MS = 50;
const PERSIST = !DEMO && !params.has("warp");
const NOT_SAVED = new Set(["task", "role", "look"]);
// Away longer than the cap: skip the excess (timers simply expire), then simulate the last `cap` ms.
function catchUpPlan(ms, cap, step = STEP_MS) {
    ms = Math.max(0, ms || 0);
    const run = Math.min(ms, cap);
    return { skip: ms - run, steps: Math.floor(run / step) };
}
function catchUp(ms, cap = CATCHUP_MS) {
    const { skip, steps } = catchUpPlan(ms, cap);
    clockSkew += skip;
    for (let i = 0; i < steps; i++) {
        clockSkew += STEP_MS;
        simulate(STEP_MS / 1000, tnow());
    }
    parts.length = 0; // particles from the gap would all land in the first visible frame
    last = tnow();
}
// shared furniture is stored by index so references survive the round trip
function packRef(k, v) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
        const p = POIS.indexOf(v);
        if (p >= 0) return { $poi: p };
        const d = DESKS.indexOf(v);
        if (d >= 0) return { $desk: d };
    }
    return v;
}
const unpackRef = (k, v) =>
    v && typeof v === "object" ? (v.$poi != null ? POIS[v.$poi] : v.$desk != null ? DESKS[v.$desk] : v) : v;
function saveState() {
    if (!PERSIST || firstPoll) return;
    const ws = [...workers.values()].map((w) =>
        Object.fromEntries(Object.entries(w).filter(([k]) => !NOT_SAVED.has(k))),
    );
    const doc = {
        at: Date.now(),
        t: tnow(),
        pois: POIS.length,
        desks: DESKS.length,
        workers: ws,
        cat,
        bot,
        pong,
        talks,
        convoPair,
        lastQuip,
        tvFlashUntil,
        consoleSwap,
        told: [...told],
        prevRuns: [...prevRuns],
        prevState: [...prevState],
        selected,
        showNames,
    };
    try {
        localStorage.setItem(STATE_KEY, JSON.stringify(doc, packRef));
    } catch (e) {
        /* storage full or private mode: start fresh next time */
    }
}
// Returns the milliseconds away, or null when there is nothing usable to restore.
function restoreState() {
    if (!PERSIST) return null;
    let s = null;
    try {
        s = JSON.parse(localStorage.getItem(STATE_KEY) || "null", unpackRef);
    } catch (e) {
        s = null;
    }
    const away = s && Date.now() - s.at;
    if (
        !s ||
        s.pois !== POIS.length ||
        s.desks !== DESKS.length ||
        !(away >= 0) ||
        away > STATE_MAX_AGE ||
        !Array.isArray(s.workers)
    )
        return null;
    for (const o of s.workers) {
        const w = Object.assign(makeWorker({ id: o.id }), o);
        if (w.poi) w.poi.taken = w.id;
        if (w.desk) w.desk.owner = w.id;
    }
    Object.assign(cat, s.cat);
    Object.assign(bot, s.bot);
    Object.assign(pong, s.pong);
    Object.assign(talks, s.talks);
    if (s.consoleSwap) Object.assign(consoleSwap, s.consoleSwap);
    convoPair = s.convoPair;
    lastQuip = s.lastQuip || 0;
    tvFlashUntil = s.tvFlashUntil || 0;
    for (const [k, v] of s.told || []) told.set(k, v);
    for (const [k, v] of s.prevRuns || []) prevRuns.set(k, v);
    for (const [k, v] of s.prevState || []) prevState.set(k, v);
    if (s.showNames) toggleNames();
    selected = s.selected || null;
    clockSkew = s.t - performance.now(); // resume the simulation clock at the instant we left
    firstPoll = false;
    return away;
}
addEventListener("pagehide", saveState);
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        saveState();
        return;
    }
    if (!booted) return;
    // a hidden page gets no animation frames; replay the gap instead of freezing then jumping
    const gap = tnow() - last;
    clockSkew -= gap;
    catchUp(gap);
});
