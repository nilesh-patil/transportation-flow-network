/* Transportation Flow Network - overview hero network graph.
   Renders the pre-baked layout (data/network.json) on a canvas in two modes:
     - "force":  community-clustered force-directed node-link
     - "bundle": radial hierarchical edge bundling (zones on a ring grouped by
                 community, backbone flows drawn as bundled curves)
   262 zone nodes colored by Leiden community, sized by strength; edges are the
   disparity-filter backbone. Hover a node to trace its backbone; hover or click a
   community in the legend to isolate it; wheel to zoom, drag to pan. No deps. */
(function () {
  "use strict";

  var PAPER = "#fffff8", INK = "#151515", FAINT = "#8a8a82";
  var canvas = document.getElementById("net-canvas");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var tip = document.getElementById("net-tip");
  var legendEl = document.getElementById("net-legend");

  var data = null, comm = [], W = 0, H = 0, dpr = 1;
  var base = { s: 1, ox: 0, oy: 0 };
  var view = { k: 1, tx: 0, ty: 0 };
  var mode = "force";
  var hover = -1, pinned = -1, hoverIso = -1, wmax = 1, adj = [];
  function iso() { return pinned >= 0 ? pinned : hoverIso; }

  var forceBounds = { minx: 0, miny: 0, w: 1, h: 1 };
  var RING_BOUNDS = { minx: 0.02, miny: 0.02, w: 0.96, h: 0.96 };
  var R_RING = 0.46, R_IN = 0.17, BETA = 0.82;
  var bundlePaths = null;   // lazily computed normalized polylines, per edge

  // ---- geometry ------------------------------------------------------------
  function ringPos(a) { return [0.5 + R_RING * Math.cos(a), 0.5 + R_RING * Math.sin(a)]; }
  function nodePos(n) { return mode === "bundle" ? ringPos(n.a) : [n.x, n.y]; }
  function curBounds() { return mode === "bundle" ? RING_BOUNDS : forceBounds; }
  function toScreen(x, y) {
    var sx = x * base.s + base.ox, sy = y * base.s + base.oy;
    return [sx * view.k + view.tx, sy * view.k + view.ty];
  }
  function radius(n) { return (2.4 + n.r * 15) * Math.sqrt(view.k); }

  function fit() {
    var b = curBounds(), pad = 30;
    base.s = Math.min((W - 2 * pad) / b.w, (H - 2 * pad) / b.h);
    base.ox = (W - b.w * base.s) / 2 - b.minx * base.s;
    base.oy = (H - b.h * base.s) / 2 - b.miny * base.s;
  }
  function resize() {
    var rect = canvas.parentElement.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    W = rect.width; H = rect.height;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    fit(); draw();
  }

  // ---- hierarchical edge bundling paths (normalized, computed once) --------
  function commCtrl(c) { var m = comm[c].ma; return [0.5 + R_IN * Math.cos(m), 0.5 + R_IN * Math.sin(m)]; }
  function chaikin(pts, iters) {
    for (var it = 0; it < iters; it++) {
      var out = [pts[0]];
      for (var i = 0; i < pts.length - 1; i++) {
        var p = pts[i], q = pts[i + 1];
        out.push([0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]]);
        out.push([0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]]);
      }
      out.push(pts[pts.length - 1]);
      pts = out;
    }
    return pts;
  }
  function buildBundles() {
    var nodes = data.nodes, center = [0.5, 0.5];
    bundlePaths = data.edges.map(function (e) {
      var ni = nodes[e[0]], nj = nodes[e[1]];
      var Pi = ringPos(ni.a), Pj = ringPos(nj.a), cp;
      if (ni.c === nj.c) cp = [Pi, commCtrl(ni.c), Pj];
      else cp = [Pi, commCtrl(ni.c), center, commCtrl(nj.c), Pj];
      var n = cp.length, sp = [];
      for (var k = 0; k < n; k++) {
        var t = k / (n - 1);
        var lx = Pi[0] + (Pj[0] - Pi[0]) * t, ly = Pi[1] + (Pj[1] - Pi[1]) * t;
        sp.push([BETA * cp[k][0] + (1 - BETA) * lx, BETA * cp[k][1] + (1 - BETA) * ly]);
      }
      return chaikin(sp, 2);
    });
  }

  // ---- draw ----------------------------------------------------------------
  function draw() {
    if (!data) return;
    ctx.clearRect(0, 0, W, H);
    var nodes = data.nodes, edges = data.edges;
    var hi = hover >= 0, ei = iso(), bundle = mode === "bundle";

    for (var e = 0; e < edges.length; e++) {
      var a = edges[e][0], b = edges[e][1], w = edges[e][2];
      var na = nodes[a], nb = nodes[b], intra = na.c === nb.c;
      var strong = hi && (a === hover || b === hover);
      if (hi && !strong) continue;
      if (!hi && ei >= 0 && !(na.c === ei && nb.c === ei)) continue;
      var lw = 0.25 + (w / wmax) * 3.2;
      ctx.beginPath();
      if (bundle) {
        var poly = bundlePaths[e], p0 = toScreen(poly[0][0], poly[0][1]);
        ctx.moveTo(p0[0], p0[1]);
        for (var q = 1; q < poly.length; q++) { var pp = toScreen(poly[q][0], poly[q][1]); ctx.lineTo(pp[0], pp[1]); }
      } else {
        var sa = toScreen(na.x, na.y), sb = toScreen(nb.x, nb.y);
        ctx.moveTo(sa[0], sa[1]); ctx.lineTo(sb[0], sb[1]);
      }
      if (strong) {
        ctx.strokeStyle = comm[na.c] ? comm[na.c].color : INK;
        ctx.globalAlpha = 0.6; ctx.lineWidth = Math.max(0.9, lw);
      } else {
        ctx.strokeStyle = intra ? (comm[na.c] ? comm[na.c].color : FAINT) : FAINT;
        ctx.globalAlpha = bundle ? (intra ? 0.16 : 0.07) : (intra ? 0.13 : 0.05);
        ctx.lineWidth = lw;
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    var nbrs = hi ? adj[hover] : null;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i], pos = nodePos(n), p = toScreen(pos[0], pos[1]), r = radius(n);
      var dim = hi ? !(i === hover || (nbrs && nbrs.has(i))) : (ei >= 0 && n.c !== ei);
      ctx.beginPath();
      ctx.arc(p[0], p[1], r, 0, 2 * Math.PI);
      ctx.fillStyle = comm[n.c] ? comm[n.c].color : FAINT;
      ctx.globalAlpha = dim ? 0.12 : 0.92; ctx.fill();
      ctx.globalAlpha = dim ? 0.12 : 1;
      ctx.lineWidth = (i === hover) ? 2.2 : 0.8;
      ctx.strokeStyle = (i === hover) ? INK : PAPER;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // ---- picking + tooltip ---------------------------------------------------
  function shown(i) { var ei = iso(); return !(ei >= 0 && data.nodes[i].c !== ei); }
  function pick(mx, my) {
    var best = -1, bestD = 1e9;
    for (var i = 0; i < data.nodes.length; i++) {
      if (!shown(i)) continue;
      var pos = nodePos(data.nodes[i]), p = toScreen(pos[0], pos[1]);
      var dx = p[0] - mx, dy = p[1] - my, d = dx * dx + dy * dy;
      var rr = Math.max(radius(data.nodes[i]) * radius(data.nodes[i]), 36);
      if (d < rr && d < bestD) { bestD = d; best = i; }
    }
    return best;
  }
  function showTip(n, mx, my) {
    tip.innerHTML = "<span class='nt-zone'>" + n.zone + "</span> <span class='nt-boro'>" +
      (n.borough || "") + "</span><span class='nt-row'>" + (comm[n.c] ? comm[n.c].name : "?") +
      "</span><span class='nt-row'>in " + n.ins.toLocaleString() + " &middot; out " + n.outs.toLocaleString() + "</span>";
    tip.hidden = false;
    tip.style.left = Math.min(mx + 14, W - tip.offsetWidth - 6) + "px";
    tip.style.top = Math.max(my - 14 - tip.offsetHeight, 6) + "px";
  }

  // ---- legend + mode toggle ------------------------------------------------
  function buildLegend() {
    legendEl.innerHTML = "";
    comm.forEach(function (c) {
      var li = document.createElement("li");
      li.className = "net-leg"; li.dataset.cid = c.id;
      li.innerHTML = "<i style='background:" + c.color + "'></i>" + c.name + " <span class='net-leg-n'>" + c.n + "</span>";
      li.addEventListener("click", function () {
        pinned = (pinned === c.id) ? -1 : c.id; hover = -1; tip.hidden = true; syncLegend(); draw();
      });
      li.addEventListener("mouseenter", function () { hoverIso = c.id; draw(); });
      li.addEventListener("mouseleave", function () { hoverIso = -1; draw(); });
      legendEl.appendChild(li);
    });
    syncLegend();
  }
  function syncLegend() {
    [].forEach.call(legendEl.children, function (li) { li.classList.toggle("is-active", +li.dataset.cid === pinned); });
  }
  function setMode(m) {
    if (m === mode) return;
    mode = m;
    if (m === "bundle" && !bundlePaths) buildBundles();
    hover = -1; tip.hidden = true; view = { k: 1, tx: 0, ty: 0 };
    [].forEach.call(document.querySelectorAll(".net-mode"), function (btn) {
      btn.setAttribute("aria-pressed", String(btn.dataset.mode === m));
    });
    fit(); draw();
  }

  // ---- events --------------------------------------------------------------
  var dragging = false, lastX = 0, lastY = 0;
  canvas.addEventListener("mousemove", function (ev) {
    var rect = canvas.getBoundingClientRect(), mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    if (dragging) { view.tx += mx - lastX; view.ty += my - lastY; lastX = mx; lastY = my; draw(); return; }
    var h = pick(mx, my);
    if (h !== hover) { hover = h; draw(); }
    if (h >= 0) { showTip(data.nodes[h], mx, my); canvas.style.cursor = "pointer"; }
    else { tip.hidden = true; canvas.style.cursor = "grab"; }
  });
  canvas.addEventListener("mouseleave", function () { hover = -1; tip.hidden = true; draw(); });
  canvas.addEventListener("mousedown", function (ev) {
    var rect = canvas.getBoundingClientRect();
    dragging = true; lastX = ev.clientX - rect.left; lastY = ev.clientY - rect.top; canvas.style.cursor = "grabbing";
  });
  window.addEventListener("mouseup", function () { dragging = false; canvas.style.cursor = "grab"; });
  canvas.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    var rect = canvas.getBoundingClientRect(), mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    var nk = Math.min(8, Math.max(0.5, view.k * Math.exp(-ev.deltaY * 0.0012))), f = nk / view.k;
    view.tx = mx - (mx - view.tx) * f; view.ty = my - (my - view.ty) * f; view.k = nk; draw();
  }, { passive: false });
  [].forEach.call(document.querySelectorAll(".net-mode"), function (btn) {
    btn.addEventListener("click", function () { setMode(btn.dataset.mode); });
  });

  // ---- load ----------------------------------------------------------------
  fetch("data/network.json").then(function (r) {
    if (!r.ok) throw new Error("network.json " + r.status); return r.json();
  }).then(function (d) {
    data = d; comm = d.communities;
    wmax = d.edges.reduce(function (m, e) { return Math.max(m, e[2]); }, 1);
    var xs = d.nodes.map(function (n) { return n.x; }), ys = d.nodes.map(function (n) { return n.y; });
    var mnx = Math.min.apply(null, xs), mxx = Math.max.apply(null, xs), mny = Math.min.apply(null, ys), mxy = Math.max.apply(null, ys);
    forceBounds = { minx: mnx, miny: mny, w: (mxx - mnx) || 1, h: (mxy - mny) || 1 };
    adj = d.nodes.map(function () { return new Set(); });
    d.edges.forEach(function (e) { adj[e[0]].add(e[1]); adj[e[1]].add(e[0]); });
    buildLegend();
    resize();
  }).catch(function (err) {
    var cap = document.getElementById("net-fallback");
    if (cap) cap.hidden = false;
    // eslint-disable-next-line no-console
    console.error(err);
  });

  window.addEventListener("resize", function () { if (data) resize(); });
})();
