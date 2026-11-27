// Office page. Games room and lounge games: table tennis, foosball, darts and the console TV.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// ================================================================ ping-pong
const pong = {
    t: 0.5,
    dir: 1,
    pause: 0,
    speed: 0.8,
    swingL: 0,
    swingR: 0,
    active: false,
    rally: 0,
    serve: 0,
    score: [0, 0],
    pair: "",
    gameAt: 0,
};
// Table-tennis scoring (lifted into tests/test_office.py): first to eleven, win by two. side 0 = left player.
function pongPoint(score, side) {
    const s = score.slice();
    s[side]++;
    return { score: s, won: s[side] >= 11 && s[side] - s[1 - side] >= 2 ? side : -1 };
}
// The umpire's call for a score (lifted into tests/test_office.py): "deuce" when level from 10-10, "advantage" one
// ahead past it, "game point" when the leader needs one more; side is who holds it (-1 for none).
function pongCall(score) {
    const [a, b] = score,
        hi = Math.max(a, b),
        side = a > b ? 0 : 1;
    if (a >= 10 && b >= 10) return a === b ? { call: "deuce", side: -1 } : { call: "advantage", side };
    return hi >= 10 && a !== b ? { call: "game point", side } : { call: "", side: -1 };
}
// Award a point on the flip counter; a won game gets a cheer and both players head off soon after. Ambient.
function scorePoint(side, now) {
    const [pl, pr] = PONG_POIS.map((p) => p.taken && workers.get(p.taken));
    const r = pongPoint(pong.score, side),
        winner = side ? pr : pl,
        loser = side ? pl : pr,
        was = pongCall(pong.score);
    pong.score = r.score;
    if (r.won < 0) {
        // the umpire calls the big points; saving a game point gets its own moment
        const c = pongCall(r.score),
            who = c.side < 0 ? null : c.side ? pr : pl;
        if (c.call)
            floatText(
                PONG.x + (PONG.w >> 1),
                PONG.y - 14,
                c.call === "deuce" ? "DEUCE" : c.call.toUpperCase() + (who ? " " + whoOf(who) : ""),
                "#ffd166",
            );
        if (was.side === 1 - side && was.call !== "deuce" && winner) {
            winner.emote = "star";
            winner.emoteUntil = now + 2200;
            say(winner, pick(["saved it!", "not today!", "still alive!", "not over yet"], Math.random()), now);
        } else if (c.call === "game point" && who) {
            who.emote = "star";
            who.emoteUntil = now + 1800;
            say(who, pick(["one more", "serve it up", "here we go"], Math.random()), now);
        }
        return false;
    }
    floatText(
        PONG.x + (PONG.w >> 1),
        PONG.y - 14,
        "GAME! " + Math.max(...r.score) + "-" + Math.min(...r.score),
        "#ffd166",
    );
    starBurst(PONG.x + (PONG.w >> 1), PONG.y + 8);
    if (winner) {
        winner.emote = "star";
        winner.emoteUntil = now + 2600;
        say(winner, pick(["get in!", "game, set, tea", "winner stays on!", "you make the tea"], Math.random()), now);
    }
    if (loser) {
        loser.emote = "bang";
        loser.emoteUntil = now + 2600;
    }
    for (const w of [pl, pr]) if (w) w.dwellUntil = now + rnd(3000, 6000);
    pong.score = [0, 0];
    pong.gameAt = 0;
    return true;
}
function pongStep(dt, now) {
    const [pl, pr] = PONG_POIS.map((p) => p.taken && workers.get(p.taken));
    pong.active = !!(pl && pr && !pl.path.length && !pr.path.length);
    if (!pong.active) {
        pong.t = 0.5;
        pong.rally = 0;
        return;
    }
    const pair = pl.id + "|" + pr.id;
    if (pair !== pong.pair) {
        pong.pair = pair;
        pong.score = [0, 0];
        pong.gameAt = now;
    } // new pairing, fresh game
    // a game in progress keeps both players at the table (up to 4 minutes); a real run still calls them away
    if (pong.score[0] + pong.score[1] && now - pong.gameAt < 240000)
        for (const w of [pl, pr]) w.dwellUntil = Math.max(w.dwellUntil, now + 4000);
    if (pong.pause > 0) {
        pong.pause -= dt;
        if (pong.pause <= 0) {
            pong.t = pong.serve;
            pong.dir = pong.serve ? -1 : 1;
        }
        return;
    }
    const prevT = pong.t;
    pong.t += (pong.dir * dt) / pong.speed;
    const u = pong.dir > 0 ? pong.t : 1 - pong.t,
        pu = pong.dir > 0 ? prevT : 1 - prevT;
    if (pong.t >= 1 || pong.t <= 0) {
        const right = pong.t >= 1;
        pong.t = clamp(pong.t, 0, 1);
        if (pong.rally > 2 && Math.random() < 0.14) {
            const winner = right ? pl : pr;
            pong.pause = 1.5;
            pong.rally = 0;
            pong.serve = right ? 0 : 1;
            if (scorePoint(right ? 0 : 1, now)) return;
            winner.emote = "star";
            winner.emoteUntil = now + 1400;
            if (now - lastQuip > 3000) say(winner, pick(QUIPS.pong, Math.random()), now);
        } else {
            pong.dir *= -1;
            pong[right ? "swingR" : "swingL"] = now + 160;
            pong.rally++;
            pong.speed = rnd(0.6, 0.95);
        }
    }
}
function drawPong(now) {
    const { x, y, w, h } = PONG;
    ctx.fillStyle = "#1b1830";
    for (const lx of [x + 3, x + w - 5]) {
        ctx.fillRect(lx, y + h, 2, 6);
    }
    ctx.fillStyle = "#1a4d36";
    ctx.fillRect(x, y + h, w, 3);
    ctx.fillStyle = "#14141c";
    ctx.fillRect(x - 1, y - 1, w + 2, h + 2);
    ctx.fillStyle = "#2f8a5f";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = "#3a9c6c";
    ctx.fillRect(x, y, w, 2);
    ctx.fillStyle = "#e8f4ec";
    ctx.fillRect(x, y, w, 1);
    ctx.fillRect(x, y + h - 1, w, 1);
    ctx.fillRect(x, y, 1, h);
    ctx.fillRect(x + w - 1, y, 1, h);
    ctx.globalAlpha = 0.6;
    ctx.fillRect(x + 1, y + (h >> 1), w - 2, 1);
    ctx.globalAlpha = 1;
    // net
    const nx = x + (w >> 1);
    ctx.fillStyle = "#3a3a4a";
    ctx.fillRect(nx, y - 3, 1, h + 5);
    ctx.fillStyle = "#d8d8e4";
    ctx.fillRect(nx - 1, y - 3, 1, h + 4);
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(nx - 1, y - 4, 2, 2);
    ctx.fillRect(nx - 1, y + h, 2, 2);
    if (pong.active) {
        // flip score counter on the table's near edge; digits are drawn after the upscale in present()
        ctx.fillStyle = "#14141c";
        ctx.fillRect(nx - 10, y + h - 6, 21, 9);
        ctx.fillStyle = "#f4f1e8";
        ctx.fillRect(nx - 9, y + h - 5, 8, 7);
        ctx.fillRect(nx + 2, y + h - 5, 8, 7);
        ctx.fillStyle = "#c9c4bc";
        ctx.fillRect(nx - 9, y + h - 2, 8, 1);
        ctx.fillRect(nx + 2, y + h - 2, 8, 1);
    }
    // ball
    if (pong.active && pong.pause <= 0) {
        const u = pong.dir > 0 ? pong.t : 1 - pong.t;
        const hgt =
            u < 0.7
                ? lerp(9, 0, u / 0.7) + 8 * Math.sin((Math.PI * u) / 0.7)
                : lerp(0, 9, (u - 0.7) / 0.3) + 5 * Math.sin((Math.PI * (u - 0.7)) / 0.3);
        const bxp = Math.round(lerp(PONG.L, PONG.R, pong.t)),
            by = PONG.y + 13;
        if (bxp > x && bxp < x + w) {
            ctx.fillStyle = "#00000055";
            ctx.fillRect(bxp, by, 2, 1);
        }
        ctx.fillStyle = "#fffaf0";
        ctx.fillRect(bxp, Math.round(by - hgt - 2), 2, 2);
    } else if (!pong.active) {
        ctx.fillStyle = "#fffaf0";
        ctx.fillRect(x + 12, y + 8, 2, 2);
    }
}

// Click the table-tennis table: call a rally in progress (a long one gets jinxed and the point ends), or, when it's
// free, two idle colleagues come over for a game (lifted into tests/test_office.py). World-only.
const hitPong = (p) => p.x >= PONG.x && p.x <= PONG.x + PONG.w && p.y >= PONG.y - 4 && p.y <= PONG.y + PONG.h + 6;
function pongClickOutcome(active, rally, players, recruits) {
    return active ? (rally >= 3 ? "jinx" : "cheer") : players < 2 ? "alone" : recruits ? "game" : "warmup";
}
function clickPong(now) {
    const ws = [...workers.values()],
        cx = PONG.x + (PONG.w >> 1),
        cy = PONG.y - 6;
    const [pl, pr] = PONG_POIS.map((p) => p.taken && workers.get(p.taken));
    const react = (w, emote, lines) => {
        if (w && now >= w.quipUntil) {
            w.emote = emote;
            w.emoteUntil = now + 2200;
            say(w, pick(lines, Math.random()), now);
        }
    };
    const free = PONG_POIS.filter((p) => !p.taken),
        fans = [];
    if (!pong.active)
        for (const spot of free) {
            const f = coffeeRunner(
                spot,
                ws.filter((o) => !fans.some(([fan]) => fan === o)),
            );
            if (f) fans.push([f, spot]);
        }
    const out = pongClickOutcome(pong.active, pong.rally, PONG_POIS.length - free.length + fans.length, fans.length);
    if (out === "jinx") {
        const loser = pong.dir > 0 ? pr : pl,
            big = pongCall(pong.score).call; // the ball was heading their way
        floatText(cx, cy, "rally " + pong.rally + (big ? " at " + big : "") + "! *tok* ...out", "#fffaf0");
        pong.pause = 1.5;
        pong.serve = pong.dir > 0 ? 1 : 0;
        pong.rally = 0;
        if (scorePoint(pong.dir > 0 ? 0 : 1, now)) return;
        react(loser, "bang", ["you jinxed it!", "don't count out loud!", "that was going so well"]);
        return;
    }
    if (out === "cheer") {
        // the verdict reads the score
        const c = pongCall(pong.score),
            who = c.side < 0 ? null : c.side ? pr : pl;
        if (c.call === "deuce") {
            floatText(cx, cy, "deuce! anyone's game", "#fffaf0");
            react(pong.dir > 0 ? pl : pr, "bang", ["shh!", "not helping", "my hands are shaking"]);
            return;
        }
        if (who) {
            floatText(cx, cy, c.call + ", no pressure", "#fffaf0");
            react(who, "bang", ["don't say that!", "thanks a lot", "now I'm nervous"]);
            return;
        }
        floatText(cx, cy, "come on!", "#fffaf0");
        react(pong.dir > 0 ? pl : pr, "star", ["watch this", "no pressure then", "spin incoming"]);
        return;
    }
    if (out === "game") {
        for (const [f, spot] of fans) {
            leaveSpot(f);
            f.carry = null;
            f.item = null;
            sendTo(f, spot);
            f.emote = "star";
            f.emoteUntil = now + 2400;
        }
        if (fans[0])
            say(fans[0][0], pick(["fancy a game?", "first to eleven?", "loser makes the tea"], Math.random()), now);
        floatText(cx, cy, "*tok tok*", "#fffaf0");
        return;
    }
    if (out === "warmup") {
        floatText(cx, cy, "warming up", "#fffaf0");
        return;
    }
    floatText(cx, cy, "*tok... tok... tok*", "#c9c4bc");
    react(cheerer({ x: cx, y: PONG.y + 30 }, ws, 200), "q", [
        "no one free for a game",
        "everyone's busy",
        "I'll play you later",
    ]);
}

// Click the foosball table: spin the attacking player's rods mid-game (a spun goal never counts), or when it's free two idle colleagues come over. World-only.
const hitFoos = (p) => p.x >= FOOS.x && p.x <= FOOS.x + FOOS.w && p.y >= FOOS.y - 4 && p.y <= FOOS.y + FOOS.h + 6;
function clickFoos(now) {
    const ws = [...workers.values()],
        cx = FOOS.x + (FOOS.w >> 1),
        cy = FOOS.y - 6;
    const free = FOOS_POIS.filter((p) => !p.taken),
        fans = [];
    if (!foos.active)
        for (const spot of free) {
            const f = coffeeRunner(
                spot,
                ws.filter((o) => !fans.some(([fan]) => fan === o)),
            );
            if (f) fans.push([f, spot]);
        }
    const out = pongClickOutcome(foos.active, 0, FOOS_POIS.length - free.length + fans.length, fans.length);
    if (out === "cheer" && foos.pause <= 0 && foos.spin <= 0) {
        // spin the attacking player's rods: the ball flies at goal, and a spun goal never counts
        const [pl, pr] = FOOS_POIS.map((p) => workers.get(p.taken)),
            by = foos.vx > 0 ? 0 : 1,
            rival = by ? pl : pr;
        foos.spin = 1.4;
        foos.spinBy = by;
        foos.vx = by ? -80 : 80;
        foos.vy = (FOOS.y + FOOS.h / 2 - foos.y) * 1.6;
        floatText(cx, cy, "*whirrrr*", "#fffaf0");
        if (rival) {
            rival.emote = "bang";
            rival.emoteUntil = now + 2200;
            say(rival, pick(["no spinning!", "oi! that's spinning", "pub rules: no spinning"], Math.random()), now);
        }
        return;
    }
    if (out === "cheer") {
        floatText(cx, cy, "shoot!", "#fffaf0");
        return;
    }
    if (out === "game") {
        for (const [f, spot] of fans) {
            leaveSpot(f);
            f.carry = null;
            f.item = null;
            sendTo(f, spot);
            f.emote = "star";
            f.emoteUntil = now + 2400;
        }
        if (fans[0]) say(fans[0][0], pick(["foosball?", "first to five?", "no spinning, mind"], Math.random()), now);
        floatText(cx, cy, "*clack clack*", "#fffaf0");
        return;
    }
    if (out === "warmup") {
        floatText(cx, cy, "lining up", "#fffaf0");
        return;
    }
    floatText(cx, cy, "*clack*", "#c9c4bc");
    const c = cheerer({ x: cx, y: FOOS.y + 30 }, ws, 200);
    if (c && now >= c.quipUntil) {
        c.emote = "q";
        c.emoteUntil = now + 2200;
        say(c, pick(["no one free for a game", "everyone's busy", "fancy a game later?"], Math.random()), now);
    }
}

// Click an arcade cabinet to drop in a coin (world-only): whoever is playing gets an extra life and plays on, and a
// free cabinet lights its coin slot and tempts the nearest idle colleague over (lifted into tests/test_office.py).
const hitArcade = (p) => ARCADES.find((a) => p.x >= a.x && p.x <= a.x + 24 && p.y >= a.y && p.y <= a.y + 46) || null;
function arcadeCoin(played, walking, recruit) {
    return played ? "continue" : walking ? "walking" : recruit ? "recruit" : "credit";
}
function insertCoin(a, now) {
    const ws = [...workers.values()],
        spot = POIS.find((q) => q.arcade === a),
        cx = a.x + 12,
        cy = a.y - 4;
    const cur = spot && spot.taken && workers.get(spot.taken),
        f = !cur && spot ? coffeeRunner(spot, ws) : null;
    const out = arcadeCoin(!!(cur && !cur.path.length), !!cur, !!f);
    a.coinT = 0; // stamped on the next drawn frame
    if (out === "continue") {
        floatText(cx, cy, "*clink* CONTINUE?", "#ffd166");
        cur.dwellUntil = Math.max(cur.dwellUntil || 0, now + 20000);
        cur.emote = "star";
        cur.emoteUntil = now + 2200;
        if (now >= cur.quipUntil)
            say(cur, pick(["extra life! cheers {user}", "one more go", "I was on my last life!"], Math.random()), now);
        return;
    }
    a.credit = true;
    floatText(cx, cy, "*clink* CREDIT 1", "#ffd166");
    if (out === "recruit") {
        leaveSpot(f);
        f.carry = null;
        f.item = null;
        sendTo(f, spot);
        f.emote = "star";
        f.emoteUntil = now + 2400;
        say(f, pick(["ooh, a free go!", "is that a credit? mine", "high score's mine"], Math.random()), now);
        return;
    }
    if (out === "walking") return;
    const c = cheerer({ x: cx, y: a.y + 60 }, ws, 200);
    if (c && now >= c.quipUntil) {
        c.emote = "q";
        c.emoteUntil = now + 2200;
        say(c, pick(["I'll have that go later", "no one free for a go", "save me that credit"], Math.random()), now);
    }
}

// ================================================================ foosball and darts (games room, ambient)
const foos = {
    x: 0,
    y: 0,
    vx: 0,
    vy: 0,
    active: false,
    pause: 0,
    rods: [0, 0, 0, 0],
    score: [0, 0],
    pair: "",
    gameAt: 0,
    spin: 0,
    spinBy: 0,
};
// Foosball scoring (lifted into tests/test_office.py): pub rules, first to five, and a goal off a spun rod
// doesn't count. side 0 = left player (red, shooting right).
function foosGoal(score, side, spun) {
    if (spun) return { score: score.slice(), won: -1, void: true };
    const s = score.slice();
    s[side]++;
    return { score: s, won: s[side] >= 5 ? side : -1, void: false };
}
function foosStep(dt, now) {
    const [pl, pr] = FOOS_POIS.map((p) => p.taken && workers.get(p.taken));
    const was = foos.active;
    foos.active = !!(pl && pr && !pl.path.length && !pr.path.length);
    if (!foos.active) {
        foos.spin = 0;
        return;
    }
    const pair = pl.id + "|" + pr.id;
    if (pair !== foos.pair) {
        foos.pair = pair;
        foos.score = [0, 0];
        foos.gameAt = now;
    } // new pairing, fresh game
    // a game in progress keeps both players at the table (up to 3 minutes); a real run still calls them away
    if (foos.score[0] + foos.score[1] && now - foos.gameAt < 180000)
        for (const w of [pl, pr]) w.dwellUntil = Math.max(w.dwellUntil, now + 4000);
    if (foos.spin > 0) foos.spin -= dt;
    const L = FOOS.x + 4,
        R = FOOS.x + FOOS.w - 5,
        T = FOOS.y + 3,
        B = FOOS.y + FOOS.h - 4,
        mid = FOOS.y + FOOS.h / 2;
    if (!was || foos.pause > 0) {
        if (was) foos.pause -= dt;
        if (!was || foos.pause <= 0) {
            foos.x = FOOS.x + FOOS.w / 2;
            foos.y = mid;
            const a = rnd(-0.6, 0.6);
            foos.vx = Math.cos(a) * 46 * (Math.random() < 0.5 ? -1 : 1);
            foos.vy = Math.sin(a) * 46;
            foos.pause = 0;
        }
        return;
    }
    foos.x += foos.vx * dt;
    foos.y += foos.vy * dt;
    if (foos.y < T || foos.y > B) {
        foos.vy *= -1;
        foos.y = clamp(foos.y, T, B);
    }
    for (let i = 0; i < 4; i++)
        foos.rods[i] = clamp(foos.y - mid, -6, 6) * (i % 2 ? 0.8 : 1) + Math.sin(now / 90 + i) * 0.8;
    // a rod kicks the ball back now and then (never while it's being spun at goal); otherwise it reaches the goal mouth
    if (foos.spin <= 0)
        for (const rx of [FOOS.x + 12, FOOS.x + 23, FOOS.x + 30, FOOS.x + 41])
            if (Math.abs(foos.x - rx) < 1.2 && Math.random() < 0.35) {
                foos.vx *= -1.05;
                foos.vy += rnd(-20, 20);
            }
    if (foos.x < L || foos.x > R) {
        if (Math.abs(foos.y - mid) < 6) {
            const side = foos.x > R ? 0 : 1,
                scorer = side ? pr : pl,
                loser = side ? pl : pr,
                cx = FOOS.x + (FOOS.w >> 1);
            const r = foosGoal(foos.score, side, foos.spin > 0 && foos.spinBy === side);
            foos.pause = 1.2;
            foos.x = clamp(foos.x, L, R);
            foos.spin = 0;
            foos.score = r.score;
            if (r.void) {
                floatText(cx, FOOS.y - 14, "SPUN! no goal", "#ff8a7a");
                loser.emote = "bang";
                loser.emoteUntil = now + 2000;
                say(
                    loser,
                    pick(
                        ["doesn't count!", "spinning! no goal", "that's not foosball, that's a blender"],
                        Math.random(),
                    ),
                    now,
                );
            } else if (r.won >= 0) {
                floatText(cx, FOOS.y - 14, "GAME! " + r.score[side] + "-" + r.score[1 - side], "#ffd166");
                starBurst(cx, FOOS.y + 8);
                scorer.emote = "star";
                scorer.emoteUntil = now + 2600;
                say(
                    scorer,
                    pick(["get in!", "five! winner stays on", "and that's the game", "you're buying"], Math.random()),
                    now,
                );
                loser.emote = "bang";
                loser.emoteUntil = now + 2600;
                for (const w of [pl, pr]) w.dwellUntil = now + rnd(3000, 6000);
                foos.score = [0, 0];
                foos.gameAt = 0;
            } else {
                scorer.emote = "star";
                scorer.emoteUntil = now + 1400;
                if (now - lastQuip > 3000) say(scorer, pick(QUIPS.foos, Math.random()), now);
            }
        } else {
            foos.vx *= -1;
            foos.x = clamp(foos.x, L, R);
        }
    }
    foos.vx = clamp(foos.vx, -80, 80);
    foos.vy = clamp(foos.vy, -40, 40);
}
function drawFoos(now) {
    const { x, y, w, h } = FOOS,
        mid = y + (h >> 1);
    ctx.fillStyle = "#1b1410";
    for (const lx of [x + 2, x + w - 5]) ctx.fillRect(lx, y + h, 3, 6);
    ctx.fillStyle = "#3a2418";
    ctx.fillRect(x - 2, y - 2, w + 4, h + 4);
    ctx.fillStyle = "#6b4a32";
    ctx.fillRect(x - 2, y - 2, w + 4, 2);
    ctx.fillStyle = "#2a1a12";
    ctx.fillRect(x - 2, y + h + 2, w + 4, 3);
    ctx.fillStyle = "#2f8a4f";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = "#37995a";
    for (let i = 0; i < w; i += 8) ctx.fillRect(x + i, y, 4, h);
    ctx.fillStyle = "#e8f4ec88";
    ctx.fillRect(x + (w >> 1), y, 1, h);
    ctx.fillRect(x, y, w, 1);
    ctx.fillRect(x, y + h - 1, w, 1);
    ctx.fillStyle = "#0d0b16";
    ctx.fillRect(x - 2, mid - 5, 2, 10);
    ctx.fillRect(x + w, mid - 5, 2, 10);
    if (foos.active) {
        ctx.fillStyle = "#fffaf0";
        ctx.fillRect(Math.round(foos.x) - 1, Math.round(foos.y) - 1, 2, 2);
    }
    // bead scorers on the top rail, one per side: scored beads slide to the player's end, in their colour
    ctx.fillStyle = "#1b1410";
    ctx.fillRect(x + 1, y - 2, 18, 1);
    ctx.fillRect(x + w - 19, y - 2, 18, 1);
    for (let side = 0; side < 2; side++)
        for (let b = 0; b < 5; b++) {
            const won = foos.active && b < foos.score[side],
                bx = side
                    ? won
                        ? x + w - 3 - b * 3
                        : x + w - 18 + (4 - b) * 3
                    : won
                      ? x + 1 + b * 3
                      : x + 16 - (4 - b) * 3;
            ctx.fillStyle = won ? (side ? "#5b8ff9" : "#ff5a5a") : "#5a4432";
            ctx.fillRect(bx, y - 3, 2, 2);
            if (won) {
                ctx.fillStyle = "#fffaf0";
                ctx.fillRect(bx, y - 3, 1, 1);
            }
        }
    [12, 23, 30, 41].forEach((rx, i) => {
        if (foos.active && foos.spin > 0 && i % 2 === foos.spinBy) {
            // a spun rod: the men are a blur
            ctx.fillStyle = "#b8bcc8";
            ctx.fillRect(x + rx, y - 4, 1, h + 8);
            ctx.fillStyle = "#1b1830";
            ctx.fillRect(x + rx - 1, y - 6, 3, 2);
            ctx.fillRect(x + rx - 1, y + h + 4, 3, 2);
            ctx.fillStyle = (i === 0 || i === 2 ? "#d94848" : "#3b6fd9") + "99";
            const ph = ((now / 40) | 0) % 2;
            for (const my of i % 3 === 0 ? [mid] : [mid - 8, mid + 8]) ctx.fillRect(x + rx - 3 + ph, my - 1, 5, 2);
            return;
        }
        const off = Math.round(foos.active ? foos.rods[i] : 0);
        ctx.fillStyle = "#b8bcc8";
        ctx.fillRect(x + rx, y - 4, 1, h + 8);
        ctx.fillStyle = "#1b1830";
        ctx.fillRect(x + rx - 1, y - 6, 3, 2);
        ctx.fillRect(x + rx - 1, y + h + 4, 3, 2);
        ctx.fillStyle = i === 0 || i === 2 ? "#d94848" : "#3b6fd9";
        for (const my of i % 3 === 0 ? [mid] : [mid - 8, mid + 8])
            ctx.fillRect(x + rx - 1, clamp(my + off, y + 1, y + h - 4) - 1, 3, 3);
    });
}
// The user's own darts: click the board to throw. World-only - never touches the runner.
function dartScore(dx, dy) {
    const SEGS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5],
        d = Math.hypot(dx, dy);
    if (d <= 1) return 50;
    if (d <= 2) return 25;
    if (d > 9) return 0;
    const a = ((Math.atan2(dx, -dy) * 180) / Math.PI + 369) % 360; // clockwise from the top, 20 centred
    return SEGS[Math.floor(a / 18) % 20] * (d > 8 ? 2 : d > 4 && d <= 6 ? 3 : 1);
}
const playerDarts = { n: 0, total: 0, at: -1e9, best: 0, d: [0, 1, 2].map(() => ({ x: 0, y: 0, t: 0 })) };
try {
    const best = sessionStorage.getItem("office.dartsBest") ?? sessionStorage.getItem("office.robBest");
    playerDarts.best = Number(best) || 0;
} catch {
    /* storage blocked: best lasts until reload */
}
const hitDartboard = (p) => Math.hypot(p.x - DARTS.x, p.y - DARTS.y) < 14;
function throwDart(now) {
    if (playerDarts.n === 3) {
        playerDarts.n = 0;
        playerDarts.total = 0;
    }
    const g = () => Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random()) * 4.2;
    const dx = g(),
        dy = g(),
        s = dartScore(dx, dy),
        dart = playerDarts.d[playerDarts.n++];
    dart.x = Math.round(DARTS.x + clamp(dx, -13, 13));
    dart.y = Math.round(DARTS.y + clamp(dy, -13, 13));
    dart.t = 0; // flight clock starts on the next frame
    playerDarts.total += s;
    playerDarts.at = now;
    floatText(
        DARTS.x + (playerDarts.n - 2) * 32,
        DARTS.y - 18,
        s ? String(s) : "miss",
        s >= 50 || (s > 20 && s % 3 === 0) ? "#ffd166" : s ? "#f4f6f8" : "#ff8a8a",
    );
    if (playerDarts.n < 3) return;
    const t = playerDarts.total,
        fan = [...workers.values()].find((w) => w.act === "darts" && !w.path.length);
    const line =
        t >= 180
            ? "ONE HUNDRED AND EIGHTY!"
            : t >= 100
              ? `ton-plus, ${USER_NAME}!`
              : t >= 60
                ? "tidy arrows"
                : t
                  ? `unlucky, ${USER_NAME}`
                  : "mind the wallpaper!";
    const ch = dartsChallenge.by && workers.get(dartsChallenge.by),
        live = ch && ch.act === "darts" && !ch.path.length && now < dartsChallenge.until;
    if (live) settleChallenge(ch, t, now);
    else if (fan) {
        say(fan, line, now);
        fan.emote = t >= 100 ? "star" : "q";
        fan.emoteUntil = now + 1800;
    } else floatText(DARTS.x, DARTS.y - 30, USER_NAME + ": " + t, "#7ee0b5");
    if (t > playerDarts.best) {
        // chalked on the scoreboard
        if (playerDarts.best) {
            floatText(SCORE.x + 19, SCORE.y - 26, "NEW BEST!", "#ffd166");
            starBurst(SCORE.x + 19, SCORE.y + 15);
        }
        playerDarts.best = t;
        try {
            sessionStorage.setItem("office.dartsBest", String(t));
        } catch {
            /* ignore */
        }
    }
}
// A colleague who has settled in at the board throws down a challenge: beat the user's chalked best (or 60 before
// they have one) with the next three darts inside a minute. World-only; challengeVerdict is lifted into tests/test_office.py.
const dartsChallenge = { by: null, target: 0, until: 0 };
function challengeVerdict(total, target) {
    return total > target ? "beat" : total === target ? "tie" : "lost";
}
function dartsStep(now) {
    if (dartsChallenge.by && now >= dartsChallenge.until) dartsChallenge.by = null;
    if (dartsChallenge.by || !booted) return; // never during ?warp or away catch-up
    for (const w of workers.values()) {
        if (
            w.act !== "darts" ||
            w.path.length ||
            w.challenged === w.arrivedAt ||
            now - w.arrivedAt < 5000 ||
            now < w.quipUntil
        )
            continue;
        w.challenged = w.arrivedAt; // once per visit to the board
        if (hash(w.id + w.arrivedAt) > 0.5) continue;
        const target = playerDarts.best || 60;
        Object.assign(dartsChallenge, { by: w.id, target, until: now + 60000 });
        w.emote = "bang";
        w.emoteUntil = now + 2400;
        say(
            w,
            pick(
                playerDarts.best
                    ? [
                          `bet you can't beat ${target}, {user}`,
                          `${target}? beat that, {user}`,
                          "go on, {user}, best of three",
                      ]
                    : ["fancy a game, {user}? first to 60", "{user}! three darts, beat 60"],
                Math.random(),
            ),
            now,
        );
        floatText(DARTS.x - 24, DARTS.y + 22, "CHALLENGE: beat " + target, "#ffd166");
        return;
    }
}
function settleChallenge(ch, t, now) {
    const v = challengeVerdict(t, dartsChallenge.target);
    dartsChallenge.by = null;
    ch.emote = v === "beat" ? "star" : v === "tie" ? "q" : "heart";
    ch.emoteUntil = now + 2400;
    say(
        ch,
        pick(
            v === "beat"
                ? ["fine, you win. rematch?", "lucky arrows, {user}!", "I'll get you next time"]
                : v === "tie"
                  ? ["a draw! sudden death?", "dead level!"]
                  : [`${t}? told you, {user}`, "the board's safe from you", "better luck next time!"],
            Math.random(),
        ),
        now,
    );
    if (v === "beat") starBurst(DARTS.x, DARTS.y);
}
function drawPlayerDarts(now) {
    if (tnow() - playerDarts.at > 20000) return;
    for (let i = 0; i < playerDarts.n; i++) {
        const d = playerDarts.d[i];
        if (!d.t) d.t = now;
        const u = REDUCED ? 1 : clamp((now - d.t) / 200, 0, 1);
        const x = Math.round(lerp(DARTS.x, d.x, u)),
            y = Math.round(lerp(DARTS.y + 130, d.y, u));
        ctx.fillStyle = "#1b1830";
        ctx.fillRect(x, y, 1, 3);
        ctx.fillStyle = "#7ee0b5";
        ctx.fillRect(x - 1, y + 3, 3, 1);
    }
}
function drawDarts(now) {
    drawPlayerDarts(now);
    let thrown = 0;
    for (const w of workers.values()) {
        if (w.act !== "darts" || w.path.length) continue;
        const k = Math.floor((now - w.arrivedAt) / 1300),
            n = k % 5;
        thrown = Math.floor(k / 5) * 3 + Math.min(n, 3);
        for (let i = 0; i < Math.min(n, 3); i++) {
            const a = hash(w.id + k + i) * Math.PI * 2,
                r = hash(w.id + i + "r" + Math.floor(k / 5)) * 10;
            const dx = Math.round(DARTS.x + Math.cos(a) * r),
                dy = Math.round(DARTS.y + Math.sin(a) * r);
            ctx.fillStyle = "#1b1830";
            ctx.fillRect(dx, dy, 1, 2);
            ctx.fillStyle = ["#ffd166", "#7ee0b5", "#ff6b9a"][i];
            ctx.fillRect(dx - 1, dy + 2, 3, 1);
        }
    }
    ctx.fillStyle = "#e8e4d8"; // chalk tally on the scoreboard
    const rows = playerDarts.best ? 1 : 2; // the user's best takes the bottom row once they have one
    for (let i = 0; i < Math.min(thrown, rows * 10); i++) {
        const gx = 1182 + (i % 10) * 3 + Math.floor((i % 10) / 5) * 2,
            gy = 384 + Math.floor(i / 10) * 10;
        ctx.fillRect(gx, gy, 1, 6);
    }
}
function drawSink(x, y) {
    ctx.fillStyle = "#3a3f4a";
    ctx.fillRect(x - 11, y, 22, 7);
    ctx.fillStyle = "#9aa3b2";
    ctx.fillRect(x - 10, y + 1, 20, 5);
    ctx.fillStyle = "#c9d0dc";
    ctx.fillRect(x - 10, y + 1, 20, 1);
    ctx.fillStyle = "#b8bcc8";
    ctx.fillRect(x, y - 7, 1, 7);
    ctx.fillRect(x - 3, y - 7, 4, 1);
    ctx.fillRect(x - 3, y - 6, 1, 2);
    const washer = [...workers.values()].find((w) => w.act === "wash" && !w.path.length);
    if (washer) {
        const t = tnow();
        ctx.fillStyle = "#9fd8ff";
        ctx.fillRect(x - 3, y - 4 + (Math.floor(t / 90) % 3), 1, 2);
        ctx.fillStyle = "#f4fbff";
        for (let i = 0; i < 4; i++) ctx.fillRect(x - 8 + i * 4 + Math.round(Math.sin(t / 300 + i)), y + 2, 2, 1);
    }
}
function drawIslandTop() {
    const fx = ISLAND.x + 48,
        fy = ISLAND.y + 6; // fruit bowl
    pxEllipse(ctx, fx, fy + 2, 7, 2, "#f4f6f8");
    pxEllipse(ctx, fx, fy + 2, 6, 1, "#d4d8e0");
    ctx.fillStyle = "#e85d5d";
    ctx.fillRect(fx - 4, fy - 1, 3, 3);
    ctx.fillStyle = "#ffd166";
    ctx.fillRect(fx - 1, fy - 2, 4, 3);
    ctx.fillStyle = "#7ee0b5";
    ctx.fillRect(fx + 3, fy, 3, 2);
    for (const p of POIS) {
        if (!p.bar || !p.taken) continue;
        const w = workers.get(p.taken);
        if (!w || w.path.length || (w.act !== "eat" && w.act !== "sip")) continue;
        const drk =
            w.carry && DRINKS.has(w.carry)
                ? w.carry
                : w.act === "sip"
                  ? "mug"
                  : hash(w.id + "drk") > 0.4
                    ? "mug"
                    : "water";
        if (w.act === "eat") {
            const left = clamp(1 - (tnow() - w.arrivedAt) / (w.dwellLen || 30000), 0, 1);
            pxEllipse(ctx, p.x, ISLAND.y + 12, 4, 1, "#f4f6f8");
            if (left > 0.1) {
                ctx.fillStyle = hash(w.id + "food") > 0.5 ? "#e8c27a" : "#c8463c";
                ctx.fillRect(p.x - 2, ISLAND.y + 11, Math.max(1, Math.round(4 * left)), 2);
            }
            drawItem(drk, p.x + 6, ISLAND.y + 9, w, tnow());
        } else drawItem(drk, p.x - 1, ISLAND.y + 10, w, tnow());
    }
}
function drawDiningTop() {
    // plates at lunch or with food; a cuppa or water when taking a break outside lunch; Friday cake in the middle
    const cake = cakeNow();
    if (cake === "slice") {
        pxEllipse(ctx, DINING.x + 48, DINING.y + 12, 9, 3, "#f4f6f8");
        blit(ctx, "pieSlice", DINING.x + 41, DINING.y + 5);
    } else if (cake) blit(ctx, cake === "whole" ? "pieWhole" : "pieCut", DINING.x + 35, DINING.y + 1);
    else {
        ctx.fillStyle = "#1b1830";
        ctx.fillRect(DINING.x + 46, DINING.y + 3, 5, 7);
        ctx.fillStyle = "#9fd8ff";
        ctx.fillRect(DINING.x + 47, DINING.y + 5, 3, 4);
    }
    for (const p of POIS) {
        if (!p.dine || !p.taken) continue;
        const w = workers.get(p.taken);
        if (!w || w.path.length || (w.act !== "eat" && w.act !== "sip")) continue;
        const py = p.face === "down" ? DINING.y + 5 : DINING.y + 12,
            drk =
                w.carry && DRINKS.has(w.carry)
                    ? w.carry
                    : w.act === "sip"
                      ? "mug"
                      : hash(w.id + "drk") > 0.4
                        ? "mug"
                        : "water";
        if (w.act === "eat") {
            const left = clamp(1 - (tnow() - w.arrivedAt) / (w.dwellLen || 30000), 0, 1);
            pxEllipse(ctx, p.x, py, 4, 1, "#f4f6f8");
            if (left > 0.1) {
                ctx.fillStyle = hash(w.id + "food") > 0.5 ? "#e8c27a" : "#c8463c";
                ctx.fillRect(p.x - 2, py - 1, Math.max(1, Math.round(4 * left)), 2);
            }
            drawItem(drk, p.x + 7, py - 3, w, tnow());
        } else drawItem(drk, p.x - 1, py - 2, w, tnow());
    }
}
function drawCoffeeTableTop() {
    ctx.fillStyle = "#c9e3ff";
    ctx.fillRect(478, 522, 9, 6);
    ctx.fillStyle = "#e85d5d";
    ctx.fillRect(479, 523, 7, 2); // magazine
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(500, 524, 7, 2);
    ctx.fillStyle = "#d94848";
    ctx.fillRect(501, 524, 1, 1); // remote
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(515, 521, 5, 5);
    ctx.fillStyle = "#f4ecff";
    ctx.fillRect(516, 522, 3, 3); // mug
}

// ================================================================ games room den: console TV
// Attract-mode demos on a rotation, each opening with a burst of static and a title card. Ambient only.
const GAME_MS = 18000,
    STATIC_MS = 320,
    TITLE_MS = 2600;
const TET_STACK = [2, 3, 1, 4, 3, 2, 1, 3],
    TET_COL = ["#e84040", "#40c0e8", "#f0d030", "#40d060", "#a050e0", "#f08a30", "#4060e8"];
const MM_GRAIN = [
    [5, 2],
    [30, 4],
    [18, 9],
    [40, 10],
    [8, 16],
    [26, 17],
    [36, 23],
    [12, 24],
];
const CONSOLE_GAMES = [
    {
        name: "Sonic",
        title: ["SONIC", "THE HEDGEHOG"],
        col: "#ffd84a",
        quips: ["Green Hill Zone!", "save my rings!", "gotta go fast!"],
        draw: (R, t) => {
            R("#2a64d8", 0, 0, 48, 9);
            R("#4a86ec", 0, 9, 48, 4);
            R("#78aef4", 0, 13, 48, 2);
            for (let i = 0; i < 2; i++) {
                const x = ((((i * 32 - Math.floor(t / 120)) % 64) + 64) % 64) - 8;
                R("#ffffff", x, 3 + i * 2, 7, 2);
                R("#ffffff", x + 2, 2 + i * 2, 3, 1);
            }
            R("#1f7fd0", 0, 15, 48, 2);
            for (let i = 0; i < 4; i++) R("#cfe8ff", (((i * 13 - Math.floor(t / 60)) % 48) + 48) % 48, 15, 2, 1);
            const hill = t / 90;
            for (let x = 0; x < 48; x++) {
                const h = 3 + Math.round(2 * Math.sin((x + hill) / 4));
                R("#1f8f3a", x, 19 - h, 1, h);
                R("#38b04a", x, 19 - h, 1, 1);
            }
            const g = Math.floor(t / 25) % 8;
            R("#58d040", 0, 19, 48, 1);
            R("#2f9a2a", 0, 20, 48, 1);
            for (let cy = 0; cy < 2; cy++)
                for (let cx = 0; cx < 14; cx++) R((cx + cy) % 2 ? "#8e4318" : "#c46a28", cx * 4 - g, 21 + cy * 3, 4, 3);
            for (let i = 0; i < 3; i++) {
                const x = ((((i * 16 + 40 - Math.floor(t / 25)) % 56) + 56) % 56) - 4,
                    y = 13 + (i % 2) * 2;
                if (x >= 15 && x <= 22) {
                    R("#ffffff", x + 1, y - 1, 1, 1);
                    R("#ffffff", x + 3, y + 1, 1, 1);
                    continue;
                } // collected
                R("#ffd84a", x, y, 3, 3);
                R("#b07a10", x + 1, y + 1, 1, 1);
            }
            const f = Math.floor(t / 80) % 2,
                x0 = 17,
                y0 = 11;
            R("#1238a8", x0 - 3, y0 + 1, 3, 2);
            R("#1238a8", x0 - 2, y0 + 3, 2, 2);
            R("#1a4ad8", x0, y0, 6, 5);
            R("#1a4ad8", x0 + 1, y0 + 5, 4, 2);
            R("#f0c090", x0 + 4, y0 + 3, 3, 2);
            R("#f0c090", x0 + 2, y0 + 5, 2, 1);
            R("#ffffff", x0 + 3, y0 + 1, 2, 2);
            R("#000000", x0 + 4, y0 + 1, 1, 2);
            R("#000000", x0 + 6, y0 + 3, 1, 1);
            R("#e02020", x0 - 1 + f * 3, y0 + 7, 3, 1);
            R("#a01010", x0 + 2 - f * 3, y0 + 7, 3, 1);
        },
    },
    {
        name: "Micro Machines",
        title: ["MICRO", "MACHINES"],
        col: "#ff5050",
        quips: ["dibs on the red car!", "mind the cereal bowl!", "kitchen table track!"],
        draw: (R, t) => {
            R("#b8803f", 0, 0, 48, 27);
            for (const y of [6, 13, 20]) R("#9a6634", 0, y, 48, 1);
            for (const [x, y] of MM_GRAIN) R("#a87436", x, y, 3, 1);
            for (let i = 0; i < 28; i++) {
                const a = (i / 28) * Math.PI * 2;
                R("#f0b040", Math.round(24 + Math.cos(a) * 21), Math.round(13 + Math.sin(a) * 11), 2, 1);
            }
            for (let i = 0; i < 14; i++) {
                const a = (i / 14) * Math.PI * 2;
                R("#f0b040", Math.round(23 + Math.cos(a) * 10), Math.round(13 + Math.sin(a) * 4), 2, 1);
            }
            R("#e8eef2", 19, 12, 9, 3);
            R("#ffffff", 20, 11, 7, 1);
            R("#c9d2da", 20, 15, 7, 1);
            R("#fffaf0", 21, 12, 5, 2);
            R("#e8a838", 22, 12, 1, 1);
            R("#e8a838", 24, 13, 1, 1);
            for (let i = 0; i < 2; i++) {
                const a = t / 700 - i * (0.5 + 0.25 * Math.sin(t / 2100)),
                    x = Math.round(24 + Math.cos(a) * 16),
                    y = Math.round(13 + Math.sin(a) * 7.5);
                const wide = Math.abs(Math.sin(a)) > 0.6,
                    w = wide ? 3 : 2,
                    h = wide ? 2 : 3;
                R("#00000055", x, y + 1, w, h);
                R(i ? "#3050e8" : "#e83030", x - 1, y - 1, w, h);
                R("#ffffffaa", x - 1, y - 1, 1, 1);
            }
        },
    },
    {
        name: "Tetris",
        title: ["TETRIS"],
        col: "#40c0e8",
        quips: ["line piece, please!", "save the I-bar!", "who stacks like that?"],
        draw: (R, t) => {
            R("#0b0b1a", 0, 0, 48, 27);
            R("#2a2a52", 0, 0, 15, 27);
            R("#2a2a52", 33, 0, 15, 27);
            R("#9a9ab0", 15, 0, 1, 27);
            R("#9a9ab0", 32, 0, 1, 27);
            R("#9a9ab0", 15, 26, 18, 1);
            for (let c = 0; c < 8; c++)
                for (let r = 0; r < TET_STACK[c]; r++) R(TET_COL[(c * 3 + r) % 7], 16 + c * 2, 24 - r * 2, 2, 2);
            const k = Math.floor(t / 5200),
                col = TET_COL[k % 7],
                c0 = 1 + (k % 4);
            const land = Math.min(12 - TET_STACK[c0], 11 - TET_STACK[c0 + 1], 12 - TET_STACK[c0 + 2]);
            const r0 = Math.min(Math.floor((t % 5200) / 380), land);
            R(col, 16 + c0 * 2, r0 * 2, 6, 2);
            R(col, 18 + c0 * 2, r0 * 2 + 2, 2, 2);
            R("#0b0b1a", 36, 3, 9, 7);
            const nx = TET_COL[(k + 1) % 7];
            R(nx, 37, 5, 6, 2);
            R(nx, 39, 7, 2, 2);
            R("#0b0b1a", 2, 3, 11, 4);
            for (let i = 0; i < 4; i++) R("#f4f6f8", 3 + i * 2, 4, 1, 2);
        },
    },
    {
        name: "Pac-Man",
        title: ["PAC-MAN"],
        col: "#ffe000",
        quips: ["waka waka!", "watch out for Blinky", "power pellet time!"],
        draw: (R, t) => {
            const wc = "#2a3cf0",
                box = (x, y, w, h) => {
                    R(wc, x, y, w, 1);
                    R(wc, x, y + h - 1, w, 1);
                    R(wc, x, y, 1, h);
                    R(wc, x + w - 1, y, 1, h);
                };
            R("#000000", 0, 0, 48, 27);
            box(0, 0, 48, 27);
            box(5, 4, 11, 5);
            box(32, 4, 11, 5);
            box(5, 19, 11, 5);
            box(32, 19, 11, 5);
            box(19, 5, 10, 6);
            R("#ffb8de", 22, 5, 4, 1);
            for (let x = 3; x < 46; x += 4) R("#ffb8a0", x, 2, 1, 1);
            if (Math.floor(t / 250) % 2) {
                R("#ffb8a0", 2, 23, 2, 2);
                R("#ffb8a0", 44, 23, 2, 2);
            }
            const b = Math.floor(t / 300) % 2;
            R("#ffb8de", 21, 6 + b, 2, 3);
            R("#40e0e0", 25, 7 - b, 2, 3);
            const p = Math.floor(t / 45) % 80,
                dir = p < 40 ? 1 : -1,
                px = dir > 0 ? 3 + p : 43 - (p - 40);
            for (let x = 4; x < 45; x += 4) if (dir > 0 ? x > px + 2 : x < px) R("#ffb8a0", x, 14, 1, 1);
            R("#ffe000", px, 13, 3, 3);
            if (Math.floor(t / 120) % 2) R("#000000", dir > 0 ? px + 2 : px, 14, 1, 1);
            const gx = px - dir * 9;
            R("#ff2020", gx, 13, 3, 3);
            R("#ffffff", gx, 13, 1, 1);
            R("#ffffff", gx + 2, 13, 1, 1);
            R("#000000", gx + 1 + (Math.floor(t / 150) % 2), 15, 1, 1);
        },
    },
    {
        name: "Street Fighter II",
        title: ["STREET", "FIGHTER II"],
        col: "#ffd800",
        quips: ["HADOUKEN!", "dibs on Ryu!", "no button-mashing!"],
        draw: (R, t) => {
            R("#f08848", 0, 0, 48, 6);
            R("#f8a860", 0, 6, 48, 5);
            R("#f8c878", 0, 11, 48, 8);
            R("#6a2a2a", 10, 8, 28, 2);
            R("#6a2a2a", 14, 7, 20, 1);
            R("#4a1a1a", 14, 10, 2, 9);
            R("#4a1a1a", 32, 10, 2, 9);
            R("#a8703c", 0, 19, 48, 8);
            R("#8a5a2c", 0, 21, 48, 1);
            R("#8a5a2c", 0, 24, 48, 1);
            const lossL = Math.floor((t / 700) % 10),
                lossR = Math.floor((t / 500) % 14);
            R("#c01818", 3, 2, 18, 2);
            R("#ffd800", 3, 2, 18 - lossL, 2);
            R("#c01818", 27, 2, 18, 2);
            R("#ffd800", 27 + lossR, 2, 18 - lossR, 2);
            R("#ffd800", 22, 1, 4, 4);
            R("#c01818", 23, 2, 2, 2);
            const ph = t % 3200,
                fireball = ph < 1100;
            const fighter = (x, gi, hair, band, face, punch) => {
                const y0 = 9;
                R("#f0c090", x + 1, y0, 3, 3);
                R(hair, x + 1, y0, 3, 1);
                if (band) R(band, x + 1, y0 + 1, 3, 1);
                R(gi, x, y0 + 3, 5, 4);
                R("#1b1830", x, y0 + 6, 5, 1);
                R(gi, x, y0 + 7, 2, 3);
                R(gi, x + 3, y0 + 7, 2, 3);
                if (punch) {
                    R(gi, face > 0 ? x + 5 : x - 3, y0 + 4, 3, 1);
                    R("#f0c090", face > 0 ? x + 8 : x - 4, y0 + 4, 1, 1);
                } else R("#f0c090", face > 0 ? x + 4 : x, y0 + 5, 1, 1);
            };
            fighter(
                13 + Math.round(Math.sin(t / 400)),
                "#f4f6f8",
                "#3a2a1a",
                "#e02020",
                1,
                fireball || Math.floor(t / 300) % 7 === 2,
            );
            fighter(30 - Math.round(Math.sin(t / 330)), "#e02020", "#f0d030", null, -1, Math.floor(t / 300) % 9 === 5);
            if (fireball) {
                const hx = Math.round(20 + (ph / 1100) * 8);
                R("#60c8ff", hx, 12, 3, 3);
                R("#e8f8ff", hx + 1, 13, 1, 1);
            }
        },
    },
];
// Click the console TV or deck to swap cartridges; cycles on from the chosen game every GAME_MS (lifted into tests/test_office.py).
const consoleSwap = { at: null, idx: 0 };
function consoleSlot(now, swap = consoleSwap, n = CONSOLE_GAMES.length) {
    if (swap && swap.at != null) {
        const elapsed = swap.at === 0 ? 0 : Math.max(0, now - swap.at),
            k = Math.floor(elapsed / GAME_MS);
        return { idx: (((swap.idx + k) % n) + n) % n, t: elapsed - k * GAME_MS, manual: k === 0 };
    }
    const pos = Math.max(0, now),
        k = Math.floor(pos / GAME_MS);
    return { idx: ((k % n) + n) % n, t: pos - k * GAME_MS, manual: false };
}
const hitConsole = (p) => p.x >= DEN.x && p.x <= DEN.x + 64 && p.y >= DEN.tv.y && p.y <= 592;
function swapConsole(now) {
    const next = (consoleSlot(now).idx + 1) % CONSOLE_GAMES.length,
        g = CONSOLE_GAMES[next];
    consoleSwap.idx = next;
    consoleSwap.at = 0; // stamped on the next rendered frame so headless raf and tnow() cannot drift
    const players = [...workers.values()].filter((w) => w.act === "console" && !w.path.length);
    if (players.length) {
        const p0 = pick(players, Math.random());
        say(p0, pick(g.quips, Math.random()), now);
        p0.emote = "star";
        p0.emoteUntil = now + 2200;
        const p1 = players.find((w) => w !== p0);
        if (p1 && p1.quipUntil <= now) {
            p1.quip = pick(
                ["pass the pad!", "my turn next!", "player two ready!", "hey, I was winning!"],
                Math.random(),
            );
            p1.quipStart = now + 1300;
            p1.quipUntil = now + 4100;
        }
    }
    // on demand: call idle colleagues over until two are on the pads (counting anyone already heading there)
    const ws = [...workers.values()],
        coming = ws.filter((w) => w.state === "resting" && w.poi && w.poi.tag === "console").length,
        fans = [];
    for (let i = coming; i < 2; i++) {
        const spot = POIS.find((p) => p.tag === "console" && !p.taken),
            fan =
                spot &&
                coffeeRunner(
                    { x: DEN.x + 32, y: DEN.y + 60 },
                    ws.filter((o) => !fans.includes(o)),
                );
        if (!fan) break;
        fans.push(fan);
        leaveSpot(fan);
        fan.carry = null;
        fan.item = null;
        sendTo(fan, spot);
        fan.emote = "star";
        fan.emoteUntil = now + 2400;
        say(
            fan,
            pick(
                fans.length + coming > 1
                    ? ["player two!", "I'm on the blue pad", "budge up!"]
                    : ["ooh, " + g.name + "!", "who put " + g.name + " on?", "save me a beanbag!"],
                Math.random(),
            ),
            now,
        );
    }
}
// Click the kitchen coffee machine to brew a fresh pot; every fifth brew it wants descaling (lifted into tests/test_office.py).
const hitCoffee = (p) => p.x >= 996 && p.x <= 1019 && p.y >= 30 && p.y <= 66;
let coffeeBrews = 0;
function brewOutcome(n, atMachine, hasFan) {
    return n % 5 === 0 ? "descale" : atMachine ? "serve" : hasFan ? "tempt" : "alone";
}
function brewCoffee(now) {
    coffeeBrews++;
    const ws = [...workers.values()],
        spot = POIS.find((q) => q.tag === "coffee");
    const at = spot && spot.taken && workers.get(spot.taken),
        here = at && !at.path.length ? at : null;
    const fan = !here && spot && !spot.taken && coffeeRunner(spot, ws);
    const out = brewOutcome(coffeeBrews, !!here, !!fan);
    if (out === "descale") {
        for (let i = 0; i < 4; i++)
            spawn({
                type: "spark",
                x: 1007,
                y: 40,
                vx: rnd(-14, 14),
                vy: rnd(-18, 4),
                life: 0.5,
                max: 0.5,
                c: "#ff6b6b",
            });
        floatText(1007, 70, "DESCALE ME", "#ff6b6b");
        const near = here || cheerer({ x: 1007, y: 106 }, ws, 200);
        if (near && now >= near.quipUntil) {
            near.emote = "bang";
            near.emoteUntil = now + 2000;
            say(near, pick(["who's turn to descale?", "not again!", "it's the hard water"], Math.random()), now);
        }
        return;
    }
    for (let i = 0; i < 10; i++)
        spawn({
            type: "steam",
            x: 1004 + Math.random() * 6,
            y: 34 - Math.random() * 4,
            vx: 0,
            vy: -10 - Math.random() * 8,
            life: 1.6,
            max: 1.6,
        });
    floatText(1007, 70, "fresh pot", "#e8c39e");
    if (out === "serve") {
        here.emote = "heart";
        here.emoteUntil = now + 2200;
        say(here, pick(["ooh, fresh pot!", "perfect timing", "smells amazing"], Math.random()), now);
    } else if (out === "tempt") {
        leaveSpot(fan);
        fan.carry = null;
        fan.item = null;
        sendTo(fan, spot);
        fan.emote = "cup";
        fan.emoteUntil = now + 2400;
        say(fan, pick(["do I smell coffee?", "fresh pot? don't mind if I do", "coffee!"], Math.random()), now);
    }
}
// Click the fridge to open it: the light comes on, and every fourth look someone's yoghurt has gone (lifted into tests/test_office.py).
const hitFridge = (p) => p.x >= 1033 && p.x <= 1063 && p.y >= 36 && p.y <= 94;
let fridgeOpens = 0;
const fridgeDoor = { at: null, until: 0 };
function fridgeOutcome(n, atFridge, hasFan) {
    return n % 4 === 0 ? "yoghurt" : atFridge ? "share" : hasFan ? "tempt" : "alone";
}
function openFridge(now) {
    fridgeOpens++;
    fridgeDoor.at = null;
    fridgeDoor.until = 1500;
    const ws = [...workers.values()],
        spot = POIS.find((q) => q.tag === "fridge");
    const at = spot && spot.taken && workers.get(spot.taken),
        here = at && !at.path.length ? at : null;
    const fan = !here && spot && !spot.taken && coffeeRunner(spot, ws);
    const out = fridgeOutcome(fridgeOpens, !!here, !!fan);
    if (out === "yoghurt") {
        floatText(1048, 104, "who ate my yoghurt?", "#ffb3c7");
        const near = here || cheerer({ x: 1048, y: 108 }, ws, 220);
        if (near && now >= near.quipUntil) {
            near.emote = "bang";
            near.emoteUntil = now + 2200;
            say(
                near,
                pick(
                    ["it had my NAME on it", "not again!", "I'm putting a note up", "who's been at the yoghurt?"],
                    Math.random(),
                ),
                now,
            );
        }
    } else if (out === "share") {
        here.emote = "q";
        here.emoteUntil = now + 2200;
        say(here, pick(["shut the door, it's beeping", "just looking!", "any cheese left?"], Math.random()), now);
    } else if (out === "tempt") {
        leaveSpot(fan);
        fan.carry = null;
        fan.item = null;
        sendTo(fan, spot);
        fan.emote = "q";
        fan.emoteUntil = now + 2400;
        say(fan, pick(["ooh, what's in there?", "snack time?", "is that cheese?"], Math.random()), now);
    } else floatText(1048, 104, "*hmmm*", "#e8eef4");
}
function drawFridgeOpen(now) {
    // lit interior on the render clock, door swung open to the right
    if (!fridgeDoor.until) return;
    if (fridgeDoor.at === null) fridgeDoor.at = now;
    if (now - fridgeDoor.at > fridgeDoor.until) {
        fridgeDoor.until = 0;
        return;
    }
    const R = (c, x, y, w, h) => {
        ctx.fillStyle = c;
        ctx.fillRect(x, y, w, h);
    };
    R("#d8cfae", 1034, 55, 28, 38);
    R("#fff7dc", 1035, 56, 26, 36);
    for (const y of [66, 77, 88]) R("#cbbf98", 1035, y, 26, 1);
    R("#f4f4f0", 1037, 59, 4, 7);
    R("#5a9bd4", 1037, 59, 4, 2); // milk
    R("#ffb3c7", 1045, 62, 4, 4);
    R("#ffb3c7", 1050, 62, 4, 4); // yoghurts
    R("#f2c84b", 1054, 73, 5, 4);
    R("#7cc36b", 1038, 72, 8, 5);
    R("#d9534f", 1040, 84, 4, 4);
    R("#e6a04b", 1047, 83, 9, 5);
    R("#3b2f2f", 1063, 52, 5, 42);
    R("#9a8a88", 1064, 53, 3, 40);
    R("#c9bdb0", 1064, 70, 3, 1);
    ctx.save();
    ctx.globalAlpha = 0.22;
    pxEllipse(ctx, 1048, 102, 18, 5, "#fff2c0");
    ctx.restore();
}
// Click the lounge fire to poke it: sparks and a flare, embers briefly revive, a cold grate just clunks,
// and every fifth poke of a lit fire sends a puff of smoke into the room (lifted into tests/test_office.py).
const hitFire = (p) => p.x >= FP.x + 12 && p.x <= FP.x + 68 && p.y >= FP.y + 14 && p.y <= FP.y + 60;
let firePokes = 0;
const fireFlare = { at: null, until: 0 };
function pokeOutcome(n, st, atFire) {
    return !st ? "cold" : n % 5 === 0 ? "smoke" : st === 1 ? "revive" : atFire ? "careful" : "flare";
}
function pokeFire(now) {
    const st = fireNow(),
        ws = [...workers.values()],
        cx = FP.x + 40,
        cy = FP.y + 36;
    if (st) firePokes++;
    const here = POIS.filter((q) => q.tag === "fire" && q.taken)
        .map((q) => workers.get(q.taken))
        .find((w) => w && !w.path.length);
    const out = pokeOutcome(firePokes, st, !!here),
        near = here || cheerer({ x: cx, y: FP.y + 88 }, ws, 220);
    const react = (w, emote, lines) => {
        if (w && now >= w.quipUntil) {
            w.emote = emote;
            w.emoteUntil = now + 2200;
            say(w, pick(lines, Math.random()), now);
        }
    };
    if (out === "cold") {
        floatText(cx, FP.y + 64, "*clunk*", "#c9c4bc");
        react(near, "q", ["it's not lit", "fire's out till morning", "nothing in there but ash"]);
        return;
    }
    if (out === "smoke") {
        for (let i = 0; i < 14; i++)
            spawn({
                type: "steam",
                x: cx - 8 + Math.random() * 16,
                y: cy,
                vx: 0,
                vy: -6 - Math.random() * 8,
                life: 2,
                max: 2,
            });
        floatText(cx, FP.y + 64, "*cough*", "#c9c4bc");
        react(near, "bang", ["open a window!", "is the flue open?", "who poked it?"]);
        return;
    }
    fireFlare.at = null;
    fireFlare.until = st === 1 ? 2200 : 1400;
    for (let i = 0; i < 9; i++)
        spawn({
            type: "spark",
            x: cx + rnd(-12, 12),
            y: cy + 4,
            vx: rnd(-10, 10),
            vy: rnd(-30, -12),
            life: 0.7,
            max: 0.7,
            c: i % 3 ? "#ffa62b" : "#ffe27a",
        });
    floatText(cx, FP.y + 64, out === "revive" ? "*whoomph*" : "*crackle*", "#ffb46b");
    if (out === "revive") react(near, "heart", ["still some life in it", "ooh, it's back", "one more log?"]);
    else if (out === "careful") react(here, "bang", ["careful!", "mind my eyebrows", "steady on"]);
    else react(near, "heart", ["lovely", "that's better", "toasty"]);
}
// Click the lounge grandfather clock to make it strike the hour: one bong per hour (12-hour), and every
// seventh strike it loses count and strikes thirteen. The nearest colleague reacts to the time (lifted into tests/test_office.py).
const hitClock = (p) => p.x >= 389 && p.x <= 409 && p.y >= 382 && p.y <= 453;
let clockStrikes = 0,
    chiming = false;
function chimeOutcome(n, h) {
    const mood = h >= 22 || h < 6 ? "late" : h < 9 ? "early" : h >= 12 && h < 14 ? "lunch" : h >= 17 ? "home" : "day";
    return n % 7 === 0 ? { bongs: 13, mood: "thirteen" } : { bongs: h % 12 || 12, mood };
}
const CHIME_LINES = {
    late: ["shh, people are napping", "is it really that late?", "go to bed, {user}"],
    early: ["too early for bongs", "is it that time already?", "coffee first"],
    lunch: ["lunch o'clock!", "that's my stomach's cue", "sandwich time"],
    home: ["home time?", "I hear you, clock", "nearly time to log off"],
    day: ["already?", "where does the day go?", "back to it then"],
    thirteen: ["thirteen?!", "someone wind that thing properly", "that clock needs a service"],
};
// It also strikes on its own as office time turns each hour, silenced overnight like a real clock's night switch.
function autoChime(h, prev) {
    return prev != null && h !== prev && h >= 7 && h < 22;
}
let chimeHour = null;
// The post: ambient, seeded per date like the weather. Monday to Saturday it lands mid-morning (Monday's is heavier,
// with the weekend's), a slot at a time it's collected by colleagues who wander over, and anything left is gone by
// 17:30 (13:00 on Saturdays), so a reload never shows a stale bank. No Sunday post. Never runner output.
const OWN_SLOT = 4; // {user}'s own pigeonhole, the middle one: colleagues leave it alone, so it waits for a click
function postFor(key, day) {
    if (day === 0) return null;
    const sat = day === 6,
        at = Math.round((sat ? 600 : 570) + hash("postAt" + key) * (sat ? 120 : 90)),
        end = sat ? 780 : 1050;
    const n = Math.min(9, 1 + Math.floor(hash("postN" + key) * 5) + (day === 1 ? 2 : 0));
    const order = [0, 1, 2, 3, 4, 5, 6, 7, 8].sort((a, b) => hash("postI" + key + a) - hash("postI" + key + b));
    return {
        at,
        slots: order
            .slice(0, n)
            .sort((a, b) => a - b)
            .map((i) => {
                const r = hash("postK" + key + i);
                return {
                    i,
                    kind: r < 0.55 ? "letter" : r < 0.85 ? "flyer" : "postcard",
                    by: i === OWN_SLOT ? end : Math.round(at + 20 + hash("postBy" + key + i) * (end - at - 20)),
                };
            }),
    };
}
function postWaiting(plan, min, taken) {
    return plan && min >= plan.at ? plan.slots.filter((s) => min < s.by && !taken.has(s.i)) : [];
}
const postTaken = new Set();
let postKey = "",
    postMin = null,
    ownChecked = false;
function postNow() {
    const T = clock(),
        d = new Date(),
        key = `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
    if (key !== postKey) {
        postKey = key;
        postTaken.clear();
        postCache.k = -1;
        ownChecked = false;
    }
    return { plan: postFor(key, T.day), min: T.h * 60 + T.m };
}
const postCache = { k: -1, v: [] };
function postLeft() {
    // cached per minute and collection, as it's read every frame
    const p = postNow(),
        k = p.min * 16 + postTaken.size;
    if (k !== postCache.k) {
        postCache.k = k;
        postCache.v = postWaiting(p.plan, p.min, postTaken);
    }
    return postCache.v;
}
const POST_QUIPS = {
    letter: ["anything for me?", "another bank statement", "who still sends letters?", "ooh, handwritten"],
    flyer: ["just flyers", "pizza menu, keeping that", "recycling, this", "'have you considered solar?'"],
    postcard: [
        "a postcard! wish you were here, apparently",
        "postcard from somewhere sunny",
        "someone's having a nice time",
    ],
    none: ["nothing for me", "beaten to it", "empty again"],
};
function collectPost(w, now) {
    const left = postLeft().filter((x) => x.i !== OWN_SLOT),
        s = left.length ? left[Math.floor(Math.random() * left.length)] : null;
    if (s) postTaken.add(s.i);
    w.item = s ? "papers" : null;
    w.emote = s ? (s.kind === "postcard" ? "heart" : s.kind === "letter" ? "q" : "note") : "q";
    w.emoteUntil = now + 2200;
    if (now - lastQuip > 3000 || s) say(w, pick(POST_QUIPS[s ? s.kind : "none"], Math.random()), now);
}
function postStep(now) {
    // the post lands with a thud at the front door; the nearest idle colleague goes to see
    const p = postNow(),
        was = postMin;
    postMin = p.min;
    if (!booted || !p.plan || was === null || !(was < p.plan.at && p.min >= p.plan.at)) return; // never during ?warp or catch-up
    doorFlashUntil = now + 900;
    floatText(DOOR.x + 16, DOOR.y + 30, "*thud* post!", "#f4efe1");
    const spot = POIS.find((q) => q.tag === "post"),
        f = spot && !spot.taken ? coffeeRunner(spot, [...workers.values()]) : null;
    if (f) {
        leaveSpot(f);
        f.carry = null;
        f.item = null;
        sendTo(f, spot);
        say(f, pick(["post's here!", "I'll get it", "that'll be the post"], Math.random()), now);
    }
}
function drawPost() {
    // what's waiting pokes out of each slot's slit: cream letters, coloured flyers, a sky-blue postcard
    for (const s of postLeft()) {
        const x = PIGEON.x + [5, 16, 26][s.i % 3],
            y = PIGEON.y + [4, 15, 25][Math.floor(s.i / 3)] - 1;
        ctx.fillStyle =
            s.kind === "letter" ? "#f4efe1" : s.kind === "postcard" ? "#8fd3ff" : s.i % 2 ? "#ffd166" : "#ff8fb1";
        ctx.fillRect(x, y, 5, 2);
        ctx.fillStyle = "#00000040";
        ctx.fillRect(x, y + 2, 5, 1);
    }
    if (hovered === "post") {
        ctx.strokeStyle = "#f4efe1cc";
        ctx.lineWidth = 1;
        ctx.strokeRect(PIGEON.x - 1.5, PIGEON.y - 1.5, PIGEON.w + 3, PIGEON.h + 3);
    }
}
function postText() {
    const p = postNow(),
        n = postWaiting(p.plan, p.min, postTaken).length,
        hm = (m) => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
    if (!p.plan) return "pigeonholes · no post on Sundays";
    if (p.min < p.plan.at) return "pigeonholes · post usually comes about " + hm(Math.round(p.plan.at / 30) * 30);
    const mine = postWaiting(p.plan, p.min, postTaken).some((s) => s.i === OWN_SLOT);
    return n ? `pigeonholes · ${n} waiting` + (mine ? " · one's yours" : "") : "pigeonholes · all collected";
}
// Click the pigeonholes to check {user}'s own slot (world-only; lifted into tests/test_office.py). Colleagues never
// take it, so whatever lands there waits until {user} looks, or the bank is cleared at the end of the day.
function ownPost(plan, min, taken, checked) {
    if (!plan) return "sunday";
    if (min < plan.at) return "early";
    const s = plan.slots.find((x) => x.i === OWN_SLOT);
    if (s && min < s.by && !taken.has(OWN_SLOT)) return s.kind;
    return checked ? "again" : "empty";
}
function checkPost(now) {
    const p = postNow(),
        out = ownPost(p.plan, p.min, postTaken, ownChecked),
        who = USER_NAME === "You" ? "you" : USER_NAME;
    const cx = PIGEON.x + 18,
        cy = PIGEON.y - 2,
        hm = (m) => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
    const got = out === "letter" || out === "flyer" || out === "postcard";
    if (got) {
        postTaken.add(OWN_SLOT);
        ownChecked = true;
    } else if (out === "empty") ownChecked = true;
    floatText(
        cx,
        cy,
        {
            sunday: "*rattle* no post on Sundays",
            early: `nothing yet · post's about ${p.plan ? hm(Math.round(p.plan.at / 30) * 30) : ""}`,
            letter: `a letter for ${who}`,
            flyer: `flyers for ${who}`,
            postcard: `a postcard for ${who}!`,
            empty: `*rattle* nothing for ${who}`,
            again: "already collected yours",
        }[out],
        got ? "#ffd166" : "#f4efe1",
    );
    const c = cheerer({ x: 402, y: 100 }, [...workers.values()], 160);
    if (!c || now < c.quipUntil || (!got && Math.random() < 0.5)) return;
    c.emote = out === "postcard" ? "heart" : "q";
    c.emoteUntil = now + 2200;
    say(
        c,
        pick(
            {
                letter: ["ooh, who's it from?", "bill or birthday?", "handwritten, {user}?"],
                flyer: ["same pizza menu as me", "straight in the recycling", "solar again?"],
                postcard: ["where's that from?", "wish I was there", "lucky {user}"],
                empty: ["nothing for me either", "it's all email now", "maybe tomorrow"],
                early: ["post's not been yet", "keen, {user}"],
                sunday: ["it's Sunday, {user}", "no post today"],
                again: ["you've had yours, {user}", "checking twice?"],
            }[out],
            Math.random(),
        ),
        now,
    );
}
function clockStep() {
    if (!booted) return; // never during ?warp or away catch-up
    const h = clock().h;
    if (autoChime(h, chimeHour)) strikeClock(true);
    chimeHour = h;
}
function strikeClock(auto = false) {
    if (chiming) return; // let one strike finish before the next
    chiming = true;
    const h = clock().h,
        out = auto ? chimeOutcome(1, h) : chimeOutcome(++clockStrikes, h),
        gap = REDUCED ? 260 : 520;
    for (let i = 0; i < out.bongs; i++)
        setTimeout(() => floatText(399 + (i % 2 ? 6 : -6), 398, "*bong*", "#e8d9a8"), i * gap);
    setTimeout(() => {
        chiming = false;
        const now = last || tnow(),
            w = cheerer({ x: 399, y: 470 }, [...workers.values()], 240);
        if (w && now >= w.quipUntil) {
            w.emote = out.mood === "thirteen" ? "q" : "bang";
            w.emoteUntil = now + 2200;
            say(w, pick(CHIME_LINES[out.mood], Math.random()), now);
        }
    }, out.bongs * gap);
}
function consolePlayed() {
    for (const p of POIS)
        if (p.tag === "console" && p.taken) {
            const w = workers.get(p.taken);
            if (w && !w.path.length) return true;
        }
    return false;
}
const STATIC_GREYS = ["#2a2a2e", "#5a5a60", "#8c8c94", "#c4c4cc", "#ececf2"];
let noiseSeed = 1;
function drawConsoleScreen(now) {
    if (consoleSwap.at === 0) consoleSwap.at = now;
    const { idx, t } = consoleSlot(now),
        g = CONSOLE_GAMES[idx];
    const R = (c, x, y, w, h) => {
        ctx.fillStyle = c;
        ctx.fillRect(GS.x + x, GS.y + y, w, h);
    };
    ctx.save();
    ctx.beginPath();
    ctx.rect(GS.x, GS.y, GS.w, GS.h);
    ctx.clip();
    if (t < STATIC_MS) {
        // channel-change static
        noiseSeed = (Math.floor(now / 40) * 7919) | 1;
        for (let y = 0; y < GS.h; y++)
            for (let x = 0; x < GS.w; x += 2) {
                noiseSeed = (noiseSeed * 1103515245 + 12345) & 0x7fffffff;
                ctx.fillStyle = STATIC_GREYS[(noiseSeed >> 16) % 5];
                ctx.fillRect(GS.x + x, GS.y + y, 2, 1);
            }
    } else {
        g.draw(R, t);
        if (t < STATIC_MS + TITLE_MS) R("#000000b8", 0, 8, GS.w, 11);
    }
    ctx.fillStyle = "#ffffff10";
    for (let i = 0; i < 12; i++) ctx.fillRect(GS.x + i * 2, GS.y, 2, 12 - i); // glass sheen
    ctx.restore();
}
function drawConsoleText(now) {
    const { idx, t } = consoleSlot(now);
    if (t < STATIC_MS || t >= STATIC_MS + TITLE_MS) return;
    const g = CONSOLE_GAMES[idx],
        n = g.title.length,
        px = Math.min(4.2, 44 / Math.max(...g.title.map((l) => l.length)));
    vctx.save();
    vctx.font = `${Math.round(px * S)}px "Press Start 2P"`;
    vctx.fillStyle = g.col;
    vctx.textAlign = "center";
    vctx.textBaseline = "middle";
    g.title.forEach((l, i) =>
        vctx.fillText(
            l,
            Math.round((GS.x + GS.w / 2) * S),
            Math.round((GS.y + 13.5 + (i - (n - 1) / 2) * (px + 1.5)) * S),
        ),
    );
    vctx.restore();
}
function drawDen(now) {
    blit(ctx, "mediaUnit", DEN.x, DEN.y);
    blit(ctx, "tvSmall", DEN.tv.x, DEN.tv.y);
    drawConsoleScreen(now);
    const slot = consoleSlot(now),
        g = CONSOLE_GAMES[slot.idx];
    // the console on the rug in front: a black slab with a red stripe, cartridge slot and power light
    const cx = 849,
        cy = 584,
        on = consolePlayed() || slot.manual;
    ctx.fillStyle = "#00000040";
    ctx.fillRect(cx, cy + 5, 13, 1);
    ctx.fillStyle = "#0b0a10";
    ctx.fillRect(cx - 1, cy - 1, 14, 7);
    ctx.fillStyle = "#25232e";
    ctx.fillRect(cx, cy, 12, 5);
    ctx.fillStyle = "#3a3846";
    ctx.fillRect(cx, cy, 12, 1);
    ctx.fillStyle = "#14131a";
    ctx.fillRect(cx + 3, cy + 1, 6, 2);
    const hop = !REDUCED && slot.manual && slot.t < 420 ? Math.round(Math.sin((slot.t / 420) * Math.PI) * 3) : 0;
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(cx + 4, cy - 1 - hop, 4, 2);
    ctx.fillStyle = g.col;
    ctx.fillRect(cx + 4, cy - 1 - hop, 4, 1);
    ctx.fillStyle = "#d94848";
    ctx.fillRect(cx + 1, cy + 4, 4, 1);
    ctx.fillStyle = on ? "#7ee0b5" : "#d94848";
    ctx.fillRect(cx + 10, cy + 3, 1, 1);
    if (hovered === "console") {
        ctx.strokeStyle = "#ffffffaa";
        ctx.lineWidth = 1;
        ctx.strokeRect(DEN.tv.x - 0.5, DEN.tv.y - 0.5, 53, 36);
    }
}
// the employee-of-the-week frame: a gilt frame and plaque for the crowned holder, plain wood for this week's leader so far
const framePic = { key: null, c: null };
function drawFrame(now) {
    const f = FRAME,
        v = eotwView,
        gold = !!(v && v.kind === "holder"),
        w = v && workers.get(v.id);
    ctx.fillStyle = "#00000038";
    ctx.fillRect(f.x + 2, f.y + f.h, f.w - 2, 2);
    ctx.fillStyle = "#2a1712";
    ctx.fillRect(f.x, f.y, f.w, f.h);
    ctx.fillStyle = gold ? "#b8862a" : "#6b3f2a";
    ctx.fillRect(f.x + 1, f.y + 1, f.w - 2, f.h - 2);
    ctx.fillStyle = gold ? "#f4d27a" : "#8a5a3a";
    ctx.fillRect(f.x + 1, f.y + 1, f.w - 2, 1);
    ctx.fillRect(f.x + 1, f.y + 1, 1, f.h - 2);
    ctx.fillStyle = "#e9e2cf";
    ctx.fillRect(f.x + 3, f.y + 3, f.w - 6, 23);
    if (w) {
        const key = v.id + "|" + lookKey(w.look);
        if (framePic.key !== key) {
            framePic.key = key;
            framePic.c = portrait(w.look, 26);
        }
        ctx.drawImage(framePic.c, 2, 0, 22, 23, f.x + 3, f.y + 3, 22, 23);
    } else {
        pxEllipse(ctx, f.x + 14, f.y + 11, 4, 4, "#c4bba6");
        ctx.fillStyle = "#c4bba6";
        ctx.fillRect(f.x + 7, f.y + 17, 14, 9);
    } // vacancy
    ctx.fillStyle = gold ? "#ffd166" : "#b8ab90";
    ctx.fillRect(f.x + 4, f.y + 29, f.w - 8, 6);
    ctx.fillStyle = "#00000055";
    ctx.fillRect(f.x + 7, f.y + 31, f.w - 14, 1);
    ctx.fillRect(f.x + 9, f.y + 33, f.w - 18, 1);
    if (gold) {
        ctx.fillStyle = "#ffd166";
        ctx.fillRect(f.x + 13, f.y - 3, 2, 2);
        ctx.fillRect(f.x + 12, f.y - 2, 4, 1);
    } // a little gold star on top
    if (now < frameFlashUntil && !REDUCED)
        for (let i = 0; i < 6; i++) {
            const a = now / 300 + (i * Math.PI) / 3;
            ctx.fillStyle = i % 2 ? "#ffd166" : "#fffaf0";
            ctx.fillRect(Math.round(f.x + 14 + Math.cos(a) * 20), Math.round(f.y + 19 + Math.sin(a) * 23), 1, 1);
        }
    if (hovered === "frame") {
        ctx.strokeStyle = "#ffd166cc";
        ctx.lineWidth = 1;
        ctx.strokeRect(f.x - 1.5, f.y - 1.5, f.w + 3, f.h + 3);
    }
}
function drawDynamicProps(now, counts) {
    drawCeefaxScreen(now);
    drawDarts(now);
    drawFrame(now);
    drawPost();
    // whiteboard kanban: the Assistant board as sticky notes - the user's pile, the AI's pile, snoozed, and a tally of today's wins
    ctx.fillStyle = "#f4f6f8";
    ctx.fillRect(BOARD.x, BOARD.y, BOARD.w, BOARD.h);
    const cols = kanbanCols(kanban),
        cw = BOARD.w / cols.length;
    boardHits = [];
    cols.forEach((col, ci) => {
        const cx0 = Math.round(BOARD.x + ci * cw);
        ctx.fillStyle = col.col;
        ctx.fillRect(cx0 + 3, BOARD.y + 3, Math.round(cw) - 6, 2);
        if (ci) {
            ctx.fillStyle = "#d4d8e0";
            ctx.fillRect(cx0, BOARD.y + 2, 1, BOARD.h - 4);
        }
        if (col.key === "done") {
            // five-bar gates in green marker
            ctx.fillStyle = "#2f8a5f";
            for (let i = 0; i < Math.min(col.tally, 40); i++) {
                const g = Math.floor(i / 5),
                    gx = cx0 + 5 + (g % 3) * 12,
                    gy = BOARD.y + 9 + Math.floor(g / 3) * 9;
                if (i % 5 === 4) pxLine(ctx, gx - 1, gy + 5, gx + 9, gy + 1, "#2f8a5f");
                else ctx.fillRect(gx + (i % 5) * 2, gy, 1, 6);
            }
            if (col.tally) boardHits.push({ x: cx0, y: BOARD.y, w: cw, h: BOARD.h, title: `${col.tally} done today` });
            return;
        }
        col.notes.forEach((note, n) => {
            const nx = cx0 + 3 + (n % 4) * 10,
                ny = BOARD.y + 9 + Math.floor(n / 4) * 9;
            if (ny > BOARD.y + BOARD.h - 8) return;
            const tilt = hash(note.title) < 0.5 ? 0 : 1,
                hot = boardHover === note.title;
            ctx.fillStyle = "#0002";
            ctx.fillRect(nx + 1, ny + 1 + tilt, 8, 7);
            ctx.fillStyle = hot ? "#1b1830" : col.key === "later" ? "#d8d4e4" : NOTE_COL[note.type] || "#fff3a0";
            ctx.fillRect(nx, ny + tilt, 8, 7);
            ctx.fillStyle = "#0004";
            ctx.fillRect(nx + 2, ny + 3 + tilt, 4, 1);
            ctx.fillRect(nx + 2, ny + 5 + tilt, 3, 1);
            if (note.new) {
                ctx.fillStyle = Math.floor(now / 600) % 2 ? "#ff3b3b" : "#b02020";
                ctx.fillRect(nx + 3, ny - 1 + tilt, 2, 2);
            }
            boardHits.push({ x: nx, y: ny, w: 9, h: 8, title: note.title || "(untitled)" });
        });
    });
    // sketches from whoever is at the whiteboard
    for (const w of workers.values()) {
        if (w.act !== "write" || w.path.length) continue;
        const prog = clamp((now - w.arrivedAt) / (w.dwellLen || 20000), 0, 1),
            n = Math.floor(prog * 10);
        ctx.fillStyle = ["#e85d5d", "#5b8cff", "#2f8a5f"][Math.floor(hash(w.id + "mk") * 3)];
        for (let i = 0; i < n; i++) {
            const lx = Math.round(w.x - 14 + (i % 3) * 10),
                ly = BOARD.y + 38 + Math.floor(i / 3) * 5,
                len = 4 + Math.floor(hash(w.id + i) * 5);
            if (i % 4 === 3) {
                ctx.fillRect(lx, ly - 1, 6, 1);
                ctx.fillRect(lx, ly + 2, 6, 1);
                ctx.fillRect(lx, ly - 1, 1, 4);
                ctx.fillRect(lx + 5, ly - 1, 1, 4);
            } else for (let k = 0; k < len; k++) ctx.fillRect(lx + k, ly + Math.round(Math.sin(k + i) * 0.8), 1, 1);
        }
    }
    // wall clock hands
    const T = clock(),
        { x: cx, y: cy } = WALL_CLOCK;
    const ma = ((T.m + (HOUR_OVERRIDE != null ? 0 : T.s / 60)) / 60) * Math.PI * 2,
        ha = (((T.h % 12) + T.m / 60) / 12) * Math.PI * 2,
        sa = (T.s / 60) * Math.PI * 2;
    pxLine(ctx, cx, cy, cx + Math.sin(ha) * 4, cy - Math.cos(ha) * 4, "#1b1830");
    pxLine(ctx, cx, cy, cx + Math.sin(ma) * 6, cy - Math.cos(ma) * 6, "#3a2a22");
    if (HOUR_OVERRIDE == null) pxLine(ctx, cx, cy, cx + Math.sin(sa) * 6, cy - Math.cos(sa) * 6, "#d94848");
    ctx.fillStyle = "#d94848";
    ctx.fillRect(cx, cy, 1, 1);
    // badge reader LED
    const doorFlash = now < doorFlashUntil;
    ctx.fillStyle = doorFlash && Math.floor(now / 110) % 2 ? "#ffffff" : "#7ee0b5";
    ctx.fillRect(DOOR.x + 40, DOOR.y + 25, 2, 2);
    if (hovered === "door") {
        ctx.strokeStyle = "#7ee0b5cc";
        ctx.lineWidth = 1;
        ctx.strokeRect(DOOR.x - 4.5, DOOR.y - 4.5, 50, 63);
    }
    // copier light
    const copFlash = now < copierFlashUntil;
    ctx.fillStyle = copFlash ? (Math.floor(now / 110) % 2 ? "#b79bff" : "#7ee0b5") : "#3d6b5a";
    ctx.fillRect(COPIER.x + 40, COPIER.y + 18, 2, 1);
    if (hovered === "copier") {
        ctx.strokeStyle = "#ffffffaa";
        ctx.lineWidth = 1;
        ctx.strokeRect(COPIER.x - 0.5, COPIER.y - 0.5, 54, 46);
    }
}
// live sky in every window: gradient, drifting clouds and birds by day, stars, moon and a passing plane by night
const FW_COLS = ["#ff6b6b", "#ffd166", "#7ee0b5", "#6aa6ff", "#ff9fd8", "#ffffff"],
    FW_RGB = ["255,107,107", "255,209,102", "126,224,181", "106,166,255", "255,159,216", "255,255,255"];
// live firework bursts, reused every frame (the sky draws them, the lighting pass flashes the room with their colour)
const bursts = Array.from({ length: 9 }, () => ({ on: false, wx: 0, x: 0, y: 0, age: 0, col: 0, r: 0 }));
function fireworkStep(secs, fw) {
    if (!(fw > 0)) {
        for (const b of bursts) b.on = false;
        return;
    }
    bursts.forEach((b, i) => {
        const per = 2.4 + hash("fw" + i) * 3.6,
            cyc = secs / per + hash("fp" + i),
            k = Math.floor(cyc),
            id = i + "-" + k;
        b.age = (cyc - k) * per;
        b.on = fw > 0 && b.age <= 1.5 && hash("fk" + id) <= fw;
        if (!b.on) return;
        b.wx = WINDOWS[Math.floor(hash("fx" + id) * WINDOWS.length)];
        b.x = b.wx + 7 + Math.round(hash("fz" + id) * 18);
        b.y = 16 + Math.round(hash("fy" + id) * 26);
        b.col = Math.floor(hash("fc" + id) * FW_COLS.length);
        b.r = 5 + hash("fr" + id) * 5;
    });
}
function drawSky(now) {
    const T = clock(),
        [top, bot2] = skyColours(T),
        dark = darkness(T),
        night = dark > 0.4,
        wet = T.wx === "rain",
        grey = T.wx !== "clear",
        dusk = grey ? 0 : golden(T);
    const g = ctx.createLinearGradient(0, 8, 0, 74);
    g.addColorStop(0, top);
    g.addColorStop(1, bot2);
    const secs = now / 1000;
    fireworkStep(secs, dark > 0.3 && !wet && SEASON ? fireworksFor(SEASON, SMO, SD, T.t) : 0);
    for (const wx of WINDOWS) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(wx + 2, 8, 28, 66);
        ctx.clip();
        ctx.fillStyle = g;
        ctx.fillRect(wx + 2, 8, 28, 66);
        if (grey) {
            ctx.fillStyle = night ? "#1a1c26" : "#8b95a3";
            ctx.globalAlpha = wet ? 0.7 : 0.45;
            ctx.fillRect(wx + 2, 8, 28, 66);
            ctx.globalAlpha = 1;
        }
        if (dark > 0.25 && !wet)
            for (let i = 0; i < 12; i++) {
                const sx = wx + 3 + Math.floor(hash(wx + "s" + i) * 26),
                    sy = 10 + Math.floor(hash(wx + "t" + i) * 42);
                ctx.globalAlpha =
                    clamp((dark - 0.25) * 3, 0, 1) *
                    (0.45 + 0.55 * Math.abs(Math.sin(secs * (0.6 + hash(i + "f" + wx)) + i)));
                ctx.fillStyle = i % 4 ? "#ffffff" : "#ffe9a8";
                ctx.fillRect(sx, sy, 1, 1);
            }
        ctx.globalAlpha = 1;
        // sun by day (eastern meeting-room window), moon by night
        if (!night && dark < 0.3 && !grey) {
            const sy = dusk ? 40 + dusk * 18 : 18;
            pxEllipse(ctx, 858, sy, 5, 5, dusk ? "#ffb070" : "#fff6c8");
            ctx.globalAlpha = 0.25;
            pxEllipse(ctx, 858, sy, 8, 8, "#fff6c8");
            ctx.globalAlpha = 1;
        }
        if (night && !grey) {
            pxEllipse(ctx, 74, 20, 4, 4, "#fff4c8");
            pxEllipse(ctx, 76, 19, 3, 3, top);
        }
        // clouds drift across the whole facade so windows stay continuous
        if (dark < 0.5)
            for (let i = 0; i < (grey ? 16 : 9); i++) {
                const span = W + 120,
                    cxp = ((hash("c" + i) * span + secs * (2 + hash("v" + i) * 3)) % span) - 60,
                    cyp = 14 + Math.floor(hash("y" + i) * 30),
                    s = hash("s" + i) > 0.6 ? 2 : 1;
                if (cxp + 14 * s < wx || cxp > wx + 32) continue;
                ctx.globalAlpha = 0.85 * (1 - dark * 1.6);
                ctx.fillStyle = grey ? (wet ? "#a9b2bd" : "#d3d9e0") : dusk ? "#ffd8c0" : "#ffffff";
                const cx2 = Math.round(cxp);
                ctx.fillRect(cx2, cyp + 2 * s, 12 * s, 3 * s);
                ctx.fillRect(cx2 + 2 * s, cyp, 6 * s, 3 * s);
                ctx.fillRect(cx2 + 6 * s, cyp - s, 4 * s, 3 * s);
                ctx.fillStyle = grey ? "#7d8794" : dusk ? "#e8a0a0" : "#d6e6f4";
                ctx.fillRect(cx2 + s, cyp + 4 * s, 10 * s, s);
                ctx.globalAlpha = 1;
            }
        // birds by day
        if (dark < 0.2 && !wet)
            for (let i = 0; i < 3; i++) {
                const span = W + 200,
                    bxp = Math.round(((hash("b" + i) * span + secs * (10 + i * 3)) % span) - 100),
                    byp = 24 + i * 6 + Math.round(Math.sin(secs + i) * 2);
                if (bxp < wx || bxp > wx + 32) continue;
                ctx.fillStyle = "#2a3550";
                const up = Math.floor(secs * 6 + i) % 2;
                ctx.fillRect(bxp - 2, byp - up, 1, 1);
                ctx.fillRect(bxp - 1, byp, 1, 1);
                ctx.fillRect(bxp, byp - 1 + up, 1, 1);
                ctx.fillRect(bxp + 1, byp, 1, 1);
                ctx.fillRect(bxp + 2, byp - up, 1, 1);
            }
        // plane by night
        if (night) {
            const pxp = Math.round(((secs * 14) % 2200) - 300),
                pyp = 16 + Math.round(((secs * 14) % 2200) / 200);
            if (pxp > wx && pxp < wx + 32) {
                ctx.fillStyle = "#c9c1e0";
                ctx.fillRect(pxp - 2, pyp, 5, 1);
                ctx.fillStyle = Math.floor(secs * 2) % 2 ? "#ff4d4d" : "#fffaf0";
                ctx.fillRect(pxp + 2, pyp, 1, 1);
            }
        }
        // fireworks (bonfire week, New Year): each burst goes off in one window's view; Halloween bats cross the whole facade
        for (const b of bursts) {
            if (!b.on || b.wx !== wx) continue;
            ctx.fillStyle = FW_COLS[b.col];
            if (b.age < 0.3) {
                ctx.globalAlpha = 0.8;
                ctx.fillRect(b.x, Math.round(b.y + (1 - b.age / 0.3) * 40), 1, 2);
            } else {
                const r = Math.min(1, (b.age - 0.3) / 0.35) * b.r,
                    sag = Math.round((b.age - 0.3) * 4);
                ctx.globalAlpha = clamp(1.5 - b.age, 0, 1);
                for (let a = 0; a < 12; a++) {
                    const an = (a / 12) * 6.283,
                        c = Math.cos(an),
                        sn = Math.sin(an);
                    ctx.fillRect(Math.round(b.x + c * r), Math.round(b.y + sn * r) + sag, 1, 1);
                    if (r > 3) ctx.fillRect(Math.round(b.x + c * (r - 2)), Math.round(b.y + sn * (r - 2)) + sag, 1, 1);
                }
                if (b.age < 0.6) {
                    ctx.fillStyle = "#fffaf0";
                    ctx.fillRect(b.x, b.y, 1, 1);
                }
            }
            ctx.globalAlpha = 1;
        }
        if (SEASON === "halloween" && dark > 0.3)
            for (let i = 0; i < 3; i++) {
                const span = W + 200,
                    bxp = Math.round(((hash("bat" + i) * span + secs * (16 + i * 5)) % span) - 100),
                    byp = 20 + i * 9 + Math.round(Math.sin(secs * 3 + i) * 3);
                if (bxp < wx || bxp > wx + 32) continue;
                ctx.fillStyle = "#05040a";
                const up = Math.floor(secs * 9 + i) % 2;
                ctx.fillRect(bxp - 1, byp, 3, 2);
                ctx.fillRect(bxp - 3, byp - up, 2, 1);
                ctx.fillRect(bxp + 2, byp - up, 2, 1);
                ctx.fillRect(bxp - 4, byp + 1 - up * 2, 1, 1);
                ctx.fillRect(bxp + 4, byp + 1 - up * 2, 1, 1);
            }
        // skyline with flickering office lights
        for (let i = 0; i < 6; i++) {
            const bw = 4 + Math.floor(hash(wx + "b" + i) * 5),
                bh = 8 + Math.floor(hash(wx + "h" + i) * 18),
                bxp = wx + 2 + i * 5;
            ctx.fillStyle = night ? "#141433" : dusk ? "#5a4a7a" : "#7f9fc4";
            ctx.fillRect(bxp, 74 - bh, bw, bh);
            if (dark > 0.2)
                for (let k = 0; k < 4; k++)
                    if (hash(wx + "l" + i + k + Math.floor(secs / (25 + hash(i + k) * 40))) > 0.5) {
                        ctx.fillStyle = "#ffd166";
                        ctx.fillRect(bxp + 1 + (k % 2) * 2, 74 - bh + 2 + Math.floor(k / 2) * 4, 1, 1);
                    }
            if (wet) {
                ctx.fillStyle = night ? "#20223a" : "#9aa6b6";
                ctx.globalAlpha = 0.5;
                ctx.fillRect(bxp, 74 - bh, bw, bh);
                ctx.globalAlpha = 1;
            } // haze
            if (i === 3 && bh > 18) {
                ctx.fillStyle = Math.floor(secs) % 2 ? "#ff4d4d" : "#5a1a1a";
                ctx.fillRect(bxp + 1, 73 - bh, 1, 1);
            }
        }
        if (wet) {
            // falling streaks behind the glass, then a few drops running down it
            ctx.fillStyle = night ? "#6a7290" : "#e2ecf8";
            ctx.globalAlpha = 0.55;
            for (let i = 0; i < 14; i++) {
                const ry = 8 + ((hash(wx + "r" + i) * 66 + secs * (150 + i * 9)) % 72) - 6,
                    rx = wx + 2 + Math.floor(hash(wx + "q" + i) * 28) + Math.round((ry - 8) * 0.15);
                ctx.fillRect(rx, Math.round(ry), 1, 4);
            }
            ctx.globalAlpha = 0.8;
            for (let i = 0; i < 3; i++) {
                const sp = 3 + hash(wx + "d" + i) * 6,
                    dy = 8 + ((hash(wx + "e" + i) * 66 + secs * sp) % 66),
                    dx = wx + 4 + Math.floor(hash(wx + "x" + i) * 24);
                ctx.fillRect(dx, Math.round(dy), 1, 2);
                ctx.globalAlpha = 0.35;
                ctx.fillRect(dx, Math.round(dy) - 4, 1, 4);
                ctx.globalAlpha = 0.8;
            }
            ctx.globalAlpha = 1;
        }
        ctx.restore();
    }
}
function render(now, counts) {
    drawSky(now);
    ctx.drawImage(bg, 0, 0);
    drawDynamicProps(now, counts);
    drawWetFloor(ctx, clock().wx === "rain");
    // y-sorted world
    const items = [];
    for (const p of PROPS)
        items.push({
            y: p.base,
            draw: () => {
                if (p.draw) p.draw(now);
                else blit(ctx, p.key, p.x, p.y);
                if (p.after) p.after(now);
            },
        });
    for (const w of workers.values()) {
        const leg = seatLeg(w),
            s = leg ? leg.sort : !w.path.length && w.spot && w.spot.sort != null ? w.spot.sort : w.y;
        items.push({ y: s, draw: () => drawWorker(w, now) });
    }
    items.push({ y: bot.y, draw: () => drawBot(now) });
    for (const e of eggs)
        if (!e.found)
            items.push({
                y: e.base,
                draw: () => {
                    blit(ctx, e.brown ? "eggB" : "eggW", e.x - 5, e.y - 12);
                    if (hovered === "egg" && hoverEgg === e) {
                        ctx.strokeStyle = "#ffd166cc";
                        ctx.lineWidth = 1;
                        ctx.strokeRect(e.x - 6.5, e.y - 13.5, 13, 15);
                    }
                },
            });
    const catDesk = cat.onDesk && DESKS[cat.deskIdx];
    items.push({
        y: cat.ride ? bot.y + 1 : catDesk ? catDesk.y + 36 : cat.onBed ? BED.y + 62 : cat.y,
        draw: () => drawCat(now),
    });
    items.sort((a, b) => a.y - b.y);
    for (const it of items) it.draw();
    drawParts(ctx);
    for (const w of workers.values()) drawStatusBubble(w, now);
    lighting(now, counts);
}
// Late at night the lamps run on motion sensors: a room nobody has been in for SENSOR_HOLD ms
// fades dark, and its lamps snap back on when someone walks in. Equipment (TV, rack, arcades, screens) stays lit.
function roomAt(x, y) {
    if (y < MID) return x < 600 ? "office" : x < 880 ? "meeting" : "kitchen";
    return x < 150 ? "firstaid" : x < 760 ? "lounge" : x < 1150 ? "games" : "userOffice";
}
function sensorHours(T) {
    return T.t >= 22 || T.t < 6;
}
const SENSOR_HOLD = 20000,
    roomLit = { office: 1, meeting: 1, kitchen: 1, firstaid: 1, lounge: 1, games: 1, userOffice: 1 },
    roomSeen = {
        office: -1e9,
        meeting: -1e9,
        kitchen: -1e9,
        firstaid: -1e9,
        lounge: -1e9,
        games: -1e9,
        userOffice: -1e9,
    };
// A dark room's tubes don't fade up: they strike - blink, die, blink, glow dim, then settle (seconds since the strike).
const STRIKE = [
    [0.08, 1],
    [0.2, 0],
    [0.27, 1],
    [0.42, 0],
    [0.6, 0.45],
    [0.8, 0.8],
];
function tubeStrike(age) {
    for (const [end, v] of STRIKE) if (age < end) return v;
    return 1;
}
const roomStrike = { office: 9, meeting: 9, kitchen: 9, firstaid: 9, lounge: 9, games: 9, userOffice: 9 }; // seconds since each room last struck
function sensorLights(dt, now) {
    // runs in simulate, so ?warp and catch-up play the sensors out too
    const on = !sensorHours(clock());
    for (const w of workers.values()) roomSeen[roomAt(w.x, w.y)] = now;
    for (const k in roomLit) {
        const want = on || now - roomSeen[k] < SENSOR_HOLD ? 1 : 0;
        roomStrike[k] = want && roomLit[k] < 0.05 && !REDUCED ? 0 : roomStrike[k] + dt;
        // on is a quick flicker-up, off a slow fade; reduced motion just switches
        roomLit[k] = REDUCED ? want : want ? Math.min(1, roomLit[k] + dt * 4) : Math.max(0, roomLit[k] - dt / 3);
    }
}
// Rainy days: anyone who crosses the welcome mat picks up wet shoes and leaves a few fading prints on the floor.
// Ambient only - a pool of PRINT_MAX prints is reused, so the hot path never allocates.
const PRINT_STEPS = 14,
    PRINT_GAP = 7,
    PRINT_LIFE = 10,
    PRINT_MAX = 48;
const prints = Array.from({ length: PRINT_MAX }, () => ({ x: 0, y: 0, dir: "down", life: 0 }));
let printNext = 0;
function shoeWet(steps, wet, x, y) {
    // wet steps left after this frame's position
    return wet && x > DOOR.x - 22 && x < DOOR.x + 42 && y < DOOR.front.y + 12 ? PRINT_STEPS : steps;
}
function wetPrints(dt, wet) {
    for (const p of prints) if (p.life > 0) p.life -= dt;
    if (REDUCED) return;
    for (const w of workers.values()) {
        w.wetSteps = shoeWet(w.wetSteps || 0, wet, w.x, w.y);
        if (!w.wetSteps || !w.path.length || seatLeg(w) || w.printAt == null) {
            w.printAt = w.walkDist;
            continue;
        }
        if (w.walkDist - w.printAt < PRINT_GAP) continue;
        w.printAt = w.walkDist;
        w.wetSteps--;
        w.printSide = !w.printSide;
        const p = prints[printNext];
        printNext = (printNext + 1) % PRINT_MAX;
        const side = w.printSide ? 2 : -2,
            across = w.dir === "up" || w.dir === "down";
        p.x = Math.round(w.x + (across ? side : 0));
        p.y = Math.round(w.y + (across ? 0 : side / 2));
        p.dir = w.dir;
        p.life = PRINT_LIFE;
    }
}
function drawWetFloor(c, wet) {
    if (wet) {
        // the mat darkens and goes blotchy while it's raining
        c.fillStyle = "rgba(24,16,30,.32)";
        c.fillRect(DOOR.x - 1, WALL + 2, 34, 7);
        c.fillStyle = "rgba(24,16,30,.25)";
        for (let i = 0; i < 6; i++) c.fillRect(DOOR.x + 2 + i * 5, WALL + 3 + (i % 3) * 2, 2, 1);
    }
    for (const p of prints) {
        if (p.life <= 0) continue;
        c.globalAlpha = 0.6 * Math.min(1, (p.life / PRINT_LIFE) * 2);
        c.fillStyle = "#161c2c";
        if (p.dir === "up" || p.dir === "down") c.fillRect(p.x, p.y - 1, 1, 2);
        else c.fillRect(p.x - 1, p.y, 2, 1);
    }
    c.globalAlpha = 1;
}
function lighting(now, counts) {
    const T = clock(),
        dark = darkness(T),
        inDark = indoorDarkness(T),
        lamp = lampStrength(T),
        grey = T.wx !== "clear",
        warm = grey ? 0 : golden(T);
    if (T.wx === "rain" && dark < 0.5) {
        ctx.fillStyle = `rgba(40,52,72,${(0.1 * (1 - dark * 2)).toFixed(3)})`;
        ctx.fillRect(0, 0, W, H);
    } // overcast gloom
    if (dark < 0.35 && !grey) {
        // light shafts through the windows; warmer and longer when the sun is low
        ctx.save();
        ctx.globalCompositeOperation = "lighter";
        const len = 80 + warm * 50,
            a = Math.round((1 - dark / 0.35) * (warm ? 36 : 26))
                .toString(16)
                .padStart(2, "0"),
            col = warm ? "#ffc890" : "#fff6d0";
        for (const wx of WINDOWS) {
            const g = ctx.createLinearGradient(0, WALL, 0, WALL + len);
            g.addColorStop(0, col + a);
            g.addColorStop(1, col + "00");
            ctx.fillStyle = g;
            ctx.beginPath();
            ctx.moveTo(wx + 2, WALL);
            ctx.lineTo(wx + 30, WALL);
            ctx.lineTo(wx + 30 + len * 0.3, WALL + len);
            ctx.lineTo(wx + 2 + len * 0.3, WALL + len);
            ctx.fill();
        }
        ctx.restore();
    }
    if (warm > 0) {
        ctx.save();
        ctx.globalCompositeOperation = "overlay";
        ctx.fillStyle = `rgba(255,140,60,${(0.2 * warm).toFixed(3)})`;
        ctx.fillRect(0, 0, W, H);
        ctx.restore();
    }
    if (inDark <= 0 && lamp <= 0) return;
    const lights = [
        { x: 150, y: 14, r: 70, fx: 1, c: "255,200,120" },
        { x: 414, y: 14, r: 70, fx: 1, c: "255,200,120" },
        { x: 420, y: 100, r: 80, fx: 1, c: "255,210,140" },
        { x: 622, y: 278, r: 80, fx: 1, c: "255,210,140" },
        { x: 740, y: 40, r: 90, fx: 1, c: "235,240,255" },
        { x: WALL_CLOCK.x, y: WALL_CLOCK.y, r: 16, c: "255,230,190" },
        { x: 958, y: 62, r: 60, fx: 1, c: "255,230,180" },
        { x: 1138, y: 62, r: 60, fx: 1, c: "255,230,180" },
        { x: 1008, y: 196, r: 90, fx: 1, c: "255,210,150" },
        { x: 1228, y: 64, r: 40, c: "255,90,90" },
        { x: 1259, y: 66, r: 26, c: "200,230,255" },
        { x: RACK.x + 23, y: RACK.y + 24, r: 34 + counts.working * 2, c: "120,255,170" },
        { x: 30, y: MID + 16, r: 60, fx: 1, c: "255,200,120" },
        { x: NOOK.x + 108, y: NOOK.y - 4, r: 50, fx: 1, c: "255,220,150" },
        { x: 18, y: 640, r: 50, fx: 1, c: "255,220,150" },
        { x: 608, y: MID + 16, r: 60, fx: 1, c: "255,200,120" },
        { x: 678, y: MID + 16, r: 60, fx: 1, c: "255,200,120" },
        { x: 652, y: 462, r: 80, fx: 1, c: "255,210,140" },
        { x: 354, y: 566, r: 80, fx: 1, c: "255,210,140" },
        {
            x: TV.x + TV.w / 2,
            y: TV.y + TV.h + 24,
            r: 96 + Math.round(Math.sin(now / 160) * 4 + Math.sin(now / 47) * 3),
            c: "120,170,255",
        },
        {
            x: GS.x + GS.w / 2,
            y: GS.y + 34,
            r: 56 + Math.round(Math.sin(now / 130) * 3 + Math.sin(now / 53) * 2),
            c: "130,180,255",
        },
        { x: 934, y: 618, r: 60, fx: 1, c: "255,210,140" },
        { x: 1000, y: 548, r: 90, fx: 1, c: "255,220,170" },
        { x: FOOS.x + 26, y: FOOS.y - 10, r: 60, fx: 1, c: "255,220,170" },
        { x: 1170, y: 672, r: 70, fx: 1, c: "255,210,140" },
        { x: USER_DESK.x + 44, y: USER_DESK.y - 4, r: 50, fx: 1, c: "255,220,160" },
        { x: DARTS.x, y: DARTS.y, r: 26, fx: 1, c: "255,230,190" },
    ];
    for (const d of DESKS) if (deskBusy(d)) lights.push({ x: d.x + 18, y: d.y + 2, r: 46, c: "120,200,255" });
    for (const b of bursts)
        if (b.on && b.age >= 0.3 && b.age < 1.4) {
            const k = clamp(1.5 - b.age, 0, 1);
            lights.push(
                { x: b.x, y: b.y, r: Math.round(8 + 18 * k), c: FW_RGB[b.col] },
                { x: b.x, y: WALL + 20, r: Math.round(60 * k), c: FW_RGB[b.col] },
            );
        } // firework flash through the glass
    const fire = fireNow();
    if (fire)
        lights.push({
            x: FP.x + 40,
            y: FP.y + 64,
            r: fire === 2 ? 84 + (REDUCED ? 0 : Math.round(Math.sin(now / 80) * 3 + Math.sin(now / 37) * 2)) : 42,
            c: "255,140,60",
        });
    if (fridgeDoor.until && fridgeDoor.at !== null) lights.push({ x: 1048, y: 80, r: 44, c: "255,244,214" }); // the open fridge's bulb lights a dark kitchen
    if (XMAS) lights.push({ x: 460, y: 290, r: 58 + (REDUCED ? 0 : Math.floor(now / 900) % 2) * 6, c: "255,190,110" }); // tree lights
    if (SEASON === "halloween")
        for (const [x, y] of [
            [912, 58],
            [511, 89],
            [617, 94],
            [1165, 206],
        ])
            lights.push({ x, y, r: 20 + (REDUCED ? 0 : Math.round(Math.sin(now / 110 + x) * 2)), c: "255,140,40" });
    if (counts.locked)
        lights.push({
            x: CALL.x + 15,
            y: CALL.y + 11,
            r: 26 + (Math.floor(now / 350) % 2) * 8,
            c: tasks.some((t) => t.status === "auth-failed") ? "255,90,110" : "150,140,255",
        });
    for (const d of DESKS) if (deskGaming(d)) lights.push({ x: d.x + 18, y: d.y + 2, r: 34, c: "183,155,255" });
    for (const w of workers.values())
        if (w.item === "phone" && !w.path.length) lights.push({ x: w.x, y: w.y - 24, r: 12, c: "140,210,255" });
    for (const a of ARCADES)
        lights.push({
            x: a.x + 12,
            y: a.y + 14,
            r: arcadePlayer(a) ? 34 : 22,
            c: [1, 3, 5].map((i) => parseInt(a.col.slice(i, i + 2), 16)).join(","),
        });
    if (bot.active) lights.push({ x: bot.x, y: bot.y - 3, r: 10, c: "120,255,170" });
    for (const L of lights)
        if (L.fx) {
            const k = roomAt(L.x, L.y);
            L.lv = roomLit[k] * lamp * tubeStrike(roomStrike[k]);
        }
    if (inDark > 0) {
        lctx.globalCompositeOperation = "source-over";
        lctx.clearRect(0, 0, W, H);
        lctx.fillStyle = `rgba(10,12,40,${inDark})`;
        lctx.fillRect(0, 0, W, H);
        lctx.globalCompositeOperation = "destination-out";
        for (const L of lights) {
            if (L.lv === 0) continue;
            const r = L.r * (L.lv ?? 1) * (L.flicker ? 0.9 + 0.1 * Math.sin(now / 90) : 1);
            const g = lctx.createRadialGradient(L.x, L.y, 0, L.x, L.y, r);
            g.addColorStop(0, "rgba(0,0,0,.85)");
            g.addColorStop(1, "rgba(0,0,0,0)");
            lctx.fillStyle = g;
            lctx.fillRect(L.x - r, L.y - r, r * 2, r * 2);
        }
        ctx.drawImage(light, 0, 0);
    }
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const glowBase = Math.max(inDark / 0.62, lamp * 0.55);
    for (const L of lights) {
        if (L.lv === 0) continue;
        const g = ctx.createRadialGradient(L.x, L.y, 0, L.x, L.y, L.r * 0.8);
        g.addColorStop(0, `rgba(${L.c},${0.16 * (L.lv ?? 1) * glowBase})`);
        g.addColorStop(1, `rgba(${L.c},0)`);
        ctx.fillStyle = g;
        ctx.fillRect(L.x - L.r, L.y - L.r, L.r * 2, L.r * 2);
    }
    ctx.restore();
}
function ambient(dt, now) {
    if (Math.random() < dt * 4)
        spawn({ type: "steam", x: 1006 + Math.random() * 3, y: 34, vx: 0, vy: -10, life: 1.6, max: 1.6 });
    for (const d of DESKS)
        if (deskBusy(d) && Math.random() < dt * 1.5)
            spawn({ type: "steam", x: d.x + 47 + Math.random() * 2, y: d.y - 1, vx: 0, vy: -8, life: 1.2, max: 1.2 });
    for (const w of workers.values())
        if (w.state === "hurt" && w.hasTea && !w.path.length && Math.random() < dt * 1.5)
            spawn({ type: "steam", x: w.x - 1 + Math.random() * 2, y: w.y - 16, vx: 0, vy: -8, life: 1.1, max: 1.1 });
    const T = clock();
    if (darkness(T) < 0.3 && T.wx === "clear" && Math.random() < dt * 10) {
        const wx = pick(WINDOWS, Math.random()),
            yy = WALL + Math.random() * (70 + golden(T) * 40),
            life = rnd(3, 6);
        spawn({
            type: "mote",
            x: wx + 4 + Math.random() * 26 + (yy - WALL) * 0.3,
            y: yy,
            vx: 0,
            vy: 0,
            life,
            max: life,
            seed: Math.random() * 9,
        });
    }
}

// display-space pass: crisp upscaling plus readable text
let S = 2;
// Scene fills the cabinet width; the canvas backing store is in device pixels so the
// nearest-neighbour upscale and the text drawn after it stay sharp.
const cabinet = stage.parentElement;
function resize() {
    const dpr = window.devicePixelRatio || 1,
        cs = getComputedStyle(cabinet);
    const cssW = cabinet.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    view.width = Math.round(cssW * dpr);
    view.height = Math.round((view.width * H) / W);
    S = view.width / W;
    view.style.width = cssW + "px";
    view.style.height = (cssW * H) / W + "px";
    vctx.imageSmoothingEnabled = false;
    // the full-size TV page keeps its 4:3 shape: as wide as fits the scene, never taller than it
    cfx.style.width = Math.min(cssW * 0.92, 640, (((cssW * H) / W) * 0.92 * 4) / 3) + "px";
}
// speech bubbles that would overlap stack upwards; rects is a flat [x, y, w, h, ...] list reused each frame
function dodge(rects, x, y, w, h, gap) {
    for (let moved = true, n = 0; moved && n < 8; n++) {
        moved = false;
        for (let i = 0; i < rects.length; i += 4) {
            const rx = rects[i],
                ry = rects[i + 1],
                rw = rects[i + 2],
                rh = rects[i + 3];
            if (x < rx + rw && x + w > rx && y < ry + rh && y + h > ry) {
                y = ry - h - gap;
                moved = true;
            }
        }
    }
    return y;
}
const quipRects = [];
function label(text, x, y, opts = {}) {
    const size = Math.max(
        Math.round((11 * (window.devicePixelRatio || 1) * (opts.size || 7)) / 7),
        Math.round((opts.size || 7) * S),
    );
    vctx.font = `${opts.weight || 600} ${size}px "Pixelify Sans"`;
    const tw = vctx.measureText(text).width,
        padX = Math.round(3 * S),
        padY = Math.round(1.5 * S),
        bh = size + padY * 2;
    const lx = Math.round(Math.min(Math.max(x * S - tw / 2 - padX, 2), view.width - tw - padX * 2 - 2));
    let ly = Math.round(y * S - bh);
    if (opts.dodge) {
        ly = dodge(opts.dodge, lx, ly, tw + padX * 2, bh + (opts.tail ? Math.round(3 * S) : 0), Math.round(S));
        opts.dodge.push(lx, ly, tw + padX * 2, bh + (opts.tail ? Math.round(3 * S) : 0));
    }
    vctx.fillStyle = opts.bg || "#0d0b16e0";
    vctx.fillRect(lx, ly, tw + padX * 2, bh);
    if (opts.border) {
        vctx.fillStyle = opts.border;
        vctx.fillRect(lx, ly + bh - Math.max(1, Math.round(S / 2)), tw + padX * 2, Math.max(1, Math.round(S / 2)));
    }
    if (opts.tail) {
        vctx.fillStyle = opts.bg;
        vctx.beginPath();
        vctx.moveTo(x * S - 3 * S, ly + bh);
        vctx.lineTo(x * S + 3 * S, ly + bh);
        vctx.lineTo(x * S, ly + bh + 3 * S);
        vctx.fill();
    }
    vctx.fillStyle = opts.color || "#f4ecff";
    vctx.textBaseline = "top";
    vctx.fillText(
        opts.reveal != null ? text.slice(0, opts.reveal) : text,
        lx + padX,
        ly + padY + Math.round(size * 0.05),
    );
    return ly;
}
function quipLabel(text, start, until, x, y, now) {
    // Measure and dodge on the full text so the bubble never shifts width or swaps stacking order as it types out.
    const reveal = Math.min(text.length, Math.floor((now - start) / 32) + 1);
    vctx.globalAlpha = clamp(Math.min((until - now) / 300, (now - start) / 120), 0, 1);
    label(text, x, y - Math.round(Math.max(0, 1 - (now - start) / 160) * 3), {
        size: 6.5,
        bg: "#fffaf0",
        color: "#1b1830",
        tail: true,
        weight: 500,
        reveal,
        dodge: quipRects,
    });
    vctx.globalAlpha = 1;
}
function present(now) {
    vctx.imageSmoothingEnabled = false;
    vctx.drawImage(scene, 0, 0, view.width, view.height);
    if (playerDarts.best) {
        // the user's best three darts, chalked on the games-room scoreboard
        vctx.font = `500 ${Math.round(6.5 * S)}px "Pixelify Sans"`;
        vctx.textBaseline = "alphabetic";
        vctx.textAlign = "center";
        vctx.fillStyle = "#e8e4d8d0";
        vctx.fillText(
            USER_NAME.toUpperCase() + " " + playerDarts.best,
            Math.round((SCORE.x + 19) * S),
            Math.round((SCORE.y + 26) * S),
        );
        vctx.textAlign = "left";
    }
    if (pong.active) {
        // table-tennis flip counter digits
        const nx = PONG.x + (PONG.w >> 1),
            by = PONG.y + PONG.h + 1;
        vctx.font = `600 ${Math.round(6 * S)}px "Pixelify Sans"`;
        vctx.textBaseline = "alphabetic";
        vctx.textAlign = "center";
        vctx.fillStyle = "#1b1830";
        vctx.fillText(String(pong.score[0]), Math.round((nx - 5) * S), Math.round(by * S));
        vctx.fillText(String(pong.score[1]), Math.round((nx + 6) * S), Math.round(by * S));
        vctx.textAlign = "left";
    }
    const sorted = [...workers.values()].sort((a, b) => a.y - b.y);
    quipRects.length = 0;
    for (const w of sorted) {
        const top = headY(w) - (w.state !== "resting" || (w.emote && now < w.emoteUntil) ? 16 : 3);
        const focus = w.id === hovered || w.id === selected;
        if (showNames || focus)
            label(whoOf(w), w.x, top, {
                size: focus ? 7 : 6,
                color: focus ? "#ffd166" : "#f4ecff",
                border: STATE_COL[w.state],
                dodge: quipRects,
            });
    }
    for (const w of sorted)
        if (w.newStarter && !showNames && w.id !== hovered && w.id !== selected)
            label("NEW", w.x, headY(w) - (w.state !== "resting" || (w.emote && now < w.emoteUntil) ? 16 : 3), {
                size: 5,
                bg: "#7ee0b5",
                color: "#0d0b16",
                weight: 700,
                dodge: quipRects,
            });
    for (const w of sorted)
        if (w.state === "hurt" && w.streak >= 2 && !showNames && w.id !== hovered && w.id !== selected)
            label("✕" + w.streak, w.x, headY(w) - 16, {
                size: 5,
                bg: "#ff6b6b",
                color: "#0d0b16",
                weight: 700,
                dodge: quipRects,
            });
    // front-most speaker keeps its spot; those behind lift above it
    for (let i = sorted.length - 1; i >= 0; i--) {
        const w = sorted[i],
            focus = w.id === hovered || w.id === selected;
        if (w.quip && now < w.quipUntil && now >= w.quipStart && !(showNames && !focus))
            quipLabel(
                w.quip,
                w.quipStart,
                w.quipUntil,
                w.x,
                headY(w) - (w.state !== "resting" || (w.emote && now < w.emoteUntil) ? 16 : 3) - (focus ? 12 : 1),
                now,
            );
    }
    drawCeefaxText(now);
    drawConsoleText(now);
    if (cat.quip && now < cat.quipUntil && now >= cat.quipStart)
        quipLabel(cat.quip, cat.quipStart, cat.quipUntil, cat.x, cat.y - 16, now);
    if (boardHover)
        label(
            boardHover.length > 60 ? boardHover.slice(0, 58) + "…" : boardHover,
            BOARD.x + BOARD.w / 2,
            BOARD.y + BOARD.h + 12,
            { size: 6, color: "#ffd166", border: "#e8964a", dodge: quipRects },
        );
    if (hovered === "cat" && !(cat.quip && now < cat.quipUntil))
        label("office cat", cat.x, cat.y - 16, { size: 6, color: "#ffd166", border: "#e8964a", dodge: quipRects });
    if (hovered === "console") {
        const g = CONSOLE_GAMES[consoleSlot(now).idx];
        label(g.name, GS.x + GS.w / 2, DEN.tv.y - 2, { size: 6, color: g.col, border: g.col, dodge: quipRects });
    }
    if (hovered === "userDesk")
        label(officeName() + " · door's open", USER_DESK.x + 29, USER_DESK.y - 22, {
            size: 6,
            color: "#ffd166",
            border: "#e8964a",
            dodge: quipRects,
        });
    if (hovered === "post")
        label(postText(), PIGEON.x + 18, PIGEON.y + PIGEON.h + 24, {
            size: 6,
            color: "#f4efe1",
            border: "#8c8ca0",
            dodge: quipRects,
        });
    if (hovered === "frame")
        label(eotwText(eotwView), FRAME.x + 14, FRAME.y + FRAME.h + 26, {
            size: 6,
            color: "#ffd166",
            border: "#e8964a",
            dodge: quipRects,
        });
    if (hovered === "copier")
        label("copier", COPIER.x + 26, COPIER.y - 2, {
            size: 6,
            color: "#ffd166",
            border: "#e8964a",
            dodge: quipRects,
        });
    if (hovered === "door")
        label("front door · badge ok", DOOR.x + 20, DOOR.y - 4, {
            size: 6,
            color: "#7ee0b5",
            border: "#7ee0b5",
            dodge: quipRects,
        });
    if (hovered === "call")
        label(
            counts.locked ? `Video call · ${counts.locked} waiting on sign-in` : "Video call · connected",
            CALL.x + 15,
            CALL.y - 4,
            {
                size: 6,
                color: counts.locked ? "#ff6b6b" : "#7ee0b5",
                border: counts.locked ? "#ff6b6b" : "#7ee0b5",
                dodge: quipRects,
            },
        );
    if (hint.kind && !ceefax.open) {
        // shortcut: hints are learnt per kind after 3 clicks (localStorage), no reset UI
        const age = performance.now() - hint.since,
            w = hint.id && workers.get(hint.id);
        const hSt = w ? w.state : hint.kind === "call" ? (counts.locked ? "locked" : null) : null;
        const hCanCancel = w ? !!(w.task && w.task.queued) : true;
        const text =
            age > HINT_DWELL && hintUses(hint.kind) < HINT_LEARNT ? hintFor(hint.kind, hSt, DEMO, hCanCancel) : null;
        if (text) {
            vctx.globalAlpha = REDUCED ? 1 : clamp((age - HINT_DWELL) / 150, 0, 1);
            label(text, hint.x, hint.y > H - 40 ? hint.y - 10 : hint.y + 22, {
                size: 5.5,
                bg: "#0d0b16c8",
                color: "#cfc8e8",
                weight: 500,
                dodge: quipRects,
            });
            vctx.globalAlpha = 1;
        }
    }
    if (drag.id && drag.moved) drawDrag();
    for (const p of parts)
        if (p.type === "float") {
            vctx.globalAlpha = Math.min(1, (p.life / p.max) * 2);
            label(p.text, p.x, p.y, { size: 8, bg: "#0000", color: p.c, weight: 700, dodge: quipRects });
            vctx.globalAlpha = 1;
        }
}

function drawDrag() {
    // tether from the worker's real spot to a ghost under the cursor; the worker itself never moves
    const w = workers.get(drag.id),
        t = tasks.find((x) => x.id === drag.id);
    if (!w || !t) return;
    const rm = roomAt(drag.x, drag.y),
        d = dropAction(behaviour(t), rm, DEMO, !!t.queued);
    const col = d.kind === "cancel" ? "#b79bff" : "#ffd166",
        bdr = d.kind === "cancel" ? "#7a5fd6" : "#e8964a";
    if (d.kind === "run") {
        const R = ROOMS.office;
        vctx.fillStyle = d.ok ? "#ffd16624" : "#ffd16610";
        vctx.fillRect(R.x0 * S, R.y0 * S, (R.x1 - R.x0) * S, (R.y1 - R.y0) * S);
    } else if (d.kind === "cancel") {
        for (const [k, R] of Object.entries(ROOMS))
            if (k !== "office") {
                vctx.fillStyle = d.ok && k === rm ? "#b79bff28" : "#b79bff10";
                vctx.fillRect(R.x0 * S, R.y0 * S, (R.x1 - R.x0) * S, (R.y1 - R.y0) * S);
            }
    }
    vctx.strokeStyle = d.ok ? col : "#cfc8e8a0";
    vctx.lineWidth = Math.max(1, Math.round(S));
    vctx.setLineDash([3 * S, 3 * S]);
    vctx.beginPath();
    vctx.moveTo(w.x * S, (w.y - 20) * S);
    vctx.lineTo(drag.x * S, drag.y * S);
    vctx.stroke();
    vctx.setLineDash([]);
    vctx.globalAlpha = 0.85;
    vctx.imageSmoothingEnabled = false;
    if (drag.face)
        vctx.drawImage(
            drag.face,
            Math.round((drag.x - 16) * S),
            Math.round((drag.y - 32) * S),
            Math.round(32 * S),
            Math.round(32 * S),
        );
    vctx.globalAlpha = 1;
    label(d.text, drag.x, drag.y + 14, { size: 6, color: d.ok ? col : "#cfc8e8", border: d.ok ? bdr : null });
}
