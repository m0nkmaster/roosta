// Office page. Drawing: the static background and every frame of the scene.
// Classic scripts sharing one global scope, loaded in the order office.html lists them.
"use strict";

// ================================================================ static background
let bgHour = -1;
function buildBackground() {
    const T = clock();
    bgHour = T.h;
    bx.clearRect(0, 0, W, H);
    const R = ROOMS,
        below = (r) => ({ ...r, y0: MID }); // bottom-row floors run under the dividing wall so doorways show floor
    // floors: warm planks on the ops floor, herringbone meeting room, checker kitchen, clinic tiles, walnut lounge, dark games tiles
    floor(R.office, planks(32, 0, "w"));
    floor(R.meeting, herring());
    floor(R.kitchen, tiles(A.img.tile, 32, 32, 64));
    floor(below(R.firstaid), tiles(A.img.tileB, 32, 0, 32));
    floor(below(R.lounge), planks(0, 0, "l"));
    floor(below(R.games), tiles(A.img.tileB, 32, 64, 96));
    floor(below(R.userOffice), herring());
    // subtle floor wear: darker towards the front of each row
    for (const [y0, y1] of [
        [WALL, MID],
        [FLOOR2, H],
    ]) {
        const fl = bx.createLinearGradient(0, y0, 0, y1);
        fl.addColorStop(0, "#0000");
        fl.addColorStop(0.6, "#0000");
        fl.addColorStop(1, "#00000030");
        bx.fillStyle = fl;
        bx.fillRect(0, y0, W, y1 - y0);
    }
    // rugs (9-slice): meeting table, lounge sofas, games room
    rug(624, 164, 7, 5, 192, 96);
    rug(372, 484, 8, 5, 0, 0);
    rug(948, 520, 4, 3, 96, 96);
    rug(792, 584, 4, 4, 288, 0);
    rug(1166, 528, 3, 3, 192, 96);
    // console pads: leads from the console to the two middle beanbags
    pxLine(bx, 852, 589, 838, 612, "#0b0a10");
    pxLine(bx, 858, 589, 872, 612, "#0b0a10");
    // back wall (top row) and the dividing wall's face (bottom row), each room its own paint
    wallStrip(0, 600, 7, 2, WALL);
    wallStrip(600, 880, 3, 2, WALL);
    wallStrip(880, W, 9, 1, WALL);
    midStrip(0, 150, 8, 1);
    midStrip(150, 760, 13, 2);
    midStrip(760, 1150, 5, 2);
    midStrip(1150, W, 7, 2);
    for (const sx of [600, 880]) {
        bx.fillStyle = "#1b1022";
        bx.fillRect(sx - 5, 0, 10, WALL);
        bx.fillStyle = "#ffffff18";
        bx.fillRect(sx - 5, 0, 1, WALL);
    }
    for (const sx of [150, 760, 1150]) {
        bx.fillStyle = "#1b1022";
        bx.fillRect(sx - 5, MID, 10, FLOOR2 - MID);
        bx.fillStyle = "#ffffff18";
        bx.fillRect(sx - 5, MID, 1, FLOOR2 - MID);
    }
    // skirting boards
    bx.fillStyle = "#2a1a14";
    bx.fillRect(0, WALL - 4, W, 4);
    bx.fillStyle = "#ffffff14";
    bx.fillRect(0, WALL - 4, W, 1);
    midSolid((a, b) => {
        bx.fillStyle = "#2a1a14";
        bx.fillRect(a, FLOOR2 - 4, b - a, 4);
        bx.fillStyle = "#ffffff14";
        bx.fillRect(a, FLOOR2 - 4, b - a, 1);
    });
    // windows: punch the panes out so the live sky (drawn first each frame) shows through
    for (const wx of WINDOWS) {
        bx.clearRect(wx + 2, 8, 28, 66);
        bx.drawImage(A.img.windowCut, wx, -4);
        bx.fillStyle = "#00000040";
        bx.fillRect(wx + 1, 76, 30, 2);
    }
    // wall decor, top row
    blit(bx, "paintL", 98, 30);
    blit(bx, "poster", 262, 20);
    blit(bx, "lampWall", 140, 0);
    blit(bx, "lampWall", 404, 0);
    bx.fillStyle = "#00000038";
    bx.fillRect(PIGEON.x + 2, PIGEON.y + PIGEON.h, PIGEON.w - 2, 2);
    blit(bx, "pigeonholes", PIGEON.x, PIGEON.y);
    bx.fillStyle = "#c9a24a";
    bx.fillRect(PIGEON.x + 16, PIGEON.y + 15 + 3, 5, 1); // brass name plate on {user}'s own slot (OWN_SLOT)
    splashback(886, 1030);
    splashback(1066, 1210);
    // whiteboard frame (live content drawn each frame)
    bx.fillStyle = "#3a3a4a";
    bx.fillRect(BOARD.x - 3, BOARD.y - 3, BOARD.w + 6, BOARD.h + 6);
    bx.fillStyle = "#8c8ca0";
    bx.fillRect(BOARD.x - 2, BOARD.y - 2, BOARD.w + 4, BOARD.h + 4);
    bx.fillStyle = "#5a5a6e";
    bx.fillRect(BOARD.x + 10, BOARD.y + BOARD.h + 3, BOARD.w - 20, 3);
    bx.fillStyle = "#e85d5d";
    bx.fillRect(BOARD.x + 20, BOARD.y + BOARD.h + 2, 5, 1);
    bx.fillStyle = "#5b8cff";
    bx.fillRect(BOARD.x + 28, BOARD.y + BOARD.h + 2, 5, 1);
    // door with frame and a badge reader
    bx.fillStyle = "#2a1712";
    bx.fillRect(DOOR.x - 4, DOOR.y - 4, 40, 62);
    bx.fillStyle = "#6b3f2a";
    bx.fillRect(DOOR.x - 3, DOOR.y - 3, 38, 61);
    bx.fillStyle = "#3b2216";
    bx.fillRect(DOOR.x - 1, DOOR.y - 1, 34, 59);
    blit(bx, "door", DOOR.x, DOOR.y);
    bx.fillStyle = "#1b1830";
    bx.fillRect(DOOR.x + 38, DOOR.y + 22, 6, 10);
    bx.fillStyle = "#3d3566";
    bx.fillRect(DOOR.x + 39, DOOR.y + 23, 4, 8);
    // welcome mat
    bx.fillStyle = "#3a2a22";
    bx.fillRect(DOOR.x - 2, WALL + 1, 36, 9);
    bx.fillStyle = "#6b4a32";
    bx.fillRect(DOOR.x - 1, WALL + 2, 34, 7);
    for (let i = 0; i < 34; i += 3) {
        bx.fillStyle = "#5a3d28";
        bx.fillRect(DOOR.x - 1 + i, WALL + 2, 1, 7);
    }
    // wall decor, bottom row: first-aid box, lounge TV and art, games room posters, dartboard and chalk scoreboard
    firstAidBox(56, 378);
    blit(bx, "lampWall", 20, MID + 2);
    drawTvSet();
    blit(bx, "paintA", 626, 374);
    blit(bx, "lampWall", 598, MID + 2);
    blit(bx, "lampWall", 668, MID + 2);
    blit(bx, "poster", 948, 372);
    blit(bx, "poster2", 976, 372);
    if (SEASON !== "pride") blit(bx, "paintL", 1228, 376); // the user's office art (Pride hangs a flag there instead)
    blit(bx, "posterGalaxy", 778, 383);
    blit(bx, "posterPeak", 808, 374);
    blit(bx, "posterNight", 848, 384);
    blit(bx, "posterCocktail", 880, 383);
    blit(bx, "posterSkull", 912, 388);
    dartboard(DARTS.x, DARTS.y);
    bx.fillStyle = "#3a2a22";
    bx.fillRect(SCORE.x, SCORE.y, 38, 30);
    bx.fillStyle = "#24302a";
    bx.fillRect(SCORE.x + 2, SCORE.y + 2, 34, 26);
    seasonalWalls();
    const shadow = (y) => {
        const sh = bx.createLinearGradient(0, y, 0, y + 16);
        sh.addColorStop(0, "#00000070");
        sh.addColorStop(1, "#0000");
        return sh;
    };
    bx.fillStyle = shadow(WALL);
    bx.fillRect(0, WALL, W, 16);
    midSolid((a, b) => {
        bx.fillStyle = shadow(FLOOR2);
        bx.fillRect(a, FLOOR2, b - a, 16);
    });
    // the dividing wall's cap, and door posts at each opening
    midSolid((a, b) => {
        bx.fillStyle = "#1e1624";
        bx.fillRect(a, MID - 9, b - a, 9);
        bx.fillStyle = "#4b3d52";
        bx.fillRect(a, MID - 8, b - a, 7);
        bx.fillStyle = "#65566d";
        bx.fillRect(a, MID - 8, b - a, 2);
        bx.fillStyle = "#3a2f40";
        bx.fillRect(a, MID - 2, b - a, 1);
    });
    for (const [a, b] of MID_GAPS) {
        bx.fillStyle = "#00000028";
        bx.fillRect(a, MID - 9, b - a, FLOOR2 - MID + 9);
        bx.fillStyle = "#3a2a22";
        bx.fillRect(a + 2, FLOOR2 - 3, b - a - 4, 3);
        bx.fillStyle = "#7a5a3e";
        bx.fillRect(a + 3, FLOOR2 - 2, b - a - 6, 1);
        for (const px of [a, b - 4]) {
            bx.fillStyle = "#1e1624";
            bx.fillRect(px, MID - 9, 4, FLOOR2 - MID + 9);
            bx.fillStyle = "#6b4a32";
            bx.fillRect(px + 1, MID - 8, 2, FLOOR2 - MID + 6);
        }
    }
    // wall clock body (hands are live)
    drawClockFace(bx);
    // doorways: thresholds and the shadow each partition casts eastward
    for (const P of PARTS) {
        let y = P.y0;
        for (const [a, b] of [...P.gaps, [P.y1, P.y1]]) {
            if (a > y) {
                bx.fillStyle = "#0000002a";
                bx.fillRect(P.x + 5, y, 5, a - y);
            }
            y = b;
        }
        for (const [a, b] of P.gaps) {
            bx.fillStyle = "#3a2a22";
            bx.fillRect(P.x - 5, a, 10, b - a);
            bx.fillStyle = "#7a5a3e";
            bx.fillRect(P.x - 4, a, 8, b - a);
            bx.fillStyle = "#5e432e";
            for (let yy = a + 3; yy < b; yy += 6) bx.fillRect(P.x - 4, yy, 8, 1);
        }
    }
    // contact shadows under furniture
    for (const p of PROPS)
        if (p.block && !p.noShadow) {
            const [x0, , x1, y1] = p.block;
            bx.fillStyle = "#00000026";
            bx.fillRect(x0 + 1, y1 - 2, x1 - x0, 4);
            bx.fillStyle = "#00000018";
            bx.fillRect(x0 + 3, y1 + 2, x1 - x0 - 2, 2);
        }
    // throw line for darts
    bx.fillStyle = "#e8e4d8";
    bx.fillRect(DARTS.x - 12, 512, 24, 1);
    // robot vacuum dock
    bx.fillStyle = "#1b1a22";
    bx.fillRect(DOCK.x - 9, DOCK.y - 1, 18, 6);
    bx.fillStyle = "#3a3846";
    bx.fillRect(DOCK.x - 8, DOCK.y - 1, 16, 2);
    // desk clutter baked in: papers
    for (const [i, d] of DESKS.entries()) if (i % 2 === 0) blit(bx, "paper", d.x + 29, d.y + 4);
}
function floor(r, fill) {
    bx.save();
    bx.beginPath();
    bx.rect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0);
    bx.clip();
    fill(r);
    bx.restore();
}
const planks = (sx, sy, seed) => (r) => {
    for (let x = r.x0; x < r.x1; x += 32) {
        const off = Math.floor(hash(seed + x) * 3) * 32;
        for (let y = r.y0 - off; y < r.y1; y += 96) bx.drawImage(A.img.wood, sx, sy, 32, 96, x, y, 32, 96);
    }
};
const herring = () => (r) => {
    for (let x = r.x0; x < r.x1; x += 32)
        for (let y = r.y0; y < r.y1; y += 96) bx.drawImage(A.img.herring, 64, 0, 32, 96, x, y, 32, 96);
};
const tiles = (im, sx, syA, syB) => (r) => {
    for (let y = r.y0; y < r.y1; y += 32)
        for (let x = r.x0; x < r.x1; x += 32)
            bx.drawImage(im, sx, ((x - r.x0 + (y - r.y0)) / 32) % 2 ? syA : syB, 32, 32, x, y, 32, 32);
};
// solid stretches of the dividing wall between doorways
function midSolid(fn) {
    let a = 0;
    for (const [g0, g1] of [...MID_GAPS, [W, W]]) {
        if (g0 > a) fn(a, g0);
        a = g1;
    }
}
function midStrip(x0, x1, col, row) {
    midSolid((a, b) => {
        const s = Math.max(a, x0),
            e = Math.min(b, x1);
        if (e > s) wallStrip(s, e, col, row, FLOOR2);
    });
}
function wallStrip(x0, x1, col, row, yb) {
    const sx = col * 96 + 32,
        sy = row * 128 + 6;
    for (let x = x0; x < x1; x += 32)
        bx.drawImage(A.img.walls, sx, sy, Math.min(32, x1 - x), 90, x, yb - 90, Math.min(32, x1 - x), 90);
}
function splashback(x0, x1) {
    // white kitchen tiles behind the worktop
    bx.fillStyle = "#cfd6d4";
    bx.fillRect(x0, 30, x1 - x0, 20);
    bx.fillStyle = "#e9eeec";
    for (let y = 31; y < 50; y += 5) for (let x = x0 + ((y / 5) % 2 ? 0 : 4); x < x1; x += 8) bx.fillRect(x, y, 7, 4);
    bx.fillStyle = "#00000030";
    bx.fillRect(x0, 49, x1 - x0, 1);
}
// wall decor for the season, baked into the background with the rest of the walls
function seasonalWalls() {
    if (XMAS) {
        for (let x = 0; x < W; x += 128) blit(bx, "xlights", x, 0); // fairy lights strung along the back wall
        midSolid((a, b) => {
            bx.save();
            bx.beginPath();
            bx.rect(a, MID, b - a, 20);
            bx.clip();
            for (let x = a; x < b; x += 128) blit(bx, "xlights", x, MID + 1);
            bx.restore();
        });
        blit(bx, "wreath", DOOR.x + 6, DOOR.y + 8);
        blit(bx, "garland", 890, 28);
        blit(bx, "garland", 1070, 28);
        blit(bx, "swag", 322, MID + 4);
        blit(bx, "swag", 800, MID + 4);
        blit(bx, "wreath", 116, 380);
    }
    if (SEASON === "halloween") {
        blit(bx, "webL", 0, 0);
        blit(bx, "webR", 571, 0);
        blit(bx, "webR", 856, 0);
        blit(bx, "webR", 1256, 0);
        blit(bx, "webL", 155, MID);
        blit(bx, "webR", 1256, MID);
        blit(bx, "webL", 765, MID);
        blit(bx, "skeleton", 206, 370); // hung up in the lounge for the party
    }
    if (SEASON === "pride") {
        blit(bx, "prideProgress", FP.x + 15, 356);
        blit(bx, "prideRainbow", 1222, 376);
    }
}
function firstAidBox(x, y) {
    bx.fillStyle = "#1b1830";
    bx.fillRect(x - 1, y - 1, 26, 22);
    bx.fillStyle = "#f4f6f8";
    bx.fillRect(x, y, 24, 20);
    bx.fillStyle = "#d4d8e0";
    bx.fillRect(x, y + 17, 24, 3);
    bx.fillStyle = "#2f9e5f";
    bx.fillRect(x + 10, y + 4, 4, 11);
    bx.fillRect(x + 6, y + 8, 12, 4);
}
function dartboard(x, y) {
    for (const [r, c] of [
        [12, "#1b1410"],
        [11, "#2a2018"],
        [9, "#d94848"],
        [8, "#1b1830"],
        [6, "#f4ecd8"],
        [4, "#2f8a5f"],
        [2, "#d94848"],
        [1, "#ffd166"],
    ])
        pxEllipse(bx, x, y, r, r, c);
    for (let i = 0; i < 8; i++) {
        const a = (i / 8) * Math.PI;
        bx.fillStyle = "#00000030";
        bx.fillRect(Math.round(x + Math.cos(a) * 7), Math.round(y + Math.sin(a) * 7), 1, 1);
        bx.fillRect(Math.round(x - Math.cos(a) * 7), Math.round(y - Math.sin(a) * 7), 1, 1);
    }
}
function rug(x, y, cw, ch, sx0, sy0) {
    for (let j = 0; j < ch; j++)
        for (let i = 0; i < cw; i++) {
            const sx = sx0 + (i === 0 ? 0 : i === cw - 1 ? 64 : 32),
                sy = sy0 + (j === 0 ? 0 : j === ch - 1 ? 64 : 32);
            bx.drawImage(A.img.rug, sx, sy, 32, 32, x + i * 32, y + j * 32, 32, 32);
        }
}
function drawWallSeg(x, y0, y1) {
    const L = x - 4,
        top = y0 - 20,
        face = y1 - 20;
    ctx.fillStyle = "#1e1624";
    ctx.fillRect(L - 1, top, 10, face - top + 20);
    ctx.fillStyle = "#4b3d52";
    ctx.fillRect(L, top, 8, face - top);
    ctx.fillStyle = "#65566d";
    ctx.fillRect(L + 1, top, 2, face - top);
    ctx.fillStyle = "#3a2f40";
    ctx.fillRect(L + 6, top, 1, face - top);
    ctx.fillStyle = "#8d7c84";
    ctx.fillRect(L, face, 8, 17);
    ctx.fillStyle = "#a8979e";
    ctx.fillRect(L, face, 8, 2);
    ctx.fillStyle = "#77666e";
    ctx.fillRect(L + 7, face + 2, 1, 15);
    ctx.fillStyle = "#3a2a22";
    ctx.fillRect(L, face + 17, 8, 3);
}
function drawDrip(x, y) {
    ctx.fillStyle = "#9aa4a8";
    ctx.fillRect(x, y + 2, 1, 36);
    ctx.fillRect(x - 4, y + 38, 9, 2);
    ctx.fillRect(x - 3, y + 2, 7, 1);
    ctx.fillStyle = "#cfe8f2";
    ctx.fillRect(x + 2, y + 3, 4, 7);
    ctx.fillStyle = "#ffffff99";
    ctx.fillRect(x + 2, y + 3, 1, 6);
    ctx.fillStyle = "#cfe8f2";
    ctx.fillRect(x + 4, y + 10, 1, 8);
}
function drawClockFace(c) {
    const { x, y } = WALL_CLOCK,
        R = 9;
    for (let dy = -R - 1; dy <= R + 1; dy++)
        for (let dx = -R - 1; dx <= R + 1; dx++) {
            const d2 = dx * dx + dy * dy;
            if (d2 <= (R + 1.2) ** 2) {
                c.fillStyle = d2 > (R - 0.6) ** 2 ? "#2a1a12" : d2 > (R - 1.8) ** 2 ? "#8a5a32" : "#f4ecd8";
                c.fillRect(x + dx, y + dy, 1, 1);
            }
        }
    c.fillStyle = "#00000030";
    c.fillRect(x - R + 2, y + R + 1, 2 * R - 3, 1);
    for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        c.fillStyle = i % 3 ? "#b8ab90" : "#3a2a22";
        c.fillRect(Math.round(x + Math.sin(a) * 6), Math.round(y - Math.cos(a) * 6), 1, 1);
    }
}

// ================================================================ rendering
const SIT_DROP = 6;
function drawWorker(w, now) {
    const celebrating = w.celebrateUntil > now,
        greeting = !!(w.greetPeer && w.greetUntil > now);
    const leg = seatLeg(w),
        spot = leg || w.spot || {};
    const moving = w.path.length > 0 && !celebrating && !greeting && !leg && !(w.holdUntil > now);
    // On the shuffle between approach point and seat, only take the seated pose once over the seat;
    // otherwise long approaches (side sofas) sit down in mid-air and glide in.
    const onSeat = !leg || Math.hypot(w.x - leg.x, w.y - leg.y) < 6;
    const pose = !celebrating && !greeting && (!w.path.length || leg) && onSeat ? spot.pose : null,
        sitting = pose === "sit",
        floorSit = pose === "floor";
    let anim = "Idle",
        frame,
        row = ROW[w.dir] ?? 2;
    if (celebrating) {
        row = ROW[w.dir] ?? ROW.down;
        frame = 1;
    } else if (greeting) {
        row = ROW[w.dir] ?? ROW.right;
        frame = Math.floor((now / 420 + w.phase) % COLS.Idle);
    } else if (moving) {
        anim = "Walk";
        frame = Math.floor(w.walkDist / 4) % COLS.Walk;
    } else if (sitting) {
        anim = "Sitting";
        frame = 2;
        row = ROW[w.glanceUntil > now && w.state === "working" ? w.glanceDir : spot.face];
    } else if (floorSit) {
        anim = "Sitting";
        frame = spot.face === "down" ? 1 : 0;
        row = ROW[spot.face];
    } else {
        frame = Math.floor((now / (w.state === "queued" ? 170 : 420) + w.phase) % COLS.Idle);
        if (w.lookUntil > now) row = ROW[w.lookDir];
    }
    let bob = 0,
        sway = 0;
    if (celebrating) bob = -Math.round(Math.abs(Math.sin((now - w.celebrateStart) / 115)) * 6);
    else if (sitting && w.state === "working")
        bob = w.thinkUntil > now ? 0 : Math.floor(now / (w.tension === 3 ? 85 : 140) + w.phase) % 2;
    else if (w.state === "hurt") bob = moving ? 1 : Math.floor(now / 500) % 2;
    else if (w.listening && Math.floor(now / 230 + w.phase) % 6 === 0) bob = 1;
    else if (!moving && w.poi && (w.poi.tag === "arcade" || w.poi.tag === "console") && w.state === "resting")
        bob = Math.floor(now / 110 + w.phase) % 3 === 0 ? 1 : 0;
    if (w.state === "locked" && w.line === 0 && !moving && now - w.knockAt < 780 && (now - w.knockAt) % 260 < 110)
        bob -= 1;
    if (w.thinkUntil > now && sitting) sway = Math.floor(now / 600) % 2 ? 1 : 0;
    if (sitting) bob += SIT_DROP; // the LPC chair frame is as tall as standing; sink the hips onto the seat
    const px = Math.round(w.x - 32) + sway,
        py = Math.round(w.y - 61 + bob);
    if (!sitting) pxEllipse(ctx, w.x, w.y, celebrating && bob < -3 ? 6 : 8, 2, "#00000040");
    if (selected === w.id || hovered === w.id) {
        ctx.strokeStyle = selected === w.id ? "#ffd166" : "#ffffffaa";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.ellipse(Math.round(w.x) + 0.5, Math.round(w.y) + 0.5, 11, 4, 0, 0, 7);
        ctx.stroke();
    }
    ctx.drawImage(sheet(w.look, anim), frame * FR, row * FR, FR, FR, px, py, FR, FR);
    // ping-pong paddle
    if (!moving && w.poi && w.poi.tag === "pong" && !w.path.length) {
        const right = w.poi.face === "right",
            swing = (right ? pong.swingL : pong.swingR) > now ? 2 : 0;
        const hx = Math.round(w.x + (right ? 7 + swing : -9 - swing)),
            hy = Math.round(w.y - 26);
        ctx.fillStyle = "#1b1830";
        ctx.fillRect(hx - 1, hy - 1, 4, 5);
        ctx.fillStyle = "#d94848";
        ctx.fillRect(hx, hy, 2, 3);
        ctx.fillStyle = "#8b5a3c";
        ctx.fillRect(hx + (right ? -1 : 2), hy + 3, 1, 2);
    }
    drawHeld(w, now, moving, sitting, floorSit, bob);
    // talking: hand gestures and little sound ticks by the mouth
    if (w.speaking && Math.floor(now / 700 + w.phase) % 3 === 0) {
        const s = w.dir === "left" ? -1 : 1,
            lift = Math.floor(now / 175) % 2;
        ctx.fillStyle = SKIN[w.look.tone];
        ctx.fillRect(Math.round(w.x + s * 6), Math.round(w.y - 31 - lift + bob), 2, 2);
    }
    if (w.speaking && Math.floor(now / 180) % 3) {
        const s = w.dir === "left" ? -1 : 1,
            mx = Math.round(w.x + s * 9),
            my = Math.round(w.y - 42);
        ctx.fillStyle = "#fffaf0";
        ctx.fillRect(mx, my - 2, 1, 1);
        ctx.fillRect(mx + s, my, 1, 1);
        ctx.fillRect(mx, my + 2, 1, 1);
    }
    if (sitting && w.state === "working" && w.tension >= 2) {
        // a bead of sweat runs down the temple
        const t = (now / 1700 + w.phase) % 1,
            s = w.dir === "left" ? -1 : 1;
        if (t < 0.6) {
            ctx.fillStyle = "#8fd3ff";
            ctx.fillRect(Math.round(w.x + s * 5), Math.round(w.y - 44 + bob + (REDUCED ? 0 : t * 8)), 1, 2);
        }
    }
    if (w.state === "hurt" && !moving) {
        // dizzy stars
        for (let i = 0; i < 3; i++) {
            const a = now / 300 + i * 2.1;
            ctx.fillStyle = "#ffd166";
            ctx.fillRect(Math.round(w.x + Math.cos(a) * 9), Math.round(w.y - 50 + Math.sin(a) * 3), 1, 1);
        }
    }
}
function headY(w) {
    return w.y - 47;
}
const SKIN = {
    Peach: "#f0c4a0",
    Porcelain: "#f6dcc8",
    Tan: "#d9a070",
    Honey: "#c8905a",
    Brown: "#8d5a3a",
    Coffee: "#5e3a26",
};
const BOOK_COLS = ["#7a1f1f", "#2f5a8a", "#2f7d5b", "#7a4bd1", "#b8862a"];
// pixel props: (x, y) is the item's top-left
function drawItem(name, x, y, w, now) {
    const R = (c, a, b, ww, hh) => {
        ctx.fillStyle = c;
        ctx.fillRect(x + a, y + b, ww, hh);
    };
    if (name === "mug") {
        R("#1b1830", -1, -1, 5, 5);
        R(w.mugCol || "#f4ecff", 0, 0, 3, 3);
        R("#4a2a1a", 0, 0, 3, 1);
        R("#1b1830", 3, 1, 1, 1);
    } else if (name === "water") {
        R("#1b1830", -1, -1, 5, 6);
        R("#d6f0ff", 0, 0, 3, 4);
        R("#6ab0e0", 0, 2, 3, 2);
    } else if (name === "snack" || name === "sandwich") {
        const left = clamp(1 - (now - w.arrivedAt) / (w.dwellLen || 30000), 0.25, 1),
            ww = Math.max(2, Math.round((name === "snack" ? 4 : 6) * (w.act === "eat" && !w.path.length ? left : 1)));
        if (name === "snack") {
            R("#1b1830", -1, -1, ww + 2, 5);
            R("#e85d5d", 0, 0, ww, 3);
            R("#ffd166", 0, 1, ww, 1);
        } else {
            R("#1b1830", -1, -1, ww + 2, 5);
            R("#e8c27a", 0, 0, ww, 3);
            R("#7ec850", 0, 1, ww, 1);
            R("#c8463c", 0, 2, ww, 1);
        }
    } else if (name === "book") {
        const cov = BOOK_COLS[Math.floor(hash(w.id + "bk") * BOOK_COLS.length)];
        R("#1b1830", -1, -1, 9, 6);
        R(cov, 0, 0, 7, 4);
        R("#f4ecd8", 1, 0, 2, 3);
        R("#f4ecd8", 4, 0, 2, 3);
        if (now - (w.bitAt || 0) < 350) R("#ffffff", 2 + Math.floor((now - w.bitAt) / 120), -1, 1, 3);
        else {
            R("#b8ab90", 1, 1, 2, 1);
            R("#b8ab90", 4, 1, 2, 1);
        }
    } else if (name === "phone") {
        R("#1b1830", -1, -1, 5, 6);
        R("#2a2836", 0, 0, 3, 4);
        R(Math.floor(now / 400 + w.phase) % 5 ? "#8fd3ff" : "#e6f7ff", 0, 0, 3, 3);
        R("#ffffff", Math.floor(now / 300 + w.phase) % 3, 1, 1, 1);
    } else if (name === "can") {
        R("#1b1830", -1, -1, 7, 5);
        R("#3d9c5c", 0, 0, 5, 3);
        R("#5fc48f", 0, 0, 5, 1);
    } else if (name === "marker") {
        R("#1b1830", 0, 0, 1, 3);
        R("#e85d5d", 0, -1, 1, 1);
    } else if (name === "papers") {
        R("#1b1830", -1, -1, 6, 7);
        R("#f4f6f8", 0, 0, 4, 5);
        R("#c9ccd6", 1, 1, 2, 1);
        R("#c9ccd6", 1, 3, 2, 1);
    }
}
function drawHeld(w, now, moving, sitting, floorSit, bob) {
    if (
        (w.state !== "resting" &&
            !(w.state === "working" && moving && w.carry === "papers") &&
            !(w.state === "hurt" && sitting && w.hasTea)) ||
        w.celebrateUntil > now
    )
        return;
    const name = w.state === "hurt" ? "mug" : moving ? w.carry || null : w.item;
    if (!name) return;
    const dir = moving ? w.dir : (w.spot && w.spot.face) || w.dir;
    const s = dir === "left" ? -1 : 1;
    // writing on the whiteboard: the marker shows above the shoulder
    if (name === "marker") {
        if (!moving) {
            const t = now / 260;
            drawItem(
                "marker",
                Math.round(w.x + 6 + Math.cos(t) * 2),
                Math.round(w.y - 42 + Math.sin(t * 1.3) * 2 + bob),
                w,
                now,
            );
        }
        return;
    }
    if (dir === "up" && !(moving && name === "papers")) return; // hidden behind the body, except a stack carried under the arm
    const raise =
        !moving &&
        (w.act === "sip" ||
            w.act === "eat" ||
            (DRINKS.has(name) && (w.act === "tv" || w.act === "talk" || w.act === "gaze"))) &&
        now - (w.bitAt || 0) < 750;
    let hx, hy;
    if (moving) {
        hx = dir === "down" ? w.x + 5 : dir === "up" ? w.x + 5 : w.x + s * 5 - (s < 0 ? 3 : 0);
        hy = w.y - 24;
    } else if (sitting) {
        hx = dir === "down" ? w.x - 2 : w.x + s * 6 - (s < 0 ? 3 : 0);
        hy = w.y - 20;
    } else if (floorSit) {
        hx = dir === "down" ? w.x - 3 : w.x + s * 5 - (s < 0 ? 3 : 0);
        hy = w.y - 16;
    } else {
        hx = dir === "down" ? w.x - 2 : w.x + s * 5 - (s < 0 ? 3 : 0);
        hy = w.y - 27;
    }
    if (name === "can") {
        hx = w.x + s * 9 - (s < 0 ? 5 : 0);
        hy = w.y - 25;
    }
    if (name === "book" && dir === "down") hx = w.x - 4;
    if (raise) {
        hy -= 7;
        hx += dir === "down" ? 1 : -s * 2;
    }
    drawItem(name, Math.round(hx), Math.round(hy + bob), w, now);
}
function drawCafeTable(t) {
    pxEllipse(ctx, t.x, t.y + 3, 6, 1, "#00000040");
    ctx.fillStyle = "#3a2a22";
    ctx.fillRect(t.x - 1, t.y - 6, 3, 9);
    ctx.fillRect(t.x - 4, t.y + 2, 9, 1);
    pxEllipse(ctx, t.x, t.y - 8, 10, 4, "#2a1a14");
    pxEllipse(ctx, t.x, t.y - 9, 9, 3, "#a8724a");
    pxEllipse(ctx, t.x - 2, t.y - 10, 5, 1, "#c48a5c");
    for (const sd of [-1, 1]) {
        // plates at lunch or with food; a cuppa or water outside lunch
        const p = POIS.find((q) => q.cafe === t && Math.sign(q.x - t.x) === sd),
            w = p && p.taken && workers.get(p.taken);
        if (!w || w.path.length || (w.act !== "eat" && w.act !== "sip")) continue;
        const px0 = t.x + sd * 4 - 2,
            drk = w.carry && DRINKS.has(w.carry) ? w.carry : "mug";
        if (w.act === "eat") {
            const left = clamp(1 - (tnow() - w.arrivedAt) / (w.dwellLen || 30000), 0, 1);
            pxEllipse(ctx, px0 + 2, t.y - 9, 3, 1, "#f4f6f8");
            if (left > 0.1) {
                ctx.fillStyle = hash(w.id + "food") > 0.5 ? "#e8c27a" : "#c8463c";
                ctx.fillRect(px0 + 1, t.y - 10, Math.max(1, Math.round(3 * left)), 2);
            }
            if (w.carry && DRINKS.has(w.carry)) drawItem(w.carry, t.x + sd * 7 - 1, t.y - 13, w, tnow());
        } else drawItem(drk, px0, t.y - 12, w, tnow());
    }
}
function drawStool(x, y) {
    pxEllipse(ctx, x, y, 4, 1, "#00000035");
    ctx.fillStyle = "#2a1a14";
    ctx.fillRect(x - 1, y - 5, 2, 5);
    pxEllipse(ctx, x, y - 6, 5, 2, "#1b1830");
    pxEllipse(ctx, x, y - 7, 4, 1, "#c0504d");
}
function drawMeetingClutter() {
    for (const p of POIS) {
        if (p.tag !== "meeting" || !p.taken) continue;
        const w = workers.get(p.taken);
        if (!w || w.path.length) continue;
        const north = p.face === "down",
            py0 = north ? TABLE.y + 13 : TABLE.y + 24;
        ctx.fillStyle = "#1b1830";
        ctx.fillRect(p.x - 5, py0 - 1, 8, 7);
        ctx.fillStyle = "#f4f6f8";
        ctx.fillRect(p.x - 4, py0, 6, 5);
        ctx.fillStyle = "#c9ccd6";
        ctx.fillRect(p.x - 3, py0 + 1, 4, 1);
        ctx.fillRect(p.x - 3, py0 + 3, 3, 1);
        if (hash(w.id + "mt") > 0.45) {
            ctx.fillStyle = "#1b1830";
            ctx.fillRect(p.x + 4, py0, 5, 5);
            ctx.fillStyle = w.mugCol;
            ctx.fillRect(p.x + 5, py0 + 1, 3, 3);
        }
    }
}
// Run start times are only knowable client-side: remember when we first saw each run begin.
const runStart = new Map();
// overrun tiers: 0 on time, 1 running long (>110%), 2 well over (>150%), 3 way over (>250%)
function tension(p) {
    return p == null || p < 1.1 ? 0 : p < 1.5 ? 1 : p < 2.5 ? 2 : 3;
}
const TENSE_EMOTES = [
    ["bulb", "q", "bulb", "note"],
    ["q", "hourglass", "bulb"],
    ["hourglass", "bang", "q"],
    ["hourglass", "bang", "cloud"],
];
function progressOf(t) {
    const s = runStart.get(t.id);
    if (!s || !t.last_duration) return null;
    return (Date.now() - s) / (t.last_duration * 1000);
}
function drawProgress(w, x, y, now) {
    const p = progressOf(w.task),
        bw = 16,
        x0 = Math.round(x - bw / 2),
        y0 = Math.round(y);
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(x0 - 1, y0 - 1, bw + 2, 5);
    ctx.fillStyle = "#3d3566";
    ctx.fillRect(x0, y0, bw, 3);
    if (p == null) {
        const k = (Math.floor(now / 55) % (bw + 6)) - 5,
            s = clamp(k, 0, bw),
            e = clamp(k + 5, 0, bw);
        ctx.fillStyle = "#ffd166";
        if (e > s) ctx.fillRect(x0 + s, y0, e - s, 3);
    } else if (p < 1) {
        const f = Math.max(1, Math.round(bw * p));
        ctx.fillStyle = "#ffd166";
        ctx.fillRect(x0, y0, f, 3);
        ctx.fillStyle = "#fff4c8";
        ctx.fillRect(x0, y0, f, 1);
    } else {
        ctx.fillStyle = Math.floor(now / 300) % 2 ? "#ff9f43" : "#ffd166";
        ctx.fillRect(x0, y0, bw, 3);
    }
}
function drawStatusBubble(w, now) {
    const moving = w.path.length > 0,
        emoting = w.emote && now < w.emoteUntil;
    if (w.celebrateUntil > now && !emoting) return;
    if (w.state === "locked" && w.spot && w.spot.pose && w.spot.face === "up" && selected !== w.id && !emoting) return; // a back-row lock would sit on the face opposite
    const lift = selected === w.id ? Math.round(Math.abs(Math.sin(now / 220)) * 2) : 0;
    const y = headY(w) - 2 - lift;
    if (w.state === "working" && !moving) {
        const by = w.desk ? w.y - 46 - lift : y - 4;
        drawProgress(w, w.x, by, now);
        if (emoting) emoteBubble(ctx, w.emote, w.x, by - 3);
        return;
    }
    if (w.state === "queued" && w.desk && !moving) {
        emoteBubble(ctx, emoting ? w.emote : "pad", w.x, w.y - 46 - lift);
        return;
    } // gaming, not working: no progress bar
    if (emoting) {
        emoteBubble(ctx, w.emote, w.x, y);
        return;
    }
    if (w.state === "locked") bubble(ctx, w.x, y, (x0, y0) => drawIcon(ctx, "lock", x0, y0), "#ffd6d6");
    else if (w.state === "hurt")
        moving
            ? bubble(ctx, w.x, y, (x0, y0) => drawIcon(ctx, "cloud", x0, y0 + 1), "#dfe3f0")
            : bubble(
                  ctx,
                  w.x,
                  y - (Math.floor(now / 300) % 2),
                  (x0, y0) => drawIcon(ctx, "bang", x0 + 1, y0),
                  "#ffd6d6",
              );
    else if (w.state === "queued") bubble(ctx, w.x, y, (x0, y0) => drawIcon(ctx, "hourglass", x0, y0), "#e6dcff");
}
function deskBusy(d) {
    const w = d && d.owner && workers.get(d.owner);
    return !!(w && w.state === "working" && !w.path.length);
}
function deskGaming(d) {
    const w = d && d.owner && workers.get(d.owner);
    return !!(w && w.state === "queued" && !w.path.length);
}
// a falling-blocks game on the laptop of a writer waiting for the writer lock
function drawLaptopGame(d, now) {
    const x0 = d.x + 11,
        y0 = d.y - 6,
        tick = Math.floor(now / 240),
        round = Math.floor(tick / 30),
        seed = d.x + ":" + d.y;
    const cols = ["#ff6b9a", "#7ee0b5", "#ffd166", "#6aa6ff", "#b79bff"];
    ctx.fillStyle = "#141026";
    ctx.fillRect(x0 - 1, y0, 14, 8);
    for (let c = 0; c < 6; c++) {
        const h = 1 + Math.floor(hash(seed + round + c) * 2);
        for (let r = 0; r < h; r++) {
            ctx.fillStyle = cols[(c + r + round) % 5];
            ctx.fillRect(x0 + c * 2, y0 + 6 - r * 2, 2, 2);
        }
    }
    const piece = Math.floor(tick / 3),
        pc = Math.floor(hash(seed + "p" + piece) * 5);
    ctx.fillStyle = cols[piece % 5];
    ctx.fillRect(x0 + pc * 2, y0 + (tick % 3), 4, 2);
}
// The user's desk: papers, a mug, a nameplate and a desk lamp (their chair stays empty: the user isn't one of the workers)
function drawUserDesk() {
    const { x, y } = USER_DESK;
    blit(ctx, "paper", x + 6, y + 4);
    blit(ctx, "lampTable", x + 34, y - 20);
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(x + 23, y + 3, 6, 6);
    ctx.fillStyle = "#5b8cff";
    ctx.fillRect(x + 24, y + 4, 4, 4);
    ctx.fillStyle = "#ffffff55";
    ctx.fillRect(x + 24, y + 4, 1, 4);
    ctx.fillStyle = "#3a2a22";
    ctx.fillRect(x + 20, y + 11, 16, 4);
    ctx.fillStyle = "#c8962a";
    ctx.fillRect(x + 21, y + 12, 14, 2); // nameplate
    if (hovered === "userDesk") {
        ctx.strokeStyle = "#ffd166cc";
        ctx.lineWidth = 1;
        ctx.strokeRect(x - 0.5, y - 0.5, 59, 36);
    }
}
function drawDeskTop(d, now) {
    const on = deskBusy(d),
        game = !on && deskGaming(d);
    blit(ctx, on || game ? "laptopOn" : "laptopOff", d.x + 8, d.y - 8);
    if (game) drawLaptopGame(d, now);
    const t = d.touch;
    if (t) {
        if (t.stem) blit(ctx, t.stem, t.x, t.y - 9);
        blit(ctx, t.k, t.x, t.y);
    }
    if (on) {
        // scrolling code on the screen (or key-mash while the cat sits on the keyboard)
        const paws = cat.onDesk && cat.onDesk === d.owner;
        for (let i = 0; i < 4; i++) {
            const ln = Math.floor(now / (paws ? 110 : 380)) + i,
                len = paws ? 11 : 3 + Math.floor(hash(d.x + ":" + ln) * 9);
            ctx.fillStyle = paws
                ? ln % 2
                    ? "#ff6b6b"
                    : "#ffd166"
                : ["#7ee0b5", "#e6f7ff", "#ffd166", "#b79bff"][ln % 4];
            ctx.fillRect(d.x + 11 + (paws || ln % 3 === 0 ? 0 : 2), d.y - 5 + i * 2, len, 1);
        }
    }
    // mug
    const mx = d.x + 46,
        my = d.y + 1;
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(mx - 1, my - 1, 6, 6);
    ctx.fillStyle = d.mug;
    ctx.fillRect(mx, my, 4, 4);
    ctx.fillStyle = "#ffffff55";
    ctx.fillRect(mx, my, 1, 4);
    ctx.fillStyle = "#1b1830";
    ctx.fillRect(mx + 5, my + 1, 1, 2);
    ctx.fillStyle = "#4a2a1a";
    ctx.fillRect(mx, my, 4, 1);
}
// The meeting room's video-call screen: idle shows a dim call tile; with a sign-in down the call freezes on
// grey tiles over a blinking red "reconnecting" bar (green once auth is back and the blocked tasks can retry).
let callFlashUntil = 0;
function drawCallScreen(now) {
    const { x, y } = CALL,
        down = counts.locked > 0,
        gate = down && tasks.some((t) => t.status === "auth-failed"),
        flash = now < callFlashUntil;
    pxEllipse(ctx, x + 15, y + 49, 10, 2, "#00000035");
    ctx.fillStyle = "#2a2838";
    ctx.fillRect(x + 14, y + 22, 3, 26);
    ctx.fillRect(x + 6, y + 47, 19, 2);
    ctx.fillStyle = "#14121b";
    ctx.fillRect(x, y, 30, 22);
    ctx.fillStyle = "#3d3a52";
    ctx.fillRect(x, y, 30, 1);
    const sx = x + 2,
        sy = y + 2;
    if (down) {
        ctx.fillStyle = "#464775";
        ctx.fillRect(sx, sy, 26, 18);
        for (let i = 0; i < 4; i++) {
            // frozen participant tiles
            const tx = sx + 1 + (i % 2) * 13,
                ty = sy + 1 + Math.floor(i / 2) * 6;
            ctx.fillStyle = "#5c5d8f";
            ctx.fillRect(tx, ty, 11, 5);
            ctx.fillStyle = "#8a8bb8";
            ctx.fillRect(tx + 4, ty + 1, 3, 2);
            ctx.fillRect(tx + 3, ty + 3, 5, 2);
        }
        ctx.fillStyle = gate ? (Math.floor(now / 400) % 2 ? "#ff4d4d" : "#8a2a3a") : "#3d9970";
        ctx.fillRect(sx, sy + 13, 26, 5);
        ctx.fillStyle = "#fffaf0";
        for (let k = 0; k < 3; k++)
            if (!gate || Math.floor(now / 300) % 4 > k) ctx.fillRect(sx + 10 + k * 3, sy + 15, 2, 1);
    } else {
        ctx.fillStyle = flash ? "#2d4a40" : "#1e1c2c";
        ctx.fillRect(sx, sy, 26, 18);
        ctx.fillStyle = flash ? "#7ee0b5" : "#4b4a8c";
        ctx.fillRect(sx + 10, sy + 6, 6, 6);
        ctx.fillStyle = flash ? "#2d4a40" : "#1e1c2c";
        ctx.fillRect(sx + 11, sy + 7, 4, 1);
        ctx.fillRect(sx + 12, sy + 8, 2, 3); // the call app's logo
    }
    if (hovered === "call") {
        ctx.strokeStyle = down ? "#ff6b6bcc" : "#7ee0b5cc";
        ctx.lineWidth = 1;
        ctx.strokeRect(x - 1.5, y - 1.5, 33, 53);
    }
}
function drawRack(x, y, idx, now) {
    ctx.fillStyle = "#4a4860";
    ctx.fillRect(x, y, 22, 5);
    ctx.fillStyle = "#5c5a74";
    ctx.fillRect(x, y, 22, 1);
    ctx.fillStyle = "#14121b";
    ctx.fillRect(x, y + 5, 22, 41);
    ctx.fillStyle = "#24222f";
    ctx.fillRect(x + 2, y + 7, 18, 36);
    const busy = counts.working,
        rate = 90 + 520 / (1 + busy);
    for (let s = 0; s < 6; s++) {
        const sy = y + 8 + s * 6;
        ctx.fillStyle = "#2f2c3d";
        ctx.fillRect(x + 3, sy, 16, 4);
        ctx.fillStyle = "#0d0b14";
        ctx.fillRect(x + 3, sy + 4, 16, 1);
        ctx.fillStyle = "#46435a";
        ctx.fillRect(x + 4, sy + 1, 6, 2);
        for (let k = 0; k < 3; k++) {
            const on =
                hash(idx + ":" + s + ":" + k + ":" + Math.floor(now / (rate * (1 + k * 0.6) + s * 13))) >
                (busy ? 0.3 : 0.75);
            const col = k === 2 && (counts.hurt || counts.locked) ? "#ff4d4d" : k === 1 ? "#ffd166" : "#7ee0b5";
            ctx.fillStyle = on ? col : "#1e2a24";
            ctx.fillRect(x + 12 + k * 2, sy + 1, 1, 1);
        }
    }
    ctx.fillStyle = "#0b0a10";
    ctx.fillRect(x + 1, y + 44, 3, 2);
    ctx.fillRect(x + 18, y + 44, 3, 2);
}
const arcadePlayer = (a) => {
    const p = POIS.find((q) => q.arcade === a);
    const w = p && p.taken && workers.get(p.taken);
    return !!(w && !w.path.length);
};
function drawArcade(a, now) {
    const { x, y, col } = a,
        played = arcadePlayer(a);
    if (played) a.credit = false; // the credit is spent the moment someone plays
    if (a.coinT === 0) a.coinT = now;
    const flash = a.coinT && now - a.coinT < 900 && Math.floor((now - a.coinT) / 150) % 2 === 0;
    ctx.fillStyle = "#0d0b16";
    ctx.fillRect(x - 1, y - 1, 26, 47);
    ctx.fillStyle = "#2a1f4a";
    ctx.fillRect(x, y, 24, 46);
    ctx.fillStyle = "#3b2d66";
    ctx.fillRect(x + 1, y, 2, 46);
    ctx.fillRect(x + 21, y, 2, 46);
    ctx.fillStyle = col;
    ctx.fillRect(x + 3, y + 1, 18, 5);
    ctx.fillStyle = "#ffffff88";
    ctx.fillRect(x + 4, y + 2, 16, 1);
    ctx.fillStyle = "#0d0b16";
    for (let i = 0; i < 4; i++) ctx.fillRect(x + 6 + i * 4, y + 3, 2, 2);
    // screen
    const sx = x + 4,
        sy = y + 8,
        sw = 16,
        sh = 13;
    ctx.fillStyle = "#05060f";
    ctx.fillRect(sx - 1, sy - 1, sw + 2, sh + 2);
    ctx.fillStyle = "#0b1030";
    ctx.fillRect(sx, sy, sw, sh);
    if (played) {
        if (a.game === 0) {
            // invaders
            const off = Math.round(Math.sin(now / 500) * 2);
            for (let r = 0; r < 2; r++)
                for (let c = 0; c < 4; c++)
                    if (hash(a.x + ":" + r + c + Math.floor(now / 6000)) > 0.2) {
                        ctx.fillStyle = r ? "#7ee0b5" : "#ff6b9a";
                        ctx.fillRect(sx + 2 + c * 4 + off, sy + 2 + r * 3 + (Math.floor(now / 3000) % 2), 2, 2);
                    }
            const shipX = sx + 7 + Math.round(Math.sin(now / 340) * 5);
            ctx.fillStyle = "#ffd166";
            ctx.fillRect(shipX, sy + sh - 2, 3, 1);
            ctx.fillRect(shipX + 1, sy + sh - 3, 1, 1);
            const bt = (now / 90) % 10;
            ctx.fillStyle = "#fffaf0";
            ctx.fillRect(shipX + 1, Math.round(sy + sh - 4 - bt), 1, 1);
        } else {
            // racer
            for (let i = 0; i < sh; i++) {
                const k = Math.round(Math.sin(i * 0.5 + now / 260) * 2);
                ctx.fillStyle = (i + Math.floor(now / 80)) % 4 < 2 ? "#3d3566" : "#262142";
                ctx.fillRect(sx + 3 + k, sy + i, 10, 1);
            }
            ctx.fillStyle = "#ff4d4d";
            ctx.fillRect(sx + 7 + Math.round(Math.sin(now / 400) * 2), sy + sh - 4, 2, 3);
        }
    } else {
        ctx.fillStyle = Math.floor(now / (a.credit ? 250 : 600)) % 2 ? (a.credit ? "#ffd166" : col) : "#3d3566";
        ctx.fillRect(sx + 3, sy + 5, 10, 2);
        ctx.fillStyle = "#3d3566";
        ctx.fillRect(sx + 1 + (Math.floor(now / 150) % 14), sy + 10, 2, 1);
    }
    ctx.fillStyle = "#ffffff14";
    ctx.fillRect(sx, sy, sw, 1);
    if (flash) {
        ctx.fillStyle = "#ffd16655";
        ctx.fillRect(sx, sy, sw, sh);
    }
    // control panel and cabinet base
    ctx.fillStyle = "#4b3d80";
    ctx.fillRect(x + 1, y + 23, 22, 6);
    ctx.fillStyle = "#5c4d96";
    ctx.fillRect(x + 1, y + 23, 22, 1);
    ctx.fillStyle = "#d94848";
    ctx.fillRect(x + 5, y + 24 + (played && Math.floor(now / 160) % 2 ? 1 : 0), 2, 2);
    ctx.fillStyle = "#ffd166";
    ctx.fillRect(x + 13, y + 25, 2, 2);
    ctx.fillStyle = "#7ee0b5";
    ctx.fillRect(x + 17, y + 25, 2, 2);
    ctx.fillStyle = "#1e1636";
    ctx.fillRect(x + 3, y + 30, 18, 15);
    ctx.fillStyle = "#0d0b16";
    ctx.fillRect(x + 10, y + 34, 4, 3);
    ctx.fillStyle = a.credit || flash ? "#ffd166" : "#ff4d4d";
    ctx.fillRect(x + 11, y + 35, 2, 1);
}
function drawBeanbag(b) {
    pxEllipse(ctx, b.x, b.y, 10, 3, "#00000035");
    pxEllipse(ctx, b.x, b.y - 5, 10, 6, "#1b1830");
    pxEllipse(ctx, b.x, b.y - 5, 9, 5, b.col);
    pxEllipse(ctx, b.x - 2, b.y - 7, 5, 2, b.hi);
    ctx.fillStyle = "#00000030";
    ctx.fillRect(b.x - 6, b.y - 4, 12, 1);
}
