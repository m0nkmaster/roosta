// Office page. The world: canvas setup, art, cast, roles, seasons, rooms, path-finding and the clock.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// Who the office works for, from the workspace PROFILE.md.
let USER_NAME = "You";
const officeName = () => (USER_NAME === "You" ? "Your office" : `${USER_NAME}'s office`);
fetch("/api/profile")
    .then((r) => r.json())
    .then((p) => {
        if (p && p.user && p.user !== "the user") USER_NAME = p.user;
    })
    .catch(() => {});

// ================================================================ setup
const W = 1280,
    H = 720,
    WALL = 80,
    MID = 354,
    FLOOR2 = 444; // MID..FLOOR2 is the face of the wall dividing the two rows of rooms
const params = new URLSearchParams(location.search);
const DEMO = params.has("demo");
const HOUR_OVERRIDE = params.has("hour") ? Number(params.get("hour")) : null;
const DAY_OVERRIDE = params.has("day") ? ((Number(params.get("day")) % 7) + 7) % 7 : null; // ?day=0..6 (0 = Sunday)
const WEATHER_OVERRIDE = ["clear", "cloudy", "rain"].includes(params.get("weather")) ? params.get("weather") : null; // ?weather=clear|cloudy|rain
const SEASON_OVERRIDE = [
    "valentine",
    "easter",
    "pride",
    "halloween",
    "bonfire",
    "christmas",
    "newyear",
    "friday13",
    "none",
].includes(params.get("season"))
    ? params.get("season")
    : null; // ?season=<theme>|none
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
// ?warp=N fast-forwards the simulation N seconds on load (headless screenshots barely tick rAF)
let clockSkew = 0;
const tnow = () => performance.now() + clockSkew;
const view = document.getElementById("view"),
    vctx = view.getContext("2d");
const stage = document.getElementById("stage");
const scene = document.createElement("canvas");
scene.width = W;
scene.height = H;
const ctx = scene.getContext("2d");
ctx.imageSmoothingEnabled = false;
const light = document.createElement("canvas");
light.width = W;
light.height = H;
const lctx = light.getContext("2d");
const bg = document.createElement("canvas");
bg.width = W;
bg.height = H;
const bx = bg.getContext("2d");
bx.imageSmoothingEnabled = false;
const LPC = "/static/vendor/lpc/";
const hash = (s) => {
    s = String(s);
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) {
        h ^= s.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return ((h >>> 0) % 100000) / 100000;
};
const pick = (arr, r) => arr[Math.floor(r * arr.length) % arr.length];
const rnd = (a, b) => a + Math.random() * (b - a);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const esc = (s) =>
    String(s ?? "").replace(
        /[&<>"']/g,
        (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );

// ================================================================ assets
const TONES = ["Peach", "Porcelain", "Tan", "Honey", "Brown", "Coffee"];
const HAIRS = ["buzzcut", "natural", "curly-short", "cowlick", "parted", "flattop"].map((h) => h + "/Black"); // unnamed workers
const SHIRTS = ["Fern", "Charcoal", "Amber", "Blue", "Amethyst", "Coral", "Cyan", "Apple", "Brown"];
const ANIMS = ["Walk", "Idle", "Sitting"];
// Long styles that spill behind the shoulders ship a second sheet drawn under the body.
const HAIR_BEHIND = new Set(["curly/Blonde", "curly/Red", "page/Blonde", "page/Raven"]);
// Each nickname gets a look that suits it (lower-cased key). body/head: m, f or old (head only).
// hair and beard are "<style>/<colour>" under vendor/lpc/hair; glasses: round or halfmoon.
// The shirt stays the role's uniform unless the look sets one; legs recolours legs and feet.
// A nickname not listed falls back to a hashed masculine look.
const CAST = {
    // the logo come to life: orange hood, purple goggles, shadow face and gold eyes (the "Roosta" sheets are recoloured LPC)
    roosta: { body: "m", tone: "Roosta", hair: "hood/Roosta", shirt: "Roosta", legs: "Roosta" },
    monty: { body: "m", head: "old", tone: "Peach", hair: "parted/Silver" }, // Monty Don, silver and swept back
    hannah: { body: "f", tone: "Peach", hair: "bob/Chestnut", glasses: "round" }, // the studious learner
    iris: { body: "f", tone: "Tan", hair: "page/Raven", glasses: "round" }, // the one with an eye for ideas
    fegus: { body: "m", tone: "Porcelain", hair: "curly-short/Red", beard: "beard-trimmed/Red", glasses: "halfmoon" }, // ginger Scot over his half-moons
    natalie: { body: "f", tone: "Honey", hair: "twists/Brown" },
    eileen: { body: "f", head: "old", tone: "Porcelain", hair: "bun/Silver" }, // silver bun, the evening shift
    hunter: { body: "m", tone: "Tan", hair: "flattop-fade/Brown", beard: "beard/Brown" }, // rugged tracker
    suki: { body: "f", tone: "Porcelain", hair: "bob-bangs/Raven" },
    phil: { body: "m", tone: "Peach", hair: "balding/Ash Brown", beard: "tache-horseshoe/Ash Brown" }, // seen-it-all support veteran
    carly: { body: "f", tone: "Brown", hair: "dreadlocks/Black" },
    viv: { body: "f", tone: "Tan", hair: "idol/Violet" }, // vivid
    kat: { body: "f", tone: "Coffee", hair: "twists-fade/Black" },
    bookworm: { body: "m", tone: "Brown", hair: "natural/Black", glasses: "round" },
    dawn: { body: "f", tone: "Peach", hair: "bob/Orange" }, // sunrise orange
    ada: { body: "f", tone: "Porcelain", hair: "page/Raven" }, // Ada Lovelace's dark centre parting
    roland: { body: "m", tone: "Peach", hair: "parted/Charcoal", beard: "tache-handlebar/Charcoal" }, // old-school newsman
    lacky: { body: "m", tone: "Porcelain", hair: "cowlick/Blonde" }, // the junior with the cowlick
    rupert: { body: "m", tone: "Porcelain", hair: "page/Blonde" }, // floppy public-school fringe
    charlie: { body: "f", tone: "Peach", hair: "curly/Red" }, // Charlie Dimmock, the other gardener
    tina: { body: "f", tone: "Brown", hair: "curly/Blonde" }, // Tina Turner's big blonde hair
    oscar: { body: "m", tone: "Tan", hair: "natural/Green", beard: "beard/Green" }, // Oscar the Grouch
    homer: { body: "m", head: "old", tone: "Peach", hair: "balding/Ash Brown" }, // Homer at the gate
    garry: { body: "m", tone: "Peach", hair: "buzzcut/Silver", beard: "beard-trimmed/Silver" }, // the director
};
const DEFAULT_NICKS = {};
// the sheet stack for a look, bottom to top
function layersOf(look) {
    const f = look.body === "f" ? "-f" : "",
        head = { m: "head", f: "head-f", old: "head-old" }[look.head || look.body];
    return [
        HAIR_BEHIND.has(look.hair) && "hair-behind/" + look.hair,
        "body" + f + "/" + look.tone,
        "legs" + f + (look.legs ? "/" + look.legs : ""),
        "feet" + f + (look.legs ? "/" + look.legs : ""),
        "shirt" + f + "/" + look.shirt,
        head + "/" + look.tone,
        look.beard && "hair/" + look.beard,
        "hair/" + look.hair,
        look.glasses && "glasses/" + look.glasses,
    ].filter(Boolean);
}
const A = { sets: {}, img: {} };
const IMGS = {
    desk: "furniture/Desk__Office.png",
    chair: "furniture/Chair_Office.png",
    copier: "furniture/Copy_Machine.png",
    fridge: "furniture/Fridge.png",
    planter: "furniture/Planter.png",
    bin: "furniture/Bin.png",
    cabinet: "furniture/Cabinet.png",
    sofa: "furniture/Sofa.png",
    vending: "furniture/Vending_Machine.png",
    cooler: "furniture/Water_Cooler.png",
    tv: "furniture/TV.png",
    lampFloor: "furniture/Lamp_Floor.png",
    screen: "furniture/Standing_Screen.png",
    bed: "furniture/Bed.png",
    endTable: "furniture/End_Table.png",
    gclock: "furniture/Clock__Grandfather.png",
    fireplace: "furniture/Fireplace.png",
    fireTools: "items/Fireplace_Accessories.png",
    shelf: "furniture/Shelf.png",
    counter: "furniture/Countertop.png",
    tileB: "floor/tile.png",
    laptop: "items/Laptop.png",
    lampTable: "items/Lamp_Table.png",
    coffee: "items/Coffee_Maker.png",
    paper: "items/Loose_Paper.png",
    boxes: "items/Boxes.png",
    portraits: "items/Tabletop_Portraits.png",
    dessert: "items/Dessert.png",
    paintL: "wall/Paintings_Landscape.png",
    paintA: "wall/Paintings_Abstract.png",
    posters: "wall/Posters.png",
    lampWall: "wall/Lamp_Wall.png",
    mailboxes: "wall/Mailboxes.png",
    walls: "structure/Painted_Walls.png",
    window: "structure/Windows.png",
    door: "structure/Door.png",
    rug: "rugs/Diamond_Rug.png",
    wood: "floor/wood.png",
    herring: "floor/herringbone.png",
    tile: "floor/tile_b.png",
    xtree: "seasonal/Christmas_Tree.png",
    xdecor: "seasonal/Christmas_Wall_Decor.png",
    presents: "seasonal/Presents.png",
    eggs: "seasonal/Eggs.png",
    flowers: "seasonal/Flowers.png",
    skel: "seasonal/Skeletons.png",
    dungeon: "seasonal/Dungeon_Elements.png",
    veg: "seasonal/Vegetables_C.png",
    pride: "seasonal/Pride_Flags.png",
};
let loaded = 0,
    total = 0;
const bar = document.getElementById("load-bar");
function img(src) {
    total++;
    return new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => {
            loaded++;
            bar.style.width = (100 * loaded) / total + "%";
            res(i);
        };
        i.onerror = () => rej(new Error(src));
        i.src = LPC + src;
    });
}
async function loadSet(dir) {
    const o = {};
    await Promise.all(
        ANIMS.map(async (a) => {
            o[a] = await img(dir + "/" + a + ".png");
        }),
    );
    return o;
}
async function preload() {
    const jobs = [];
    // every layer any look can use: both bodies in every tone and shirt, the fallback hair and the cast
    const need = new Set();
    for (const body of ["m", "f"])
        for (const tone of TONES)
            for (const shirt of SHIRTS)
                for (const hair of body === "m" ? HAIRS : [HAIRS[0]])
                    layersOf({ body, tone, shirt, hair }).forEach((p) => need.add(p));
    for (const tone of TONES) need.add("head-old/" + tone);
    for (const c of Object.values(CAST)) layersOf({ shirt: SHIRTS[0], ...c }).forEach((p) => need.add(p));
    for (const p of need) jobs.push(loadSet(p).then((s) => (A.sets[p] = s)));
    for (const [k, p] of Object.entries(IMGS)) jobs.push(img(p).then((i) => (A.img[k] = i)));
    jobs.push(document.fonts.load('12px "Pixelify Sans"'), document.fonts.load('12px "Press Start 2P"'));
    await Promise.all(jobs);
    // Window panes are opaque black in the sheet; punch them out so the sky shows through.
    const wc = document.createElement("canvas");
    wc.width = 32;
    wc.height = 84;
    const wx = wc.getContext("2d");
    wx.drawImage(A.img.window, 0, 24, 32, 84, 0, 0, 32, 84);
    const d = wx.getImageData(0, 0, 32, 84);
    for (let i = 0; i < d.data.length; i += 4)
        if (d.data[i] === 0 && d.data[i + 1] === 0 && d.data[i + 2] === 0) d.data[i + 3] = 0;
    wx.putImageData(d, 0, 0);
    A.img.windowCut = wc;
}

// sprite crops: [image, sx, sy, sw, sh]
const C = {
    desk: ["desk", 131, 80, 58, 35],
    chairBack: ["chair", 4, 3, 24, 29],
    laptopOff: ["laptop", 6, 6, 19, 22],
    laptopOn: ["laptop", 38, 6, 19, 22],
    copier: ["copier", 5, 18, 53, 45],
    fridge: ["fridge", 32, 2, 32, 62],
    vending: ["vending", 16, 0, 32, 64],
    cooler: ["cooler", 8, 9, 18, 53],
    coffee: ["coffee", 8, 2, 15, 29],
    endTable: ["endTable", 6, 3, 20, 24],
    tv: ["tv", 14, 1, 100, 61],
    sofaFront: ["sofa", 1, 145, 94, 38],
    sofaBack: ["sofa", 321, 193, 94, 31],
    lampFloor: ["lampFloor", 4, 2, 24, 49],
    lampWall: ["lampWall", 6, 4, 20, 28],
    paintL: ["paintL", 13, 33, 39, 31],
    paintA: ["paintA", 141, 1, 39, 31],
    poster: ["posters", 99, 7, 24, 36],
    poster2: ["posters", 3, 39, 24, 36],
    posterGalaxy: ["posters", 39, 35, 18, 24],
    posterPeak: ["posters", 67, 35, 27, 40],
    posterSkull: ["posters", 44, 71, 11, 17],
    posterNight: ["posters", 102, 69, 19, 23],
    posterCocktail: ["posters", 135, 67, 18, 24],
    sofaBlueBack: ["sofa", 1, 193, 94, 31],
    tvSmall: ["tv", 325, 23, 52, 34],
    books1: ["cabinet", 64, 100, 32, 70],
    books2: ["cabinet", 96, 100, 32, 70],
    plantFern: ["planter", 128, 33, 32, 51],
    plantTree: ["planter", 64, 6, 32, 78],
    plantBox: ["planter", 0, 32, 32, 52],
    bin: ["bin", 39, 3, 18, 28],
    boxes: ["boxes", 34, 4, 28, 22],
    paper: ["paper", 7, 41, 15, 8],
    screen: ["screen", 160, 0, 32, 64],
    bedTop: ["bed", 74, 96, 44, 25],
    bedBody: ["bed", 73, 18, 46, 55],
    door: ["door", 224, 38, 32, 58],
    pigeonholes: ["mailboxes", 30, 30, 37, 37], // a 3x3 bank; each slot's slit is at +4/+15/+25 across and down
    tableLong: ["desk", 0, 12, 192, 40],
    chairFront: ["chair", 4, 46, 24, 34],
    sofaGreen: ["sofa", 321, 17, 94, 38],
    drawers: ["cabinet", 96, 5, 32, 70],
    lampTable: ["lampTable", 4, 0, 24, 31],
    deskDark: ["desk", 3, 80, 58, 35],
    deskWhite: ["desk", 67, 80, 58, 35],
    deskGrey: ["desk", 3, 144, 58, 35],
    island: ["desk", 0, 12, 96, 40],
    counterA: ["counter", 48, 140, 144, 46],
    counterB: ["counter", 48, 140, 144, 46],
    mediaUnit: ["shelf", 0, 75, 64, 21],
    coffeeTable: ["shelf", 1, 43, 62, 21],
    cabinetLow: ["shelf", 112, 11, 32, 21],
    sofaSideR: ["sofa", 416, 128, 29, 82],
    sofaSideL: ["sofa", 451, 128, 29, 82],
    gclock0: ["gclock", 7, 22, 18, 71],
    gclock1: ["gclock", 39, 22, 18, 71],
    gclock2: ["gclock", 71, 22, 18, 71],
    fireplace: ["fireplace", 8, 114, 80, 74], // stone surround, wooden mantel; the firebox is the dark arch at +18..+57, +28..+43
    fireTools: ["fireTools", 11, 0, 10, 29],
    stockingR: ["fireTools", 33, 15, 9, 15],
    stockingG: ["fireTools", 44, 15, 8, 16],
    stockingW: ["fireTools", 53, 15, 10, 17],
    // seasonal decor (seasonal/*): the tree's two frames differ only in which lights are lit
    xtree0: ["xtree", 4, 4, 85, 114],
    xtree1: ["xtree", 100, 4, 85, 114],
    wreath: ["xdecor", 6, 6, 20, 22],
    swag: ["xdecor", 13, 32, 72, 22],
    garland: ["xdecor", 0, 64, 128, 22],
    xlights: ["xdecor", 0, 96, 128, 14],
    giftBig: ["presents", 36, 1, 26, 31],
    giftTall: ["presents", 71, 2, 12, 28],
    giftGold: ["presents", 100, 4, 23, 28],
    giftGreen: ["presents", 3, 5, 23, 22],
    giftWhite: ["presents", 131, 6, 26, 26],
    giftTiny: ["presents", 171, 11, 10, 13],
    giftPink: ["presents", 3, 37, 23, 22],
    giftBlue: ["presents", 100, 36, 23, 28],
    eggW: ["eggs", 10, 9, 10, 12],
    eggB: ["eggs", 42, 9, 10, 12],
    // desk keepsakes: three tabletop photo frames and a bud vase that takes one stem (seasonal/Flowers row 0, 9 colours 32px apart)
    pieWhole: ["dessert", 3, 5, 26, 21],
    pieCut: ["dessert", 6, 107, 26, 21],
    pieSlice: ["dessert", 0, 96, 14, 11],
    photoFam: ["portraits", 10, 37, 13, 20],
    photoSolo: ["portraits", 10, 69, 13, 20],
    photoPair: ["portraits", 41, 37, 16, 20],
    budVase: ["flowers", 108, 76, 8, 13],
    ...Object.fromEntries(Array.from({ length: 9 }, (_, i) => ["stem" + i, ["flowers", 12 + i * 32, 2, 7, 13]])),
    vaseWhite: ["flowers", 42, 73, 12, 22],
    vasePink: ["flowers", 10, 105, 12, 22],
    roses: ["flowers", 199, 66, 19, 15],
    daffs: ["flowers", 263, 66, 19, 15],
    skeleton: ["skel", 64, 0, 32, 61],
    skull: ["skel", 4, 3, 20, 20],
    webR: ["dungeon", 40, 0, 24, 32],
    webL: ["dungeon", 32, 40, 32, 23],
    gourds: ["veg", 228, 35, 25, 21],
    pumpkin: ["veg", 257, 43, 11, 8],
    prideRainbow: ["pride", 7, 1, 50, 30],
    prideProgress: ["pride", 71, 1, 50, 30],
};
function blit(c, key, x, y, flip) {
    const [k, sx, sy, sw, sh] = C[key];
    if (flip) {
        c.save();
        c.scale(-1, 1);
        c.drawImage(A.img[k], sx, sy, sw, sh, -Math.round(x) - sw, Math.round(y), sw, sh);
        c.restore();
    } else c.drawImage(A.img[k], sx, sy, sw, sh, Math.round(x), Math.round(y), sw, sh);
}
// crisp pixel primitives (no anti-aliasing, so they survive the nearest-neighbour upscale)
function pxEllipse(c, cx, cy, rx, ry, col) {
    c.fillStyle = col;
    cx = Math.round(cx);
    cy = Math.round(cy);
    for (let dy = -ry; dy <= ry; dy++) {
        const half = Math.round(rx * Math.sqrt(Math.max(0, 1 - (dy / (ry + 0.5)) ** 2)));
        c.fillRect(cx - half, cy + dy, half * 2 + 1, 1);
    }
}
function pxLine(c, x0, y0, x1, y1, col) {
    c.fillStyle = col;
    const n = Math.max(1, Math.round(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0))));
    for (let i = 0; i <= n; i++)
        c.fillRect(Math.round(x0 + ((x1 - x0) * i) / n), Math.round(y0 + ((y1 - y0) * i) / n), 1, 1);
}
function drawPix(c, rows, pal, x, y, flip) {
    const w = rows[0].length;
    for (let r = 0; r < rows.length; r++)
        for (let q = 0; q < w; q++) {
            const ch = rows[r][q];
            if (ch === ".") continue;
            c.fillStyle = pal[ch];
            c.fillRect(x + (flip ? w - 1 - q : q), y + r, 1, 1);
        }
}

// ================================================================ characters
const FR = 64,
    ROW = { up: 0, left: 1, down: 2, right: 3 },
    COLS = { Walk: 8, Idle: 3, Sitting: 3 };
const sheetCache = new Map();
const lookKey = (look) => layersOf(look).join("|");
function sheet(look, anim) {
    const key = lookKey(look) + anim;
    if (sheetCache.has(key)) return sheetCache.get(key);
    const layers = layersOf(look)
        .map((p) => A.sets[p])
        .filter(Boolean);
    const src = layers[0][anim],
        c = document.createElement("canvas");
    c.width = src.width;
    c.height = src.height;
    const x = c.getContext("2d");
    for (const layer of layers) x.drawImage(layer[anim], 0, 0);
    sheetCache.set(key, c);
    return c;
}
function portrait(look, size) {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const x = c.getContext("2d");
    x.imageSmoothingEnabled = false;
    const crop = 30,
        off = (size - crop) / 2;
    x.drawImage(sheet(look, "Idle"), 17, 2 * FR + 9, crop, crop, off, off + 1, crop, crop);
    return c;
}

// ================================================================ roles
const ROLES = {
    guard: { name: "Gatekeeper", icon: "🪪", shirt: "Charcoal", likes: ["door"] },
    gardener: { name: "Groundskeeper", icon: "🌿", shirt: "Fern", likes: ["plant", "window"] },
    scribe: { name: "Apprentice", icon: "✍️", shirt: "Amethyst", likes: ["books", "read", "chat", "sofa"] },
    auditor: { name: "Inspector", icon: "📋", shirt: "Blue", likes: ["peek", "meeting", "darts"] },
    engineer: {
        name: "Mechanic",
        icon: "🔧",
        shirt: "Amber",
        likes: ["arcade", "console", "pong", "foos", "board", "peek"],
    },
    watcher: { name: "Lookout", icon: "🔭", shirt: "Cyan", likes: ["window"] },
    tracker: { name: "Detective", icon: "🔎", shirt: "Coral", likes: ["window", "coffee", "board"] },
    clerk: { name: "Clerk", icon: "🗂️", shirt: "Brown", likes: ["books", "coffee", "meeting", "table"] },
    concierge: { name: "Concierge", icon: "🛎️", shirt: "Amber", likes: ["sofa", "chat", "console", "tv"] },
    worker: {
        name: "Worker",
        icon: "⚙️",
        shirt: "Apple",
        likes: ["sofa", "arcade", "pong", "foos", "darts", "console"],
    },
};
function roleOf(t) {
    const s = ((t.skill || "") + " " + (t.id || "")).toLowerCase();
    if (s.includes("gardener")) return "gardener";
    if (s.includes("learner")) return "scribe";
    if (s.includes("auditor")) return "auditor";
    if (s.includes("engineer")) return "engineer";
    if (/watch|support/.test(s)) return "watcher";
    if (/tracker|incident/.test(s)) return "tracker";
    if (t.id === "assistant" || s.includes("self-chat")) return "concierge";
    if (/okr|roadmap|comms|brief|digest|standup|review|archive|triage/.test(s)) return "clerk";
    return "worker";
}
function lookOf(t) {
    const shirt = ROLES[roleOf(t)].shirt;
    const cast =
        CAST[
            String(t.nickname || "")
                .trim()
                .toLowerCase()
        ] ||
        CAST[
            String(t.id || "")
                .trim()
                .toLowerCase()
        ];
    if (cast) return { shirt, ...cast };
    return { body: "m", tone: pick(TONES, hash(t.id + "tone")), hair: pick(HAIRS, hash(t.id + "hair")), shirt };
}
const levelOf = (n) => Math.max(1, Math.floor(Math.sqrt(n || 0)));
// new starters wear a NEW tag for their first runs; crossing the line is a real event
const NEW_RUNS = 10;
function starter(prev, n) {
    n = n || 0;
    return {
        isNew: n < NEW_RUNS,
        toGo: Math.max(0, NEW_RUNS - n),
        passed: prev != null && prev < NEW_RUNS && n >= NEW_RUNS,
    };
}
function behaviour(t) {
    if (t.status === "running") return "working";
    if (t.queued || t.waiting_behind) return "queued";
    if (t.status === "auth-failed" || t.status === "blocked") return "locked";
    if (t.status === "error" || t.status === "interrupted") return "hurt";
    return "resting";
}
const NOTE_COL = {
    task: "#ffd166",
    review: "#ff9f6b",
    teams: "#9db8ff",
    email: "#b79bff",
    jira: "#7fd3ff",
    decision: "#ff8fb1",
};
let kanban = { notes: [], later: 0, done: 0 },
    boardHits = [],
    boardHover = null,
    kanbanAt = 0;
function kanbanCols(b) {
    const notes = b.notes || [];
    return [
        { key: "user", col: "#ffd166", notes: notes.filter((n) => n.owner === "user") },
        { key: "ai", col: "#b79bff", notes: notes.filter((n) => n.owner !== "user") },
        {
            key: "later",
            col: "#8c8ca0",
            notes: Array.from({ length: b.later || 0 }, (_, i) => ({ title: "snoozed", i })),
        },
        { key: "done", col: "#7ee0b5", notes: [], tally: b.done || 0 },
    ];
}
async function pollKanban() {
    if (Date.now() - kanbanAt < 60e3) return;
    kanbanAt = Date.now();
    try {
        const r = await fetch("/api/board/count", { cache: "no-store" });
        if (r.ok) kanban = await r.json();
    } catch (e) {}
}
const hitBoardNote = (p) => boardHits.find((h) => p.x >= h.x && p.x < h.x + h.w && p.y >= h.y && p.y < h.y + h.h);
const hitBoard = (p) => p.x > BOARD.x && p.x < BOARD.x + BOARD.w && p.y > BOARD.y && p.y < BOARD.y + BOARD.h;
const STATE_COL = { working: "#ffd166", queued: "#b79bff", locked: "#ff6b6b", hurt: "#ff6b6b", resting: "#7ee0b5" };
const UI_COL = {
    working: "var(--st-working)",
    queued: "var(--st-queued)",
    locked: "var(--st-locked)",
    hurt: "var(--st-hurt)",
    resting: "var(--st-resting)",
};
const STATE_LABEL = {
    working: "On shift",
    queued: "Waiting their turn",
    locked: "Signed out",
    hurt: "In sick bay",
    resting: "Off shift",
};

// ================================================================ seasons
// Seasonal themes on the UK calendar: ambient decor, fireworks and chatter only, picked from today's date
// (?season= overrides). Decor is fixed at load; the page reloads itself at the first hour boundary after the theme changes.
function easterSunday(y) {
    // anonymous Gregorian algorithm; mo is 0-based
    const a = y % 19,
        b = Math.floor(y / 100),
        c = y % 100,
        d = Math.floor(b / 4),
        e = b % 4,
        f = Math.floor((b + 8) / 25),
        g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - d - g + 15) % 30,
        i = Math.floor(c / 4),
        k = c % 4,
        l = (32 + 2 * e + 2 * i - h - k) % 7,
        m = Math.floor((a + 11 * h + 22 * l) / 451);
    const n = h + l - 7 * m + 114;
    return { mo: Math.floor(n / 31) - 1, d: (n % 31) + 1 };
}
function seasonFor(y, mo, d) {
    const day = Date.UTC(y, mo, d) / 864e5,
        e = easterSunday(y),
        easter = Date.UTC(y, e.mo, e.d) / 864e5;
    if ((mo === 11 && d === 31) || (mo === 0 && d === 1)) return "newyear";
    if (mo === 11 || (mo === 0 && d <= 5)) return "christmas"; // decorations up for December, down after Twelfth Night
    if (day >= easter - 7 && day <= easter + 1) return "easter"; // Palm Sunday to Easter Monday
    if (mo === 1 && d >= 10 && d <= 14) return "valentine";
    if (mo === 5) return "pride";
    if (mo === 9 && d >= 20) return "halloween";
    if (mo === 10 && d <= 7) return "bonfire";
    if (d === 13 && new Date(Date.UTC(y, mo, d)).getUTCDay() === 5) return "friday13"; // only when no bigger theme claims the day
    return null;
}
function seasonNow() {
    if (SEASON_OVERRIDE) return SEASON_OVERRIDE === "none" ? null : SEASON_OVERRIDE;
    const d = new Date();
    return seasonFor(d.getFullYear(), d.getMonth(), d.getDate());
}
// presents pile up under the tree through December and are gone once they're opened on the 25th
function presentsFor(mo, d) {
    if (mo === 11) return d >= 25 ? 0 : Math.min(6, 1 + Math.floor(d / 4));
    return 0;
}
// fireworks in the windows (0..1 busyness): bonfire-week evenings, busiest on the 5th; New Year's Eve peaking at midnight
function fireworksFor(season, mo, d, t) {
    if (season === "bonfire") return t >= 17 && t < 23 ? (mo === 10 && d === 5 ? 1 : 0.35) : 0;
    if (season === "newyear") {
        if (mo === 11 && t >= 20) return t >= 23.9 ? 1 : 0.3;
        if (mo === 0 && d === 1 && t < 1) return t < 0.5 ? 1 : 0.3;
    }
    return 0;
}
// what the crew chats about: after Christmas Day the Secret Santa talk turns to leftovers
function seasonChat(season, mo, d) {
    if (!season) return null;
    return season === "christmas" && ((mo === 11 && d >= 25) || mo === 0) ? "xmasafter" : season;
}
// Easter egg hunt: a date-seeded handful of the hiding spots (world-only; found eggs are remembered for the day)
function eggSpots(seed, pool, n) {
    return pool
        .map((p, i) => ({ p, k: hash(seed + ":" + i) }))
        .sort((a, b) => a.k - b.k)
        .slice(0, n)
        .map((e) => e.p);
}
const SEASON = seasonNow(),
    XMAS = SEASON === "christmas" || SEASON === "newyear";
const TODAY = new Date(),
    TODAY_KEY = `${TODAY.getFullYear()}-${TODAY.getMonth() + 1}-${TODAY.getDate()}`;
// ?season= out of season plays a typical day of it (fireworks on the 5th, New Year's Eve, a mid-December pile of presents)
const [SMO, SD] = {
    newyear: [11, 31],
    bonfire: [10, 5],
    christmas: [11, 12],
    halloween: [9, 31],
    valentine: [1, 14],
    pride: [5, 15],
}[SEASON_OVERRIDE] || [TODAY.getMonth(), TODAY.getDate()];
const SEASON_CHAT = SEASON ? "s_" + seasonChat(SEASON, SMO, SD) : null;

// ================================================================ level layout
// Two rows of rooms. Top (back wall with windows): office | meeting room | kitchen.
// Bottom (behind the dividing wall): first aid | lounge | games room.
// The dividing wall's face runs MID..FLOOR2 with doorways; the bottom rooms hang their TV, boards and art on it.
const ROOMS = {
    office: { x0: 0, x1: 600, y0: WALL, y1: MID, name: "Ops floor" },
    meeting: { x0: 600, x1: 880, y0: WALL, y1: MID, name: "Meeting room" },
    kitchen: { x0: 880, x1: W, y0: WALL, y1: MID, name: "Kitchen" },
    firstaid: { x0: 0, x1: 150, y0: FLOOR2, y1: H, name: "First aid" },
    lounge: { x0: 150, x1: 760, y0: FLOOR2, y1: H, name: "Lounge" },
    games: { x0: 760, x1: 1150, y0: FLOOR2, y1: H, name: "Games room" },
    userOffice: { x0: 1150, x1: W, y0: FLOOR2, y1: H, name: "Your office" },
};
// Desks: worker sits south of the desk, back to camera, laptop screen facing us.
const DESKS = [];
for (const dy of [118, 222])
    for (const dx of [28, 140, 252, 364])
        DESKS.push({
            x: dx,
            y: dy,
            seat: { x: dx + 29, y: dy + 50 },
            owner: null,
            mug: pick(["#e85d5d", "#5b8cff", "#f4ecff", "#7ee0b5", "#ffd166", "#b79bff"], hash("mug" + dx + dy)),
        });
// Personal touches so the desks aren't clones: a photo frame (only where no papers lie, they're wider) or a bud vase whose
// stem changes colour each week, as if someone brings fresh flowers; one desk in four stays bare (hot-desk tidy).
const WEEK = Math.floor((Date.now() / 864e5 + 3) / 7); // weeks since the Monday before 1 Jan 1970, so the stem changes on Mondays
for (const [i, d] of DESKS.entries()) {
    const r = hash("touch" + d.x + d.y),
        photo = i % 2 ? pick(["photoFam", "photoSolo", "photoPair"], hash("ph" + d.x + d.y)) : null;
    d.touch =
        r < 0.25
            ? null
            : photo && r < 0.7
              ? { k: photo, x: d.x + 31, y: d.y - 13 }
              : { k: "budVase", x: d.x + 36, y: d.y - 9, stem: "stem" + Math.floor(hash("st" + i + ":" + WEEK) * 9) };
}
const BOARD = { x: 650, y: 12, w: 180, h: 56 };
const FRAME = { x: 430, y: 20, w: 28, h: 38 }; // employee of the week, on the wall by the front door
const DOOR = { x: 468, y: 22, front: { x: 484, y: 100 } };
const PIGEON = { x: 384, y: 34, w: 37, h: 37 }; // the post's pigeonholes, under the wall lamp between the shelves and the frame
const COPIER = { x: 532, y: 72 };
// Video-call screen on a stand at the head of the meeting table: where workers wait while a sign-in is down
const CALL = { x: 846, y: 130, front: { x: 861, y: 218 } };
const WALL_CLOCK = { x: 624, y: 34 };
const RACK = { x: 530, y: 272 };
const TABLE = { x: 644, y: 196 };
const ISLAND = { x: 960, y: 190 };
const CAFE = [
    { x: 1004, y: 300 },
    { x: 1236, y: 296 },
]; // one by the breakfast bar, one in the far corner
const DINING = { x: 1112, y: 190 };
const BED = { x: 26, y: 476 };
const FP = { x: 182, y: 386 }; // lounge fireplace, hearth on the floor line (FLOOR2)
const TV = { x: 442, y: 364, w: 116, h: 64 }; // the screen; the bezel is drawn around it
const SOFA_BACK = { x: 453, y: 578 },
    SOFA_L = { x: 380, y: 492 },
    SOFA_R = { x: 591, y: 492 };
const DOCK = { x: 272, y: 707 };
const ARCADES = [
    { x: 786, y: 452, col: "#ff6b9a", game: 0 },
    { x: 816, y: 452, col: "#6aa6ff", game: 1 },
    { x: 846, y: 452, col: "#7ee0b5", game: 2 },
];
const PONG = { x: 968, y: 560, w: 64, h: 26 };
PONG.L = PONG.x - 5;
PONG.R = PONG.x + PONG.w + 5;
const FOOS = { x: 990, y: 636, w: 52, h: 30 };
const DARTS = { x: 1066, y: 392 },
    SCORE = { x: 1008, y: 378 }; // dartboard and its chalk scoreboard
const USER_DESK = { x: 1188, y: 548 }; // the user's office: their desk faces the door, visitors sit across it
// games room den: a TV and console on a low unit, a row of beanbags and a sofa behind, all facing the screen
const DEN = { x: 823, y: 560, tv: { x: 829, y: 527 } },
    GS = { x: DEN.tv.x + 2, y: DEN.tv.y + 3, w: 48, h: 27 },
    DEN_SOFA = { x: 808, y: 646 };
const BEANBAGS = [
    { x: 806, y: 620, col: "#c0504d", hi: "#e07a6e" },
    { x: 838, y: 620, col: "#3d8c8c", hi: "#5fb3b0" },
    { x: 872, y: 620, col: "#7a4bd1", hi: "#a07ae8" },
    { x: 904, y: 620, col: "#e8a33d", hi: "#f4c470" },
];
// interior partitions: x, the floor span they run along, and doorways (y ranges) left open
const PARTS = [
    {
        x: 600,
        y0: WALL,
        y1: MID - 8,
        gaps: [
            [96, 140],
            [292, 340],
        ],
    },
    {
        x: 880,
        y0: WALL,
        y1: MID - 8,
        gaps: [
            [112, 156],
            [292, 340],
        ],
    },
    { x: 150, y0: FLOOR2, y1: H, gaps: [[604, 652]] },
    {
        x: 760,
        y0: FLOOR2,
        y1: H,
        gaps: [
            [476, 524],
            [624, 672],
        ],
    },
    { x: 1150, y0: FLOOR2, y1: H, gaps: [[600, 648]] },
];
// doorways through the dividing wall (x ranges): office→first aid, office→lounge, meeting→lounge, kitchen→games
const MID_GAPS = [
    [98, 138],
    [262, 306],
    [690, 734],
    [1086, 1130],
];

// props are y-sorted with the workers; `base` is their floor contact line
const PROPS = [];
const prop = (key, x, y, opt = {}) => {
    const sw = C[key] ? C[key][3] : opt.w,
        sh = C[key] ? C[key][4] : opt.h;
    PROPS.push({
        key,
        x,
        y,
        w: sw,
        h: sh,
        base: opt.base ?? y + sh,
        block: opt.block === false ? null : opt.block || [x, y + sh - 12, x + sw, y + sh],
        ...opt,
    });
};
for (const P of PARTS) {
    let y = P.y0;
    for (const [a, b] of [...P.gaps, [P.y1, P.y1]]) {
        if (a > y) {
            const y0 = y,
                y1 = a;
            prop("wall", P.x - 5, y0 - 20, {
                w: 10,
                h: y1 - y0 + 20,
                base: y1,
                block: [P.x - 4, y0, P.x + 4, y1],
                draw: () => drawWallSeg(P.x, y0, y1),
                noShadow: true,
            });
        }
        y = b;
    }
}
// --- ops floor
for (const [i, d] of DESKS.entries()) {
    d.kind = ["desk", "desk", "deskDark", "desk", "deskGrey", "desk", "desk", "deskWhite"][i % 8];
    prop(d.kind, d.x, d.y, { block: [d.x, d.y + 6, d.x + 58, d.y + 35], after: (now) => drawDeskTop(d, now) });
    prop("chairBack", d.seat.x - 12, d.seat.y - 22, {
        base: d.seat.y + 2,
        block: [d.seat.x - 10, d.seat.y - 5, d.seat.x + 10, d.seat.y + 4],
        noShadow: true,
    });
}
prop("books1", 300, 22, { base: 92 });
prop("books2", 332, 22, { base: 92 });
prop("copier", COPIER.x, COPIER.y);
prop("bin", 6, 300, { base: 328 });
prop("plantFern", 6, 96, { base: 147 });
if (XMAS) {
    // the Christmas tree takes the potted tree's corner, presents where the boxes were
    prop("xtree0", 418, 226, {
        base: 340,
        block: [438, 326, 484, 340],
        draw: (now) => blit(ctx, REDUCED || Math.floor(now / 900) % 2 ? "xtree0" : "xtree1", 418, 226),
    });
    const GIFTS = [
        ["giftGreen", 424, 346],
        ["giftBig", 452, 348],
        ["giftTiny", 484, 347],
        ["giftGold", 478, 344],
        ["giftPink", 402, 347],
        ["giftTall", 504, 345],
    ];
    for (const [k, x, b] of GIFTS.slice(0, presentsFor(SMO, SD)))
        prop(k, x, b - C[k][4], { base: b, block: false, noShadow: true });
} else {
    prop("plantTree", 440, 262, { base: 340, block: [444, 326, 468, 340] });
    prop("boxes", 494, 318, { base: 340 });
}
prop("lampFloor", 408, 96, { base: 145 });
prop("rack", RACK.x, RACK.y, {
    w: 22,
    h: 46,
    block: [RACK.x, RACK.y + 34, RACK.x + 46, RACK.y + 46],
    draw: (now) => drawRack(RACK.x, RACK.y, 0, now),
});
prop("rack", RACK.x + 24, RACK.y, { w: 22, h: 46, block: false, draw: (now) => drawRack(RACK.x + 24, RACK.y, 1, now) });
// --- meeting room: long table, chairs either side, whiteboard and clock on the wall
prop("tableLong", TABLE.x, TABLE.y, {
    block: [TABLE.x, TABLE.y + 8, TABLE.x + 192, TABLE.y + 40],
    after: () => drawMeetingClutter(),
});
const MEET_X = [668, 716, 764, 812],
    MEET_N = MEET_X.map((x) => ({ x, y: TABLE.y + 12 })),
    MEET_S = MEET_X.map((x) => ({ x, y: TABLE.y + 54 }));
for (const sP of MEET_N) prop("chairFront", sP.x - 12, sP.y - 30, { base: sP.y - 1, block: false });
for (const sP of MEET_S)
    prop("chairBack", sP.x - 12, sP.y - 22, {
        base: sP.y + 2,
        block: [sP.x - 10, sP.y - 6, sP.x + 10, sP.y + 4],
        noShadow: true,
    });
prop("call", CALL.x, CALL.y, {
    w: 30,
    h: 50,
    base: CALL.y + 50,
    block: [CALL.x + 2, CALL.y + 42, CALL.x + 28, CALL.y + 50],
    draw: (now) => drawCallScreen(now),
});
prop("plantFern", 840, 288, { base: 339 });
prop("lampFloor", 610, 272, { base: 321 });
prop("cabinetLow", 606, 96, { base: 117 });
// --- kitchen: fitted units along the back wall, breakfast bar with stools, two café tables
prop("counterA", 886, 56, { base: 94 });
prop("coffee", 1000, 33, { base: 95, block: false });
prop("fridge", 1032, 32, { base: 96, after: (now) => drawFridgeOpen(now) });
prop("counterB", 1066, 48, { base: 94, after: () => drawSink(1150, 50) });
prop("vending", 1212, 31, { base: 95 });
prop("cooler", 1250, 40, { base: 93 });
prop("island", ISLAND.x, ISLAND.y, {
    block: [ISLAND.x, ISLAND.y + 10, ISLAND.x + 96, ISLAND.y + 40],
    after: () => drawIslandTop(),
});
const BAR = [972, 996, 1020, 1044].map((x) => ({ x, y: ISLAND.y + 58 }));
for (const s of BAR)
    prop("stool", s.x - 5, s.y - 8, {
        w: 10,
        h: 9,
        base: s.y,
        block: [s.x - 5, s.y - 3, s.x + 5, s.y + 2],
        noShadow: true,
        draw: () => drawStool(s.x, s.y),
    });
for (const t of CAFE) {
    prop("cafe", t.x - 10, t.y - 12, {
        w: 20,
        h: 16,
        base: t.y + 4,
        block: [t.x - 8, t.y - 2, t.x + 8, t.y + 4],
        draw: () => drawCafeTable(t),
    });
    for (const sd of [-1, 1])
        prop("stool", t.x + sd * 16 - 5, t.y - 8, {
            w: 10,
            h: 9,
            base: t.y,
            block: [t.x + sd * 16 - 5, t.y - 3, t.x + sd * 16 + 5, t.y + 2],
            noShadow: true,
            draw: () => drawStool(t.x + sd * 16, t.y),
        });
}
// dining table: chairs either side, like the meeting room but for lunch
prop("island", DINING.x, DINING.y, {
    block: [DINING.x, DINING.y + 8, DINING.x + 96, DINING.y + 40],
    after: () => drawDiningTop(),
});
const DINE_N = [1136, 1184].map((x) => ({ x, y: DINING.y + 12 })),
    DINE_S = [1136, 1184].map((x) => ({ x, y: DINING.y + 54 }));
for (const sP of DINE_N) prop("chairFront", sP.x - 12, sP.y - 30, { base: sP.y - 1, block: false });
for (const sP of DINE_S)
    prop("chairBack", sP.x - 12, sP.y - 22, {
        base: sP.y + 2,
        block: [sP.x - 10, sP.y - 6, sP.x + 10, sP.y + 4],
        noShadow: true,
    });
prop("plantTree", 892, 262, { base: 340, block: [896, 326, 920, 340] });
prop("bin", 1254, 120, { base: 148 });
prop("plantFern", 1236, 96, { base: 147 });
// --- first aid: bed behind a screen, IV drip stand, waiting chairs
prop("bedTop", BED.x + 1, BED.y, { base: BED.y + 26, block: [BED.x, BED.y, BED.x + 46, BED.y + 60] });
prop("bedBody", BED.x, BED.y + 14, { base: BED.y + 60, block: false, noShadow: true });
prop("drip", BED.x - 14, BED.y + 4, {
    w: 10,
    h: 40,
    base: BED.y + 44,
    block: false,
    noShadow: true,
    draw: () => drawDrip(BED.x - 10, BED.y + 4),
});
prop("screen", BED.x + 52, BED.y - 6, {
    block: [BED.x + 52, BED.y + 44, BED.x + 84, BED.y + 58],
    after: () => {
        const cx = BED.x + 67,
            cy = BED.y + 14;
        ctx.fillStyle = "#d94848";
        ctx.fillRect(cx - 1, cy - 4, 3, 9);
        ctx.fillRect(cx - 4, cy - 1, 9, 3);
    },
});
for (const x of [24, 50, 76, 102])
    prop("chairFront", x - 12, 570, { base: 599, block: [x - 10, 588, x + 10, 598], noShadow: true });
prop("plantBox", 112, 650, { base: 702 });
prop("endTable", 8, 650, { base: 674 });
prop("lampTable", 6, 630, { base: 675, block: false });
// --- lounge: wall TV, U of sofas round a coffee table, bookshelves, grandfather clock
prop("mediaUnit", TV.x + TV.w / 2 - 32, 446, {
    base: 468,
    block: [TV.x + TV.w / 2 - 32, 452, TV.x + TV.w / 2 + 32, 468],
});
prop("sofaBack", SOFA_BACK.x, SOFA_BACK.y, {
    block: [SOFA_BACK.x, SOFA_BACK.y + 8, SOFA_BACK.x + 94, SOFA_BACK.y + 31],
});
prop("sofaSideR", SOFA_L.x, SOFA_L.y, { block: [SOFA_L.x, SOFA_L.y + 8, SOFA_L.x + 26, SOFA_L.y + 82] });
prop("sofaSideL", SOFA_R.x, SOFA_R.y, { block: [SOFA_R.x + 3, SOFA_R.y + 8, SOFA_R.x + 29, SOFA_R.y + 82] });
prop("coffeeTable", 469, 520, { base: 541, block: [469, 528, 531, 541], after: () => drawCoffeeTableTop() });
prop("books1", 322, 382, { base: 452 });
prop("books2", 354, 382, { base: 452 });
prop("fireplace", FP.x, FP.y, {
    block: [FP.x, FP.y + 58, FP.x + 80, FP.y + 74],
    draw: (now) => {
        blit(ctx, "fireplace", FP.x, FP.y);
        drawFire(now, fireNow());
        blit(ctx, "fireTools", FP.x + 3, FP.y + 43); // poker, brush and shovel on the hearth, by the left pillar
        if (XMAS) {
            blit(ctx, "stockingR", FP.x + 1, FP.y + 17);
            blit(ctx, "stockingG", FP.x + 36, FP.y + 17);
            blit(ctx, "stockingW", FP.x + 69, FP.y + 17);
        } // hung from the mantel
    },
});
prop("gclock0", 390, 382, {
    base: 453,
    draw: (now) => blit(ctx, "gclock" + [0, 1, 2, 1][Math.floor(now / 520) % 4], 390, 382),
});
const NOOK = { x: 168, y: 512 };
prop("sofaGreen", NOOK.x, NOOK.y, { block: [NOOK.x, NOOK.y + 10, NOOK.x + 94, NOOK.y + 38] });
prop("endTable", NOOK.x + 100, NOOK.y + 12, { base: NOOK.y + 36 });
prop("lampTable", NOOK.x + 98, NOOK.y - 10, { base: NOOK.y + 37, block: false });
prop("lampFloor", 640, 456, { base: 505 });
prop("lampFloor", 342, 560, { base: 609 });
prop("plantTree", 724, 616, { base: 694, block: [728, 680, 752, 694] });
prop("plantFern", 160, 650, { base: 701 });
// --- games room: arcades along the wall, console den, table tennis, foosball, darts
for (const a of ARCADES)
    prop("arcade", a.x, a.y, {
        w: 24,
        h: 46,
        block: [a.x, a.y + 32, a.x + 24, a.y + 46],
        draw: (now) => drawArcade(a, now),
    });
prop("pong", PONG.x, PONG.y - 4, {
    w: PONG.w,
    h: PONG.h + 10,
    base: PONG.y + PONG.h + 4,
    block: [PONG.x, PONG.y + 12, PONG.x + PONG.w, PONG.y + PONG.h + 4],
    draw: (now) => drawPong(now),
});
prop("foos", FOOS.x, FOOS.y - 4, {
    w: FOOS.w,
    h: FOOS.h + 10,
    base: FOOS.y + FOOS.h + 4,
    block: [FOOS.x, FOOS.y + 8, FOOS.x + FOOS.w, FOOS.y + FOOS.h + 4],
    draw: (now) => drawFoos(now),
});
prop("denTv", DEN.x, DEN.tv.y, {
    w: 64,
    h: 54,
    base: DEN.y + 21,
    block: [DEN.x, DEN.y - 8, DEN.x + 64, DEN.y + 21],
    draw: (now) => drawDen(now),
});
for (const b of BEANBAGS)
    prop("beanbag", b.x - 10, b.y - 12, {
        w: 20,
        h: 14,
        base: b.y,
        block: [b.x - 9, b.y - 6, b.x + 9, b.y + 1],
        noShadow: true,
        draw: () => drawBeanbag(b),
    });
prop("sofaBlueBack", DEN_SOFA.x, DEN_SOFA.y, { block: [DEN_SOFA.x, DEN_SOFA.y + 8, DEN_SOFA.x + 94, DEN_SOFA.y + 31] });
prop("lampFloor", 922, 612, { base: 661 });
prop("plantFern", 1100, 652, { base: 703 });
// --- The user's office: a desk facing the door with two visitor chairs, bookshelves, a filing cabinet, lamp and plant
prop("books1", 1158, 382, { base: 452 });
prop("books2", 1190, 382, { base: 452 });
prop("chairFront", USER_DESK.x + 17, USER_DESK.y - 18, { base: USER_DESK.y + 11, block: false }); // the user's chair, empty
prop("deskDark", USER_DESK.x, USER_DESK.y, {
    block: [USER_DESK.x, USER_DESK.y + 6, USER_DESK.x + 58, USER_DESK.y + 35],
    after: () => drawUserDesk(),
});
const VISIT = [1204, 1236].map((x) => ({ x, y: USER_DESK.y + 54 }));
for (const sP of VISIT)
    prop("chairBack", sP.x - 12, sP.y - 22, {
        base: sP.y + 2,
        block: [sP.x - 10, sP.y - 6, sP.x + 10, sP.y + 4],
        noShadow: true,
    });
prop("drawers", 1244, 452, { base: 521, block: [1244, 509, 1276, 521] });
prop("lampFloor", 1158, 660, { base: 709 });
prop("plantTree", 1244, 616, { base: 694, block: [1248, 680, 1272, 694] });
prop("vendingG", 900, 450, { base: 514, block: [900, 500, 932, 514], draw: () => blit(ctx, "vending", 900, 450) });
// --- seasonal table-top and floor decor (never blocks: the walk grid stays the same all year)
const deco = (key, x, y, base) => prop(key, x, y, { base, block: false, noShadow: true });
const vase = (vk, fk, x, y, base) =>
    prop(vk, x, y, {
        base,
        block: false,
        noShadow: true,
        draw: () => {
            blit(ctx, vk, x, y);
            blit(ctx, fk, x - 4, y - 11);
        },
    });
if (SEASON === "halloween") {
    deco("gourds", 900, 48, 95);
    deco("pumpkin", 506, 85, 93);
    deco("pumpkin", 612, 90, 118);
    deco("skull", 306, 4, 93);
    deco("pumpkin", 1160, 202, 231);
}
if (SEASON === "valentine") {
    vase("vasePink", "roses", 1154, 192, 231);
    vase("vasePink", "roses", 960, 44, 95);
}
if (SEASON === "easter") {
    vase("vaseWhite", "daffs", 1154, 192, 231);
    vase("vaseWhite", "daffs", 960, 44, 95);
    vase("vaseWhite", "daffs", 614, 74, 118);
}

// points of interest for off-shift roaming
const POIS = [];
const poi = (tag, x, y, face, opt = {}) => POIS.push({ tag, x, y, face, pose: null, ...opt, taken: null });
// ops floor
poi("window", 30, 98, "up");
poi("window", 70, 98, "up");
poi("window", 196, 98, "up");
poi("window", 236, 98, "up");
poi("art", 124, 98, "up");
poi("books", 316, 100, "up");
poi("books", 348, 100, "up");
poi("door", 452, 104, "down", { only: "guard" });
poi("post", 402, 100, "up"); // the pigeonholes: only worth the walk while post is waiting (postLeft)
poi("chat", 196, 304, "right", { pair: 1 });
poi("chat", 222, 304, "left", { pair: 1 });
poi("chat", 300, 318, "right", { pair: 2 });
poi("chat", 326, 318, "left", { pair: 2 });
poi("plant", XMAS ? 404 : 432, 338, "right");
poi("copier", 512, 124, "up"); // at Christmas the plant-waterer tends the tree instead poi("phone", 24, 340, "down"); poi("phone", 434, 196, "left");
for (const d of DESKS) poi("peek", d.seat.x + 24, d.seat.y + 2, "left", { desk: d });
// meeting room
for (const sP of MEET_N)
    poi("meeting", sP.x, sP.y, "down", { pose: "sit", sort: sP.y, approach: { x: sP.x, y: sP.y - 22 } });
for (const sP of MEET_S)
    poi("meeting", sP.x, sP.y, "up", { pose: "sit", sort: sP.y + 1, approach: { x: sP.x, y: sP.y + 14 } });
poi("board", 710, 104, "up");
poi("board", 780, 104, "up");
poi("window", 858, 98, "up");
// Signed out: the meeting seats nearest the call screen fill first
const CALL_SEATS = POIS.filter((p) => p.tag === "meeting").sort((a, b) => b.x - a.x || a.y - b.y);
// queued writers without a free desk stare out of the ops-floor windows (two stand just behind), then the meeting-room window
poi("window", 50, 112, "up", { only: "queue" });
poi("window", 216, 112, "up", { only: "queue" });
const QUEUE_WINDOWS = POIS.filter((p) => p.tag === "window").sort(
    (a, b) => (a.x > 600) - (b.x > 600) || a.y - b.y || a.x - b.x,
);
poi("chat", 640, 316, "right", { pair: 3 });
poi("chat", 666, 316, "left", { pair: 3 });
// kitchen
poi("coffee", 1007, 106, "up");
poi("fridge", 1048, 108, "up");
poi("vending", 1228, 108, "up");
poi("cooler", 1259, 104, "up");
poi("sink", 1150, 104, "up");
poi("chat", 912, 130, "right", { pair: 4 });
poi("chat", 938, 130, "left", { pair: 4 });
for (const s of BAR)
    poi("table", s.x, s.y, "up", { pose: "sit", sort: s.y + 1, approach: { x: s.x, y: s.y + 14 }, bar: true });
for (const sP of DINE_N)
    poi("table", sP.x, sP.y, "down", { pose: "sit", sort: sP.y, approach: { x: sP.x, y: sP.y - 22 }, dine: true });
for (const sP of DINE_S)
    poi("table", sP.x, sP.y, "up", { pose: "sit", sort: sP.y + 1, approach: { x: sP.x, y: sP.y + 14 }, dine: true });
for (const t of CAFE) {
    poi("table", t.x - 16, t.y + 1, "right", {
        pose: "sit",
        sort: t.y + 1,
        approach: { x: t.x - 28, y: t.y + 2 },
        cafe: t,
    });
    poi("table", t.x + 16, t.y + 1, "left", {
        pose: "sit",
        sort: t.y + 1,
        approach: { x: t.x + 28, y: t.y + 2 },
        cafe: t,
    });
}
// lounge
for (let i = 0; i < 3; i++)
    poi("sofa", SOFA_BACK.x + 18 + i * 29, SOFA_BACK.y + 22, "up", {
        pose: "sit",
        sort: SOFA_BACK.y + 20,
        approach: { x: SOFA_BACK.x + 18 + i * 29, y: SOFA_BACK.y - 6 },
    });
// Side sofas are tall sprites sorted on their bottom edge (y + 82), so sitters sort just past it
// or the sofa paints over them.
for (let i = 0; i < 3; i++)
    poi("sofa", SOFA_L.x + 15, SOFA_L.y + 30 + i * 22, "right", {
        pose: "sit",
        sort: SOFA_L.y + 83 + i,
        approach: { x: SOFA_L.x + 38, y: SOFA_L.y + 30 + i * 22 },
    });
for (let i = 0; i < 3; i++)
    poi("sofa", SOFA_R.x + 14, SOFA_R.y + 30 + i * 22, "left", {
        pose: "sit",
        sort: SOFA_R.y + 83 + i,
        approach: { x: SOFA_R.x - 9, y: SOFA_R.y + 30 + i * 22 },
    });
poi("tv", 446, 496, "up");
poi("tv", 556, 496, "up");
poi("books", 338, 462, "up");
poi("books", 370, 462, "up");
poi("fire", FP.x + 22, FP.y + 88, "up");
poi("fire", FP.x + 56, FP.y + 88, "up"); // warming hands at the hearth (only while it's lit)
for (let i = 0; i < 3; i++)
    poi("read", NOOK.x + 18 + i * 29, NOOK.y + 30, "down", {
        pose: "sit",
        sort: NOOK.y + 39,
        approach: { x: NOOK.x + 18 + i * 29, y: NOOK.y + 48 },
    });
poi("read", 420, 676, "down", { pose: "floor" });
poi("read", 640, 660, "left", { pose: "floor" });
poi("chat", 668, 560, "right", { pair: 5 });
poi("chat", 694, 560, "left", { pair: 5 });
poi("phone", 300, 690, "down");
poi("plant", 712, 690, "right");
// games room
for (const a of ARCADES) poi("arcade", a.x + 12, a.y + 58, "up", { arcade: a });
poi("pong", PONG.L - 9, PONG.y + 18, "right", { pair: 9 });
poi("pong", PONG.R + 9, PONG.y + 18, "left", { pair: 9 });
poi("foos", FOOS.x - 10, FOOS.y + 18, "right", { pair: 10 });
poi("foos", FOOS.x + FOOS.w + 10, FOOS.y + 18, "left", { pair: 10 });
poi("darts", DARTS.x, 520, "up");
poi("books", 1174, 462, "up");
poi("books", 1206, 462, "up");
for (const sP of VISIT)
    poi("visit", sP.x, sP.y, "up", { pose: "sit", sort: sP.y + 1, approach: { x: sP.x, y: sP.y + 14 } });
poi("vending", 916, 524, "up");
poi("chat", 1062, 700, "right", { pair: 6 });
poi("chat", 1088, 700, "left", { pair: 6 });
poi("phone", 950, 700, "down");
// first aid
poi("plant", 100, 690, "right");
poi("bedside", 96, 548, "left", { only: "errand" });
const BEDSIDE = POIS.find((p) => p.tag === "bedside");
for (const b of BEANBAGS)
    poi("console", b.x, b.y - 1, "up", { pose: "floor", sort: b.y + 1, approach: { x: b.x, y: b.y + 12 } });
for (let i = 0; i < 3; i++)
    poi("console", DEN_SOFA.x + 18 + i * 29, DEN_SOFA.y + 22, "up", {
        pose: "sit",
        sort: DEN_SOFA.y + 20,
        approach: { x: DEN_SOFA.x + 18 + i * 29, y: DEN_SOFA.y - 6 },
    });
// employee of the week: the winner steps up under the frame on Friday at 16:00 (never a roaming spot)
poi("frame", 436, 100, "down", { only: "ceremony" });
const FRAME_POI = POIS.find((p) => p.tag === "frame");
// Easter egg hunt: six of these spots get an egg each day (x, y = where it sits; base = draw order). Click to find them.
const EGG_POOL = [
    { x: 546, y: 82, base: 118 },
    { x: 340, y: 24, base: 93 },
    { x: 49, y: 490, base: 539 },
    { x: 520, y: 532, base: 542 },
    { x: 716, y: 700, base: 701 },
    { x: 878, y: 500, base: 501 },
    { x: 872, y: 612, base: 621 },
    { x: 1030, y: 210, base: 231 },
    { x: 630, y: 100, base: 118 },
    { x: 512, y: 92, base: 93 },
    { x: 1120, y: 706, base: 707 },
    { x: 20, y: 150, base: 151 },
];
const EGG_KEY = "office-eggs-" + TODAY_KEY;
const eggs =
    SEASON === "easter"
        ? eggSpots(TODAY_KEY, EGG_POOL, 6).map((p) => ({ ...p, found: false, brown: hash(TODAY_KEY + p.x) > 0.5 }))
        : [];
try {
    const got = JSON.parse(localStorage.getItem(EGG_KEY) || "[]");
    for (const e of eggs) e.found = got.includes(e.x + "," + e.y);
} catch (e) {
    /* private mode: a fresh hunt */
}
const PONG_POIS = POIS.filter((p) => p.tag === "pong"),
    FOOS_POIS = POIS.filter((p) => p.tag === "foos");
const WINDOWS = [14, 54, 180, 220, 842];
// Sick-bay layout: index 0 gets the hospital bed, 1..4 sit on the four waiting chairs, and any overflow
// (e.g. after a laptop sleep or network blip) stands in staggered triage lanes below the chairs so nobody stacks.
function sickSpot(i) {
    if (i <= 0)
        return {
            x: BED.x + 23,
            y: BED.y + 40,
            face: "down",
            pose: "sit",
            sort: BED.y + 61,
            approach: { x: BED.x + 23, y: BED.y + 66 },
        };
    if (i <= 4) {
        const x = [24, 50, 76, 102][i - 1];
        return { x, y: 600, face: "down", pose: "sit", sort: 600, approach: { x, y: 614 } };
    }
    const k = i - 5,
        x = [44, 68, 92, 116, 24, 48, 72, 96][k % 8],
        y = Math.min(700, 664 + Math.floor(k / 4) * 32);
    return { x, y, face: "down" };
}
// The sicker worker (longest consecutive failure streak) gets the single hospital bed; others take the waiting chairs.
function sickOrder(list, streaks = {}) {
    return [...list].sort(
        (a, b) =>
            ((streaks && streaks[b.id]) || b._demoStreak || 0) - ((streaks && streaks[a.id]) || a._demoStreak || 0),
    );
}
// Signed out: an auth-failed task (index 0) stands at the call screen, blocked tasks sit round the meeting table nearest
// the screen first, and any overflow stands in two staggered rows south of the table (lifted into tests/test_office.py).
function callSpot(i, seats) {
    if (i <= 0) return { x: CALL.front.x, y: CALL.front.y, face: "up" };
    if (i <= seats.length) return seats[i - 1];
    const k = i - 1 - seats.length,
        row = Math.floor(k / 6) % 2;
    return { x: 812 - (k % 6) * 24 - row * 12, y: 290 + row * 42, face: "up" };
}
// Writers waiting on the writer lock in the order the Office saw each join (the runner exposes no order), so the
// longest-waiting gets the next free desk; ties keep list order (lifted into tests/test_office.py).
// When the runner's scheduler will next start a task (ms), mirroring its gates: day gate, then a pending retry,
// then run_at (once a day) or interval since last_run. null = not today (lifted into tests/test_office.py).
function dueAt(t, now) {
    const d = new Date(now),
        day = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][d.getDay()];
    if (
        (t.weekdays_only && (d.getDay() === 0 || d.getDay() === 6)) ||
        (t.days_of_week && t.days_of_week.length && !t.days_of_week.includes(day))
    )
        return null;
    const retry = t.retry_at ? Date.parse(t.retry_at) : NaN;
    if (!isNaN(retry)) return retry;
    const last = t.last_run ? Date.parse(t.last_run) : NaN;
    if (t.run_at) {
        const [h, m] = t.run_at.split(":").map(Number),
            tgt = new Date(d);
        tgt.setHours(h, m, 0, 0);
        if (now < +tgt) return +tgt;
        if (!isNaN(last) && last >= +tgt) {
            tgt.setDate(tgt.getDate() + 1);
            return +tgt;
        }
        return now;
    }
    if (!t.interval) return null;
    return isNaN(last) ? now : last + t.interval * 1000;
}
// In the last few minutes before the scheduler starts them, off-shift workers drift back to the ops floor
// (still off shift: only a real run seats them). Weight for a spot in `room`, due in `dueIn` ms (lifted into tests/test_office.py).
const SHIFT_SOON = 180000;
function shiftPull(dueIn, room) {
    if (dueIn === null || !(dueIn > 0) || dueIn > SHIFT_SOON) return 1;
    return room === "office" ? 8 : 0.3;
}
// The card's note for an off-shift worker inside that window: walking back, or already there (lifted into tests/test_office.py).
function shiftNote(dueIn, moving) {
    if (dueIn === null || !(dueIn > 0) || dueIn > SHIFT_SOON) return "";
    return moving ? " · heading back for the next shift" : ` · on shift in ${Math.max(1, Math.ceil(dueIn / 60000))}m`;
}
// How late (ms) the scheduler is starting a worker whose slot has passed. The runner checks every 30s, so 10 minutes
// late means it is stalled or asleep; never for a run in hand, a writer-lock wait or a sign-in block (lifted into tests/test_office.py).
const OVERDUE = 600000,
    LATE_WATCH = 120000;
function overdueBy(t, now) {
    if (t.status === "running" || t.status === "blocked" || t.status === "auth-failed" || t.queued || t.waiting_behind)
        return 0;
    let at = dueAt(t, now);
    if (at === now && t.run_at && !t.retry_at) {
        const [h, m] = t.run_at.split(":").map(Number),
            d = new Date(now);
        d.setHours(h, m, 0, 0);
        at = +d;
    }
    const late = at === null ? 0 : now - at;
    return late > OVERDUE ? late : 0;
}
// The status bar's overdue clause: the latest worker the Office has watched stay late (w.late), plus how many others.
function lateNote(list, who, fmt) {
    const late = list.filter((w) => w.late > 0).sort((a, b) => b.late - a.late);
    if (!late.length) return "";
    const first = `${who(late[0])} ${fmt(late[0].late / 1000)} overdue`;
    return late.length === 1 ? first : `${first} (+${late.length - 1} more)`;
}
function queueOrder(list, since = {}) {
    return list
        .map((t, i) => [t, i])
        .sort((a, b) => (since[a[0].id] ?? Infinity) - (since[b[0].id] ?? Infinity) || a[1] - b[1])
        .map((p) => p[0]);
}
// The auth probe itself (auth-failed) stands at the call screen; tasks blocked waiting on it sit round the table.
function lockOrder(list) {
    return [...list].sort((a, b) => (b.status === "auth-failed") - (a.status === "auth-failed"));
}

// ================================================================ navigation grid (8px cells, A*)
const CELL = 8,
    GW = W / CELL,
    GH = H / CELL,
    grid = new Uint8Array(GW * GH),
    hug = new Float32Array(GW * GH),
    roomy = new Uint8Array(GW * GH);
function buildGrid() {
    grid.fill(0);
    hug.fill(0);
    roomy.fill(0);
    const blockRect = (x0, y0, x1, y1) => {
        for (let gy = Math.floor(y0 / CELL); gy <= Math.floor((y1 - 1) / CELL); gy++)
            for (let gx = Math.floor(x0 / CELL); gx <= Math.floor((x1 - 1) / CELL); gx++)
                if (gx >= 0 && gy >= 0 && gx < GW && gy < GH) grid[gy * GW + gx] = 1;
    };
    blockRect(0, 0, W, WALL + 10);
    blockRect(0, H - 6, W, H);
    // the dividing wall: its cap and face, open only at the doorways
    let gx0 = 0;
    for (const [a, b] of [...MID_GAPS, [W, W]]) {
        if (a > gx0) blockRect(gx0, MID - 14, a, FLOOR2 + 8);
        gx0 = b;
    }
    for (const p of PROPS) if (p.block) blockRect(...p.block);
    // extra A* cost beside furniture so routes keep a body-width off it (1 cell: heavy, 2 cells: light)
    for (let gy = 0; gy < GH; gy++)
        for (let gx = 0; gx < GW; gx++) {
            if (grid[gy * GW + gx]) continue;
            let d = 3;
            for (let oy = -2; oy <= 2; oy++)
                for (let ox = -2; ox <= 2; ox++)
                    if (!walkable(gx + ox, gy + oy)) d = Math.min(d, Math.max(Math.abs(ox), Math.abs(oy)));
            hug[gy * GW + gx] = d === 1 ? 2 : d === 2 ? 0.3 : 0;
            // routes only use cells a body fits through: a walker's feet span a cell either side
            roomy[gy * GW + gx] = walkable(gx - 1, gy) && walkable(gx + 1, gy) ? 1 : 0;
        }
}
const roomyAt = (gx, gy) => gx >= 0 && gy >= 0 && gx < GW && gy < GH && roomy[gy * GW + gx] === 1;
const walkable = (gx, gy) => gx >= 0 && gy >= 0 && gx < GW && gy < GH && !grid[gy * GW + gx];
const walkablePx = (x, y) => walkable(Math.floor(x / CELL), Math.floor(y / CELL));
function nearestOpen(gx, gy) {
    if (roomyAt(gx, gy)) return [gx, gy];
    for (let r = 1; r < 12; r++)
        for (let dy = -r; dy <= r; dy++)
            for (let dx = -r; dx <= r; dx++)
                if (Math.max(Math.abs(dx), Math.abs(dy)) === r && roomyAt(gx + dx, gy + dy)) return [gx + dx, gy + dy];
    return [gx, gy];
}
const BODY = 6; // half-width of a walker's feet
const bodyClear = (x, y) => walkablePx(x, y) && walkablePx(x - BODY, y) && walkablePx(x + BODY, y);
function lineClear(ax, ay, bx2, by) {
    const steps = Math.ceil(Math.hypot(bx2 - ax, by - ay) / 4);
    for (let i = 1; i < steps; i++) {
        const x = ax + ((bx2 - ax) * i) / steps,
            y = ay + ((by - ay) * i) / steps;
        if (!bodyClear(x, y)) return false;
    }
    return true;
}
const N = GW * GH,
    gScore = new Float32Array(N),
    fScore = new Float32Array(N),
    from = new Int32Array(N),
    closed = new Uint8Array(N);
function findPath(sx, sy, tx, ty) {
    const [ax, ay] = nearestOpen(Math.floor(sx / CELL), Math.floor(sy / CELL));
    const [gx, gy] = nearestOpen(Math.floor(tx / CELL), Math.floor(ty / CELL));
    gScore.fill(Infinity);
    from.fill(-1);
    closed.fill(0);
    const start = ay * GW + ax,
        goal = gy * GW + gx;
    const hx = (i) => {
        const x = i % GW,
            y = (i / GW) | 0,
            dx = Math.abs(x - gx),
            dy = Math.abs(y - gy);
        return Math.max(dx, dy) + 0.414 * Math.min(dx, dy);
    };
    // binary heap keyed on fScore
    const heap = [];
    const push = (i) => {
        heap.push(i);
        let k = heap.length - 1;
        while (k > 0) {
            const p = (k - 1) >> 1;
            if (fScore[heap[p]] <= fScore[heap[k]]) break;
            [heap[p], heap[k]] = [heap[k], heap[p]];
            k = p;
        }
    };
    const pop = () => {
        const top = heap[0],
            last = heap.pop();
        if (heap.length) {
            heap[0] = last;
            let k = 0;
            for (;;) {
                const l = 2 * k + 1,
                    r = l + 1;
                let m = k;
                if (l < heap.length && fScore[heap[l]] < fScore[heap[m]]) m = l;
                if (r < heap.length && fScore[heap[r]] < fScore[heap[m]]) m = r;
                if (m === k) break;
                [heap[m], heap[k]] = [heap[k], heap[m]];
                k = m;
            }
        }
        return top;
    };
    gScore[start] = 0;
    fScore[start] = hx(start);
    push(start);
    let found = false,
        guard = 0;
    while (heap.length && guard++ < 20000) {
        const cur = pop();
        if (closed[cur]) continue;
        if (cur === goal) {
            found = true;
            break;
        }
        closed[cur] = 1;
        const cx = cur % GW,
            cy = (cur / GW) | 0;
        for (let dy = -1; dy <= 1; dy++)
            for (let dx = -1; dx <= 1; dx++) {
                if (!dx && !dy) continue;
                const nx = cx + dx,
                    ny = cy + dy;
                if (!roomyAt(nx, ny)) continue;
                if (dx && dy && (!roomyAt(cx + dx, cy) || !roomyAt(cx, cy + dy))) continue;
                const ni = ny * GW + nx;
                if (closed[ni]) continue;
                const ng = gScore[cur] + (dx && dy ? 1.414 : 1) + hug[ni];
                if (ng < gScore[ni]) {
                    gScore[ni] = ng;
                    fScore[ni] = ng + hx(ni);
                    from[ni] = cur;
                    push(ni);
                }
            }
    }
    const pts = [];
    if (found) {
        for (let i = goal; i !== -1 && i !== start; i = from[i])
            pts.push({ x: (i % GW) * CELL + CELL / 2, y: ((i / GW) | 0) * CELL + CELL / 2 });
        pts.reverse();
    }
    pts.push({ x: tx, y: ty });
    // string-pull: drop waypoints we can see past
    const out = [];
    let px = sx,
        py = sy;
    for (let i = 0; i < pts.length; i++) {
        const nxt = pts[i + 1];
        if (nxt && lineClear(px, py, nxt.x, nxt.y)) continue;
        out.push(pts[i]);
        px = pts[i].x;
        py = pts[i].y;
    }
    return out;
}

// ================================================================ time of day
function clock() {
    const d = new Date();
    const h = HOUR_OVERRIDE ?? d.getHours(),
        m = HOUR_OVERRIDE != null ? 0 : d.getMinutes();
    return {
        h,
        m,
        s: d.getSeconds() + d.getMilliseconds() / 1000,
        t: h + m / 60,
        day: DAY_OVERRIDE ?? d.getDay(),
        wx: WEATHER_OVERRIDE ?? weatherFor(d.getFullYear(), d.getMonth(), d.getDate(), h),
        ...sunTimes(d),
    };
}
// Ambient weather, not a live feed: seeded per date and three-hour block, as wet as London tends to be that month.
// shortcut: invented, not forecast; take a real feed if the dashboard ever grows a weather endpoint.
const RAIN_ODDS = [0.5, 0.42, 0.4, 0.38, 0.38, 0.35, 0.33, 0.36, 0.38, 0.46, 0.5, 0.5];
function weatherFor(y, mo, d, h) {
    const day = hash(`wx${y}-${mo}-${d}`),
        blk = hash(`wx${y}-${mo}-${d}-${Math.floor(h / 3)}`);
    const p = RAIN_ODDS[mo] * (0.5 + day); // a wet day stays wet, a dry one stays mostly dry
    return blk < p ? "rain" : blk < p + 0.3 ? "cloudy" : "clear";
}
// Local sunrise/sunset in clock hours, so a November 18:00 is dark and a June 20:00 is light.
// shortcut: fixed at London (51.5N, 0E), good to ~10 min; take the viewer's position if the user ever travels with it.
function sunTimes(d) {
    const doy = Math.round(
        (Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) - Date.UTC(d.getFullYear(), 0, 0)) / 864e5,
    );
    const rad = Math.PI / 180,
        lat = 51.5 * rad,
        decl = 23.44 * rad * Math.sin((2 * Math.PI * (284 + doy)) / 365);
    const B = (2 * Math.PI * (doy - 81)) / 365,
        eot = 9.87 * Math.sin(2 * B) - 7.53 * Math.cos(B) - 1.5 * Math.sin(B); // minutes
    const noon = 12 - d.getTimezoneOffset() / 60 - eot / 60;
    const half =
        Math.acos(
            clamp((Math.sin(-0.833 * rad) - Math.sin(lat) * Math.sin(decl)) / (Math.cos(lat) * Math.cos(decl)), -1, 1),
        ) /
        rad /
        15;
    return { rise: noon - half, set: noon + half };
}
function darkness(T) {
    // outdoor sky darkness: 0 = full day, ~0.62 = deep night; dusk runs from 30 min before sunset to 90 min after
    const { t, rise, set } = T;
    if (t >= rise + 0.5 && t < set - 0.5) return 0;
    if (t >= set - 0.5 && t < set + 1.5) return (0.62 * (t - set + 0.5)) / 2;
    if (t >= rise - 1.5 && t < rise + 0.5) return 0.62 * (1 - (t - rise + 1.5) / 2);
    return 0.62;
}
// Night-shift behaviour (naps, the robot vacuum, the Night shift headline) follows clock hours (21:00-07:00),
// not sunset, so a 16:45 November afternoon doesn't put the crew to sleep or send the vacuum out.
function nightShift(T) {
    return T.t >= 21 || T.t < 7;
}
// During working hours (07:00-17:30) the office keeps its room lights on when the winter sun sets early,
// then dims through the evening wind-down (17:30-21:00) into full night-shift lamp pools after 21:00.
function indoorDarkness(T) {
    const d = darkness(T);
    if (nightShift(T)) return d;
    if (T.t < 17.5) return Math.min(d * 0.4, 0.22);
    return Math.min(d, 0.22 + (0.4 * (T.t - 17.5)) / 3.5);
}
// Indoor lamps switch on as dusk begins and also glow softly on grey or rainy daytime afternoons.
function lampStrength(T) {
    const d = darkness(T);
    if (d > 0) return clamp(d / 0.22, 0, 1);
    return T.wx === "rain" ? 0.55 : T.wx === "cloudy" ? 0.3 : 0;
}
// The lounge fire: lit through the day in the cold months (October and April only when it's grey),
// down to embers in the evening and out overnight. 0 = cold grate, 1 = embers, 2 = burning (tests/test_office.py).
function fireState(mo, T) {
    const cold = mo >= 10 || mo <= 2 || ((mo === 9 || mo === 3) && T.wx !== "clear");
    if (!cold || T.t < 8 || T.t >= 23) return 0;
    return T.t < 20 ? 2 : 1;
}
const fireNow = () => fireState(SMO, clock());
const FLAME = [4, 7, 9, 11, 10, 11, 9, 7, 4];
function drawFire(now, st) {
    const x0 = FP.x + 22,
        fl = FP.y + 43,
        tt = REDUCED ? 0 : now; // logs' left end, firebox floor
    let flare = 0; // a poke flares the flames, fading over fireFlare.until ms on the render clock
    if (fireFlare.until) {
        if (fireFlare.at === null) fireFlare.at = now;
        flare = 1 - (now - fireFlare.at) / fireFlare.until;
        if (flare <= 0) {
            fireFlare.until = 0;
            flare = 0;
        }
    }
    ctx.fillStyle = "#3b2414";
    ctx.fillRect(x0 + 2, fl - 3, 32, 3);
    ctx.fillStyle = "#6b4226";
    ctx.fillRect(x0 + 6, fl - 5, 24, 2);
    ctx.fillStyle = "#8a5a34";
    ctx.fillRect(x0 + 2, fl - 3, 1, 3);
    ctx.fillRect(x0 + 6, fl - 5, 1, 2); // cut log ends
    if (!st) {
        ctx.fillStyle = "#5c5a58";
        ctx.fillRect(x0 + 4, fl - 1, 28, 1);
        return;
    } // cold grate, grey ash
    if (st === 1) {
        // embers glowing along the logs
        for (let i = 0; i < 7; i++) {
            const k = Math.sin(tt / 400 + i * 2.3);
            if (k > -0.3) {
                ctx.fillStyle = k > 0.5 ? "#ff8a2a" : "#b8321a";
                ctx.fillRect(x0 + 4 + i * 4, fl - 3 - (i % 2) * 2, 2, 1);
            }
        }
    }
    if (st === 2 || flare > 0) {
        // embers only show flames while a poke revives them
        const sc = st === 2 ? 1 + 0.55 * flare : 0.8 * flare;
        for (let i = 0; i < FLAME.length; i++) {
            const h = Math.max(
                    2,
                    Math.round(sc * FLAME[i] * (0.72 + 0.28 * Math.sin(tt / 90 + i * 1.7) * Math.sin(tt / 53 + i))),
                ),
                x = x0 + 4 + i * 3,
                y = fl - 4;
            ctx.fillStyle = "#e0501c";
            ctx.fillRect(x, y - h, 3, h);
            ctx.fillStyle = "#ffa62b";
            ctx.fillRect(x, y - Math.round(h * 0.65), 3, Math.round(h * 0.65));
            ctx.fillStyle = "#ffe27a";
            ctx.fillRect(x + 1, y - Math.round(h * 0.35), 1, Math.round(h * 0.35));
        }
    }
    // warm glow on the hearth that shows even by day (the night lamp pool is in lighting())
    const r = st === 2 ? 44 : 26,
        a = (st === 2 ? 0.2 : 0.1) * (0.85 + 0.15 * Math.sin(tt / 70)),
        cx = FP.x + 40,
        cy = FP.y + 52;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    g.addColorStop(0, `rgba(255,150,60,${a.toFixed(3)})`);
    g.addColorStop(1, "rgba(255,150,60,0)");
    ctx.fillStyle = g;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
    ctx.restore();
}
function golden(T) {
    // warm low-sun strength, 0..1, peaking just before sunset and just after sunrise
    const { t, rise, set } = T;
    if (Math.abs(t - set + 0.25) < 2) return clamp(1 - Math.abs(t - set + 0.25) / 1.5, 0, 1);
    if (Math.abs(t - rise - 0.25) < 2) return clamp(1 - Math.abs(t - rise - 0.25) / 1.5, 0, 1);
    return 0;
}
function skyColours(T) {
    const { t, rise, set } = T;
    if (t >= rise + 0.5 && t < set - 0.5) return ["#6fbcf0", "#c9ecff"];
    if (t >= set - 0.5 && t < set + 0.5) return ["#5a6bc2", "#ffb27a"];
    if (t >= set + 0.5 && t < set + 1.5) return ["#2a2a6b", "#c76b8a"];
    if (t >= rise - 1 && t < rise + 0.5) return ["#4a5aa8", "#ffc994"];
    return ["#0b0f2e", "#1e2456"];
}
