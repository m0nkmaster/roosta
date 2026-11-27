// Office page. Workers: where they go, what they do off shift, what they say, and the overtime errands.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// ================================================================ workers
const workers = new Map();
let tasks = [],
    selected = null,
    hovered = null,
    showNames = false,
    firstPoll = true;
function makeWorker(t) {
    const now = tnow();
    const w = {
        id: t.id,
        task: t,
        role: roleOf(t),
        look: lookOf(t),
        x: 0,
        y: 0,
        dir: "down",
        path: [],
        spot: null,
        dwellUntil: 0,
        emote: null,
        emoteUntil: 0,
        nextEmote: now + 3000 + hash(t.id) * 12000,
        quip: null,
        quipStart: 0,
        quipUntil: 0,
        speed: 30 + hash(t.id + "spd") * 14,
        v: 0,
        walkDist: 0,
        phase: hash(t.id) * 6.28,
        desk: null,
        poi: null,
        lookDir: "down",
        lookUntil: 0,
        nextLook: now + rnd(2000, 8000),
        nextThink: now + rnd(4000, 14000),
        thinkUntil: 0,
        celebrateUntil: 0,
        celebrateStart: 0,
        lastGreet: 0,
        knockAt: 0,
        knocks: 3,
        nextKnock: 0,
        arrivedAt: now,
        speaking: false,
        listening: false,
        act: null,
        item: null,
        carry: null,
        bitAt: 0,
        nextBit: 0,
        dwellLen: 20000,
        mugCol: pick(["#e85d5d", "#5b8cff", "#f4ecff", "#7ee0b5", "#ffd166", "#b79bff"], hash(t.id + "mug")),
    };
    workers.set(t.id, w);
    return w;
}
function releaseSpot(w) {
    if (w.poi) {
        w.poi.taken = null;
        w.poi = null;
    }
    if (w.desk) {
        w.desk.owner = null;
        w.desk = null;
    }
}
function goTo(w, spot, instant) {
    const old = w.spot;
    w.spot = spot;
    w.legT = 0;
    w.holdUntil = 0;
    if (instant) {
        w.x = spot.x;
        w.y = spot.y;
        w.path = [];
        w.dir = spot.face || "down";
        return;
    }
    // Getting up (or interrupted mid sit-down/stand-up): slide out to the seat's approach point before
    // walking, still seated-sorted, so nobody walks out through the furniture.
    const leg = seatLeg(w);
    const seat =
        leg && leg.approach
            ? leg
            : old && old.pose && old.approach && Math.hypot(w.x - old.x, w.y - old.y) < 3
              ? old
              : null;
    const from = seat ? seat.approach : w;
    const via = spot.approach ? [spot.approach] : [];
    w.path = findPath(from.x, from.y, (via[0] || spot).x, (via[0] || spot).y);
    if (seat) w.path.unshift({ x: seat.approach.x, y: seat.approach.y, seat });
    if (via.length) w.path.push({ x: spot.x, y: spot.y, seat: spot.pose ? spot : null });
}
const seatLeg = (w) => (w.path.length && w.path[0].seat) || null;
function sendTo(w, p) {
    if (w.poi) {
        w.lastPoi = w.poi;
        w.poi.taken = null;
    }
    p.taken = w.id;
    w.poi = p;
    goTo(w, p);
}
// A status spot (signed-out seat, queue window) outranks a roamer: whoever holds it moves on at their next idle tick.
function claimPoi(w, p) {
    const o = p.taken && p.taken !== w.id && workers.get(p.taken);
    if (o) {
        o.poi = null;
        if (o.state === "resting") {
            o.dwellUntil = 0;
            o.act = null;
            o.item = null;
        }
    }
    p.taken = w.id;
    w.poi = p;
}
const deskSeat = (d) => ({
    x: d.seat.x,
    y: d.seat.y,
    face: "up",
    pose: "sit",
    sort: d.seat.y + 1,
    approach: { x: d.seat.x, y: d.seat.y + 14 },
});
const nearestFreeDesk = (w) =>
    DESKS.filter((d) => !d.owner).sort(
        (a, b) => Math.hypot(a.seat.x - w.x, a.seat.y - w.y) - Math.hypot(b.seat.x - w.x, b.seat.y - w.y),
    )[0] || null;
function sitAtDesk(w, d, instant) {
    d.owner = w.id;
    w.desk = d;
    const s = deskSeat(d);
    if (!instant && !w.path.length && Math.hypot(w.x - s.x, w.y - s.y) < 3) {
        w.spot = s;
        w.dir = "up";
        return;
    } // already in the chair
    goTo(w, s, instant);
}
// A queued writer with no free desk stares out of the first free window (roamers there make way).
function toWindow(w, instant) {
    const p = QUEUE_WINDOWS.find(
        (s) => !s.taken || s.taken === w.id || (workers.get(s.taken) || {}).state !== "queued",
    );
    if (p) {
        claimPoi(w, p);
        goTo(w, p, instant);
    } else goTo(w, { x: 110 + (w.line % 4) * 16, y: 112, face: "up" }, instant);
}
const isNight = () => nightShift(clock());
const isWeekend = () => {
    const d = clock().day;
    return d === 0 || d === 6;
};
// the week's mood colours idle chatter only (ambient): Monday-morning blues, Friday-afternoon buzz, lazy weekends
function weekMood(day, t) {
    if (day === 0 || day === 6) return "weekend";
    if (day === 1 && t < 12) return "monday";
    if (day === 5 && t >= 15) return "friday";
    return null;
}
const moodNow = () => {
    const c = clock();
    return weekMood(c.day, c.t);
};
// Friday cake (ambient): someone brings a pie in at 14:30; it's cut into by 15:30 and the last slice sits there, unclaimed, until 18:00
function cakeStage(day, t) {
    if (day !== 5 || t < 14.5 || t >= 18) return null;
    return t < 15.5 ? "whole" : t < 16.75 ? "cut" : "slice";
}
const cakeNow = () => {
    const c = clock();
    return cakeStage(c.day, c.t);
};
// weekends: off-shift crew drift to the lounge and library; desk-ish chores lose their pull (ambient only)
function weekendBias(tag) {
    if (
        [
            "sofa",
            "tv",
            "arcade",
            "pong",
            "foos",
            "darts",
            "console",
            "read",
            "coffee",
            "fridge",
            "vending",
            "window",
            "table",
        ].includes(tag)
    )
        return 2.2;
    if (["meeting", "board", "copier", "peek", "phone", "books"].includes(tag)) return 0.3;
    return 1;
}
// Off-shift daily rhythm (ambient only - real statuses still map to desk/window/meeting room/sick bay):
// weekday mornings pull the crew to coffee and the board; 12:00-14:00 fills the kitchen for lunch;
// afternoons keep the crew around the board, shelves and kettle; evenings wind down in the lounge and games room;
// late nights empty the meeting room and kitchen so their motion-sensor lamps go dark while night owls hang out in the lounge and den.
function dayPhase(day, t) {
    if (t >= 21 || t < 7) return "night";
    if (day === 0 || day === 6) return "weekend";
    if (t < 10.5) return "morning";
    if (t >= 12 && t < 14) return "lunch";
    if (t >= 17.5) return "evening";
    return "afternoon";
}
function dayBias(tag, phase, room) {
    if (tag === "fire") return phase === "morning" || phase === "weekend" ? 2.5 : 1.5; // a cold start draws the crew to the hearth
    if (tag === "visit")
        return phase === "morning" || phase === "afternoon" ? 0.8 : phase === "lunch" || phase === "evening" ? 0.25 : 0; // the user's office: working hours only
    if (phase === "weekend") return weekendBias(tag);
    if (phase === "morning") {
        if (["coffee", "board", "meeting"].includes(tag)) return 3.2;
        if (["chat", "books", "copier", "peek"].includes(tag)) return 2;
        if (["arcade", "console", "pong", "foos", "darts"].includes(tag)) return 0.15;
        if (["sofa", "tv", "table", "fridge", "vending"].includes(tag)) return 0.5;
        return 1;
    }
    if (phase === "lunch") {
        if (tag === "table") return 6;
        if (tag === "fridge" || tag === "vending") return 4.5;
        if (["coffee", "cooler", "sink"].includes(tag)) return 2.5;
        if (tag === "chat") return room === "kitchen" ? 3 : 0.8;
        if (["meeting", "board", "copier", "books", "peek"].includes(tag)) return 0.2;
        if (["sofa", "tv", "read", "study", "arcade", "console", "pong", "foos", "darts"].includes(tag)) return 0.35;
        return 1;
    }
    if (phase === "afternoon") {
        if (["board", "meeting", "coffee", "cooler", "books", "peek", "copier", "chat"].includes(tag)) return 2.2;
        if (["table", "fridge", "vending"].includes(tag)) return 0.7;
        if (["sofa", "tv"].includes(tag)) return 0.45;
        if (["arcade", "console", "pong", "foos", "darts"].includes(tag)) return 0.25;
        return 1;
    }
    if (phase === "evening") {
        if (["sofa", "tv", "console", "arcade", "pong", "foos", "darts", "read"].includes(tag)) return 2.4;
        if (["meeting", "board", "copier", "books"].includes(tag)) return 0.2;
        return 1;
    }
    if (phase === "night") {
        if (room === "meeting" || room === "kitchen") return 0;
        if (["sofa", "tv", "console", "arcade", "read", "study"].includes(tag)) return 3;
        if (["pong", "foos", "darts"].includes(tag)) return 1.4;
        if (["copier", "books", "window", "art", "door"].includes(tag)) return 0.15;
        return 1;
    }
    return 1;
}
const phaseNow = () => {
    const c = clock();
    return dayPhase(c.day, c.t);
};
function tableAct(carry, phase, r) {
    if (FOODS.has(carry) || phase === "lunch") return "eat";
    if (carry === "book") return "read";
    if (DRINKS.has(carry)) return "sip";
    return r < 0.65 ? "sip" : r < 0.85 ? "read" : "phone";
}
function mateOf(w) {
    if (!w.poi || !w.poi.pair) return null;
    const q = POIS.find((p) => p.pair === w.poi.pair && p !== w.poi && p.taken);
    return q ? workers.get(q.taken) : null;
}
function choosePoi(w) {
    const r = ROLES[w.role],
        phase = phaseNow();
    const due = w.task ? dueAt(w.task, Date.now()) : null,
        dueIn = due === null ? null : due - Date.now();
    if (w.role === "guard" && phase !== "night" && phase !== "lunch") {
        const d = POIS.find((p) => p.only === "guard");
        if (d && !d.taken && w.lastPoi !== d && Math.random() < 0.6) return d;
    }
    const free = POIS.filter(
        (p) =>
            !p.taken &&
            (!p.only || p.only === w.role) &&
            p !== w.lastPoi &&
            !(p.tag === "meeting" && counts.locked) &&
            (p.tag !== "fire" || fireNow() === 2) &&
            (p.tag !== "post" || postLeft().some((x) => x.i !== OWN_SLOT)) &&
            (p.tag !== "peek" || (deskBusy(p.desk) && p.desk.owner !== w.id)),
    );
    const weights = free.map((p) => {
        const rm = roomAt(p.x, p.y),
            bias = dayBias(p.tag, phase, rm);
        if (!bias) return 0;
        let k = (r.likes.includes(p.tag) ? 4 : 1) * bias * shiftPull(dueIn, rm);
        if (p.pair && free.length && POIS.some((q) => q.pair === p.pair && q !== p && q.taken)) k *= 3.5;
        if (p.tag === "peek") k *= 1.5;
        if (p.tag === "post") k *= 1 + postLeft().filter((x) => x.i !== OWN_SLOT).length; // a full bank of post draws people over
        if (p.dine && cakeNow() && cakeNow() !== "slice") k *= 4; // word gets round: there's cake
        k *= 1 / (1 + Math.hypot(p.x - w.x, p.y - w.y) / 260);
        if (w.carry) {
            if (KITCHEN[p.tag] || p.tag === "books") k *= 0.08;
            else if (CARRY_TO.has(p.tag)) k *= 3;
            if (w.carry === "book" && READ_SPOTS.has(p.tag)) k *= 3;
            if ((w.carry === "snack" || w.carry === "sandwich") && p.tag === "table") k *= 4;
        } else if (KITCHEN[p.tag]) k *= phase === "lunch" ? 2.2 : 1.6;
        return k;
    });
    let sum = weights.reduce((a, b) => a + b, 0),
        x = Math.random() * sum;
    for (let i = 0; i < free.length; i++) {
        x -= weights[i];
        if (x <= 0) return free[i];
    }
    return free[0] || null;
}

// ================================================================ off-shift activities
// Every spot has a visible activity; kitchen trips hand the worker something to carry to a seat.
const KITCHEN = { coffee: "mug", cooler: "water", vending: "snack", fridge: "sandwich" };
const CARRY_TO = new Set(["sofa", "console", "read", "study", "table", "chat", "window", "tv"]);
const READ_SPOTS = new Set(["read", "study", "sofa"]);
const DRINKS = new Set(["mug", "water"]),
    FOODS = new Set(["snack", "sandwich"]);
const DWELL = {
    fetch: [4000, 7000],
    browse: [6000, 10000],
    tv: [30000, 70000],
    read: [30000, 60000],
    eat: [25000, 45000],
    sip: [20000, 35000],
    talk: [20000, 40000],
    phone: [12000, 25000],
    gaze: [10000, 20000],
    water: [10000, 16000],
    write: [14000, 26000],
    meet: [30000, 60000],
    papers: [8000, 14000],
    guard: [20000, 40000],
    nap: [40000, 80000],
    peek: [6000, 11000],
    pong: [8000, 14000],
    foos: [9000, 16000],
    darts: [10000, 20000],
    wash: [6000, 10000],
    arcade: [25000, 50000],
    console: [30000, 70000],
    pose: [9000, 11000],
    visit: [15000, 30000],
    warm: [12000, 22000],
    post: [5000, 8000],
};
function chooseAct(w, p) {
    const c = w.carry,
        night = isNight(),
        tag = p.tag;
    if (KITCHEN[tag]) return "fetch";
    if (tag === "books") return "browse";
    if (tag === "plant") return w.role === "gardener" ? "water" : "phone";
    if (tag === "board") return "write";
    if (tag === "meeting") return "meet";
    if (tag === "copier") return "papers";
    if (tag === "door") return "guard";
    if (tag === "frame") return "pose";
    if (tag === "post") return "post";
    if (tag === "visit") return "visit";
    if (tag === "chat") return "talk";
    if (tag === "fire") return "warm";
    if (tag === "table")
        return p.dine && !c && cakeNow() && cakeNow() !== "slice" ? "eat" : tableAct(c, phaseNow(), Math.random());
    if (["peek", "bedside", "pong", "arcade", "phone", "foos", "darts", "console"].includes(tag)) return tag;
    if (tag === "sink") return "wash";
    if (tag === "tv" || tag === "sofa") return "tv"; // every lounge seat faces the TV
    if (tag === "window" || tag === "art") return "gaze";
    // reading nooks, rugs, study desks
    if (c === "book") return "read";
    if (FOODS.has(c)) return "eat";
    if (DRINKS.has(c)) return Math.random() < 0.5 ? "sip" : "read";
    if (night && tag !== "study" && Math.random() < 0.35) return "nap";
    return Math.random() < 0.65 || tag === "study" ? "read" : "phone";
}
function itemFor(w) {
    const a = w.act,
        c = w.carry;
    if (a === "read") return "book";
    if (a === "phone") return "phone";
    if (a === "water") return "can";
    if (a === "write") return "marker";
    if (a === "papers") return "papers";
    if (a === "eat") return FOODS.has(c) ? c : w.poi && w.poi.tag === "table" ? null : "snack";
    if (a === "sip") return w.poi && w.poi.tag === "table" ? null : c || "mug";
    if (a === "tv" || a === "talk") return c && c !== "book" ? c : null;
    if (a === "warm") return DRINKS.has(c) ? c : null;
    if (a === "gaze") return c && c !== "book" ? c : hash(w.id + "ph") > 0.5 ? "phone" : null;
    return null;
}
function leaveSpot(w) {
    // what the worker takes with them
    const tag = w.poi && w.poi.tag;
    if (KITCHEN[tag]) w.carry = KITCHEN[tag];
    else if (tag === "books") w.carry = "book";
    else if (w.carry && w.item === w.carry && (w.act === "eat" || w.act === "read" || Math.random() < 0.7))
        w.carry = null;
    w.act = null;
    w.item = null;
}
function dwellFor(w) {
    if (w.errand && w.act === "fetch") return rnd(1600, 2400);
    const d = DWELL[w.act] || [12000, 28000];
    return rnd(d[0], d[1]);
}
// A queued writer already at a desk keeps it when the writer lock frees and the run starts, and a writer queued
// again straight after its run stays put (lifted into tests/test_office.py).
function keepsDesk(prevState, nextState) {
    return (prevState === "queued" && nextState === "working") || (prevState === "working" && nextState === "queued");
}
// When a sick-bay patient gets called back to retry (at a desk or waiting for the writer lock),
// any colleague visiting at BEDSIDE (or bringing tea) waves them off and Nurse Puss escorts them out.
function sickSendOff(prevState, nextState, patientId, ws, catOnBed) {
    if (prevState !== "hurt" || (nextState !== "working" && nextState !== "queued")) return null;
    let nurse = null,
        atBedside = false,
        otherHurt = false;
    for (const o of ws || []) {
        if (!o || o.id === patientId) continue;
        if (o.state === "hurt") {
            otherHurt = true;
            continue;
        }
        if (o.state !== "resting") continue;
        if (o.poi && o.poi.tag === "bedside" && (!o.path || !o.path.length)) {
            nurse = o.id;
            atBedside = true;
        } else if (!nurse && (o.errand === patientId || o.errandKind === "tea")) nurse = o.id;
    }
    return { nurse, atBedside, keepTea: otherHurt, catEscort: catOnBed === patientId };
}
const queuedSince = {};
function assign(list) {
    const now = tnow(),
        wasFirst = firstPoll,
        groups = { working: [], queued: [], locked: [], hurt: [], resting: [] };
    for (const t of list) groups[behaviour(t)].push(t);
    for (const t of groups.queued) if (queuedSince[t.id] === undefined) queuedSince[t.id] = now;
    for (const id in queuedSince) if (!groups.queued.some((t) => t.id === id)) delete queuedSince[id];
    groups.queued = queueOrder(groups.queued, queuedSince);
    groups.locked = lockOrder(groups.locked);
    groups.hurt = sickOrder(groups.hurt, streaks);
    const seen = new Set();
    for (const [state, arr] of Object.entries(groups))
        arr.forEach((t, i) => {
            seen.add(t.id);
            let w = workers.get(t.id);
            const fresh = !w;
            if (!w) {
                w = makeWorker(t);
                spawnAt(w);
            }
            w.task = t;
            w.role = roleOf(t);
            w.look = lookOf(t);
            if (w.state === state && !fresh && state !== "locked" && state !== "hurt") {
                w.line = i;
                return;
            } // a queued writer keeps its desk or window
            if (w.state === state && !fresh && w.line === i) return;
            // Only an off-shift worker on a cold start is placed directly; everyone else walks, including to a desk.
            const prev = w.state;
            w.state = state;
            if (prev === "working" && state !== "working") {
                w.lastDesk = w.desk;
                w.lastTension = Math.max(w.tension || 0, tension(progressOf(t)));
            }
            if (prev !== state) w.tension = 0;
            const instant = firstPoll && fresh && state === "resting";
            const keep = w.desk && keepsDesk(prev, state) ? w.desk : null,
                gotTurn = !firstPoll && prev === "queued" && state === "working";
            const sendOff = !firstPoll && sickSendOff(prev, state, w.id, workers.values(), cat.onBed);
            if (state !== "resting" || prev !== "resting") {
                releaseSpot(w);
                w.act = null;
                w.item = null;
                w.errand = null;
                w.errandKind = null;
                w.reliefWith = null;
                w.reliefKind = null;
                w.reliefUntil = 0;
                w.reliefDesk = 0;
                w.greetPeer = null;
                w.greetKind = null;
                w.greetDesk = 0;
                w.greetUntil = 0;
                w.sendOffFor = null;
                w.sendOffUntil = 0;
                if (state !== "hurt") w.hasTea = false;
                if (state !== "resting") w.carry = null;
            }
            w.celebrateUntil = 0;
            if (state === "working") {
                // a running task outranks a queued one: with every desk taken, a gamer gives up their seat for the window
                let d = (keep && !keep.owner && keep) || nearestFreeDesk(w);
                if (!d) {
                    d = DESKS.find((x) => (workers.get(x.owner) || {}).state === "queued") || null;
                    const q = d && workers.get(d.owner);
                    if (q) {
                        d.owner = null;
                        q.desk = null;
                        toWindow(q);
                        if (!firstPoll) say(q, pick(QUIPS.deskBumped, Math.random()), now);
                    }
                }
                if (d) sitAtDesk(w, d, instant);
                else goTo(w, { x: 200 + i * 14, y: 196, face: "up" }, instant);
                if (!firstPoll) {
                    w.emote = gotTurn || sendOff ? "star" : "bang";
                    w.emoteUntil = now + (sendOff ? 1800 : 1100);
                    say(w, pick(gotTurn ? QUIPS.gameOver : sendOff ? QUIPS.retry : QUIPS.start, Math.random()), now);
                }
            } else if (state === "queued") {
                w.line = i;
                const d = (keep && !keep.owner && keep) || nearestFreeDesk(w);
                if (d) sitAtDesk(w, d, instant);
                else toWindow(w, instant);
                if (sendOff) {
                    w.emote = "star";
                    w.emoteUntil = now + 1800;
                    say(w, pick(QUIPS.retry, Math.random()), now);
                }
            } else if (state === "locked") {
                w.line = i;
                const sp = callSpot(i, CALL_SEATS);
                if (sp.tag) claimPoi(w, sp);
                goTo(w, sp, instant);
                if (!firstPoll && prev !== "locked") say(w, pick(QUIPS.locked, Math.random()), now);
            } else if (state === "hurt") {
                w.line = i;
                goTo(w, sickSpot(i), instant);
            } else {
                w.dwellUntil = instant ? now + rnd(4000, 24000) : 0;
                if (instant) {
                    const p = choosePoi(w);
                    if (p) {
                        p.taken = w.id;
                        w.poi = p;
                        goTo(w, p, true);
                        if (p.tag === "table") w.carry = pick(["mug", "water", "sandwich", "snack"], Math.random());
                        else if (KITCHEN[p.tag] === undefined && CARRY_TO.has(p.tag) && Math.random() < 0.4)
                            w.carry = pick(["mug", "water", "snack", "sandwich", "book"], Math.random());
                        w.act = chooseAct(w, p);
                        w.item = itemFor(w);
                        w.arrivedAt = now;
                        w.dwellLen = w.dwellUntil - now;
                    }
                }
            }
            if (sendOff) {
                const nw = sendOff.nurse && workers.get(sendOff.nurse);
                if (nw) {
                    if (sendOff.atBedside) {
                        nw.lookDir = dirTo(nw, w.x, w.y);
                        nw.lookUntil = now + 2800;
                        nw.sendOffFor = w.id;
                        nw.sendOffUntil = now + 2800;
                        nw.dwellUntil = Math.max(nw.dwellUntil || 0, now + 2800);
                        nw.emote = "heart";
                        nw.emoteUntil = now + 2600;
                        nw.quip = pick(QUIPS.sendOff, Math.random());
                        nw.quipStart = now + 450;
                        nw.quipUntil = now + 3400;
                    } else if (!sendOff.keepTea) {
                        nw.errand = null;
                        nw.errandKind = null;
                        nw.carry = null;
                        nw.path = [];
                        nw.dwellUntil = now + 1800;
                        nw.lookDir = dirTo(nw, w.x, w.y);
                        nw.lookUntil = now + 2200;
                        nw.emote = "heart";
                        nw.emoteUntil = now + 2200;
                        nw.quip = pick(QUIPS.sendOff, Math.random());
                        nw.quipStart = now + 450;
                        nw.quipUntil = now + 3200;
                    }
                }
                if (sendOff.catEscort) {
                    catHopOffBed(now);
                    catSay("mrrp!", now);
                    cat.follow = w.id;
                    cat.followUntil = now + 9000;
                    cat.repath = 0;
                }
            }
        });
    for (const id of [...workers.keys()])
        if (!seen.has(id)) {
            releaseSpot(workers.get(id));
            workers.delete(id);
        }
    // whoever has waited longest at a window takes the next desk that frees up
    for (const t of groups.queued) {
        const w = workers.get(t.id);
        if (!w || w.desk) continue;
        const d = nearestFreeDesk(w);
        if (!d) break;
        releaseSpot(w);
        sitAtDesk(w, d);
        if (!wasFirst) say(w, pick(QUIPS.deskFree, Math.random()), now);
    }
    firstPoll = false;
    if (wasFirst && sensorHours(clock())) {
        for (const k in roomLit) roomLit[k] = 0;
        for (const w of workers.values()) {
            const r = roomAt(w.x, w.y);
            roomSeen[r] = now;
            roomLit[r] = 1;
        }
    }
}
// Where a new worker appears before walking to their spot: somewhere in the office on a cold start
// (as if already about), otherwise through the front door.
function spawnAt(w) {
    let p = DOOR.front;
    if (firstPoll) {
        const night = phaseNow() === "night";
        const open = POIS.filter(
            (q) =>
                !q.taken &&
                !q.pose &&
                !q.pair &&
                !q.only &&
                (!night ||
                    (roomAt(q.x, q.y) !== "meeting" &&
                        roomAt(q.x, q.y) !== "kitchen" &&
                        roomAt(q.x, q.y) !== "firstaid")),
        );
        if (open.length) p = pick(open, Math.random());
    }
    w.x = p.x;
    w.y = p.y;
    w.dir = "down";
}

// ================================================================ emotes, quips, particles
const ICONS = {
    lock: ["..###..", ".#...#.", ".#...#.", "#######", "###o###", "###o###", "#######"],
    bang: ["..##...", "..##...", "..##...", "..##...", "..##...", ".......", "..##..."],
    clock: [".#####.", "#ooooo#", "#oo#oo#", "#oo##o#", "#ooooo#", "#ooooo#", ".#####."],
    hourglass: ["#######", ".#ooo#.", "..#o#..", "...#...", "..#.#..", ".#ooo#.", "#######"],
    pad: [".#####.", "##o##o#", "#ooo###", "##o##o#", "##...##"],
    heart: [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."],
    cup: [".#.#...", "#.#....", ".......", "#####o.", "#####.o", "#####o.", ".###..."],
    note: ["...##..", "...#.#.", "...#...", "...#...", ".###...", "####...", ".##...."],
    z: ["#####", "...#.", "..#..", ".#...", "#####"],
    book: ["###.###", "#o#.#o#", "#o#.#o#", "###.###", "#######"],
    q: [".###.", "#...#", "...#.", "..#..", ".....", "..#.."],
    star: ["...#...", "..###..", "#######", ".#####.", ".##.##.", "#.....#"],
    tv: ["#######", "#ooooo#", "#ooooo#", "#######", "..#.#.."],
    wave: ["o.o.o..", "o.o.o.o", "ooooo.o", "oooooo.", ".oooo..", "..ooo..", "..ooo.."],
    bulb: ["..###..", ".#ooo#.", ".#ooo#.", ".#ooo#.", "..#o#..", "..###..", "...#..."],
    cloud: ["..###..", ".#####.", "#######", ".#####.", "..o.o..", ".o.o..."],
    paw: [".#.#.", "#...#", ".###.", ".###."],
};
const ICON_COL = {
    lock: ["#ff6b6b", "#ffd166"],
    bang: ["#ff4d4d"],
    hourglass: ["#b79bff", "#ffd166"],
    pad: ["#7a5fd6", "#f4ecff"],
    clock: ["#3a3550", "#f4efe1"],
    heart: ["#ff6b9a"],
    cup: ["#8b5a3c", "#8b5a3c"],
    note: ["#5b6cff"],
    z: ["#6aa6ff"],
    book: ["#7a4bd1", "#f4ecff"],
    q: ["#ffb347"],
    star: ["#ffc93c"],
    tv: ["#3d3566", "#6ad1ff"],
    wave: ["#d99a6c", "#d99a6c"],
    bulb: ["#6b5a2a", "#ffe066"],
    cloud: ["#6b6b80", "#6aa6ff"],
    paw: ["#e8964a"],
};
const ROAM_EMOTES = {
    coffee: ["cup", "heart"],
    cooler: ["cup", "q"],
    vending: ["star", "q"],
    fridge: ["q", "heart"],
    sofa: ["z", "note", "tv", "heart"],
    tv: ["tv", "star"],
    books: ["book", "q"],
    window: ["star", "q", "note"],
    chat: ["heart", "note", "q", "star"],
    plant: ["heart", "note"],
    art: ["q", "heart"],
    door: ["star"],
    meeting: ["q", "star", "note", "book", "bulb"],
    board: ["q", "star", "book", "bulb"],
    read: ["book", "bulb", "z"],
    peek: ["q", "star", "bulb"],
    pong: ["star"],
    arcade: ["star", "note", "heart"],
    console: ["star", "note", "heart"],
    study: ["book", "bulb", "note"],
};
const ACT_EMOTES = {
    tv: ["tv", "star", "heart"],
    console: ["star", "heart", "note"],
    read: ["book", "bulb", "heart"],
    eat: ["heart", "star"],
    sip: ["cup", "heart"],
    phone: ["heart", "q", "note"],
    water: ["heart", "note"],
    write: ["bulb", "q"],
    meet: ["q", "bulb", "note"],
    gaze: ["star", "note"],
    nap: ["z"],
    browse: ["book", "q"],
    fetch: ["cup", "star"],
};
const FOCUSED = new Set([
    "read",
    "phone",
    "eat",
    "sip",
    "tv",
    "write",
    "water",
    "browse",
    "meet",
    "papers",
    "arcade",
    "pong",
    "foos",
    "darts",
    "wash",
    "fetch",
    "nap",
    "console",
]);
const QUIPS = {
    warm: [
        "lovely and toasty",
        "warming my hands",
        "proper cosy, this",
        "who's on log duty?",
        "nippy out there",
        "mind the sparks",
    ],
    overdue: [
        "wasn't I due on?",
        "still waiting for the call-up",
        "my shift started ages ago",
        "has the runner nodded off?",
        "anyone seen the rota?",
    ],
    tapWatch: ["*taps watch*", "aren't you meant to be on?", "you're late, you know", "runner's having a lie-in"],
    shiftSoon: [
        "nearly my shift",
        "back to it in a minute",
        "is that the time?",
        "one more sip, then work",
        "right, nearly on",
    ],
    console: [
        "gotta go fast!",
        "one more go",
        "Hadouken!",
        "who paused it?",
        "my turn next",
        "blow on the cartridge",
        "pass the pad",
        "rematch?",
    ],
    tv: ["no way!", "did you see that?", "page 302 please", "turn it up", "big news", "Ceefax, eh?", "remember this?"],
    foos: ["goal!", "no spinning!", "top bins", "rematch?"],
    darts: ["one hundred and eighty!", "double top", "bullseye!", "missed the board…"],
    eat: ["yum", "so good", "needed that", "crumbs…"],
    cake: [
        "who brought cake?",
        "is it someone's birthday?",
        "just a sliver for me",
        "Friday cake!",
        "did you bake this?",
        "go on then, small bit",
        "who's having the last slice?",
    ],
    sip: ["needed this brew", "good cuppa, that", "kettle's earnt its keep", "ah, caffeine", "proper builder's tea"],
    lunch: [
        "what did you bring?",
        "meal deal again",
        "someone's heated fish…",
        "save me a seat",
        "al desko? no chance",
        "is that sourdough?",
    ],
    morning: [
        "first brew of the day",
        "kettle's just boiled",
        "morning all",
        "stand-up in five?",
        "what's on the board?",
    ],
    afternoon: ["afternoon brew?", "3pm slump", "fancy a cuppa?", "kettle's warm", "push before five"],
    dusk: [
        "dark at four already",
        "lamps on, it's pitch out",
        "proper winter evening",
        "pitch black out there",
        "clocks went back",
        "kettle on?",
    ],
    read: ["great chapter", "hmm, interesting", "one more page"],
    phone: ["lol", "nice", "omg"],
    water: ["there you go", "drink up"],
    write: ["so if we…", "picture this", "boxes and arrows"],
    start: ["on it!", "clocking in", "to the desk!", "let's go", "shift time", "duty calls"],
    gameOver: ["game over, work time!", "got the lock!", "my turn at last", "saving my high score", "back to it"],
    deskFree: ["a desk! game on", "finally, a seat", "one more level, then work", "bagsy this desk"],
    deskBumped: ["fine, I'll take the window", "desk's all yours", "saved my game", "back to the view"],
    done: ["done!", "shipped", "nailed it", "all yours", "easy", "coffee earned"],
    fail: ["ouch", "that broke", "need a medic", "uh-oh", "not again"],
    locked: [
        "call won't connect",
        "can anyone hear me?",
        "you're on mute?",
        "reconnecting…",
        "is it just me?",
        "sign in again?",
    ],
    callCheck: ["re-check that sign-in?", "try signing in again?", "redial the call?"],
    chat: [
        "seen the dashboards?",
        "nice work",
        "coffee?",
        "busy day",
        "OKRs again",
        "ship it",
        "metrics look good",
        "who broke prod?",
        "lift is flat",
        "p-value?",
        "love that chart",
    ],
    rest: ["break time", "ahh", "lovely view", "back soon", "five minutes"],
    queue: ["one more level", "high score incoming", "waiting my turn", "any minute now"],
    queueWindow: ["nice view", "waiting my turn", "any minute now", "any desks free yet?"],
    queueCancel: ["leave the queue?", "cancel my turn?", "stand down?", "back off shift?"],
    peek: ["how's it going?", "looks good", "need a hand?", "ooh, nice"],
    pong: ["point!", "nice shot", "rematch?", "lucky!", "ace!"],
    cat: ["hello puss", "who's a good cat", "aww", "pspsps"],
    catdesk: ["not now, puss", "you again?", "no keyboard!", "I'm working…", "hello, supervisor", "shoo, I'm busy"],
    catkeys: [
        "OI! OFF THE KEYBOARD!",
        "not the deploy key!",
        "who typed ';jjjjj'?",
        "my terminal!",
        "puss, NO!",
        "that's production!",
    ],
    catshoo: ["shoo! off the keys!", "down you get!", "off! I'm debugging!", "go on, hop down", "shoo, supervisor!"],
    catbed: ["aw, nurse puss", "purr therapy", "best medicine", "goodest nurse", "warm paws"],
    sick: [
        "my stack trace hurts",
        "is it a 500 or a fever?",
        "off with a bad exit code",
        "doctor says it's DNS",
        "need a retry and a biscuit",
        "tell the logs I tried",
    ],
    sickErrand: ["tea for the sick bay!", "putting the kettle on", "playing nurse!", "cuppa coming up"],
    bedside: ["brought you a cuppa", "get well soon!", "hot sweet tea", "take five, mate", "nurse's orders"],
    sickThanks: ["cheers, needed that", "my hero", "best medicine", "rough stack trace…"],
    night: ["night owl", "quiet shift", "one more page"],
    errand: ["coffee run!", "kettle's on", "they need a brew"],
    serve: ["brought you a coffee", "here, fuel", "hang in there"],
    thanks: ["lifesaver", "cheers!", "you're a star"],
    checkIn: ["still running?", "need a second pair of eyes?", "let me have a look", "want to rubber-duck it?"],
    backseat: [
        "what do the logs say?",
        "is it stuck on a lock?",
        "tried a retry?",
        "hang on, look at that line",
        "classic race condition",
    ],
    rubberduck: [
        "don't jinx it",
        "it worked in staging",
        "shh, it's thinking",
        "nearly there, I swear",
        "one more minute",
    ],
    rain: [
        "grim out there",
        "forgot my brolly",
        "proper November, this",
        "it's chucking it down",
        "glad I'm not out in that",
    ],
    monday: [
        "is it Friday yet?",
        "how was your weekend?",
        "need. coffee.",
        "Monday again",
        "inbox zero? ha",
        "who moved my mug?",
        "case of the Mondays",
    ],
    friday: [
        "nearly the weekend!",
        "pub later?",
        "no deploys on Friday",
        "any plans?",
        "POETS day",
        "feels like Friday",
        "weekend's calling",
    ],
    weekend: [
        "lazy weekend",
        "no meetings!",
        "brunch later?",
        "weekend mode",
        "who's on call?",
        "lie-in tomorrow",
        "jeans day",
    ],
};
// A finished run gets a reaction from whoever is nearby (the finish is real; who reacts is ambient).
Object.assign(QUIPS, {
    cheer: ["nice one!", "smashed it", "go on!", "legend", "top work"],
    welcome: ["welcome aboard!", "one of us now", "knew you'd make it"],
    comeback: ["there they are!", "welcome back", "told you so"],
    sympathy: ["oof", "been there", "go easy", "nurse is in", "brew after?"],
    overrun1: ["nearly there…", "come on…", "bit slow today", "any second"],
    overrun2: ["why is this taking so long", "is it stuck?", "hmm.", "still going…", "should've had lunch"],
    clockwatch: ["look at the time", "is that clock right?", "where did the hour go", "tick tock", "it's HOW late?"],
    overrun3: ["this is a long one", "send snacks", "I live here now", "don't wait up", "make it stop"],
    relief: [
        "FINALLY!",
        "phew, it's over!",
        "it actually passed!",
        "never touching that again",
        "rubber ducking worked!",
    ],
    reliefPeer: [
        "rubber duck undefeated!",
        "told you it was that line!",
        "we fixed it!",
        "kettle's on me!",
        "high five!",
    ],
    retry: ["back in the saddle!", "patched up, let's go", "one more try", "no more 500s", "feeling better already"],
    sendOff: [
        "you've got this!",
        "take it steady!",
        "good luck out there!",
        "knock 'em dead!",
        "ring the bell when it's green!",
    ],
    welcomeHi: ["welcome to the crew!", "ten runs down, high five!", "officially one of us!", "smashed probation!"],
    comebackHi: [
        "welcome back, mate!",
        "back from the sick bay!",
        "knew you'd bounce back!",
        "high five, you're green!",
    ],
    milestoneThanks: ["cheers, mate!", "feels good to be green!", "good to be back!", "happy to be here!"],
    mentorGo: ["new starter on the go!", "I'll show them the ropes", "first runs, let me watch", "buddy duty!"],
    mentor: ["you're doing fine", "don't mind me", "I'm just here if you need me", "take your time"],
    mentorTip: [
        "read the brief twice",
        "check the output before you post",
        "that's how I'd do it",
        "nice and steady",
        "you'll be on your own soon",
    ],
    mentee: ["thanks, still finding my feet", "is this right?", "where's the kettle again?", "everyone's so nice here"],
    proudGo: ["that's my protégé!", "they did it!", "knew they'd make it!", "my new starter passed!"],
    proudHi: ["proud of you!", "taught you well!", "you're on your own now!", "told you you'd fly!"],
    proudThanks: [
        "couldn't have done it without you!",
        "thanks for the tips!",
        "you showed me the ropes!",
        "I read the brief twice!",
    ],
    // employee of the week (the record is real; the ceremony is ambient)
    eotwWho: ["who, me?!", "me? really?", "oh, stop it", "I'm not crying, you're crying"],
    eotwBusy: ["can't stop, mid-run!", "frame it, I'm busy!", "tell them I said thanks!"],
    eotwSpeech: [
        "I'd like to thank the runner",
        "couldn't have done it without cron",
        "green all week!",
        "drinks are on me!",
        "and my mum!",
    ],
    eotwCheer: ["speech! speech!", "well deserved!", "employee of the week!", "frame-worthy!", "legend!"],
    eotwMe: ["that's me!", "my best side", "looking good, eh?", "they got my good side"],
    egg: ["you found one!", "good eye!", "there's more about", "one for the basket!"],
    eggAll: ["all of them?!", "egg hunt champion!", "save me a chocolate!"],
    visit: [
        "in a meeting?",
        "door's open, so…",
        "is this about my OKRs?",
        "I'll wait",
        "nice plant, {user}",
        "got a minute?",
        "quick one, {user}?",
    ],
    // seasonal chatter (SEASON_CHAT)
    s_christmas: [
        "Secret Santa sorted?",
        "mince pie?",
        "Christmas jumper day!",
        "is it Wham! again?",
        "who's on call over Christmas?",
        "office party Friday?",
        "tinsel on the copier",
        "pigs in blankets",
    ],
    s_xmasafter: [
        "what did Santa bring?",
        "turkey sandwiches again",
        "quiet one, this week",
        "leftover mince pies",
        "who's on call till New Year?",
    ],
    s_newyear: [
        "happy new year!",
        "any resolutions?",
        "new year, new OKRs",
        "fireworks at midnight!",
        "dry January? ha",
        "auld lang syne!",
    ],
    s_halloween: [
        "trick or treat!",
        "nice costume",
        "who carved the pumpkin?",
        "spooky deploy",
        "boo!",
        "who hung up the skeleton?",
        "ghost in the machine",
    ],
    s_bonfire: [
        "remember, remember…",
        "ooh! aah!",
        "fireworks tonight?",
        "the cat hates the bangs",
        "toffee apple?",
        "sparklers at the park",
    ],
    s_valentine: [
        "who sent the roses?",
        "secret admirer?",
        "roses are red…",
        "ooh, chocolates",
        "love the new dashboards",
    ],
    s_easter: [
        "egg hunt's on!",
        "found one by the copier",
        "chocolate for breakfast",
        "long weekend!",
        "hot cross bun?",
    ],
    s_friday13: [
        "Friday the 13th…",
        "touch wood",
        "nobody deploy today",
        "don't walk under the ladder",
        "I'm not superstitious, but…",
        "who smashed a mirror?",
        "fingers crossed for the runs",
        "lucky socks on",
    ],
    blackcat: [
        "black cat! touch wood",
        "was that a black cat?",
        "crossed my path, great",
        "lucky or unlucky?",
        "not today, puss",
        "it's a sign",
    ],
    s_pride: ["happy Pride!", "love is love", "parade this weekend?", "love the flags", "proud of this lot"],
});
function cheerer(w, ws, r) {
    // nearest colleague in earshot who is standing still and awake
    let best = null,
        bd = r;
    for (const o of ws) {
        if (o === w || o.path.length || o.act === "nap" || (o.state !== "resting" && o.state !== "working")) continue;
        const d = Math.hypot(o.x - w.x, o.y - w.y);
        if (d < bd) {
            bd = d;
            best = o;
        }
    }
    return best;
}
function react(w, kind, delay) {
    const o = cheerer(w, workers.values(), 240);
    if (!o) return;
    setTimeout(() => {
        const now = tnow();
        if (o.path.length || now < o.quipUntil) return; // never talk over them
        o.lookDir = dirTo(o, w.x, w.y);
        o.lookUntil = now + 2600;
        o.emote = kind === "sympathy" ? "heart" : "star";
        o.emoteUntil = now + 2200;
        say(o, pick(QUIPS[kind], Math.random()), now);
    }, delay);
}
let lastQuip = 0;
function say(w, text, now) {
    text = text.replace(/\{user\}/g, USER_NAME === "You" ? "boss" : USER_NAME);
    w.quip = text;
    w.quipStart = now;
    w.quipUntil = now + 2400 + text.length * 60;
    lastQuip = now;
}
// shop talk: chat pairs discuss what their last runs actually produced (last_output.summary from /api/tasks)
const NEWS_MAX_AGE = 3 * 86400e3,
    NEWS_RETELLS = 2,
    told = new Map();
function cleanError(s) {
    return String(s || "")
        .replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "")
        .replace(/\s+/g, " ")
        .trim();
}
function gist(t) {
    let s = cleanError(t && t.last_output && t.last_output.summary);
    if (
        !s ||
        /^[^A-Za-z0-9+]/.test(s) ||
        /\/(Users|home|opt|tmp)\/|https?:|\.aws|token|credential|password|secret/i.test(s)
    )
        return "";
    s = s.replace(/\s+\b\d{1,2}:\d{2}(?::\d{2})?(?:Z|\s*(?:GMT|UTC|BST))?\b/gi, "").replace(/\bsince\s*$/i, "");
    const pre = s.match(/^([A-Za-z][\w &'-]{1,40}?)(?:,.{0,24}?)?:\s+(.+)$/); // "Teams archive: ..." / "Garden 7 Nov: ..."
    if (pre && pre[2].length >= 12 && !/^(no|nothing|quiet|unchanged|blocked|skipped|done|failed)\b/i.test(pre[1]))
        s = pre[2];
    s = s
        .replace(/\s*\([^)]*\)/g, "")
        .replace(/;/g, ",")
        .split(/[.!?](?:\s|$)|\s[-–—]\s/)[0]
        .replace(/[.:,]+$/, "")
        .trim();
    // Strip first-person narration so shop talk reads like natural office speech.
    s = s
        .replace(/^I\s+(updated|checked|reviewed|scanned|ran|tidied|prepared|found|built|shipped)\b/i, "$1")
        .replace(/\s+\bsince\s*$/i, "")
        .replace(/[.:,]+$/, "")
        .trim();
    if (s.length > 46) {
        s = s.slice(0, 45);
        s = s.slice(0, Math.max(s.lastIndexOf(" "), 30)).replace(/[\s,;:]+$/, "") + "…";
    }
    return s.length < 4 ? "" : s;
}
function toneOf(t) {
    const s = String((t.last_output && t.last_output.summary) || "");
    if (
        t.status === "error" ||
        /\b(blocked|failed|failing|timed out|hung|broke|error|could not|couldn't|unable)\b|\b(auth|token|session|login)\b.{0,20}\bexpired\b/i.test(
            s,
        )
    )
        return "bad";
    if (
        /\b(no new|nothing|unchanged|quiet|no change|skipped|no incident|0 (new|pages|results|changes))\b|^no /i.test(s)
    )
        return "quiet";
    return "good";
}
// The Office calls a worker by its tasks.yaml nickname, falling back to DEFAULT_NICKS or the task id.
const nickOf = (t) => String((t && (t.nickname || DEFAULT_NICKS[t.id] || t.id)) || "");
const whoOf = (w) => nickOf(w.task) || w.id;
function newsOf(w) {
    const t = w && w.task,
        at = t && Date.parse(t.last_run);
    if (!at || Date.now() - at > NEWS_MAX_AGE) return null;
    const key = t.id + "@" + t.last_run,
        text = gist(t);
    if (!text || (told.get(key) || 0) >= NEWS_RETELLS) return null;
    const tone = toneOf(t);
    return { key, text, tone, rank: (Date.now() - at < 3600e3 ? 2 : 0) + { good: 1, bad: 1.5, quiet: 0 }[tone] };
}
const TALK = {
    ask: ["what's new?", "how was your run?", "busy shift?", "anything good?", "how'd it go?"],
    back: ["you?", "and you?", "how about yours?", "your turn"],
    good: ["nice one!", "ooh, nice", "love that", "ship it", "big if true"],
    quiet: ["quiet one, then", "peaceful", "I'll take it", "no news is good news"],
    bad: ["oof", "need a hand?", "that's rough", "auth again?", "try again later?"],
    huh: ["no?", "go on", "tell me"],
};
const say1 = (k) => pick(TALK[k], Math.random());
function scriptFor(a, b) {
    const na = newsOf(a),
        nb = newsOf(b);
    if (!na && !nb) return null;
    const [s, ns, l, nl] = !nb || (na && na.rank >= nb.rank) ? [a, na, b, nb] : [b, nb, a, na];
    const lines = [
        [l.id, say1("ask")],
        [s.id, ns.text, ns.key],
        [l.id, say1(ns.tone)],
    ];
    if (nl) lines.push([s.id, say1("back")], [l.id, nl.text, nl.key], [s.id, say1(nl.tone)]);
    else if (Math.random() < 0.5) {
        // gossip about a colleague's run
        const other = [...workers.values()]
            .filter((w) => w !== a && w !== b)
            .map((w) => [w, newsOf(w)])
            .filter(([, n]) => n && n.tone !== "quiet")
            .sort((x, y) => y[1].rank - x[1].rank)[0];
        if (other)
            lines.push(
                [s.id, `heard about ${whoOf(other[0])}?`],
                [l.id, say1("huh")],
                [s.id, other[1].text, other[1].key],
                [l.id, say1(other[1].tone)],
            );
    }
    return lines;
}
function drawIcon(c, name, x, y) {
    const rows = ICONS[name],
        cols = ICON_COL[name];
    for (let r = 0; r < rows.length; r++)
        for (let q = 0; q < rows[r].length; q++) {
            const ch = rows[r][q];
            if (ch === ".") continue;
            c.fillStyle = ch === "o" ? cols[1] || cols[0] : cols[0];
            c.fillRect(x + q, y + r, 1, 1);
        }
}
function bubble(c, x, y, draw, tint) {
    // 11x11 bubble, bottom-centre at (x, y)
    const bx0 = Math.round(x - 5),
        by0 = Math.round(y - 13);
    c.fillStyle = "#1b1830";
    c.fillRect(bx0 - 1, by0, 13, 11);
    c.fillRect(bx0, by0 - 1, 11, 13);
    c.fillStyle = tint || "#fffaf0";
    c.fillRect(bx0, by0, 11, 11);
    c.fillStyle = "#0000001a";
    c.fillRect(bx0, by0 + 9, 11, 2);
    c.fillStyle = "#1b1830";
    c.fillRect(bx0 + 4, by0 + 11, 3, 1);
    c.fillRect(bx0 + 5, by0 + 12, 1, 1);
    c.fillStyle = tint || "#fffaf0";
    c.fillRect(bx0 + 4, by0 + 10, 3, 1);
    c.fillRect(bx0 + 5, by0 + 11, 1, 1);
    draw(bx0 + 2, by0 + 2);
}
function emoteBubble(c, name, x, y) {
    bubble(c, x, y, (x0, y0) =>
        drawIcon(c, name, x0 + Math.floor((7 - ICONS[name][0].length) / 2), y0 + (ICONS[name].length < 7 ? 1 : 0)),
    );
}
const parts = [];
function spawn(p) {
    if (!REDUCED || p.type === "float") parts.push(p);
}
function confetti(x, y) {
    const cols = ["#ffd166", "#7ee0b5", "#ff6b9a", "#6aa6ff", "#b79bff"];
    for (let i = 0; i < 30; i++)
        spawn({
            type: "confetti",
            x,
            y,
            vx: (Math.random() - 0.5) * 90,
            vy: -60 - Math.random() * 70,
            life: 1.4,
            max: 1.4,
            c: cols[i % 5],
        });
}
function starBurst(x, y) {
    for (let i = 0; i < 16; i++) {
        const a = (i / 16) * Math.PI * 2;
        spawn({
            type: "spark",
            x,
            y,
            vx: Math.cos(a) * 46,
            vy: Math.sin(a) * 46,
            life: 0.8,
            max: 0.8,
            c: i % 2 ? "#ffd166" : "#7ee0b5",
        });
    }
}
function floatText(x, y, text, color) {
    spawn({ type: "float", x, y, vx: 0, vy: -16, life: 1.6, max: 1.6, text, c: color });
}
function stepParts(dt) {
    for (let i = parts.length - 1; i >= 0; i--) {
        const p = parts[i];
        p.life -= dt;
        if (p.life <= 0) {
            parts.splice(i, 1);
            continue;
        }
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        if (p.type === "confetti") {
            p.vy += 160 * dt;
            p.vx *= 0.985;
        }
        if (p.type === "steam") p.vx = Math.sin(p.life * 6 + p.x) * 3;
        if (p.type === "mote") {
            p.vx = Math.sin(p.life * 1.3 + p.seed) * 2.5;
            p.vy = Math.cos(p.life * 0.9 + p.seed) * 1.5;
        }
        if (p.type === "drop" || p.type === "crumb") p.vy += 60 * dt;
        if (p.type === "paper") p.vx *= 0.9;
    }
}
function drawParts(c) {
    for (const p of parts) {
        if (p.type === "float") continue;
        c.globalAlpha = Math.min(1, (p.life / p.max) * 2);
        const x = Math.round(p.x),
            y = Math.round(p.y);
        if (p.type === "confetti") {
            c.fillStyle = p.c;
            c.fillRect(x, y, 2, 1 + (Math.round(p.life * 10) % 2));
        } else if (p.type === "steam") {
            c.fillStyle = "#ffffff";
            c.globalAlpha *= 0.35;
            c.fillRect(x, y, 1, 1);
        } else if (p.type === "spark") {
            c.fillStyle = p.c;
            c.fillRect(x, y, 1, 1);
        } else if (p.type === "zz") drawIcon(c, "z", x, y);
        else if (p.type === "icon") drawIcon(c, p.name, x, y);
        else if (p.type === "mote") {
            c.globalAlpha = 0.55 * Math.sin((Math.PI * p.life) / p.max);
            c.fillStyle = "#fff6d0";
            c.fillRect(x, y, 1, 1);
        } else if (p.type === "drop") {
            c.fillStyle = "#8fd3ff";
            c.fillRect(x, y, 1, 2);
        } else if (p.type === "crumb") {
            c.fillStyle = "#d9a85c";
            c.fillRect(x, y, 1, 1);
        } else if (p.type === "paper") {
            c.fillStyle = "#f4f6f8";
            c.fillRect(x, y, 5, 3);
            c.fillStyle = "#c9ccd6";
            c.fillRect(x + 1, y + 1, 3, 1);
        } else if (p.type === "knock") {
            c.fillStyle = "#fffaf0";
            const k = 1 + Math.round((1 - p.life / p.max) * 3);
            c.fillRect(x - 3 - k, y, 2, 1);
            c.fillRect(x + 2 + k, y, 2, 1);
            c.fillRect(x, y - 3 - k, 1, 2);
        }
        c.globalAlpha = 1;
    }
}

// ================================================================ simulation
const HURT_TRIP_S = 8; // a sick-bay trip should land within ~8s, then limp the last stretch
function speedFor(w, remain = 0) {
    let m = 1;
    if (w.state === "working") m = 1.75;
    else if (w.state === "hurt") m = Math.min(1.6, Math.max(0.5, remain / (w.speed * HURT_TRIP_S)));
    else if (w.state === "locked" || w.state === "queued") m = 1.25;
    if (w.rewardRun) m *= 1.2;
    if (w.errand)
        m *= w.errandKind === "tea" || w.errandKind === "welcome" || w.errandKind === "comeback" ? 1.75 : 1.45;
    return w.speed * m;
}
const SEAT_MS = 260,
    SIT_PAUSE = 240,
    RISE_PAUSE = 160;
function moveAlong(w, dt, now) {
    if (w.holdUntil > now) return;
    const tgt = w.path[0];
    if (tgt.seat) {
        // sitting down or getting up: a short eased shuffle, not a skate at walking pace
        if (!w.legT) w.legFrom = { x: w.x, y: w.y };
        w.legT = Math.min(1, (w.legT || 0) + (dt * 1000) / SEAT_MS);
        const e = w.legT * w.legT * (3 - 2 * w.legT);
        w.x = w.legFrom.x + (tgt.x - w.legFrom.x) * e;
        w.y = w.legFrom.y + (tgt.y - w.legFrom.y) * e;
        if (w.legT >= 1) {
            w.path.shift();
            w.legT = 0;
            w.v = 0;
            if (w.path.length) {
                w.holdUntil = now + RISE_PAUSE;
                w.dir = dirTo(w, w.path[0].x, w.path[0].y);
            }
        }
        if (!w.path.length && w.spot) arrive(w, now);
        return;
    }
    const dx = tgt.x - w.x,
        dy = tgt.y - w.y,
        d = Math.hypot(dx, dy);
    let remain = d;
    for (let i = 1; i < w.path.length && !w.path[i].seat; i++)
        remain += Math.hypot(w.path[i].x - w.path[i - 1].x, w.path[i].y - w.path[i - 1].y);
    let target = speedFor(w, remain);
    if (remain < 14) target *= Math.max(0.4, remain / 14);
    w.v += (target - w.v) * Math.min(1, dt * 6);
    const sp = Math.max(4, w.v) * dt;
    if (d <= sp) {
        w.x = tgt.x;
        w.y = tgt.y;
        w.path.shift();
        w.walkDist += d;
        const nx = w.path[0];
        if (nx && nx.seat) {
            w.holdUntil = now + SIT_PAUSE;
            w.dir = nx.seat.face || w.dir;
            w.v = 0;
        } // stop and turn before sitting
    } else {
        w.x += (dx / d) * sp;
        w.y += (dy / d) * sp;
        w.walkDist += sp;
        const ax = Math.abs(dx),
            ay = Math.abs(dy);
        let nd = w.dir;
        if (ax > ay * 1.15) nd = dx < 0 ? "left" : "right";
        else if (ay > ax * 1.15) nd = dy < 0 ? "up" : "down";
        if (nd !== w.dir && now - (w.dirAt || 0) > 180) {
            w.dir = nd;
            w.dirAt = now;
        } // no flicker on diagonals or nudges
    }
    if (!w.path.length && w.spot) arrive(w, now);
}
function arrive(w, now) {
    w.v = 0;
    w.dir = w.spot.face || w.dir;
    w.arrivedAt = now;
    w.lookUntil = 0;
    if (w.state === "working") {
        w.carry = null;
        return;
    }
    if (w.state !== "resting") return;
    w.act = chooseAct(w, w.poi || {});
    w.item = itemFor(w);
    w.nextBit = now + rnd(1500, 4000);
    w.dwellUntil = now + dwellFor(w);
    w.dwellLen = w.dwellUntil - now;
    const m = mateOf(w);
    if (m && !m.path.length) {
        const d = now + (w.poi.tag === "pong" ? rnd(30000, 60000) : rnd(15000, 30000));
        w.dwellUntil = m.dwellUntil = d;
    }
    if (w.rewardRun) {
        w.rewardRun = false;
        w.emote = (ROAM_EMOTES[w.poi && w.poi.tag] || ["cup"])[0];
        w.emoteUntil = now + 2400;
    }
    if (w.poi && w.poi.tag === "frame") eotwPose(w, now);
    else if (w.poi && w.poi.tag === "post") collectPost(w, now);
    else if (w.errand && w.poi && (w.poi.tag === "peek" || w.poi.tag === "bedside")) handOver(w, now);
    else if (w.poi && w.poi.tag === "peek" && now - lastQuip > 5000 && Math.random() < 0.5)
        say(w, pick(menteeOf(w) ? QUIPS.mentorTip : QUIPS.peek, Math.random()), now);
}
function nearestWalker(w, r) {
    let best = null,
        bd = r;
    for (const o of workers.values())
        if (o !== w && o.path.length) {
            const d = Math.hypot(o.x - w.x, o.y - w.y);
            if (d < bd) {
                bd = d;
                best = o;
            }
        }
    return best;
}
function dirTo(w, x, y) {
    const dx = x - w.x,
        dy = y - w.y;
    return Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? "left" : "right") : dy < 0 ? "up" : "down";
}
function idle(w, dt, now, night) {
    const seated = !!(w.spot && w.spot.pose);
    if (w.state === "resting") {
        if (w.reliefWith && !(w.reliefUntil > now)) {
            w.reliefWith = null;
            w.reliefKind = null;
            w.reliefDesk = 0;
            if (selected === w.id) renderDossier();
        }
        if (w.sendOffFor && !(w.sendOffUntil > now)) {
            w.sendOffFor = null;
            if (selected === w.id) renderDossier();
        }
        if (w.poi && w.poi.pair && !mateOf(w) && now - w.arrivedAt > 12000) w.dwellUntil = Math.min(w.dwellUntil, now);
        if (w.poi && w.poi.tag === "peek" && !deskBusy(w.poi.desk) && !(w.reliefUntil > now))
            w.dwellUntil = Math.min(w.dwellUntil, now);
        if (
            w.poi &&
            w.poi.tag === "bedside" &&
            !(w.sendOffUntil > now) &&
            ![...workers.values()].some((o) => o.state === "hurt" && !o.path.length)
        )
            w.dwellUntil = Math.min(w.dwellUntil, now);
        if (now > w.dwellUntil && w.errand && fetchDone(w)) return;
        if (now > w.dwellUntil) {
            const p = choosePoi(w);
            if (p) {
                leaveSpot(w);
                sendTo(w, p);
            } else w.dwellUntil = now + 5000;
            return;
        }
        actTick(w, dt, now);
    }
    // looking around / people-watching (off-shift only, so the signed-out crowd and window-gazers stay facing forward)
    const paired = w.poi && w.poi.pair && mateOf(w);
    if (!seated && !paired && now > w.nextLook && w.state === "resting" && !(w.item || FOCUSED.has(w.act))) {
        w.nextLook = now + rnd(2500, 8000);
        const near = nearestWalker(w, 70);
        if (near && Math.random() < 0.55) {
            w.lookDir = dirTo(w, near.x, near.y);
            w.lookUntil = now + 1400;
        } else if (Math.random() < 0.45) {
            const opts = ["left", "right", "down", "up"].filter((d) => d !== (w.spot && w.spot.face));
            w.lookDir = pick(opts, Math.random());
            w.lookUntil = now + rnd(900, 2400);
        }
    }
    // at the desk: occasional thinking pause
    // a run past its usual length (real timings) wears on them: more frequent, edgier pauses and the odd mutter
    if (w.state === "working" && w.desk) w.tension = tension(progressOf(w.task));
    if (w.state === "working" && w.desk && cat.onDesk !== w.id && now > w.nextThink) {
        const k = w.tension;
        const pk = peekOf(w),
            peer = pk && pk.taken && workers.get(pk.taken);
        w.nextThink = now + rnd(9000, 22000) / (1 + k);
        w.thinkUntil = now + 1800;
        w.emote = pick(TENSE_EMOTES[k], Math.random());
        w.emoteUntil = now + 1800;
        if (peer && !peer.path.length && k >= 3) {
            // colleague looking over their shoulder: rubber-duck together
            w.glanceDir = "right";
            w.glanceUntil = now + 2000;
            peer.emote = pick(["bulb", "q"], Math.random());
            peer.emoteUntil = now + 2200;
            if (now > w.quipUntil + 8000 && now > peer.quipUntil + 4000 && Math.random() < 0.65) {
                if (Math.random() < 0.5) say(peer, pick(QUIPS.backseat, Math.random()), now);
                else say(w, pick(QUIPS.rubberduck, Math.random()), now);
            }
        } else if (k >= 2 && Math.random() < 0.45) {
            // well over: swivel round to check the wall clock
            w.glanceDir = WALL_CLOCK.x < w.x ? "left" : "right";
            w.glanceUntil = now + 1700;
            w.emote = "clock";
            if (now > w.quipUntil + 20000 && Math.random() < 0.35) say(w, pick(QUIPS.clockwatch, Math.random()), now);
        } else if (k && now > w.quipUntil + 20000 && Math.random() < 0.5)
            say(w, pick(QUIPS["overrun" + k], Math.random()), now);
    }
    // tapping the frozen call screen
    if (w.state === "locked" && w.line === 0 && !w.path.length) {
        if (now > w.nextKnock) {
            w.nextKnock = now + rnd(3200, 5200);
            w.knockAt = now;
            w.knocks = 0;
        }
        if (w.knocks < 3 && now - w.knockAt > w.knocks * 260) {
            w.knocks++;
            spawn({ type: "knock", x: CALL.x + 15, y: CALL.y + 11, vx: 0, vy: 0, life: 0.25, max: 0.25 });
        }
    }
    // sick: sweat
    if (w.state === "hurt" && Math.random() < dt * 0.7)
        spawn({
            type: "drop",
            x: w.x + (Math.random() < 0.5 ? -5 : 5),
            y: w.y - 44,
            vx: 0,
            vy: 4,
            life: 0.5,
            max: 0.5,
        });
    // ambient emotes and quips
    if (now > w.nextEmote) {
        w.nextEmote = now + rnd(7000, 22000);
        if (w.state === "resting" && w.poi) {
            const opts = ACT_EMOTES[w.act] || ROAM_EMOTES[w.poi.tag];
            if (opts) {
                w.emote = pick(opts, Math.random());
                w.emoteUntil = now + 2600;
            }
            const T = clock(),
                ph = phaseNow(),
                duskNow = !night && darkness(T) > 0.25;
            const aq =
                w.act === "eat" && w.poi.dine && cakeNow() && Math.random() < 0.7
                    ? QUIPS.cake
                    : w.act === "eat" && ph === "lunch" && Math.random() < 0.65
                      ? QUIPS.lunch
                      : ph === "morning" &&
                          (w.act === "fetch" || w.act === "write" || w.act === "meet") &&
                          Math.random() < 0.55
                        ? QUIPS.morning
                        : ph === "afternoon" && w.act === "sip" && Math.random() < 0.55
                          ? duskNow && Math.random() < 0.55
                              ? QUIPS.dusk
                              : QUIPS.afternoon
                          : QUIPS[w.act];
            if (aq && !paired && now - lastQuip > 7000 && Math.random() < 0.3) say(w, pick(aq, Math.random()), now);
            if (paired && w.poi.tag === "chat" && !w.inConvo && now - lastQuip > 6000 && Math.random() < 0.5) {
                const mood =
                    SEASON_CHAT && Math.random() < 0.35
                        ? SEASON_CHAT
                        : T.wx === "rain" && Math.random() < 0.3
                          ? "rain"
                          : duskNow && Math.random() < 0.4
                            ? "dusk"
                            : (ph === "lunch" || ph === "morning" || ph === "afternoon") && Math.random() < 0.45
                              ? ph
                              : moodNow();
                say(w, pick(mood && Math.random() < 0.45 ? QUIPS[mood] : QUIPS.chat, Math.random()), now);
            } else if (seated && !QUIPS[w.act] && now - lastQuip > 9000 && Math.random() < 0.25) {
                const mood =
                    SEASON_CHAT && Math.random() < 0.3
                        ? SEASON_CHAT
                        : ph === "morning" && w.poi.tag === "meeting"
                          ? "morning"
                          : duskNow
                            ? "dusk"
                            : moodNow();
                say(
                    w,
                    pick(night ? QUIPS.night : mood && Math.random() < 0.5 ? QUIPS[mood] : QUIPS.rest, Math.random()),
                    now,
                );
            }
        }
        if (w.state === "queued" && now - lastQuip > 6000 && Math.random() < 0.4) {
            const wf = waitingForOf(w.task, tasks);
            say(
                w,
                wf && Math.random() < 0.6
                    ? pick(
                          [`waiting on ${wf.nick}`, `after you, ${wf.nick}`, `${wf.nick}'s got the lock`],
                          Math.random(),
                      )
                    : pick(w.desk ? QUIPS.queue : QUIPS.queueWindow, Math.random()),
                now,
            );
        }
        if (w.state === "locked" && now - lastQuip > 6000 && Math.random() < 0.4)
            say(w, pick(QUIPS.locked, Math.random()), now);
        if (w.state === "hurt" && !w.path.length && now - lastQuip > 6000 && Math.random() < 0.4)
            say(w, pick(QUIPS.sick, Math.random()), now);
    }
    if (w.state === "working" && w.desk && Math.random() < dt * 4)
        spawn({
            type: "spark",
            x: w.x + (Math.random() - 0.5) * 14,
            y: w.y - 30,
            vx: (Math.random() - 0.5) * 20,
            vy: -14 - Math.random() * 10,
            life: 0.6,
            max: 0.6,
            c: Math.random() < 0.5 ? "#ffd166" : "#6ad1ff",
        });
    if (w.state === "resting" && w.act === "nap" && Math.random() < dt * 0.4)
        spawn({ type: "zz", x: w.x + 6, y: w.y - 44, vx: 4, vy: -8, life: 2.2, max: 2.2 });
}
function actTick(w, dt, now) {
    if (w.path.length || !w.act) return;
    if (now > w.nextBit) {
        w.bitAt = now;
        w.nextBit = now + (w.act === "eat" ? rnd(2600, 4200) : w.act === "read" ? rnd(4000, 7000) : rnd(4500, 8000));
        if (w.act === "eat" && Math.random() < 0.6)
            for (let i = 0; i < 2; i++)
                spawn({ type: "crumb", x: w.x + rnd(-3, 3), y: w.y - 22, vx: rnd(-6, 6), vy: 4, life: 0.6, max: 0.6 });
    }
    if (w.act === "water" && Math.random() < dt * 14) {
        const s = w.dir === "left" ? -1 : 1;
        spawn({ type: "drop", x: w.x + s * 13 + rnd(-1, 1), y: w.y - 20, vx: s * 3, vy: 10, life: 0.45, max: 0.45 });
    }
    if (w.act === "fetch" && w.poi && w.poi.tag === "coffee" && Math.random() < dt * 6)
        spawn({ type: "steam", x: 1006 + Math.random() * 3, y: 34, vx: 0, vy: -12, life: 1.4, max: 1.4 });
}
// chat partners take turns; the listener nods
// one scripted conversation at a time, so the room never fills with bubbles
const talks = {};
let convoPair = null;
function talkStep(now) {
    for (const w of workers.values()) {
        w.speaking = false;
        w.listening = false;
        w.inConvo = false;
    }
    let convoAlive = false;
    for (const p of POIS) {
        if (p.tag !== "chat" || p.face !== "right" || !p.taken) continue;
        const q = POIS.find((o) => o.pair === p.pair && o !== p);
        if (!q || !q.taken) continue;
        const a = workers.get(p.taken),
            b = workers.get(q.taken);
        if (!a || !b || a.path.length || b.path.length) continue;
        const key = a.id + "|" + b.id;
        let t = talks[p.pair];
        if (!t || t.key !== key)
            t = talks[p.pair] = {
                key,
                script: scriptFor(a, b),
                i: 0,
                speaker: pick([a.id, b.id], Math.random()),
                until: now + rnd(600, 1500),
            };
        const scripted = t.script && t.i < t.script.length && (convoPair === null || convoPair === p.pair);
        if (now > t.until) {
            if (scripted) {
                const [who, text, newsKey] = t.script[t.i++];
                convoPair = p.pair;
                t.speaker = who;
                t.until = now + 1400 + text.length * 55;
                say(who === a.id ? a : b, text, now);
                if (newsKey) told.set(newsKey, (told.get(newsKey) || 0) + 1);
            } else {
                t.speaker = t.speaker === a.id ? b.id : a.id;
                t.until = now + rnd(1400, 3800);
            }
        }
        if (convoPair === p.pair && (t.i < t.script.length || now < t.until)) {
            convoAlive = true;
            a.inConvo = b.inConvo = true;
        }
        const s = t.speaker === a.id ? a : b,
            l = s === a ? b : a;
        s.speaking = true;
        l.listening = true;
    }
    if (!convoAlive) convoPair = null;
}
// walkers keep to the right of anyone in their way, ease off when there is no room, and never get shoved
// into furniture or off a clear line to their next waypoint
function separate(dt) {
    const arr = [...workers.values()],
        now = tnow();
    for (const a of arr) {
        if (!a.path.length || seatLeg(a) || a.holdUntil > now || a.celebrateUntil > now || a.greetUntil > now) continue;
        const t = a.path[0];
        let fx = t.x - a.x,
            fy = t.y - a.y;
        const fl = Math.hypot(fx, fy);
        if (fl < 0.01) continue;
        fx /= fl;
        fy /= fl;
        let sx = 0,
            sy = 0,
            slow = 1;
        for (const b of arr) {
            if (a === b || seatLeg(b)) continue; // seated colleagues count as obstacles too
            const rx = b.x - a.x,
                ry = b.y - a.y,
                d = Math.hypot(rx, ry);
            if (d > 22 || d < 0.01) continue;
            const ahead = rx * fx + ry * fy,
                side = rx * -fy + ry * fx; // side > 0: b is on a's right
            if (ahead > -4 && Math.abs(side) < 12) {
                const dir = side > 1 ? -1 : 1; // step away from b; head-on, both keep right
                const k = (22 - d) / 22;
                sx += -fy * dir * k;
                sy += fx * dir * k;
                if (ahead > 0 && d < 14) slow = Math.min(slow, 0.45);
            } else if (d < 10) {
                sx -= ((rx / d) * (10 - d)) / 10;
                sy -= ((ry / d) * (10 - d)) / 10;
            }
        }
        if (!sx && !sy) continue;
        const m = 26 * dt,
            nx = a.x + sx * m,
            ny = a.y + sy * m * 0.7;
        if (bodyClear(nx, ny) && lineClear(nx, ny, t.x, t.y)) {
            a.x = nx;
            a.y = ny;
        }
        a.v *= slow < 1 ? 1 - (1 - slow) * Math.min(1, dt * 8) : 1;
    }
}
// a wave when two people pass
function greet(now) {
    const walkers = [...workers.values()].filter(
        (w) => w.path.length && w.state === "resting" && !(w.celebrateUntil > now) && !(w.greetUntil > now),
    );
    for (let i = 0; i < walkers.length; i++)
        for (let j = i + 1; j < walkers.length; j++) {
            const a = walkers[i],
                b = walkers[j];
            if (now - a.lastGreet < 25000 || now - b.lastGreet < 25000) continue;
            if (Math.hypot(a.x - b.x, a.y - b.y) > 24) continue;
            a.lastGreet = b.lastGreet = now;
            if (Math.random() < 0.55) {
                a.emote = b.emote = "wave";
                a.emoteUntil = b.emoteUntil = now + 1500;
            }
        }
}

// ================================================================ overtime errands (coffee run + shoulder peek)
// A run past its usual length (real progress from /api/tasks timings) gets a colleague bringing it a coffee;
// once it is way over (tier 3, >=250%), a colleague walks over to look over their shoulder and rubber-duck.
// The overtime that triggers it is real; who comes over and the exchange are ambient.
let nextCoffeeCheck = 0;
function overrunErrand(p, coffeeDone, peekDone) {
    const k = tension(p);
    if (k >= 3 && !peekDone) return "peek";
    if (k >= 1 && !coffeeDone) return "coffee";
    return null;
}
function coffeeRunner(target, ws) {
    // nearest idle off-shift colleague not tied up in a pair activity
    let best = null,
        bd = Infinity;
    for (const o of ws) {
        if (
            o === target ||
            o.state !== "resting" ||
            o.path.length ||
            o.errand ||
            o.act === "nap" ||
            (o.poi && o.poi.pair)
        )
            continue;
        const d = Math.hypot(o.x - target.x, o.y - target.y);
        if (d < bd) {
            bd = d;
            best = o;
        }
    }
    return best;
}
// A new starter at work gets shadowed by the old hand: the most experienced free off-shift colleague
// (most lifetime runs, nearest on a tie), never another new starter. The run is real; the buddy is ambient.
function mentorFor(target, ws, newRuns = 10) {
    let best = null,
        br = -1,
        bd = Infinity;
    for (const o of ws) {
        if (
            o === target ||
            o.state !== "resting" ||
            o.path.length ||
            o.errand ||
            o.act === "nap" ||
            (o.poi && o.poi.pair)
        )
            continue;
        const n = (o.task && o.task.run_count) || 0;
        if (n < newRuns) continue;
        const d = Math.hypot(o.x - target.x, o.y - target.y);
        if (n > br || (n === br && d < bd)) {
            best = o;
            br = n;
            bd = d;
        }
    }
    return best;
}
// Mentor of record: whoever went to shadow a new starter most often (earlier in the roster wins a tie).
// Tallied per mentee in localStorage and forgotten once they pass probation.
function tallyMentor(tally, menteeId, mentorId) {
    const row = { ...((tally || {})[menteeId] || {}) };
    row[mentorId] = (row[mentorId] || 0) + 1;
    return { ...(tally || {}), [menteeId]: row };
}
function mentorOfRecord(tally, menteeId, ws) {
    const row = (tally || {})[menteeId];
    if (!row) return null;
    let best = null,
        bn = 0;
    for (const o of ws) {
        if (!o || o.id === menteeId) continue;
        const n = row[o.id] || 0;
        if (n > bn) {
            best = o;
            bn = n;
        }
    }
    return best;
}
function mentorFree(o) {
    return (
        !!o &&
        o.state === "resting" &&
        !(o.path && o.path.length) &&
        !o.errand &&
        o.act !== "nap" &&
        !(o.poi && o.poi.pair)
    );
}
const MENTOR_KEY = "office-mentors";
let mentorTally = {};
try {
    mentorTally = JSON.parse(localStorage.getItem(MENTOR_KEY) || "{}") || {};
} catch (e) {
    mentorTally = {};
}
function saveMentors() {
    if (!DEMO)
        try {
            localStorage.setItem(MENTOR_KEY, JSON.stringify(mentorTally));
        } catch (e) {
            /* ignore */
        }
}
const runStamp = (t) => t.id + "#" + ((t.task && t.task.run_count) || 0);
function menteeOf(w) {
    // the new starter this colleague is shadowing right now, if any
    const t = w.mentee && w.poi && w.poi.tag === "peek" && !w.path.length && workers.get(w.poi.desk.owner);
    return t && t.state === "working" && w.mentee === runStamp(t) ? t : null;
}
const peekOf = (w) => w.desk && POIS.find((q) => q.tag === "peek" && q.desk === w.desk);
function sickErrandTarget(ws) {
    for (const w of ws) {
        if (w.state !== "hurt") continue;
        const stamp = (w.task && w.task.last_run) || "hurt";
        if (w.teaFor === stamp) continue;
        return { worker: w, stamp };
    }
    return null;
}
function coffeeRuns(now) {
    if (now < nextCoffeeCheck) return;
    nextCoffeeCheck = now + 2000;
    for (const w of workers.values()) {
        if (w.state === "working" && w.desk && !w.path.length && w.newStarter && w.mentorRun !== runStamp(w)) {
            const pk = peekOf(w),
                r = pk && !pk.taken && mentorFor(w, workers.values(), NEW_RUNS);
            if (r) {
                w.mentorRun = runStamp(w);
                mentorTally = tallyMentor(mentorTally, w.id, r.id);
                saveMentors();
                leaveSpot(r);
                r.errand = w.id;
                r.errandKind = "mentor";
                r.mentee = w.mentorRun;
                r.carry = null;
                sendTo(r, pk);
                say(r, pick(QUIPS.mentorGo, Math.random()), now);
                return; // one errand at a time
            }
        }
        const s = runStart.get(w.id);
        if (w.state !== "working" || !w.desk || w.path.length || !s) continue;
        const kind = overrunErrand(progressOf(w.task), w.coffeeFor === s, w.peekFor === s),
            peek = kind && peekOf(w);
        if (!kind || !peek || peek.taken) continue;
        const bar =
            kind === "coffee"
                ? POIS.find((q) => q.tag === "coffee" && !q.taken) || POIS.find((q) => q.tag === "cooler" && !q.taken)
                : peek;
        const r = bar && coffeeRunner(w, workers.values());
        if (!r) continue;
        const hadDrink = DRINKS.has(r.carry);
        leaveSpot(r);
        r.errand = w.id;
        r.errandKind = kind;
        if (kind === "peek") {
            w.peekFor = s;
            r.carry = null;
            sendTo(r, peek);
            say(r, pick(QUIPS.checkIn, Math.random()), now);
        } else {
            w.coffeeFor = s;
            if (hadDrink || DRINKS.has(r.carry)) {
                if (!DRINKS.has(r.carry)) r.carry = "mug";
                sendTo(r, peek);
            } else {
                r.carry = null;
                sendTo(r, bar);
            }
            say(r, pick(QUIPS.errand, Math.random()), now);
        }
        return; // one errand at a time
    }
    if (!BEDSIDE.taken && ![...workers.values()].some((o) => o.errandKind === "tea")) {
        const sick = sickErrandTarget(workers.values());
        if (!sick) return;
        const ready = [...workers.values()].filter(
            (o) => DRINKS.has(o.carry) || (o.poi && (o.poi.tag === "coffee" || o.poi.tag === "cooler")),
        );
        const bar =
            POIS.find((q) => q.tag === "coffee" && !q.taken) || POIS.find((q) => q.tag === "cooler" && !q.taken);
        const r = coffeeRunner(BEDSIDE, ready) || (bar && coffeeRunner(bar, workers.values()));
        if (!r) return;
        const brew = r.poi && KITCHEN[r.poi.tag] ? KITCHEN[r.poi.tag] : DRINKS.has(r.carry) ? r.carry : null;
        leaveSpot(r);
        r.errand = sick.worker.id;
        r.errandKind = "tea";
        sick.worker.teaFor = sick.stamp;
        if (brew) {
            r.carry = brew;
            sendTo(r, BEDSIDE);
        } else {
            r.carry = null;
            sendTo(r, bar);
        }
        say(r, pick(QUIPS.sickErrand, Math.random()), now);
    }
}
// back from the machine: carry the drink to the colleague's desk or the sick bay, or give up if they moved on
function fetchDone(w) {
    const t = workers.get(w.errand);
    if (w.errandKind === "tea") {
        if (!t || t.state !== "hurt" || BEDSIDE.taken || !w.poi || !KITCHEN[w.poi.tag]) {
            w.errand = null;
            w.errandKind = null;
            return false;
        }
        leaveSpot(w);
        sendTo(w, BEDSIDE);
        return true;
    }
    const peek = t && t.state === "working" && peekOf(t);
    if (!peek || peek.taken || !w.poi || !KITCHEN[w.poi.tag]) {
        w.errand = null;
        w.errandKind = null;
        return false;
    }
    leaveSpot(w);
    sendTo(w, peek);
    return true;
}
function handOver(w, now) {
    const t = workers.get(w.errand),
        kind = w.errandKind;
    w.errand = null;
    w.errandKind = null;
    if (kind === "welcome" || kind === "comeback") {
        if (!t || t.state !== "resting" || t.greetPeer !== w.id) {
            w.dwellUntil = now;
            return;
        }
        const deskNo = t.greetDesk || 0,
            hopMs = 2200;
        t.greetPeer = null;
        t.greetKind = null;
        t.greetDesk = 0;
        t.greetUntil = 0;
        t.dir = "right";
        w.dir = "left";
        t.lookUntil = 0;
        w.lookUntil = 0;
        t.celebrateUntil = w.celebrateUntil = now + hopMs;
        t.celebrateStart = w.celebrateStart = now;
        t.reliefWith = w.id;
        t.reliefKind = kind;
        t.reliefDesk = deskNo;
        t.reliefUntil = now + hopMs;
        w.reliefWith = t.id;
        w.reliefKind = kind;
        w.reliefDesk = deskNo;
        w.reliefUntil = now + 3200;
        w.dwellUntil = Math.max(w.dwellUntil || 0, now + 3200);
        w.dwellLen = w.dwellUntil - now;
        t.emote = "heart";
        t.emoteUntil = now + hopMs;
        w.emote = "star";
        w.emoteUntil = now + 3000;
        starBurst((t.x + w.x) / 2, t.y - 30);
        const proud = kind === "welcome" && w.proudUntil > now;
        w.proudUntil = proud ? now + 3200 : 0;
        say(w, pick(QUIPS[proud ? "proudHi" : kind === "welcome" ? "welcomeHi" : "comebackHi"], Math.random()), now);
        t.quip = pick(QUIPS[proud ? "proudThanks" : "milestoneThanks"], Math.random());
        t.quipStart = now + 700;
        t.quipUntil = now + 3700;
        if (selected) renderDossier();
        return;
    }
    if (kind === "tea") {
        if (!t || t.state !== "hurt") {
            w.dwellUntil = now;
            return;
        }
        w.carry = null;
        w.item = null;
        w.dwellUntil = now + rnd(26000, 36000);
        w.dwellLen = w.dwellUntil - now;
        w.emote = "heart";
        w.emoteUntil = now + 3200;
        say(w, pick(QUIPS.bedside, Math.random()), now);
        for (const p of workers.values()) if (p.state === "hurt") p.hasTea = true;
        t.emote = "cup";
        t.emoteUntil = now + 3400;
        t.quip = pick(QUIPS.sickThanks, Math.random());
        t.quipStart = now + 1400;
        t.quipUntil = now + 4400;
        if (selected) renderDossier();
        return;
    }
    if (!t || t.state !== "working") {
        w.dwellUntil = now;
        return;
    }
    t.nextThink = Math.max(t.nextThink, now + 5000);
    if (kind === "mentor") {
        // stays for the whole run; idle() sends them off when the desk frees
        w.dwellUntil = now + rnd(150000, 180000);
        w.dwellLen = w.dwellUntil - now;
        w.emote = "bulb";
        w.emoteUntil = now + 3400;
        say(w, pick(QUIPS.mentor, Math.random()), now);
        if (cat.onDesk !== t.id) {
            t.glanceDir = "right";
            t.glanceUntil = now + 2600;
            t.emote = "heart";
            t.emoteUntil = now + 2800;
            t.quip = pick(QUIPS.mentee, Math.random());
            t.quipStart = now + 1500;
            t.quipUntil = now + 4500;
        }
        if (selected) renderDossier();
        return;
    }
    if (kind === "peek") {
        w.dwellUntil = now + rnd(22000, 32000);
        w.dwellLen = w.dwellUntil - now;
        w.emote = pick(["q", "bulb"], Math.random());
        w.emoteUntil = now + 3400;
        say(w, pick(QUIPS.backseat, Math.random()), now);
        if (cat.onDesk !== t.id) {
            t.glanceDir = "right";
            t.glanceUntil = now + 2600;
            t.emote = "bulb";
            t.emoteUntil = now + 3200;
            t.quip = pick(QUIPS.rubberduck, Math.random());
            t.quipStart = now + 1500;
            t.quipUntil = now + 4500;
        }
        return;
    }
    w.carry = null;
    w.item = null;
    w.dwellUntil = now + rnd(5000, 8000);
    w.dwellLen = w.dwellUntil - now;
    say(w, pick(QUIPS.serve, Math.random()), now);
    t.emote = "cup";
    t.emoteUntil = now + 3200;
    t.quip = pick(QUIPS.thanks, Math.random());
    t.quipStart = now + 1400;
    t.quipUntil = now + 4200;
}
