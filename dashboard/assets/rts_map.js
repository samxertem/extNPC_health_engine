/* =====================================================================
   extNPC — RTS world-map renderer (HTML5 canvas).
   Art: Kenney "Tiny Town" (CC0). One villager sprite, team-tinted per
   bloodline. Terrain, town clusters and animated units are drawn here; the
   Python side only streams world state into the `mapdata` store.
   ===================================================================== */
(function () {
  "use strict";

  var SHEET_URL = "/assets/sprites/tiny_town.png";
  var VILL_URL = "/assets/sprites/villager.png";
  var TS = 16, COLS = 12;                 // Tiny Town tiles are 16x16, 12 wide
  var VT = 24;                            // villager frames are 24x24
  var DIR_ROW = { down: 0, up: 1, left: 2, right: 3 };
  var MAPU = 100;                         // world coords run 0..100

  // tile indices picked off the sheet
  var T_GRASS = [0, 0, 0, 1], T_TREE = [4, 28, 30], T_FLOWER = 2, T_BUSH = 5;
  var T_HOUSE = [84, 85, 87, 90], T_ROAD = 43;

  function srcOf(idx) { return [(idx % COLS) * TS, Math.floor(idx / COLS) * TS]; }

  // hash → deterministic pseudo-random in [0,1)
  function hash(n) {
    n = (n ^ 61) ^ (n >>> 16); n = n + (n << 3); n = n ^ (n >>> 4);
    n = Math.imul(n, 0x27d4eb2d); n = n ^ (n >>> 15);
    return ((n >>> 0) % 100000) / 100000;
  }

  var R = (window.__rts = window.__rts || {
    data: null, pos: {}, terrain: null, terrainSeed: null,
    tints: {}, sheet: null, vill: null, started: false, t0: performance.now()
  });

  // ---- team-tinted villager sheet (whole 96x96 sheet tinted once/colour) --
  function tintSheet(hex) {
    if (R.tints[hex]) return R.tints[hex];
    var c = document.createElement("canvas");
    c.width = R.vill.width; c.height = R.vill.height;
    var x = c.getContext("2d"); x.imageSmoothingEnabled = false;
    x.drawImage(R.vill, 0, 0);
    // multiply the neutral tunic toward the team colour, keep the sprite alpha
    x.globalCompositeOperation = "source-atop";
    x.globalAlpha = 0.5; x.fillStyle = hex; x.fillRect(0, 0, c.width, c.height);
    x.globalAlpha = 1.0; x.globalCompositeOperation = "source-over";
    R.tints[hex] = c; return c;
  }

  // ---- terrain (drawn once per seed to an offscreen canvas) --------------
  function buildTerrain(seed, W, H) {
    var px = 32;                                   // on-screen tile size
    var c = document.createElement("canvas"); c.width = W; c.height = H;
    var x = c.getContext("2d"); x.imageSmoothingEnabled = false;

    // a winding river (params stored so bridges can find the crossings)
    var river = R.river = {
      baseY: H * 0.60, amp: H * 0.11,
      freq: 2 * Math.PI / (W * 0.55), phase: (seed % 100) * 0.3, half: 22
    };
    function riverY(px_) { return river.baseY + river.amp * Math.sin(px_ * river.freq + river.phase); }

    var cols = Math.ceil(W / px), rows = Math.ceil(H / px);
    for (var r = 0; r < rows; r++) {
      for (var q = 0; q < cols; q++) {
        var h = hash((q * 73856093) ^ (r * 19349663) ^ (seed * 83492791));
        var g = T_GRASS[Math.floor(h * T_GRASS.length)];
        var s = srcOf(g);
        x.drawImage(R.sheet, s[0], s[1], TS, TS, q * px, r * px, px, px);
        var h2 = hash((q * 12345) ^ (r * 6789) ^ (seed * 271));
        var deco = null;
        if (h2 > 0.90) deco = T_TREE[Math.floor(hash(q * r + seed) * T_TREE.length)];
        else if (h2 > 0.86) deco = T_BUSH;
        else if (h2 > 0.83) deco = T_FLOWER;
        if (deco !== null) {
          var sd = srcOf(deco);
          x.drawImage(R.sheet, sd[0], sd[1], TS, TS, q * px, r * px, px, px);
        }
      }
    }
    // paint the river on top of the grass (pixel-styled flat water + ripples)
    for (var xx = 0; xx < W; xx++) {
      var cy = riverY(xx);
      x.fillStyle = "#3f7fa8";
      x.fillRect(xx, cy - river.half, 1, river.half * 2);
      x.fillStyle = "#5aa0c8";
      x.fillRect(xx, cy - river.half, 1, 3);
      x.fillRect(xx, cy + river.half - 3, 1, 3);
      if ((xx + Math.floor(cy)) % 11 === 0) {
        x.fillStyle = "#7ec0e0";
        x.fillRect(xx, cy - 4 + ((xx % 7)) - 3, 3, 2);
      }
    }
    return c;
  }

  // ---- coordinate mapping (world 0..100 → canvas px, centred square) ------
  function mapper(W, H) {
    var pad = 26, S = Math.min(W, H) - 2 * pad;
    var ox = (W - S) / 2, oy = (H - S) / 2;
    return function (wx, wy) { return [ox + wx / MAPU * S, oy + wy / MAPU * S]; };
  }

  function drawTile(x, idx, cx, cy, size) {
    var s = srcOf(idx);
    x.drawImage(R.sheet, s[0], s[1], TS, TS, cx - size / 2, cy - size / 2, size, size);
  }

  // ---- the render frame --------------------------------------------------
  function frame() {
    requestAnimationFrame(frame);
    var cv = document.getElementById("rts-canvas");
    if (!cv || !R.sheet || !R.vill || !R.data) return;
    // keep the backing store matched to the displayed size (handles the tab
    // being hidden at first paint, then shown, and window resizes).
    // BOTH dimensions are measured, and from the canvas's own box rather than
    // the parent's: the CSS height is a calc() against the viewport, so a
    // hardcoded backing-store height makes the browser scale the drawing to
    // fit and squashes the whole world vertically. Height must also be able
    // to trigger the resize on its own — a window resized only vertically
    // never changes the width.
    var box = cv.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) return;   // tab hidden: nothing to size against
    var wantW = Math.max(600, Math.floor(box.width));
    var wantH = Math.max(460, Math.floor(box.height));   // matches the CSS minHeight
    if (Math.abs(cv.width - wantW) > 2 || Math.abs(cv.height - wantH) > 2) {
      cv.width = wantW; cv.height = wantH; R.terrain = null;
    }
    var W = cv.width, H = cv.height, ctx = cv.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    var data = R.data, m = mapper(W, H);
    var t = (performance.now() - R.t0) / 1000;

    // terrain (rebuild if the seed changed, e.g. on Reset)
    if (!R.terrain || R.terrainSeed !== data.seed ||
        R.terrain.width !== W || R.terrain.height !== H) {
      R.terrain = buildTerrain(data.seed || 1, W, H); R.terrainSeed = data.seed;
    }
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(R.terrain, 0, 0);

    // roads (a minimum spanning tree over the towns) then bridges over the river
    drawRoads(ctx, data, m);
    drawBridges(ctx, data, m);

    // territories (soft team-coloured rings)
    //
    // When an overlay layer is active each deme carries `wash` + `washAlpha`,
    // computed server-side from the snapshot frame. A radial gradient reads as
    // a heat field rather than a flat disc, and the ring keeps its bloodline
    // colour so the settlement stays identifiable under any layer.
    var S = Math.min(W, H) - 52;
    var layer = data.layer || "default";
    (data.demes || []).forEach(function (d) {
      var p = m(d.x, d.y), rr = d.r / MAPU * S;
      ctx.beginPath(); ctx.arc(p[0], p[1], rr, 0, 6.283);
      if (d.wash) {
        var g = ctx.createRadialGradient(p[0], p[1], rr * 0.10, p[0], p[1], rr);
        g.addColorStop(0, hexA(d.wash, Math.min(0.92, d.washAlpha * 1.7)));
        g.addColorStop(1, hexA(d.wash, d.washAlpha * 0.30));
        ctx.fillStyle = g;
      } else {
        ctx.fillStyle = hexA(d.color, 0.12);
      }
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = hexA(d.wash || d.color, d.wash ? 0.75 : 0.55);
      ctx.stroke();
    });

    // migration routes (dashed, thickness = flow)
    var wmax = 1; (data.flows || []).forEach(function (f) { if (f.w > wmax) wmax = f.w; });
    ctx.save(); ctx.setLineDash([6, 6]);
    (data.flows || []).forEach(function (f) {
      var a = m(f.x0, f.y0), b = m(f.x1, f.y1);
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
      ctx.strokeStyle = "rgba(120,180,255,0.5)";
      ctx.lineWidth = 1 + 4 * f.w / wmax; ctx.stroke();
    });
    ctx.restore();

    // settlements: a cluster of houses sized by population + a name plate
    (data.demes || []).forEach(function (d) {
      var p = m(d.x, d.y);
      var nH = Math.max(1, Math.min(6, 1 + Math.floor(d.n / 5)));
      for (var i = 0; i < nH; i++) {
        var ang = i / nH * 6.283 + d.id, rad = (nH > 1 ? 28 : 0);
        var hx = p[0] + Math.cos(ang) * rad, hy = p[1] + Math.sin(ang) * rad;
        drawTile(ctx, T_HOUSE[(i + d.id) % T_HOUSE.length], hx, hy, 34);
      }
    });

    // people: big villager sprites with 4-direction walk cycles, lerping toward
    // their target town (so migration reads as villagers walking the roads)
    var screen = {};
    var SIZE = 40;
    // draw far-to-near (higher y last) so overlaps look right
    var ppl = (data.people || []).slice().sort(function (a, b) { return a.y - b.y; });
    ppl.forEach(function (pn) {
      var cur = R.pos[pn.name];
      if (!cur) cur = R.pos[pn.name] = { x: pn.x, y: pn.y, dir: "down" };
      var dx = pn.x - cur.x, dy = pn.y - cur.y;
      var moving = Math.abs(dx) + Math.abs(dy) > 0.5;
      if (moving) {
        cur.dir = (Math.abs(dx) > Math.abs(dy))
          ? (dx < 0 ? "left" : "right") : (dy < 0 ? "up" : "down");
      }
      cur.x += dx * 0.05; cur.y += dy * 0.05;
      var p = m(cur.x, cur.y);
      var phf = strHash(pn.name);
      var walk, bob;
      if (moving) {
        walk = Math.floor(t * 7 + phf) % 4; bob = 0;
      } else {
        // idle: gentle breathing bob + a rare fidget step, so nobody is frozen
        bob = Math.sin(t * 2.2 + phf) * 1.4;
        var fid = Math.sin(t * 0.7 + phf * 1.3);
        walk = fid > 0.985 ? 1 : (fid < -0.985 ? 3 : 0);
      }
      screen[pn.name] = [p[0], p[1] - SIZE * 0.30 + bob, SIZE];
      // soft ground shadow (stays put while the body bobs)
      ctx.beginPath();
      ctx.ellipse(p[0], p[1] + SIZE * 0.06, SIZE * 0.26, SIZE * 0.11, 0, 0, 6.283);
      ctx.fillStyle = "rgba(0,0,0,0.28)"; ctx.fill();
      // sprite (its own row = facing direction, col = walk frame)
      var sheet = tintSheet(pn.color);
      var sx = walk * VT, sy = DIR_ROW[cur.dir] * VT;
      ctx.drawImage(sheet, sx, sy, VT, VT,
                    p[0] - SIZE / 2, p[1] - SIZE * 0.82 + bob, SIZE, SIZE);
    });
    R.screen = screen;

    // town name plates on top of everyone, so they stay readable
    drawNamePlates(ctx, data, m);
    drawHistoryBanner(ctx, data, W);

    // selection ring
    if (data.selected && screen[data.selected]) {
      var s = screen[data.selected];
      ctx.save();
      ctx.beginPath(); ctx.arc(s[0], s[1], 22, 0, 6.283);
      ctx.lineWidth = 3; ctx.strokeStyle = "#ffe36b";
      ctx.shadowColor = "#ffe36b"; ctx.shadowBlur = 10; ctx.stroke();
      ctx.restore();
    }

    // ambient day/night cycle — subtle, never fully dark, always readable
    var amb = dayNight(((performance.now() / 1000) % 60) / 60);
    if (amb[3] > 0.002) {
      ctx.fillStyle = "rgba(" + amb[0] + "," + amb[1] + "," + amb[2] + "," + amb[3] + ")";
      ctx.fillRect(0, 0, W, H);
    }
    // soft vignette for depth
    var vg = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.36,
                                      W / 2, H / 2, Math.max(W, H) * 0.62);
    vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(0,0,0,0.26)");
    ctx.fillStyle = vg; ctx.fillRect(0, 0, W, H);
  }

  // day/night keyframes -> [r,g,b,a] overlay (dawn·day·dusk·night)
  function dayNight(u) {
    var K = [[0.00, [255, 170, 95, 0.12]], [0.25, [255, 255, 255, 0.0]],
             [0.50, [255, 140, 70, 0.14]], [0.72, [26, 42, 92, 0.34]],
             [1.00, [255, 170, 95, 0.12]]];
    for (var i = 0; i < K.length - 1; i++) {
      if (u >= K[i][0] && u <= K[i + 1][0]) {
        var f = (u - K[i][0]) / (K[i + 1][0] - K[i][0]);
        var a = K[i][1], b = K[i + 1][1];
        return [Math.round(a[0] + (b[0] - a[0]) * f), Math.round(a[1] + (b[1] - a[1]) * f),
                Math.round(a[2] + (b[2] - a[2]) * f), a[3] + (b[3] - a[3]) * f];
      }
    }
    return [0, 0, 0, 0];
  }

  // ---- roads: a minimum spanning tree of the towns, drawn as dirt paths ----
  function mstEdges(demes) {
    var n = demes.length, inTree = [0], edges = [];
    while (inTree.length < n) {
      var best = null, bd = Infinity;
      inTree.forEach(function (i) {
        for (var j = 0; j < n; j++) {
          if (inTree.indexOf(j) >= 0) continue;
          var d = Math.hypot(demes[i].x - demes[j].x, demes[i].y - demes[j].y);
          if (d < bd) { bd = d; best = [i, j]; }
        }
      });
      if (!best) break;
      inTree.push(best[1]); edges.push(best);
    }
    return edges;
  }

  function drawRoads(ctx, data, m) {
    var demes = data.demes || [];
    if (demes.length < 2) return;
    var edges = mstEdges(demes);
    ctx.save();
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    // three stacked strokes: dark edge, dirt body, light centre track
    var layers = [[20, "rgba(60,44,30,0.55)"], [15, "rgba(122,96,62,0.95)"],
                  [6, "rgba(158,130,88,0.95)"]];
    layers.forEach(function (L) {
      ctx.lineWidth = L[0]; ctx.strokeStyle = L[1];
      edges.forEach(function (e) {
        var a = m(demes[e[0]].x, demes[e[0]].y), b = m(demes[e[1]].x, demes[e[1]].y);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      });
    });
    ctx.restore();
  }

  // wooden bridges wherever a road crosses the river
  function drawBridges(ctx, data, m) {
    if (!R.river) return;
    var demes = data.demes || [];
    if (demes.length < 2) return;
    var edges = mstEdges(demes);
    var rv = R.river;
    function riverY(x) { return rv.baseY + rv.amp * Math.sin(x * rv.freq + rv.phase); }
    edges.forEach(function (e) {
      var a = m(demes[e[0]].x, demes[e[0]].y), b = m(demes[e[1]].x, demes[e[1]].y);
      // sample the segment for the point nearest the river centreline
      var bestT = -1, bestD = 1e9;
      for (var k = 0; k <= 40; k++) {
        var tt = k / 40, x = a[0] + (b[0] - a[0]) * tt, y = a[1] + (b[1] - a[1]) * tt;
        var d = Math.abs(y - riverY(x));
        if (d < bestD) { bestD = d; bestT = tt; }
      }
      if (bestD > rv.half + 6) return;            // this road doesn't cross
      var cx = a[0] + (b[0] - a[0]) * bestT, cy = a[1] + (b[1] - a[1]) * bestT;
      var ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
      var L = rv.half * 2 + 22, Wd = 22;
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(ang);
      // planks
      ctx.fillStyle = "#8a5a34"; ctx.fillRect(-L / 2, -Wd / 2, L, Wd);
      ctx.fillStyle = "#6e4426";
      for (var px_ = -L / 2; px_ < L / 2; px_ += 6) ctx.fillRect(px_, -Wd / 2, 2, Wd);
      // rails
      ctx.fillStyle = "#5a3620";
      ctx.fillRect(-L / 2, -Wd / 2 - 3, L, 3);
      ctx.fillRect(-L / 2, Wd / 2, L, 3);
      ctx.restore();
    });
  }

  function drawNamePlates(ctx, data, m) {
    (data.demes || []).forEach(function (d) {
      var p = m(d.x, d.y);
      var label = d.label + "  " + d.n;
      ctx.font = "bold 13px system-ui, sans-serif";
      var tw = ctx.measureText(label).width;
      var py = p[1] - Math.min(d.r, 16) / 100 * 0 - 62;   // above the town
      ctx.fillStyle = "rgba(13,13,13,0.82)";
      roundRect(ctx, p[0] - tw / 2 - 8, py, tw + 16, 20, 6); ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(255,255,255,0.18)"; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(label, p[0], py + 10);

      // overlay badge: the number the active layer is actually colouring, so
      // the heat field is readable as a value and not only as a hue.
      if (d.badge) {
        ctx.font = "bold 11px system-ui, sans-serif";
        var bw = ctx.measureText(d.badge).width;
        var by = py + 23;
        ctx.fillStyle = hexA(d.wash || "#4ea3ff", 0.92);
        roundRect(ctx, p[0] - bw / 2 - 7, by, bw + 14, 17, 5); ctx.fill();
        ctx.fillStyle = "#0b0e12";
        ctx.fillText(d.badge, p[0], by + 9);
      }
    });
  }

  // Historical-mode banner: time travel must never be mistaken for live.
  function drawHistoryBanner(ctx, data, W) {
    if (!data.historical) return;
    var txt = "⏱ HISTORY — year " + data.tick;
    ctx.save();
    ctx.font = "bold 13px system-ui, sans-serif";
    var tw = ctx.measureText(txt).width;
    ctx.fillStyle = "rgba(201,133,0,0.92)";
    roundRect(ctx, W / 2 - tw / 2 - 12, 12, tw + 24, 26, 7); ctx.fill();
    ctx.fillStyle = "#141414"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(txt, W / 2, 25);
    ctx.restore();
  }

  // ---- helpers -----------------------------------------------------------
  function hexA(hex, a) {
    hex = (hex || "#888888").replace("#", "");
    var r = parseInt(hex.substr(0, 2), 16), g = parseInt(hex.substr(2, 2), 16),
        b = parseInt(hex.substr(4, 2), 16);
    return "rgba(" + r + "," + g + "," + b + "," + a + ")";
  }
  function roundRect(x, X, Y, w, h, r) {
    x.beginPath(); x.moveTo(X + r, Y); x.arcTo(X + w, Y, X + w, Y + h, r);
    x.arcTo(X + w, Y + h, X, Y + h, r); x.arcTo(X, Y + h, X, Y, r);
    x.arcTo(X, Y, X + w, Y, r); x.closePath();
  }
  function strHash(s) { var h = 0, i; for (i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }

  // ---- one-time setup: sheet load, canvas sizing, click, rAF -------------
  function ensureStarted() {
    if (R.started) return;
    R.started = true;
    R.sheet = new Image();
    R.sheet.onload = function () { requestAnimationFrame(frame); };
    R.sheet.src = SHEET_URL;
    R.vill = new Image(); R.vill.src = VILL_URL;
    // (canvas sizing is handled inside the frame loop)

    document.addEventListener("click", function (e) {
      var cv = document.getElementById("rts-canvas");
      if (!cv || e.target !== cv || !R.screen) return;
      var rect = cv.getBoundingClientRect();
      var mx = (e.clientX - rect.left) * cv.width / rect.width;
      var my = (e.clientY - rect.top) * cv.height / rect.height;
      var best = null, bestd = 26 * 26;
      for (var nm in R.screen) {
        var s = R.screen[nm], d = (s[0] - mx) * (s[0] - mx) + (s[1] - my) * (s[1] - my);
        if (d < bestd) { bestd = d; best = nm; }
      }
      if (best && window.dash_clientside && window.dash_clientside.set_props) {
        window.dash_clientside.set_props("selected", { data: best });
        // open the clicked villager's character sheet (Individual tab)
        window.dash_clientside.set_props("active-tab", { data: "individual" });
      }
    });
  }

  window.dash_clientside = window.dash_clientside || {};
  window.dash_clientside.extnpc = {
    renderMap: function (data) {
      ensureStarted();
      if (data) R.data = data;
      return "";
    }
  };
})();
