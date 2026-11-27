// Office page. Life in the background: the lounge TV (Ceefax), the office cat and the robot vacuum.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// ================================================================ lounge TV: Ceefax news
// Public BBC headlines from /api/news, laid out as Ceefax pages. A dead feed shows as not in transmission.
const ceefax = { data: null, failed: false, i: 0, shownAt: 0, open: false };
async function loadNews() {
    try {
        const r = await fetch("/api/news");
        if (!r.ok) throw new Error(r.status);
        ceefax.data = await r.json();
        ceefax.failed = false;
    } catch {
        ceefax.failed = true;
    }
    if (ceefax.open) renderCeefax();
}
// The wall TV is ambient office scenery, so distressing stories (violence, abuse, death) never air on it.
function grimNews(it) {
    return /\b(rap(e|ed|es|ing|ist)|abus(e|ed|es|er|ing)|sex(ual|ually)?|murder\w*|kill(s|ed|er|ing)?|stab(s|bed|bing)?|shot dead|shooting|assault\w*|paedophil\w*|grooming|suicide|terror\w*|massacre|genocide|tortur\w*|traffick\w*|drugged|died|dies|death|deaths|dead|bod(y|ies) found|bomb\w*|famine|war crimes?)\b/i.test(
        `${(it && it.title) || ""} ${(it && it.summary) || ""}`,
    );
}
function ceefaxPages() {
    const s = (ceefax.data && ceefax.data.sections) || {},
        out = [];
    (s.news || [])
        .filter((it) => !grimNews(it))
        .forEach((it, k) =>
            out.push({
                no: 101 + k,
                sec: "NEWS",
                col: "#ffff00",
                title: it.title,
                summary: it.summary,
                body: it.body || [],
            }),
        );
    if (bz.data)
        out.push({
            no: 152,
            sec: "QUIZ",
            col: "#ff00ff",
            quiz: true,
            title: "BAMBOOZLE!",
            summary: "Ten questions. Click to play!",
        });
    (s.sport || [])
        .filter((it) => !grimNews(it))
        .forEach((it, k) =>
            out.push({
                no: 302 + k,
                sec: "SPORT",
                col: "#00ff00",
                title: it.title,
                summary: it.summary,
                body: it.body || [],
            }),
        );
    return out;
}
function ceefaxPage(now) {
    const pages = ceefaxPages();
    if (!pages.length) return null;
    if (!ceefax.shownAt)
        ceefax.shownAt = now - 1000; // first page appears settled, not mid-roll
    else if (!ceefax.open && now - ceefax.shownAt > 12000) {
        ceefax.i = (ceefax.i + 1) % pages.length;
        ceefax.shownAt = now;
    }
    return pages[ceefax.i % pages.length];
}
const pad2 = (n) => String(n).padStart(2, "0");
function ceefaxClock() {
    const d = new Date(),
        T = clock();
    return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][T.day]} ${pad2(d.getDate())} ${d.toLocaleString("en-GB", { month: "short" })} ${pad2(T.h)}:${pad2(T.m)}/${pad2(Math.floor(T.s))}`;
}
// wrap to at most `max` lines of `cols` characters
function wrapText(text, cols, max) {
    const words = String(text || "").split(/\s+/),
        lines = [];
    let cur = "";
    for (const wd of words) {
        if ((cur + " " + wd).trim().length > cols) {
            lines.push(cur);
            cur = wd;
            if (lines.length === max) break;
        } else cur = (cur + " " + wd).trim();
    }
    if (lines.length < max && cur) lines.push(cur);
    if (lines.length === max && words.join(" ").length > lines.join(" ").length)
        lines[max - 1] = lines[max - 1].slice(0, cols - 1).replace(/\s+\S*$/, "") + "…";
    return lines;
}
// Wall-mounted flat screen: drop shadow, rounded bezel with a chin, logo, standby light.
function drawTvSet() {
    const { x, y, w, h } = TV,
        L = x - 4,
        T = y - 4,
        R = x + w + 4,
        B = y + h + 7;
    const rr = (c, x0, y0, x1, y1) => {
        bx.fillStyle = c;
        bx.fillRect(x0 + 1, y0, x1 - x0 - 2, y1 - y0);
        bx.fillRect(x0, y0 + 1, x1 - x0, y1 - y0 - 2);
    };
    rr("#00000038", L + 2, T + 3, R + 3, B + 3); // stands off the wall on its bracket
    rr("#0b0a12", L, T, R, B);
    rr("#1c1a26", L + 1, T + 1, R - 1, B - 1);
    bx.fillStyle = "#3a3848";
    bx.fillRect(L + 2, T + 1, R - L - 4, 1);
    bx.fillRect(L + 1, T + 2, 1, B - T - 4); // top-left catches the light
    bx.fillStyle = "#121019";
    bx.fillRect(L + 2, B - 2, R - L - 4, 1);
    bx.fillStyle = "#08070d";
    bx.fillRect(x - 1, y - 1, w + 2, h + 2); // recessed glass edge
    bx.fillStyle = "#8a8898";
    bx.fillRect(x + w / 2 - 3, y + h + 3, 6, 1); // logo
    bx.fillStyle = "#d94848";
    bx.fillRect(R - 6, y + h + 3, 1, 1); // standby light
}
function drawCeefaxScreen(now) {
    const { x, y, w, h } = TV,
        pg = ceefaxPage(now);
    ctx.fillStyle = "#000";
    ctx.fillRect(x, y, w, h);
    if (!pg) return;
    const rolling = now - ceefax.shownAt < 700;
    if (!rolling) {
        ctx.fillStyle = "#0000d6";
        ctx.fillRect(x, y + 7, w, 12);
        ctx.fillStyle = "#fff";
        for (let i = 0; i < 3; i++) ctx.fillRect(x + 3 + i * 7, y + 9, 6, 8);
        if (pg.quiz)
            for (const [bx0, by0, c] of bamberCells()) {
                ctx.fillStyle = c;
                ctx.fillRect(x + w - 33 + bx0, y + 21 + by0, 1, 1);
            }
    }
    // glass glare: a faint diagonal sheen across the top-left
    ctx.fillStyle = "#ffffff0d";
    for (let i = 0; i < 22; i++) ctx.fillRect(x + i * 2, y, 2, Math.max(0, 22 - i));
    if (now < tvFlashUntil) {
        ctx.fillStyle = "#ffd16640";
        ctx.fillRect(x, y, w, h);
    }
}
// text goes on after the upscale so it stays crisp; sizes are in scene pixels
function drawCeefaxText(now) {
    const { x, y, w } = TV,
        pg = ceefaxPage(now),
        font = (px) => `${Math.round(px * S)}px "Press Start 2P"`;
    const txt = (t, tx, ty, px, col) => {
        vctx.font = font(px);
        vctx.fillStyle = col;
        vctx.fillText(t, Math.round(tx * S), Math.round(ty * S));
    };
    vctx.textBaseline = "top";
    if (!pg) {
        txt(ceefax.failed ? "NOT IN TRANSMISSION" : "CEEFAX: TUNING…", x + 6, y + 28, 4.5, "#ffff00");
        return;
    }
    const rolling = now - ceefax.shownAt < 700;
    const no = rolling ? 100 + Math.floor(hash(Math.floor(now / 60)) * 800) : pg.no;
    txt(`P${pg.no} CEEFAX 1 ${no} ${ceefaxClock()}`, x + 2, y + 2, 2.8, "#fff");
    if (rolling) return;
    "BBC".split("").forEach((c, i) => txt(c, x + 3.75 + i * 7, y + 10.75, 4.5, "#0000d6"));
    txt(pg.sec, x + 26, y + 9, 8, pg.col);
    const lines = wrapText(pg.title, 21, 3);
    lines.forEach((l, i) => txt(l, x + 3, y + 22 + i * 7, 5, "#fff"));
    (pg.quiz ? wrapText(pg.summary, 16, 2) : wrapText(pg.summary, 32, 1)).forEach((l, i) =>
        txt(l, x + 3, y + 23 + lines.length * 7 + i * 5, 3.2, "#00ffff"),
    );
    [
        ["News", "#ff0000"],
        ["Sport", "#00ff00"],
        ["Weather", "#ffff00"],
        ["TV", "#00ffff"],
    ].forEach(([t, c], i) => txt(t, x + 3 + i * (w / 4), y + 58, 3.2, c));
}
// the full-size page: click the TV
const cfx = document.getElementById("ceefax");
function renderCeefax() {
    const pages = ceefaxPages(),
        pg = pages[ceefax.i % (pages.length || 1)];
    const head = `<div class="cx-head"><span>P${pg ? pg.no : 100} CEEFAX 1</span><span>${esc(ceefaxClock())}</span></div>`;
    const page = (inner) => {
        cfx.innerHTML = `<div class="cx-page">${head}${inner}</div>`;
    };
    if (!pg) {
        page(`<div class="cx-body cx-off">${ceefax.failed ? "PAGE NOT IN TRANSMISSION" : "SEARCHING…"}</div>`);
        return;
    }
    const same = pages.filter((p) => p.sec === pg.sec);
    const fast =
        `<div class="cx-fast"><button data-go="news" style="color:#f00">News</button><button data-go="sport" style="color:#0f0">Sport</button>` +
        `${bz.data ? `<button data-go="quiz" style="color:#f0f">Quiz</button>` : ""}<button data-go="prev" style="color:#ff0">◀ Prev</button><button data-go="next" style="color:#0ff">Next ▶</button></div>`;
    if (pg.quiz) {
        page(renderBamboozle() + fast);
        return;
    }
    page(
        `<div class="cx-band"><span class="cx-bbc"><b>B</b><b>B</b><b>C</b></span><span class="cx-sec" style="color:${pg.col}">${pg.sec}</span><span class="cx-no">${pg.no}</span></div>` +
            `<div class="cx-body"><h3>${esc(pg.title)}</h3><p class="cx-sum">${esc(pg.summary)}</p>${(pg.body || []).map((t) => `<p class="cx-txt">${esc(t)}</p>`).join("")}` +
            `<ul class="cx-idx">${same
                .slice(0, 8)
                .map(
                    (p) =>
                        `<li data-no="${p.no}" class="${p === pg ? "on" : ""}"><span>${p.no}</span><span>${esc(p.title)}</span></li>`,
                )
                .join("")}</ul></div>` +
            fast,
    );
}

// ---------------------------------------------------------------- Bamboozle! (page 152)
// Ten fresh questions a day from /api/bamboozle, easiest first. A wrong answer sends you back to the start.
const BZ_KEYS = [
    ["#ff0000", "1"],
    ["#00ff00", "2"],
    ["#ffff00", "3"],
    ["#3b82ff", "4"],
];
const bz = { data: null, failed: false, game: { state: "title", i: 0, pick: null } };
// Quizmaster Bamber Boozler, sampled sixel by sixel from the Channel 4 Teletext p140 title page:
// grinning yellow face, white headphones, blue hand raised, white collar. Mode 7 colours only.
const BAMBER = [
    ".............WWWWWWWWWW.........",
    "...........WW..........WWWW.....",
    "..........WW..........Y....W....",
    ".........W...........YY.....W...",
    ".........W.........YYYYY....W...",
    "...........YYYYYYYYYYYYYY...WW..",
    "...........Y..YYYYYY..YYY....W..",
    "..........Y..YYYYYYYY..YY....W..",
    "..........Y.Y.YYYYYY.Y.YY.......",
    "..........Y.Y.YYYYYY.Y.YYY..YY..",
    "..........YYY.Y.YYYY.YYYYY..YYY.",
    "..........YYYYY.YYYYYYYYYY.YY.Y.",
    "...........YYY.YYYYY.YYY..YY.YY.",
    "..........YY...YYYYY...YY..YYY..",
    ".........YY..Y..YYY..Y..YY.YY...",
    ".........YY.YYY.....YYY..YYY....",
    ".........Y...YYYYYYYYY...YYYY...",
    ".........Y.Y...YYYYYY..Y.YY.Y...",
    ".........YYYYY........YYYYY.Y...",
    "..........YYYYYYYYYYYYYYYY..Y...",
    ".....B.B...YYYYY...YYYYYYY.YY...",
    "....BB.BB...YYYYYYYYYYYYY..Y....",
    "...BBB..B......YYYYYYYY...Y.....",
    ".B.BBBB.BBB.....................",
    ".BBBBBB..BBB...WW.........WWW...",
    ".BBBBBBB.BBBB..WWWW....WWWWWW...",
    ".BBBBBBB.BBBB..WWWW....WWWWWW...",
    "BBBBBBBB..BBB..WWWWW..WWWWWW....",
];
const BAMBER_COL = { B: "#2233ff", Y: "#ffff00", W: "#ffffff" };
let bamberCache = null;
function bamberCells() {
    if (bamberCache) return bamberCache;
    const out = (bamberCache = []);
    BAMBER.forEach((row, y) =>
        [...row].forEach((c, x) => {
            if (BAMBER_COL[c]) out.push([x, y, BAMBER_COL[c]]);
        }),
    );
    return out;
}
const bamberSvg = () =>
    `<svg viewBox="0 0 32 28" preserveAspectRatio="none" shape-rendering="crispEdges" role="img" aria-label="Bamber Boozler, the quizmaster">` +
    bamberCells()
        .map(([x, y, c]) => `<rect x="${x}" y="${y}" width="1" height="1" fill="${c}"/>`)
        .join("") +
    `</svg>`;
// pure game step: title -> q -> right/over/won; "go" is Enter/Space (start, next, try again)
function bamboozleStep(g, act, k, quiz) {
    const n = quiz.questions.length;
    if (act === "go")
        act =
            g.state === "title" || g.state === "over" || g.state === "won"
                ? "start"
                : g.state === "right"
                  ? "next"
                  : "";
    if (act === "start") return { state: "q", i: 0, pick: null };
    if (act === "next" && g.state === "right") return { state: "q", i: g.i + 1, pick: null };
    if (act === "pick" && g.state === "q" && k >= 0 && k < 4) {
        if (k !== quiz.questions[g.i].answer) return { ...g, state: "over", pick: k };
        return { ...g, state: g.i === n - 1 ? "won" : "right", pick: k };
    }
    return g;
}
const bzKey = () => "office-bamboozle-" + (bz.data ? bz.data.date : "");
function bzRecord() {
    try {
        return JSON.parse(localStorage.getItem(bzKey()) || "null") || { best: 0, won: false };
    } catch (e) {
        return { best: 0, won: false };
    }
}
function bzSave(score, won) {
    const r = bzRecord();
    r.best = Math.max(r.best, score);
    r.won = r.won || won;
    try {
        localStorage.setItem(bzKey(), JSON.stringify(r));
    } catch (e) {
        /* ignore */
    }
}
async function loadQuiz() {
    try {
        const r = await fetch("/api/bamboozle");
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        if (!bz.data || bz.data.date !== d.date) {
            bz.game = { state: "title", i: 0, pick: null };
        } // a new day is a new game
        bz.data = d;
        bz.failed = false;
    } catch {
        bz.failed = true;
    }
    if (ceefax.open) renderCeefax();
}
function renderBamboozle() {
    const d = bz.data,
        g = bz.game,
        n = d.questions.length,
        rec = bzRecord();
    const rainbow = "BAMBOOZLE!"
        .split("")
        .map((c, i) => `<span style="color:${["#f00", "#0f0", "#ff0", "#0ff", "#f0f", "#fff"][i % 6]}">${c}</span>`)
        .join("");
    const band = `<div class="cx-band"><span class="bz-title">${rainbow}</span><span class="cx-no">152</span></div>`;
    let body;
    if (g.state === "title") {
        body =
            `<div class="bz-host">${bamberSvg()}<div><p>Hello! I'm <span style="color:#ff0">Bamber Boozler</span>. ${n} questions, easiest first. Answer one wrong and you're <span style="color:#f00">BAMBOOZLED</span>: back to the start.</p>` +
            `<p style="color:#0ff">${rec.won ? "You've beaten today's quiz!" : rec.best ? `Today's best: ${rec.best}/${n}` : "Fresh questions every day."}</p></div></div>` +
            (d.stale ? `<p class="bz-note">Quiz server off air: yesterday's questions</p>` : "") +
            `<p><button class="bz-go" data-bz="start">▶ PRESS ENTER TO PLAY</button></p>`;
    } else {
        const q = d.questions[g.i],
            done = g.state !== "q";
        const opts = q.options
            .map((o, k) => {
                const cls = done && k === q.answer ? "right" : done && k === g.pick ? "wrong" : "";
                return `<button class="bz-opt ${cls}" data-bz="pick" data-k="${k}"${done ? " disabled" : ""}><span class="bz-key" style="background:${BZ_KEYS[k][0]}">${BZ_KEYS[k][1]}</span><span>${esc(o)}${cls === "right" ? " ✓" : cls === "wrong" ? " ✗" : ""}</span></button>`;
            })
            .join("");
        const say = {
            q: "",
            right: `<div class="bz-say" style="color:#0f0">CORRECT!</div><p><button class="bz-go" data-bz="next">▶ Question ${g.i + 2} (ENTER)</button></p>`,
            over: `<div class="bz-say bz-flash" style="color:#f00">BAMBOOZLED!</div><p>You scored ${g.i}/${n}. <button class="bz-go" data-bz="start">▶ Try again (ENTER)</button></p>`,
            won: `<div class="bz-say bz-flash" style="color:#ff0">YOU BEAT BAMBOOZLE!</div><p>${n}/${n}. Fresh questions tomorrow. <button class="bz-go" data-bz="start">▶ Again</button></p>`,
        }[g.state];
        body = `<p class="bz-meta">Q${g.i + 1}/${n}  ${esc(q.category)}  ${esc(q.difficulty.toUpperCase())}</p><h3>${esc(q.question)}</h3><div class="bz-opts">${opts}</div>${say}`;
    }
    return `${band}<div class="cx-body bz">${body}<p class="bz-note">Keys 1-4 answer · Questions: ${esc(d.source)}</p></div>`;
}
function bamboozleAct(act, k) {
    if (!bz.data) return;
    const before = bz.game,
        g = (bz.game = bamboozleStep(before, act, k, bz.data));
    if (g === before) return;
    if (g.state === "over") bzSave(g.i, false);
    else if (g.state === "won") bzSave(bz.data.questions.length, true);
    renderCeefax();
}
const onQuizPage = () => {
    const pages = ceefaxPages();
    return ceefax.open && !!(pages[ceefax.i % (pages.length || 1)] || {}).quiz;
};
function openCeefax(open) {
    ceefax.open = open;
    cfx.hidden = !open;
    if (open) renderCeefax();
}
cfx.addEventListener("click", (e) => {
    const z = e.target.closest("[data-bz]");
    if (z) {
        bamboozleAct(z.dataset.bz, Number(z.dataset.k));
        return;
    }
    if (e.target.closest(".bz")) return; // clicking the quiz text must not switch the TV off
    const pages = ceefaxPages(),
        li = e.target.closest("li[data-no]"),
        b = e.target.closest("button[data-go]");
    if (li) ceefax.i = pages.findIndex((p) => p.no === Number(li.dataset.no));
    else if (b) {
        const go = b.dataset.go,
            n = pages.length || 1;
        if (go === "next") ceefax.i = (ceefax.i + 1) % n;
        else if (go === "prev") ceefax.i = (ceefax.i - 1 + n) % n;
        else {
            const k = pages.findIndex((p) => p.sec === go.toUpperCase());
            if (k >= 0) ceefax.i = k;
        }
    } else {
        openCeefax(false);
        return;
    }
    ceefax.shownAt = tnow();
    renderCeefax();
});
const hitTV = (p) => p.x > TV.x && p.x < TV.x + TV.w && p.y > TV.y && p.y < TV.y + TV.h;

// ================================================================ the office cat
const CAT = {
    walk1: [
        "...........d.d.",
        "...........ooo.",
        "d.........ooeop",
        ".d........ooooo",
        ".doooooooooooo.",
        "..ooodoodooowo.",
        "..oooooooooowo.",
        "..o...o..o...o.",
        "..o...o..o...o.",
    ],
    walk2: [
        "...........d.d.",
        "...........ooo.",
        "d.........ooeop",
        ".d........ooooo",
        ".doooooooooooo.",
        "..ooodoodooowo.",
        "..oooooooooowo.",
        "...o.o....o.o..",
        "...o.o....o.o..",
    ],
    sit: [
        "......d.d..",
        "......ooo..",
        ".....ooeop.",
        ".....ooooo.",
        "......owo..",
        ".....oowo..",
        "....ooodo..",
        "d...oooooo.",
        ".d..ooooo..",
        "..ddoo.oo..",
    ],
    sitL: [
        "......d.d..",
        "......ooo..",
        ".....ooeop.",
        ".....ooooo.",
        "......owo..",
        ".....oowo..",
        "....ooodo..",
        "....oooooo.",
        "d...ooooo..",
        ".dddoo.oo..",
    ],
    sleep: ["..d.d.........", ".ooooo........", "oodooooooooo..", "oooooodoodooo.", ".ooooooooooood", "..dddddddddd.."],
};
const CAT_PAL =
    SEASON === "friday13" // a black cat for Friday the 13th, yellow-eyed
        ? { o: "#2b2833", d: "#141219", e: "#f2d36b", p: "#c97b8a", w: "#45414f" }
        : { o: "#e8964a", d: "#9c5524", e: "#1b1830", p: "#ff9fb0", w: "#fff3e0" };
const cat = {
    x: 500,
    y: 420,
    dir: 1,
    path: [],
    mode: "sit",
    next: "sit",
    until: 0,
    dist: 0,
    follow: null,
    followUntil: 0,
    repath: 0,
    petCd: 0,
    ride: false,
    toBot: false,
    visit: null,
    visitBed: false,
    onDesk: null,
    onBed: null,
    deskIdx: -1,
    shooed: false,
    hopFrom: null,
    hopAt: 0,
    quip: null,
    quipStart: 0,
    quipUntil: 0,
    swish: 0,
};
function randomFloor() {
    for (let i = 0; i < 60; i++) {
        const x = rnd(12, W - 12),
            y = rnd(WALL + 24, H - 14);
        if (walkablePx(x, y)) return { x, y };
    }
    return { x: 500, y: 420 };
}
function catSpots(night) {
    const T = clock();
    if (night || darkness(T) > 0.25 || T.wx !== "clear")
        return [
            { x: RACK.x - 14, y: RACK.y + 40 },
            { x: 500, y: 560 },
            { x: 430, y: 640 },
            { x: 1180, y: 250 },
            { x: DOCK.x + 22, y: DOCK.y },
        ];
    return WINDOWS.map((wx) => ({ x: wx + 36, y: WALL + 30 })).concat([
        { x: 500, y: 560 },
        { x: 1110, y: 140 },
        { x: 980, y: 660 },
    ]);
}
function catGo(x, y, next) {
    cat.path = findPath(cat.x, cat.y, x, y);
    cat.next = next || "sit";
    cat.mode = "walk";
}
// the cat supervises: it pads over to someone really at work (deskBusy), sits by their chair and gets a look.
// Once a run is way over (tier 3, >=250%), the warm laptop is too tempting: it hops up onto the keyboard until shooed off.
// When someone is in the sick bay on the hospital bed, the cat also plays nurse and curls up on the foot of the bed.
function catShouldHop(p, hopped) {
    return !hopped && tension(p) >= 3;
}
function catVisitSpot(busy, r) {
    if (!busy.length) return null;
    const hot = busy.filter((d) => d.hop),
        pool = hot.length ? hot : busy;
    const d = pool[Math.floor(r * pool.length) % pool.length],
        x = d.seat.x - 14,
        y = d.seat.y + 8;
    if (!walkablePx(x, y)) return null;
    return d.hop ? { x, y, owner: d.owner, hop: true, kx: d.x + 15, ky: d.y + 11 } : { x, y, owner: d.owner };
}
function catSickSpot(patients) {
    const bed = (patients || []).find((w) => w.line === 0 && !w.catBedDone);
    if (!bed) return null;
    const x = BED.x + 23,
        y = BED.y + 66;
    if (!walkablePx(x, y)) return null;
    return { x, y, owner: bed.id, bed: true, bx: BED.x + 31, by: BED.y + 52 };
}
function hurtPatients() {
    return [...workers.values()]
        .filter((w) => w.state === "hurt")
        .map((w) => {
            const stamp = (w.task && w.task.last_run) || "hurt";
            return { id: w.id, line: w.line, catBedDone: w.catBedFor === stamp };
        });
}
function busyDesks() {
    return DESKS.filter(deskBusy).map((d) => {
        const w = workers.get(d.owner),
            s = runStart.get(d.owner);
        return w && s && catShouldHop(progressOf(w.task), w.catHopFor === s) ? { ...d, hop: true } : d;
    });
}
function catHopDown(now) {
    const id = cat.onDesk,
        d = DESKS[cat.deskIdx];
    cat.onDesk = null;
    cat.deskIdx = -1;
    cat.shooed = false;
    if (d) {
        cat.hopFrom = { x: cat.x, y: cat.y };
        cat.hopAt = now;
        cat.x = d.seat.x - 14;
        cat.y = d.seat.y + 8;
        cat.dir = -1;
    }
    const p = randomFloor();
    catGo(p.x, p.y, "sit");
    if (selected && selected === id) renderDossier();
}
function catHopOffBed(now) {
    const id = cat.onBed;
    cat.onBed = null;
    cat.hopFrom = { x: cat.x, y: cat.y };
    cat.hopAt = now;
    cat.x = BED.x + 23;
    cat.y = BED.y + 66;
    cat.dir = 1;
    const p = randomFloor();
    catGo(p.x, p.y, "sit");
    if (selected && selected === id) renderDossier();
}
function catVisited(now) {
    const w = workers.get(cat.visit),
        toBed = cat.visitBed;
    if (toBed) {
        if (!w || w.state !== "hurt" || w.line !== 0) {
            cat.visit = null;
            cat.visitBed = false;
            return;
        }
        if (w.path.length) return; // wait at the foot of the bed until the patient sits down
        cat.visit = null;
        cat.visitBed = false;
        if (Math.hypot(w.x - cat.x, w.y - cat.y) > 34) return;
        w.catBedFor = (w.task && w.task.last_run) || "hurt";
        cat.onBed = w.id;
        cat.hopFrom = { x: cat.x, y: cat.y };
        cat.hopAt = now;
        cat.x = BED.x + 31;
        cat.y = BED.y + 52;
        cat.dir = -1;
        cat.mode = "sleep";
        cat.until = now + 38000;
        catHearts();
        w.emote = "heart";
        w.emoteUntil = now + 3200;
        say(w, pick(QUIPS.catbed, Math.random()), now);
        catSay(pick(["prrrr", "mrrp", "purrrr"], Math.random()), now + 700);
        if (selected === w.id) renderDossier();
        return;
    }
    cat.visit = null;
    cat.visitBed = false;
    if (!w || w.state !== "working" || !w.desk || w.path.length || Math.hypot(w.x - cat.x, w.y - cat.y) > 24) return;
    const s = runStart.get(w.id);
    if (s && catShouldHop(progressOf(w.task), w.catHopFor === s)) {
        w.catHopFor = s;
        cat.onDesk = w.id;
        cat.deskIdx = DESKS.indexOf(w.desk);
        cat.shooed = false;
        cat.hopFrom = { x: cat.x, y: cat.y };
        cat.hopAt = now;
        cat.x = w.desk.x + 15;
        cat.y = w.desk.y + 11;
        cat.dir = 1;
        cat.mode = "sit";
        cat.until = now + 14000;
        w.glanceDir = "left";
        w.glanceUntil = now + 14200;
        w.emote = "bang";
        w.emoteUntil = now + 3400;
        say(w, pick(QUIPS.catkeys, Math.random()), now);
        catSay(pick(["prrrr", "mrrp", "meow"], Math.random()), now + 900);
        if (selected === w.id) renderDossier();
        return;
    }
    cat.dir = 1;
    cat.until = now + rnd(6000, 10000);
    w.glanceDir = "left";
    w.glanceUntil = now + 2600;
    w.emote = "heart";
    w.emoteUntil = now + 2200;
    if (now - lastQuip > 4000) say(w, pick(QUIPS.catdesk, Math.random()), now);
    catSay(pick(["mrrp", "meow?", "prrrr"], Math.random()), now + 1500);
}
function catSay(text, now) {
    cat.quip = text;
    cat.quipStart = now;
    cat.quipUntil = now + 1800;
}
function catHearts() {
    for (let i = 0; i < 3; i++)
        spawn({
            type: "icon",
            name: "heart",
            x: cat.x - 3 + (i - 1) * 6,
            y: cat.y - 16 - i * 3,
            vx: (i - 1) * 4,
            vy: -12,
            life: 1.3,
            max: 1.3,
        });
}
function catStep(dt, now) {
    const night = isNight();
    if (cat.ride) {
        if (!bot.active || now > cat.until) {
            cat.ride = false;
            cat.y = bot.y + 8;
            if (!walkablePx(cat.x, cat.y)) cat.y = bot.y;
            cat.mode = "sit";
            cat.until = now + 3000;
        } else {
            cat.x = bot.x;
            cat.y = bot.y;
            cat.dir = Math.cos(bot.a) < 0 ? -1 : 1;
            return;
        }
    }
    if (cat.onDesk) {
        const w = workers.get(cat.onDesk);
        if (!w || w.state !== "working" || !w.desk || w.path.length) {
            catHopDown(now);
            return;
        }
        w.glanceDir = "left";
        w.glanceUntil = Math.max(w.glanceUntil || 0, now + 400);
        if (!cat.shooed && now >= cat.until - 3000) {
            cat.shooed = true;
            w.emote = "wave";
            w.emoteUntil = now + 2600;
            say(w, pick(QUIPS.catshoo, Math.random()), now);
        }
        if (now >= cat.until) {
            catSay(pick(["mrrp!", "mew!", "hmpf"], Math.random()), now);
            catHopDown(now);
        }
        return;
    }
    if (cat.onBed) {
        const w = workers.get(cat.onBed);
        if (!w || w.state !== "hurt" || w.line !== 0 || w.path.length) {
            catHopOffBed(now);
            return;
        }
        if (Math.random() < dt * 0.35)
            spawn({ type: "zz", x: cat.x + 3, y: cat.y - 12, vx: 3, vy: -6, life: 2, max: 2 });
        if (now >= cat.until) {
            catSay(pick(["mrrp", "prrrr"], Math.random()), now);
            catHopOffBed(now);
        }
        return;
    }
    if (!cat.visit && !cat.toBot) {
        const v = catVisitSpot(busyDesks(), Math.random());
        if (v && v.hop) {
            cat.follow = null;
            cat.visit = v.owner;
            cat.visitBed = false;
            catGo(v.x, v.y, "sit");
        } else {
            const sb = catSickSpot(hurtPatients());
            if (sb) {
                cat.follow = null;
                cat.visit = sb.owner;
                cat.visitBed = true;
                catGo(sb.x, sb.y, "sit");
            }
        }
    }
    if (cat.follow) {
        const w = workers.get(cat.follow);
        if (!w || now > cat.followUntil || !w.path.length) {
            cat.follow = null;
            cat.path = [];
            cat.mode = "sit";
            cat.until = now + rnd(2000, 6000);
        } else if (now > cat.repath) {
            cat.repath = now + 700;
            const off = { left: [14, 0], right: [-14, 0], up: [0, 12], down: [0, -12] }[w.dir];
            catGo(w.x + off[0], w.y + off[1], "sit");
        }
    }
    if (cat.toBot && now > cat.repath) {
        cat.repath = now + 600;
        if (!bot.active) {
            cat.toBot = false;
        } else catGo(bot.x, bot.y, "sit");
    }
    if (cat.path.length) {
        if (cat.visit) {
            const vw = workers.get(cat.visit);
            if (
                cat.visitBed ? !vw || vw.state !== "hurt" || vw.line !== 0 : !vw || vw.state !== "working" || !vw.desk
            ) {
                cat.visit = null;
                cat.visitBed = false;
                cat.path = [];
                cat.mode = "sit";
                cat.until = now + 2000;
                return;
            }
        }
        const tgt = cat.path[0],
            dx = tgt.x - cat.x,
            dy = tgt.y - cat.y,
            d = Math.hypot(dx, dy),
            sp = (cat.follow ? 44 : cat.toBot ? 38 : cat.visit ? 36 : 24) * dt;
        if (d <= sp) {
            cat.x = tgt.x;
            cat.y = tgt.y;
            cat.path.shift();
            cat.dist += d;
        } else {
            cat.x += (dx / d) * sp;
            cat.y += (dy / d) * sp;
            cat.dist += sp;
        }
        if (Math.abs(dx) > 0.4) cat.dir = dx < 0 ? -1 : 1;
        cat.mode = "walk";
        if (SEASON === "friday13" && now > cat.petCd) {
            const w = crossedBy(cat, workers.values());
            if (w) {
                // the black cat crosses a colleague's path
                cat.petCd = now + 20000;
                w.lookDir = dirTo(w, cat.x, cat.y);
                w.lookUntil = now + 2400;
                w.emote = "bang";
                w.emoteUntil = now + 1800;
                if (now - lastQuip > 4000) say(w, pick(QUIPS.blackcat, Math.random()), now);
            }
        }
        if (cat.toBot && bot.active && Math.hypot(bot.x - cat.x, bot.y - cat.y) < 10) {
            cat.toBot = false;
            cat.path = [];
            cat.ride = true;
            cat.until = now + rnd(15000, 35000);
            return;
        }
        if (!cat.path.length && !cat.follow) {
            cat.toBot = false;
            cat.mode = cat.next;
            cat.until =
                now + (cat.mode === "sleep" ? (night ? rnd(40000, 90000) : rnd(20000, 45000)) : rnd(4000, 10000));
        }
        return;
    }
    if (cat.follow || cat.toBot) return;
    if (cat.mode === "walk") cat.mode = "sit";
    if (cat.visit) {
        catVisited(now);
        if (cat.onDesk || cat.onBed) return;
    }
    if (cat.mode === "sleep" && Math.random() < dt * 0.3)
        spawn({ type: "zz", x: cat.x + 3, y: cat.y - 12, vx: 3, vy: -6, life: 2, max: 2 });
    // a passing colleague stops to give the cat a fuss
    if (now > cat.petCd)
        for (const w of workers.values()) {
            if (
                w.state !== "resting" ||
                w.path.length ||
                (w.spot && w.spot.pose) ||
                Math.hypot(w.x - cat.x, w.y - cat.y) > 22
            )
                continue;
            cat.petCd = now + 18000;
            w.lookDir = dirTo(w, cat.x, cat.y);
            w.lookUntil = now + 2600;
            w.emote = "heart";
            w.emoteUntil = now + 2200;
            catHearts();
            if (cat.mode === "sleep") cat.mode = "sit";
            if (now - lastQuip > 5000 && Math.random() < 0.5) say(w, pick(QUIPS.cat, Math.random()), now);
            break;
        }
    if (now < cat.until) return;
    const r = Math.random(),
        walkers = [...workers.values()].filter((w) => w.path.length && w.state === "resting");
    if (bot.active && !bot.docked && r < 0.22) {
        cat.toBot = true;
        cat.repath = 0;
        return;
    }
    if (walkers.length && r < 0.4) {
        cat.follow = pick(walkers, Math.random()).id;
        cat.followUntil = now + 9000;
        cat.repath = 0;
        return;
    }
    if (r < 0.52) {
        const v = catVisitSpot(busyDesks(), Math.random());
        if (v) {
            cat.visit = v.owner;
            catGo(v.x, v.y, "sit");
            return;
        }
    }
    if (r < 0.68) {
        const s = pick(catSpots(night), Math.random());
        catGo(s.x + rnd(-6, 6), s.y + rnd(-4, 4), "sleep");
        return;
    }
    const p = randomFloor();
    catGo(p.x, p.y, "sit");
}
// an off-shift colleague walking within a stride of the cat, cat ahead of them (not trailing behind)
function crossedBy(c, ws) {
    for (const w of ws) {
        if (w.state !== "resting" || !w.path.length) continue;
        const dx = c.x - w.x,
            dy = c.y - w.y;
        if (Math.hypot(dx, dy) > 20) continue;
        const f = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] }[w.dir] || [0, 0];
        if (dx * f[0] + dy * f[1] > 0) return w;
    }
    return null;
}
const HOP_MS = 280;
function drawCat(now) {
    const flip = cat.dir < 0,
        hopping = cat.hopAt && !REDUCED && now >= cat.hopAt && now - cat.hopAt < HOP_MS;
    let cx = cat.x,
        cy = cat.y;
    if (hopping && cat.hopFrom) {
        const u = (now - cat.hopAt) / HOP_MS;
        cx = cat.hopFrom.x + (cat.x - cat.hopFrom.x) * u;
        cy = cat.hopFrom.y + (cat.y - cat.hopFrom.y) * u - Math.sin(u * Math.PI) * 10;
    }
    let rows;
    if (hopping) rows = CAT.walk1;
    else if (cat.ride || cat.mode === "sit") rows = Math.floor(now / 900 + cat.swish) % 4 === 0 ? CAT.sitL : CAT.sit;
    else if (cat.mode === "sleep") rows = CAT.sleep;
    else rows = Math.floor(cat.dist / 3) % 2 ? CAT.walk2 : CAT.walk1;
    const breathe = cat.mode === "sleep" ? Math.floor(now / 1100) % 2 : 0;
    const x0 = Math.round(cx - rows[0].length / 2),
        y0 = Math.round(cy - rows.length - (cat.ride ? 5 : 0)) + breathe;
    if (!cat.ride && !hopping) pxEllipse(ctx, cx, cy, cat.onDesk || cat.onBed ? 5 : 6, 1, "#00000038");
    drawPix(ctx, rows, CAT_PAL, x0, y0, flip);
    if (hovered === "cat") {
        ctx.strokeStyle = "#ffffffaa";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.ellipse(Math.round(cx) + 0.5, Math.round(cy) + 0.5, 9, 3, 0, 0, 7);
        ctx.stroke();
    }
}

// ================================================================ robot vacuum (night shift)
const bot = { x: DOCK.x, y: DOCK.y, a: -Math.PI / 2, active: false, docked: true, pause: 0, turn: 0, path: [] };
function botStep(dt, now) {
    const want = nightShift(clock());
    if (want && bot.docked) {
        bot.docked = false;
        bot.active = true;
        bot.a = -Math.PI / 2 + rnd(-0.6, 0.6);
        bot.pause = 0;
    }
    if (!want && bot.active) {
        bot.active = false;
        bot.path = findPath(bot.x, bot.y, DOCK.x, DOCK.y);
    }
    if (!bot.active && !bot.docked) {
        if (!bot.path.length) {
            bot.docked = true;
            bot.x = DOCK.x;
            bot.y = DOCK.y;
            bot.a = -Math.PI / 2;
            return;
        }
        const t = bot.path[0],
            dx = t.x - bot.x,
            dy = t.y - bot.y,
            d = Math.hypot(dx, dy),
            sp = 22 * dt;
        bot.a = Math.atan2(dy, dx);
        if (d <= sp) {
            bot.x = t.x;
            bot.y = t.y;
            bot.path.shift();
        } else {
            bot.x += (dx / d) * sp;
            bot.y += (dy / d) * sp;
        }
        return;
    }
    if (!bot.active) return;
    if (bot.pause > 0) {
        bot.pause -= dt;
        bot.a += bot.turn * dt;
        return;
    }
    const fx = bot.x + Math.cos(bot.a) * 9,
        fy = bot.y + Math.sin(bot.a) * 6;
    let blocked = !walkablePx(fx, fy);
    if (!blocked)
        for (const w of workers.values())
            if (Math.hypot(w.x - fx, w.y - fy) < 9) {
                blocked = true;
                break;
            }
    if (blocked) {
        bot.pause = rnd(0.5, 1.1);
        bot.turn = ((Math.random() < 0.5 ? -1 : 1) * rnd(Math.PI / 2, Math.PI)) / bot.pause;
    } else {
        bot.x += Math.cos(bot.a) * 16 * dt;
        bot.y += Math.sin(bot.a) * 13 * dt;
    }
}
function drawBot(now) {
    const x = Math.round(bot.x),
        y = Math.round(bot.y);
    pxEllipse(ctx, x, y + 1, 7, 2, "#00000045");
    pxEllipse(ctx, x, y - 2, 7, 3, "#1e1d26");
    pxEllipse(ctx, x, y - 3, 6, 2, "#46455a");
    pxEllipse(ctx, x, y - 3, 2, 1, "#6a6984");
    const lx = Math.round(x + Math.cos(bot.a) * 5),
        ly = Math.round(y - 3 + Math.sin(bot.a) * 2);
    ctx.fillStyle = bot.docked
        ? Math.floor(now / 900) % 2
            ? "#ffd166"
            : "#6b5a2a"
        : Math.floor(now / 400) % 2
          ? "#7ee0b5"
          : "#3d6b5a";
    ctx.fillRect(lx, ly, 1, 1);
}
