// Office page. Main loop and boot. Loads last; every other office-*.js file must load before it.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// ================================================================ main loop
// A minute before the scheduler really starts an off-shift worker, they notice the clock (once per due time).
let bellCheck = 0;
function shiftBell(now) {
    if (now < bellCheck || !booted) return;
    bellCheck = now + 1000;
    const wall = Date.now();
    for (const w of workers.values()) {
        // overdue only once the Office itself has watched it stay late for LATE_WATCH (a waking laptop's runner catches up in 30s)
        const late = overdueBy(w.task, wall);
        w.lateSeen = late ? w.lateSeen || wall : 0;
        w.late = late && wall - w.lateSeen >= LATE_WATCH ? late : 0;
        if (w.state !== "resting" || w.errand || w.greetPeer || w.celebrateUntil > now) continue;
        if (w.late && now > (w.lateNag || 0) && now > w.quipUntil + 1500 && !w.path.length) {
            w.lateNag = now + rnd(50000, 80000);
            w.emote = "clock";
            w.emoteUntil = now + 3000;
            say(w, pick(QUIPS.overdue, Math.random()), now);
            const o = cheerer(w, [...workers.values()], 200);
            if (o)
                setTimeout(() => {
                    const t2 = last || tnow();
                    if (t2 >= o.quipUntil) {
                        o.emote = "clock";
                        o.emoteUntil = t2 + 2400;
                        say(o, pick(QUIPS.tapWatch, Math.random()), t2);
                    }
                }, 1800);
        }
        const at = dueAt(w.task, wall);
        // a few minutes out, cut a long sit short so they wander back towards the ops floor (choosePoi does the pull)
        if (
            at !== null &&
            w.pullFor !== at &&
            shiftPull(at - wall, roomAt(w.x, w.y)) < 1 &&
            !w.path.length &&
            !w.reliefWith &&
            !w.sendOffFor
        ) {
            w.pullFor = at;
            w.dwellUntil = Math.min(w.dwellUntil, now + rnd(1500, 5000));
        }
        if (at === null || at <= wall || at - wall > 60000 || w.bellFor === at) continue;
        w.bellFor = at;
        w.emote = "clock";
        w.emoteUntil = now + 3000;
        if (now > w.quipUntil + 1500) say(w, pick(QUIPS.shiftSoon, Math.random()), now);
    }
}
function simulate(dt, now) {
    sensorLights(dt, now);
    wetPrints(dt, clock().wx === "rain");
    const night = isNight();
    talkStep(now);
    for (const w of workers.values()) {
        if (w.celebrateUntil > now) continue;
        if (w.greetPeer) {
            const gp = workers.get(w.greetPeer);
            if (!gp || gp.state !== "resting" || gp.errand !== w.id || now > w.greetUntil) {
                w.greetPeer = null;
                w.greetKind = null;
                w.greetDesk = 0;
                w.greetUntil = 0;
            } else {
                w.dir = dirTo(w, gp.x, gp.y);
                continue;
            }
        }
        if (w.path.length) moveAlong(w, dt, now);
        else idle(w, dt, now, night);
    }
    separate(dt);
    greet(now);
    shiftBell(now);
    coffeeRuns(now);
    pongStep(dt, now);
    foosStep(dt, now);
    dartsStep(now);
    clockStep();
    postStep(now);
    catStep(dt, now);
    botStep(dt, now);
    ambient(dt, now);
    stepParts(dt);
}
let last = tnow(),
    booted = false;
function frame(raf) {
    const now = raf + clockSkew,
        dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (clock().h !== bgHour) {
        if (seasonNow() !== SEASON) {
            saveState();
            location.reload();
            return;
        } // a new season's decor needs a fresh layout
        buildBackground();
    }
    simulate(dt, now);
    render(now, counts);
    present(now);
    placeDossier();
    requestAnimationFrame(frame);
}
(async () => {
    try {
        // The workspace casts its own workers in .roosta/office-cast.yaml; those looks win.
        Object.assign(
            CAST,
            await fetch("/api/office/cast")
                .then((r) => r.json())
                .catch(() => ({})),
        );
        await preload();
        buildGrid();
        buildBackground();
        resize();
        new ResizeObserver(resize).observe(cabinet);
        addEventListener("resize", resize);
        new ResizeObserver(balanceRoster).observe(document.getElementById("roster").parentElement);
        const cp = randomFloor();
        cat.x = cp.x;
        cat.y = cp.y;
        const away = restoreState();
        // status changes while away are applied at the moment we left, then the gap plays out
        loadNews();
        setInterval(loadNews, 600000);
        loadQuiz();
        setInterval(loadQuiz, 600000);
        await poll();
        setInterval(poll, 5000);
        setInterval(updateHud, 30000);
        setInterval(saveState, 10000);
        if (away != null) catchUp(away);
        const warp = Math.min(600, Number(params.get("warp")) || 0);
        if (warp) catchUp(warp * 1000, 600e3);
        last = tnow();
        booted = true;
        if (params.has("names") && !showNames) toggleNames();
        if (eggs.length)
            document
                .querySelector(".keys span:nth-child(3)")
                .append(". Easter egg hunt: six eggs are hidden around the office today");
        const want = params.get("worker") || selected;
        selected = null;
        if (want && workers.has(want)) select(want);
        if (params.has("tv")) openCeefax(true); // ?tv opens the lounge TV page (for checks); ?tv=quiz jumps to Bamboozle once it loads
        if (params.get("tv") === "quiz")
            loadQuiz().then(() => {
                const k = ceefaxPages().findIndex((p) => p.quiz);
                if (k >= 0) {
                    ceefax.i = k;
                    renderCeefax();
                }
            });
        document.getElementById("loading").remove();
        requestAnimationFrame(frame);
    } catch (err) {
        document.getElementById("loading").textContent = "Failed to load: " + err.message;
        console.error(err);
    }
})();
