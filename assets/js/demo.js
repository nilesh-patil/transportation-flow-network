/* Transportation Flow Network - live map
   Leaflet 1.9 over data/zones.geojson + data/top_edges.json.
   Recolors 263 taxi zones by a user-selected metric; optional OD-edge overlay. */
(function () {
  "use strict";

  var PAPER = "#fffff8", INK = "#151515", FAINT = "#595959", RULE = "#dcdcd4";

  // ---- color helpers -------------------------------------------------------
  function lerp(a, b, t) { return a + (b - a) * t; }
  function rgb(r, g, b) { return "rgb(" + Math.round(r) + "," + Math.round(g) + "," + Math.round(b) + ")"; }
  // two-stop interpolation through an optional mid color
  function mix(c1, c2, t) { return rgb(lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)); }
  function diverging(t, lo, mid, hi) { // t in [0,1], 0.5 = neutral
    return t <= 0.5 ? mix(lo, mid, t / 0.5) : mix(mid, hi, (t - 0.5) / 0.5);
  }
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }

  // palettes
  var BLUE = [33, 102, 172], WHITE = [248, 248, 240], RED = [163, 32, 21];      // gravity
  var GREEN = [27, 120, 55], MIDG = [245, 245, 238], PURPLE = [118, 42, 131];   // net flow
  var SEQ_LO = [247, 247, 234], SEQ_HI = [25, 65, 110];                          // volume (sequential)
  var COMMUNITY = ["#a32015", "#1f6db0", "#3f8f4f", "#b8860b"];                  // categorical
  var COMMUNITY_NAMES = [                                                        // Leiden ids -> dominant area
    "Midtown commercial core",
    "Outer boroughs + airports",
    "Downtown + Brooklyn",
    "Upper Manhattan + Bronx"
  ];
  function communityName(c) { return (c == null) ? "n/a" : (COMMUNITY_NAMES[c] || ("Community " + c)); }
  var NODATA = "#e7e7df";

  // ---- metric definitions --------------------------------------------------
  var PERIODS = ["am_peak", "midday", "pm_peak", "evening", "late_night_weekend"];
  var PERIOD_LABEL = {
    am_peak: "AM peak (6-10, weekday)",
    midday: "Midday (10-16, weekday)",
    pm_peak: "PM peak (16-20, weekday)",
    evening: "Evening (20-24)",
    late_night_weekend: "Late night / weekend"
  };

  // diverging gravity: symmetric domain around 0, clipped to [-8, 8]
  var GRAV_LIM = 8;

  var NF_CAPTION = {
    am_peak: "Early commute. Manhattan's residential edges empty out as sources while the central business district and the airports fill as sinks.",
    midday: "The lull. Net flow is muted nearly everywhere; the office core holds a mild sink, the rest of the city is close to balanced.",
    pm_peak: "The reversal begins. Midtown starts shedding the people it absorbed all morning; the corridors home turn the residential zones back into sinks.",
    evening: "Nightlife pulls. The East Village, Lower East Side and the bar districts swing hard to sink as the office core drains out as a source.",
    late_night_weekend: "The graph inverts. Downtown leisure zones are the night's strongest destinations; the daytime business sinks are now sources or empty."
  };

  // ---- state ---------------------------------------------------------------
  var state = { metric: "gravity", period: "evening", year: "2015" };
  var geoLayer = null, edgeLayer = null, zonesData = null, edgesData = null;
  var edgeMax = 1;
  var YEARS = [];                       // year axis, filled from the data
  // year-varying scalars live under properties.years[year]; community is static
  function yd(props) { return (props.years && props.years[state.year]) || null; }
  function yearVaries() { return state.metric !== "community"; }

  // Frame the Manhattan core on load: the default "where Manhattan ends" view
  // lives there, and most zones elsewhere are outside the high-coverage core.
  var map = L.map("map", { zoomControl: true, attributionControl: true })
    .setView([40.773, -73.965], 12);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    subdomains: "abcd", maxZoom: 18, opacity: 0.55
  }).addTo(map);

  // ---- per-feature color ---------------------------------------------------
  function colorFor(props) {
    var v, yr = yd(props);
    if (state.metric === "community") {           // static (2015 reference partition)
      var c = props.community;
      if (c == null) return NODATA;
      return COMMUNITY[c % COMMUNITY.length];
    }
    if (yr == null) return NODATA;                // no data for this zone-year
    if (state.metric === "gravity") {
      v = yr.gs;
      if (v == null) return NODATA;
      var t = clamp01((v + GRAV_LIM) / (2 * GRAV_LIM)); // -lim -> 0, +lim -> 1
      return diverging(t, BLUE, WHITE, RED);
    }
    if (state.metric === "netflow") {
      v = yr.nf[state.period];
      if (v == null) return NODATA;
      var tn = clamp01((v + 1) / 2); // -1 source -> 0, +1 sink -> 1
      return diverging(tn, GREEN, MIDG, PURPLE);
    }
    if (state.metric === "volume") {
      v = yr.v[state.period];
      if (v == null) return NODATA;
      // log scale: thin tail, fat core
      var tv = clamp01(Math.log10(v + 1) / Math.log10(700000));
      return mix(SEQ_LO, SEQ_HI, tv);
    }
    return NODATA;
  }

  function styleFor(feature) {
    return {
      fillColor: colorFor(feature.properties),
      fillOpacity: 0.82,
      color: PAPER,
      weight: 0.7
    };
  }

  // ---- tooltip -------------------------------------------------------------
  function metricLine(props) {
    if (state.metric === "community") {
      return "community: <span class='tip-val'>" + communityName(props.community) + "</span>";
    }
    var yr = yd(props);
    if (state.metric === "gravity") {
      var g = yr ? yr.gs : null;
      return state.year + " gravity residual: <span class='tip-val'>" +
        (g == null ? "n/a" : g.toFixed(2)) + "</span>";
    }
    if (state.metric === "netflow") {
      var nf = yr ? yr.nf[state.period] : null;
      var tag = nf == null ? "" : (nf < -0.05 ? " (source)" : nf > 0.05 ? " (sink)" : " (balanced)");
      return state.year + " net flow, " + PERIOD_LABEL[state.period] + ": <span class='tip-val'>" +
        (nf == null ? "n/a" : nf.toFixed(3)) + "</span>" + tag;
    }
    var vol = yr ? yr.v[state.period] : null;
    return state.year + " destinations, " + PERIOD_LABEL[state.period] + ": <span class='tip-val'>" +
      (vol == null ? "n/a" : vol.toLocaleString()) + "</span> trips";
  }

  function tooltipHtml(props) {
    return "<span class='tip-zone'>" + (props.zone || "Unknown zone") + "</span>" +
      " <span class='tip-boro'>" + (props.borough || "") + "</span>" +
      "<span class='tip-metric'>" + metricLine(props) + "</span>";
  }

  function onEachFeature(feature, layer) {
    layer.bindTooltip("", { sticky: true, className: "tfn-tip", direction: "top", opacity: 1 });
    layer.on({
      mouseover: function (e) {
        e.target.setStyle({ weight: 2, color: INK });
        e.target.bringToFront();
        e.target.setTooltipContent(tooltipHtml(feature.properties));
      },
      mouseout: function (e) {
        geoLayer.resetStyle(e.target);
      }
    });
  }

  // ---- legend --------------------------------------------------------------
  function gradientCss(stops) {
    return "linear-gradient(to right, " + stops.join(", ") + ")";
  }
  function buildGradientStops(fn, n) {
    var out = [];
    for (var i = 0; i <= n; i++) out.push(fn(i / n));
    return out;
  }

  function renderLegend() {
    var el = document.getElementById("legend");
    var html = "";
    if (state.metric === "gravity") {
      var gs = buildGradientStops(function (t) { return diverging(t, BLUE, WHITE, RED); }, 24);
      html =
        "<div class='legend-title'>Gravity residual &middot; " + state.year + "</div>" +
        "<div class='legend-bar'><span>under (-" + GRAV_LIM + ")</span>" +
        "<span class='legend-gradient' style='background:" + gradientCss(gs) + "'></span>" +
        "<span>over (+" + GRAV_LIM + ")</span></div>" +
        "<div class='legend-cat' style='margin-top:.4rem'><i style='background:" + NODATA +
        "'></i>gray = outside the high-coverage core</div>";
    } else if (state.metric === "community") {
      var cats = "";
      for (var i = 0; i < COMMUNITY.length; i++) {
        cats += "<span class='legend-cat'><i style='background:" + COMMUNITY[i] + "'></i>" + COMMUNITY_NAMES[i] + "</span>";
      }
      html = "<div class='legend-title'>Leiden communities (2015 reference)</div><div class='legend-cats'>" + cats + "</div>";
    } else if (state.metric === "netflow") {
      var ns = buildGradientStops(function (t) { return diverging(t, GREEN, MIDG, PURPLE); }, 24);
      html =
        "<div class='legend-title'>Net-flow imbalance &middot; " + state.year + " &middot; " + PERIOD_LABEL[state.period] + "</div>" +
        "<div class='legend-bar'><span>source (-1)</span>" +
        "<span class='legend-gradient' style='background:" + gradientCss(ns) + "'></span>" +
        "<span>sink (+1)</span></div>";
    } else {
      var vs = buildGradientStops(function (t) { return mix(SEQ_LO, SEQ_HI, t); }, 24);
      html =
        "<div class='legend-title'>Destination volume (log) &middot; " + state.year + " &middot; " + PERIOD_LABEL[state.period] + "</div>" +
        "<div class='legend-bar'><span>few</span>" +
        "<span class='legend-gradient' style='background:" + gradientCss(vs) + "'></span>" +
        "<span>many</span></div>";
    }
    el.innerHTML = html;
  }

  // ---- caption -------------------------------------------------------------
  function renderCaption() {
    var c = document.getElementById("map-caption");
    if (state.metric === "gravity") {
      c.innerHTML = "<b>Where Manhattan ends &middot; " + state.year + ".</b> Blue zones draw fewer trips " +
        "than the gravity model predicts from size and distance; red zones draw more. The demand core " +
        "(Times Sq, Midtown) runs hot red, while the East Village, Alphabet City and the Upper East/West " +
        "Side sit under-connected in blue. Drag the year to watch Midtown cool from deep red toward " +
        "neutral as commuting falls away, while the under-connected edges hold.";
    } else if (state.metric === "community") {
      c.innerHTML = "<b>Four communities (2015 reference).</b> An undirected Leiden projection splits the " +
        "graph into four blocks (significance z = 13.8) that track function more than borough lines: a " +
        "Midtown commercial core, an Upper Manhattan and Bronx group, a downtown-and-Brooklyn group, and " +
        "a large outer-borough and airport community. The partition barely moves across the decade " +
        "(consecutive-year agreement averages ARI 0.88), so the map shows the stable reference rather " +
        "than re-coloring every year; the slider drives the other three lenses.";
    } else if (state.metric === "netflow") {
      c.innerHTML = "<b>Net flow, " + state.year + " &middot; " + PERIOD_LABEL[state.period] + ".</b> Green " +
        "zones send more than they receive (sources); purple zones receive more than they send (sinks). " +
        NF_CAPTION[state.period];
    } else {
      c.innerHTML = "<b>Destinations, " + state.year + " &middot; " + PERIOD_LABEL[state.period] + ".</b> " +
        "Darker zones are the stronger arrival magnets in this window, on a log scale. Watch the East " +
        "Village climb from ordinary by day to the city's top destination at night, while Midtown's " +
        "daytime dominance fades.";
    }
  }

  // ---- OD edge overlay -----------------------------------------------------
  function edgesForYear() {
    if (!edgesData) return [];
    if (edgesData.by_year) return edgesData.by_year[state.year] || [];
    return edgesData;  // backward-compat with the old flat array
  }
  function buildEdges() {
    if (edgeLayer) { map.removeLayer(edgeLayer); }
    edgeLayer = L.layerGroup();
    var es = edgesForYear();
    edgeMax = es.reduce(function (m, e) { return Math.max(m, e.trips); }, 1);
    es.forEach(function (e) {
      if (!e.from || !e.to) return;
      var w = 0.4 + 3.6 * (e.trips / edgeMax);
      L.polyline([e.from, e.to], {
        color: INK, weight: w, opacity: 0.28, lineCap: "round", interactive: false
      }).addTo(edgeLayer);
    });
  }
  function syncEdges() {
    if (!edgeLayer) return;
    if (document.getElementById("edge-toggle").checked) edgeLayer.addTo(map);
    else map.removeLayer(edgeLayer);
  }

  // ---- redraw --------------------------------------------------------------
  function redraw() {
    if (geoLayer) geoLayer.setStyle(styleFor);
    renderLegend();
    renderCaption();
    var pr = document.getElementById("period-row");
    var needsPeriod = state.metric === "netflow" || state.metric === "volume";
    pr.classList.toggle("is-hidden", !needsPeriod);
    // The year slider drives every lens except community (a fixed 2015 reference).
    var yrwrap = document.getElementById("year-row");
    if (yrwrap) {
      yrwrap.classList.toggle("is-disabled", !yearVaries());
      var sl = document.getElementById("year-slider");
      if (sl) sl.disabled = !yearVaries();
    }
  }

  function setYearReadout() {
    var out = document.getElementById("year-readout");
    if (out) out.textContent = yearVaries() ? state.year : "2015 reference";
  }

  // ---- wiring --------------------------------------------------------------
  function wireControls() {
    document.getElementById("metric-choices").addEventListener("change", function (e) {
      if (e.target.name === "metric") {
        state.metric = e.target.value;
        setYearReadout();
        redraw();
      }
    });
    var btns = document.querySelectorAll(".period-btn");
    btns.forEach(function (b) {
      b.addEventListener("click", function () {
        state.period = b.getAttribute("data-period");
        btns.forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        redraw();
      });
    });
    document.getElementById("edge-toggle").addEventListener("change", syncEdges);

    // year slider: index into YEARS so we never depend on a contiguous range
    var sl = document.getElementById("year-slider");
    if (sl && YEARS.length) {
      sl.min = 0;
      sl.max = YEARS.length - 1;
      sl.step = 1;
      sl.value = Math.max(0, YEARS.indexOf(state.year));
      sl.addEventListener("input", function () {
        if (!yearVaries()) return;            // community lens ignores the year
        state.year = YEARS[parseInt(sl.value, 10)] || state.year;
        setYearReadout();
        buildEdges();                          // refresh the OD overlay for the new year
        syncEdges();
        redraw();
      });
    }
  }

  // ---- load ----------------------------------------------------------------
  function loadJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("Failed to load " + url + " (" + r.status + ")");
      return r.json();
    });
  }

  Promise.all([loadJSON("data/zones.geojson"), loadJSON("data/top_edges.json")])
    .then(function (res) {
      zonesData = res[0];
      edgesData = res[1];
      YEARS = (zonesData && zonesData.years) || (edgesData && edgesData.years) || ["2015"];
      // default to the earliest year so the gravity view matches the page copy
      if (YEARS.indexOf(state.year) === -1) state.year = YEARS[0];
      geoLayer = L.geoJSON(zonesData, { style: styleFor, onEachFeature: onEachFeature }).addTo(map);
      buildEdges();
      wireControls();
      setYearReadout();
      redraw();
    })
    .catch(function (err) {
      var c = document.getElementById("map-caption");
      if (c) c.innerHTML = "<b>Could not load the map data.</b> Serve this page over http " +
        "(for example <code>python3 -m http.server</code>) so the browser can fetch " +
        "<code>data/zones.geojson</code>. " + err.message;
      // eslint-disable-next-line no-console
      console.error(err);
    });
})();
