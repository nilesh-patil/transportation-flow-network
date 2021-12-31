/* Transportation Flow Network - overview hero network graph.
   Renders the pre-baked community-clustered layout (data/network.json) on a
   canvas: 262 zone nodes colored by Leiden community and sized by strength, the
   disparity-filter backbone as edges. Hover a node to trace its backbone; hover
   or click a community in the legend to isolate it. Wheel to zoom, drag to pan.
   Dependency-free. */
(function () {
  "use strict";

  var PAPER = "#fffff8", INK = "#151515", FAINT = "#8a8a82";
  var canvas = document.getElementById("net-canvas");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var tip = document.getElementById("net-tip");
  var legendEl = document.getElementById("net-legend");

  var data = null, comm = [], W = 0, H = 0, dpr = 1;
  var base = { s: 1, ox: 0, oy: 0 };       // fit transform
  var view = { k: 1, tx: 0, ty: 0 };        // user zoom/pan
  var hover = -1, isolate = -1, wmax = 1, adj = [];
  var bounds = { minx: 0, miny: 0, w: 1, h: 1 };

  function toScreen(x, y) {
    var sx = (x * base.s + base.ox), sy = (y * base.s + base.oy);
    return [sx * view.k + view.tx, sy * view.k + view.ty];
  }
  function radius(n) { return (2.4 + n.r * 15) * Math.sqrt(view.k); }

  function fit() {
    // aspect-preserving fill of the actual layout bounds (no square letterbox)
    var pad = 30;
    base.s = Math.min((W - 2 * pad) / bounds.w, (H - 2 * pad) / bounds.h);
    base.ox = (W - bounds.w * base.s) / 2 - bounds.minx * base.s;
    base.oy = (H - bounds.h * base.s) / 2 - bounds.miny * base.s;
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

  function nodeShown(i) {
    if (isolate >= 0 && data.nodes[i].c !== isolate) return false;
    return true;
  }

  function draw() {
    if (!data) return;
    ctx.clearRect(0, 0, W, H);

    // ---- edges -------------------------------------------------------------
    var nodes = data.nodes, edges = data.edges;
    var hi = hover >= 0;
    for (var e = 0; e < edges.length; e++) {
      var a = edges[e][0], b = edges[e][1], w = edges[e][2];
      var na = nodes[a], nb = nodes[b];
      var intra = na.c === nb.c;
      var on = true, strong = false;
      if (hi) { strong = (a === hover || b === hover); on = strong; }
      else if (isolate >= 0) { on = (na.c === isolate && nb.c === isolate); }
      if (!on && !hi && isolate >= 0) continue;
      if (hi && !strong) continue;
      var pa = toScreen(na.x, na.y), pb = toScreen(nb.x, nb.y);
      ctx.beginPath();
      ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]);
      var lw = 0.25 + (w / wmax) * 3.2;
      if (strong) {
        ctx.strokeStyle = comm[na.c] ? comm[na.c].color : INK;
        ctx.globalAlpha = 0.55; ctx.lineWidth = Math.max(0.8, lw);
      } else {
        ctx.strokeStyle = intra ? (comm[na.c] ? comm[na.c].color : FAINT) : FAINT;
        ctx.globalAlpha = intra ? 0.13 : 0.05; ctx.lineWidth = lw;
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // ---- nodes -------------------------------------------------------------
    var nbrs = hi ? adj[hover] : null;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i], p = toScreen(n.x, n.y), r = radius(n);
      var dim = false;
      if (hi) dim = !(i === hover || (nbrs && nbrs.has(i)));
      else if (isolate >= 0) dim = n.c !== isolate;
      ctx.beginPath();
      ctx.arc(p[0], p[1], r, 0, 2 * Math.PI);
      ctx.fillStyle = comm[n.c] ? comm[n.c].color : FAINT;
      ctx.globalAlpha = dim ? 0.12 : 0.92;
      ctx.fill();
      ctx.globalAlpha = dim ? 0.12 : 1;
      ctx.lineWidth = (i === hover) ? 2.2 : 0.8;
      ctx.strokeStyle = (i === hover) ? INK : PAPER;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // ---- picking + tooltip ---------------------------------------------------
  function pick(mx, my) {
    var best = -1, bestD = 16 * 16;
    for (var i = 0; i < data.nodes.length; i++) {
      if (!nodeShown(i)) continue;
      var p = toScreen(data.nodes[i].x, data.nodes[i].y);
      var dx = p[0] - mx, dy = p[1] - my, d = dx * dx + dy * dy;
      var rr = radius(data.nodes[i]); rr = Math.max(rr * rr, 36);
      if (d < rr && d < bestD) { bestD = d; best = i; }
    }
    return best;
  }
  function showTip(n, mx, my) {
    var net = (n.outs - n.ins);
    tip.innerHTML = "<span class='nt-zone'>" + n.zone + "</span> <span class='nt-boro'>" +
      (n.borough || "") + "</span><span class='nt-row'>" + (comm[n.c] ? comm[n.c].name : "?") +
      "</span><span class='nt-row'>in " + n.ins.toLocaleString() + " &middot; out " +
      n.outs.toLocaleString() + "</span>";
    tip.hidden = false;
    var pad = 14;
    tip.style.left = Math.min(mx + pad, W - tip.offsetWidth - 6) + "px";
    tip.style.top = Math.max(my - pad - tip.offsetHeight, 6) + "px";
  }

  // ---- legend --------------------------------------------------------------
  function buildLegend() {
    legendEl.innerHTML = "";
    comm.forEach(function (c) {
      var li = document.createElement("li");
      li.className = "net-leg";
      li.innerHTML = "<i style='background:" + c.color + "'></i>" + c.name +
        " <span class='net-leg-n'>" + c.n + "</span>";
      li.addEventListener("click", function () {
        isolate = (isolate === c.id) ? -1 : c.id;
        hover = -1; tip.hidden = true; syncLegend(); draw();
      });
      li.addEventListener("mouseenter", function () { if (isolate < 0) { isolate = c.id; draw(); } });
      li.addEventListener("mouseleave", function () { if (li.getAttribute("data-pin") !== "1") { isolate = pinned(); draw(); } });
      legendEl.appendChild(li);
    });
    syncLegend();
  }
  function pinned() { var p = legendEl.querySelector('.net-leg[data-pin="1"]'); return p ? +p.dataset.cid : -1; }
  function syncLegend() {
    [].forEach.call(legendEl.children, function (li, i) {
      var active = isolate === comm[i].id;
      li.setAttribute("data-pin", active ? "1" : "0");
      li.dataset.cid = comm[i].id;
      li.classList.toggle("is-active", active);
    });
  }

  // ---- events --------------------------------------------------------------
  var dragging = false, lastX = 0, lastY = 0, moved = false;
  canvas.addEventListener("mousemove", function (ev) {
    var rect = canvas.getBoundingClientRect();
    var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    if (dragging) {
      view.tx += mx - lastX; view.ty += my - lastY; lastX = mx; lastY = my; moved = true;
      draw(); return;
    }
    var h = pick(mx, my);
    if (h !== hover) { hover = h; draw(); }
    if (h >= 0) { showTip(data.nodes[h], mx, my); canvas.style.cursor = "pointer"; }
    else { tip.hidden = true; canvas.style.cursor = "grab"; }
  });
  canvas.addEventListener("mouseleave", function () { hover = -1; tip.hidden = true; draw(); });
  canvas.addEventListener("mousedown", function (ev) {
    var rect = canvas.getBoundingClientRect();
    dragging = true; moved = false; lastX = ev.clientX - rect.left; lastY = ev.clientY - rect.top;
    canvas.style.cursor = "grabbing";
  });
  window.addEventListener("mouseup", function () { dragging = false; canvas.style.cursor = "grab"; });
  canvas.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    var rect = canvas.getBoundingClientRect();
    var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    var f = Math.exp(-ev.deltaY * 0.0012), nk = Math.min(8, Math.max(0.5, view.k * f));
    f = nk / view.k;
    view.tx = mx - (mx - view.tx) * f; view.ty = my - (my - view.ty) * f; view.k = nk;
    draw();
  }, { passive: false });

  // ---- load ----------------------------------------------------------------
  fetch("data/network.json").then(function (r) {
    if (!r.ok) throw new Error("network.json " + r.status); return r.json();
  }).then(function (d) {
    data = d; comm = d.communities;
    wmax = d.edges.reduce(function (m, e) { return Math.max(m, e[2]); }, 1);
    var xs = d.nodes.map(function (n) { return n.x; }), ys = d.nodes.map(function (n) { return n.y; });
    var mnx = Math.min.apply(null, xs), mxx = Math.max.apply(null, xs);
    var mny = Math.min.apply(null, ys), mxy = Math.max.apply(null, ys);
    bounds = { minx: mnx, miny: mny, w: (mxx - mnx) || 1, h: (mxy - mny) || 1 };
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
