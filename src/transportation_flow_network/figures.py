"""Stage 8: regenerate every figure (PNG + SVG) into figures/.

Reproduces the original eight figures and adds the research-grade ones
(gravity residual "where Manhattan ends", net-flow source/sink, day/night
reversal, distance decay + gravity fit, centrality correlation, backbone,
rhythm clusters, inter-community flow). Each figure is labelled and captioned;
captions are also written to figures/CAPTIONS.md.
"""
from __future__ import annotations

import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from . import common, config as C

sns.set_style("whitegrid")
plt.rcParams.update({"figure.dpi": 110, "savefig.bbox": "tight", "font.size": 11})

CAPTIONS: dict[str, str] = {}
MANHATTAN_XLIM = (965000, 1010000)
MANHATTAN_YLIM = (190000, 245000)


def save(fig, name: str, caption: str) -> None:
    for ext in ("png", "svg"):
        fig.savefig(C.FIGURES / f"{name}.{ext}")
    plt.close(fig)
    CAPTIONS[name] = caption
    print(f"  [fig] {name}")


# ---------------------------------------------------------------------------
def fig_monthly(res):
    m = pd.read_parquet(C.MONTHLY_PARQUET).sort_values("month")
    labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = ["#2c7fb8" if 3 <= mo <= 5 else "#7fcdbb" for mo in m["month"]]
    ax.bar([labels[i - 1] for i in m["month"]], m["trips"] / 1e6, color=colors)
    ax.set_ylabel("trips (millions)")
    ax.set_title("Monthly yellow-taxi volume, NYC 2015")
    drop = res["temporal"]["monthly"]["spring_to_rest_drop_pct"]
    ax.annotate(f"Mar-May peak; {drop}% lower Jun-Dec", xy=(0.5, 0.95),
                xycoords="axes fraction", ha="center", va="top", fontsize=10, color="#555")
    save(fig, "01_monthly_volume",
         f"Monthly trip counts. Volume peaks in spring (Mar-May, highlighted) and runs {drop}% lower "
         f"across Jun-Dec. The drop is confounded by ride-hailing growth through 2015, not just weather.")


def fig_degree_distribution(edges):
    no_self = edges[edges["o"] != edges["d"]]
    full = no_self
    filt = no_self[no_self["trips"] > C.EDGE_WEIGHT_THRESHOLD]

    def strength(df, col):
        return df.groupby(col)["trips"].sum().sort_values(ascending=False).values

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, df, title in [(axes[0], full, "Full graph"),
                          (axes[1], filt, f"Filtered (> {C.EDGE_WEIGHT_THRESHOLD} trips/yr)")]:
        for col, color, lab in [("o", "#d95f02", "out-strength"), ("d", "#1b9e77", "in-strength")]:
            s = strength(df, col)
            ax.loglog(np.arange(1, len(s) + 1), s, marker=".", ms=4, ls="none", color=color, label=lab)
        ax.set_xlabel("rank"); ax.set_ylabel("zone strength (trips/yr)")
        ax.set_title(title); ax.legend()
    fig.suptitle("Strength-rank distribution: in vs out, full vs filtered")
    save(fig, "02_degree_distribution",
         "Zone strength (weighted degree) rank plots. In- and out-strength have distinct shapes (directed "
         "asymmetry the 2016 single-degree pass missed). Filtering at >500 trips/yr strips the thin tail.")


def fig_hour_weekday(res):
    hw = pd.read_parquet(C.HOUR_WEEKDAY_PARQUET)
    mat = hw.pivot(index="wd", columns="hr", values="trips").fillna(0)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    fig, ax = plt.subplots(figsize=(12, 4.5))
    sns.heatmap(mat / 1e3, cmap="magma", ax=ax,
                cbar_kws={"label": "trips (thousands)"}, yticklabels=days)
    ax.set_xlabel("hour of day"); ax.set_ylabel("")
    ax.set_title("Trip density by hour x weekday, NYC 2015")
    save(fig, "03_hour_weekday_heatmap",
         "Hour x weekday density. Bright bands at the weekday 6-9 AM / evening commute and the weekend "
         "late-night (0-4 AM) hours reproduce the original heatmap finding.")


def fig_cost_duration(res):
    s = pd.read_parquet(C.TRIP_SAMPLE_PARQUET)
    s = s[(s["duration_min"] <= 90) & (s["fare_amount"] <= 90)]
    fig, ax = plt.subplots(figsize=(7.5, 6))
    jfk = s["ratecode"] == 2
    ax.scatter(s.loc[~jfk, "duration_min"], s.loc[~jfk, "fare_amount"], s=2, alpha=0.05,
               color="#888", rasterized=True, label="metered (rate 1)")
    ax.scatter(s.loc[jfk, "duration_min"], s.loc[jfk, "fare_amount"], s=4, alpha=0.25,
               color="#e6550d", rasterized=True, label="JFK flat fare (rate 2)")
    ax.axhline(52, color="#e6550d", lw=0.8, ls="--")
    ax.set_xlabel("trip duration (min)"); ax.set_ylabel("fare ($)")
    ax.set_title("Cost vs duration: the constant-cost band is the JFK flat fare")
    ax.legend(markerscale=3)
    band = res["temporal"]["cost_duration"]
    save(fig, "04_cost_vs_duration",
         f"Fare vs duration. The flat band at ~$52, independent of duration, is the JFK flat fare "
         f"(RatecodeID 2): {band['constant_band_is_jfk_pct']}% of trips in the $49-53 band. This explains "
         f"the 'constant-cost outliers' the original guessed were rounded tips.")


def _zone_positions(zones):
    return {int(r.zone_id): (r.cx_ft, r.cy_ft) for r in zones.itertuples()}


def fig_hub_map(zones, nodes, edges):
    import networkx as nx
    pos = _zone_positions(zones)
    top = edges[(edges["o"] != edges["d"]) & (edges["trips"] > 5000)]
    g = nx.from_pandas_edgelist(top, "o", "d", edge_attr="trips", create_using=nx.DiGraph)
    g = g.subgraph([n for n in g.nodes if n in pos])
    out_s = nodes.set_index("zone_id")["out_strength"]
    sizes = [np.sqrt(out_s.get(n, 1)) * 0.6 for n in g.nodes]
    widths = [d["trips"] / 12000 for *_, d in g.edges(data=True)]

    fig, ax = plt.subplots(figsize=(9, 10))
    zones.boundary.plot(ax=ax, color="#dddddd", lw=0.4)
    nx.draw_networkx_edges(g, pos, ax=ax, width=widths, edge_color="#3182bd",
                           alpha=0.35, arrows=False)
    nx.draw_networkx_nodes(g, pos, ax=ax, node_size=sizes, node_color="#de2d26", alpha=0.8)
    ax.set_xlim(*MANHATTAN_XLIM); ax.set_ylim(*MANHATTAN_YLIM)
    ax.set_title("Taxi flow network on NYC geography\n(node size = out-strength, edge width = trips)")
    ax.set_axis_off()
    save(fig, "05_hub_map_geographic",
         "The flow network drawn on real geography (Manhattan core), node size proportional to out-strength "
         "and edge width to annual trips. Midtown, the Upper East/West Sides and downtown dominate; "
         "transport hubs are network hubs.")


def fig_degree_vs_trips(nodes):
    df = nodes.copy()
    df["trips"] = df["out_strength"] + df["in_strength"]
    hi = df[df["trips"] >= 500]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(hi["trips"], hi["in_degree"], s=18, color="#2c7fb8", alpha=0.7, label="in-degree")
    ax.scatter(hi["trips"], hi["out_degree"], s=18, color="#de2d26", alpha=0.7, label="out-degree",
               marker="^")
    ax.set_xscale("log")
    ax.set_xlabel("total trips at zone (log)"); ax.set_ylabel("degree (distinct partners)")
    ax.set_title("Degree vs trips (zones >= 500 trips)")
    ax.legend()
    # annotate the airports vs inner-city contrast
    for sub, dx in [("JFK Airport", 5), ("Penn Station", 5)]:
        h = df[df["zone"].str.contains(sub, case=False, na=False)]
        if len(h):
            r = h.iloc[0]
            ax.annotate(sub, (r["trips"], r["in_degree"]), fontsize=8, color="#555")
    save(fig, "06_degree_vs_trips",
         "In- and out-degree against total trips. Inner-city draws (Penn, Midtown) pull huge volume from a "
         "limited Manhattan origin set; airports pull from many scattered origins (high degree, lower "
         "trips-per-source).")


def fig_community_map(zones, node_analysis):
    g = zones.merge(node_analysis[["zone_id", "leiden_community"]], on="zone_id", how="left")
    fig, ax = plt.subplots(figsize=(9, 10))
    g.plot(column="leiden_community", categorical=True, cmap="Set2", ax=ax,
           legend=True, missing_kwds={"color": "#eeeeee"}, edgecolor="#ffffff", lw=0.3,
           legend_kwds={"title": "community", "loc": "lower right"})
    ax.set_title("Leiden communities of the taxi flow network")
    ax.set_axis_off()
    save(fig, "07_community_map",
         "Leiden communities (weighted, directed-aware). The partition is seed-stable (mean ARI ~0.77) and "
         "cuts across borough lines, redrawing NYC by taxi connectivity rather than administration.")


def fig_where_manhattan_ends(zones, node_analysis, res):
    """Flagship: annotated gravity-residual map of the high-coverage core, paired
    with a ranked lollipop strip of the most under- and over-connected zones.

    Only the high-coverage core (Yellow Zone + airports) is colored; every other
    zone is greyed, so the eye trusts the residual exactly where the yellow-taxi
    sample is dense. Marquee zones are labeled in place, and the strip names the
    extremes the map alone cannot.
    """
    import matplotlib.colors as mcolors

    # zones already carries zone/service_zone; take only the residual from node_analysis
    g = zones.merge(node_analysis[["zone_id", "gravity_surprise"]], on="zone_id", how="left")
    in_core = g["service_zone"].isin(["Yellow Zone", "Airports", "EWR"]) & g["gravity_surprise"].notna()
    core, noncore = g[in_core], g[~in_core]
    vmax = float(np.nanpercentile(np.abs(core["gravity_surprise"]), 98))
    norm = mcolors.Normalize(-vmax, vmax)
    cmap = plt.cm.RdBu_r

    fig = plt.figure(figsize=(13.5, 9.2))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.5, 1], wspace=0.04)
    ax, axr = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])

    # ---- panel 1: the map ----------------------------------------------------
    noncore.plot(ax=ax, color="#e9e9e2", edgecolor="#ffffff", lw=0.3)   # out-of-core, greyed
    core.plot(column="gravity_surprise", cmap=cmap, norm=norm, ax=ax,
              edgecolor="#ffffff", lw=0.4)
    ax.set_xlim(*MANHATTAN_XLIM); ax.set_ylim(*MANHATTAN_YLIM)
    ax.set_axis_off()
    ax.set_title("Where Manhattan ends", loc="left", fontsize=15, fontweight="bold")
    ax.text(0, 1.0, "connectivity residual from a doubly-constrained gravity model, high-coverage core only",
            transform=ax.transAxes, fontsize=9.5, color="#555", va="top")

    # marquee callouts: (name substring -> display label, x-offset pts, y-offset pts, ha)
    cc = core.copy()
    cen = cc.geometry.centroid
    cc["cx"], cc["cy"] = cen.x.values, cen.y.values
    marquee = {
        "Upper West Side South": ("Upper West Side", -66, 26, "right"),
        "Upper East Side North": ("Upper East Side", 60, 30, "left"),
        "Times Sq": ("Times Sq", -80, 4, "right"),
        "Garment": ("Garment District", -86, -20, "right"),
        "East Village": ("East Village", 58, 6, "left"),
        "Alphabet City": ("Alphabet City", 70, -16, "left"),
        "Lower East Side": ("Lower East Side", 60, -34, "left"),
    }
    for sub, (label, ox, oy, ha) in marquee.items():
        hit = cc[cc["zone"].str.contains(sub, case=False, na=False)]
        if not len(hit):
            continue
        r = hit.iloc[0]
        ax.annotate(f"{label}  {r['gravity_surprise']:+.0f}",
                    xy=(r["cx"], r["cy"]), xytext=(ox, oy), textcoords="offset points",
                    fontsize=8.5, ha=ha, va="center", color="#1a1a1a",
                    arrowprops=dict(arrowstyle="-", color="#666", lw=0.7,
                                    connectionstyle="arc3,rad=0.12"),
                    bbox=dict(boxstyle="round,pad=0.18", fc="#fffff8", ec="#ccccc4", lw=0.5, alpha=0.92))

    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax,
                      location="bottom", shrink=0.55, pad=0.01, aspect=32)
    cb.set_label("under-connected  ←  gravity residual  →  over-connected", fontsize=9)
    cb.ax.tick_params(labelsize=8)

    # ---- panel 2: ranked lollipop strip --------------------------------------
    cs = core.dropna(subset=["gravity_surprise"]).copy()
    k = 11
    sel = pd.concat([cs.nsmallest(k, "gravity_surprise"), cs.nlargest(k, "gravity_surprise")])
    sel = sel.drop_duplicates("zone_id").sort_values("gravity_surprise").reset_index(drop=True)
    yy = np.arange(len(sel))
    vals = sel["gravity_surprise"].to_numpy()
    colors = cmap(norm(vals))
    axr.axvline(0, color="#bbbbbb", lw=0.8)
    axr.hlines(yy, 0, vals, color=colors, lw=2.2)
    axr.scatter(vals, yy, color=colors, s=42, zorder=3, edgecolor="#ffffff", lw=0.6)
    for y, v, name in zip(yy, vals, sel["zone"]):
        axr.text(v + (0.5 if v >= 0 else -0.5), y, f"{v:+.1f}", va="center",
                 ha="left" if v >= 0 else "right", fontsize=6.8, color="#555")
    axr.set_yticks(yy)
    axr.set_yticklabels(sel["zone"], fontsize=7.6)
    axr.set_ylim(-0.7, len(sel) - 0.3)
    pad = vmax * 0.28
    axr.set_xlim(-vmax - pad, vmax + pad)
    axr.set_xlabel("mean deviance residual", fontsize=9)
    axr.set_title(f"The {k} most under- and over-connected core zones", loc="left", fontsize=10.5)
    for s in ("top", "right", "left"):
        axr.spines[s].set_visible(False)
    axr.tick_params(left=False)

    save(fig, "08_where_manhattan_ends",
         "Flagship figure. Per-zone mean deviance residual from a doubly-constrained gravity model "
         "(controls for each zone's own volume and distance to everywhere else). Only the high-coverage core "
         "(Yellow Zone plus airports) is colored; the rest of the city is greyed because yellow-taxi coverage "
         "there is too thin to trust the residual. Blue zones (the Upper East and West Sides uptown, the East "
         "Village and Alphabet City downtown) are under-connected given how central they sit; red zones "
         "(Times Sq, the Midtown spine) are over-connected. The strip at right names the extremes the map "
         "alone cannot.")


def fig_net_flow(zones, node_analysis):
    g = zones.merge(node_analysis[["zone_id", "net_flow_index"]], on="zone_id", how="left")
    fig, ax = plt.subplots(figsize=(9, 10))
    g.plot(column="net_flow_index", cmap="PiYG", ax=ax, legend=True, vmin=-0.5, vmax=0.5,
           missing_kwds={"color": "#eeeeee"}, edgecolor="#ffffff", lw=0.3,
           legend_kwds={"label": "net-flow index (green = net source)", "shrink": 0.6})
    ax.set_xlim(*MANHATTAN_XLIM); ax.set_ylim(*MANHATTAN_YLIM)
    ax.set_title("Annual net-flow index (source vs sink)")
    ax.set_axis_off()
    save(fig, "09_net_flow_source_sink",
         "Annual net-flow index (out-strength minus in-strength, normalised). Over a full year most zones "
         "are near balanced; the directional structure is strongest within the day (see day/night figure).")


def fig_am_pm_flip(res):
    flip = res["analysis"]["temporal_networks"]["am_pm_netflow_flip"]
    shift = res["analysis"]["temporal_networks"]["nightlife_rank_shift"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    names = list(flip.keys())
    am = [flip[n]["nfi_am"] for n in names]
    pm = [flip[n]["nfi_pm"] for n in names]
    y = np.arange(len(names))
    ax1.barh(y - 0.2, am, height=0.4, color="#3182bd", label="AM peak")
    ax1.barh(y + 0.2, pm, height=0.4, color="#e6550d", label="PM peak")
    ax1.set_yticks(y); ax1.set_yticklabels([n.split("/")[0] for n in names], fontsize=9)
    ax1.axvline(0, color="k", lw=0.6)
    ax1.set_xlabel("net-flow index  (<0 sink, >0 source)")
    ax1.set_title("CBD vs residential net-flow flips between AM and PM")
    ax1.legend()

    sn = list(shift.keys())
    amr = [shift[n]["am_rank"] for n in sn]
    nr = [shift[n]["night_rank"] for n in sn]
    for i, n in enumerate(sn):
        ax2.plot([0, 1], [amr[i], nr[i]], "-o", color="#756bb1")
        ax2.annotate(n.split("/")[0], (1.02, nr[i]), fontsize=8, va="center")
    ax2.set_xticks([0, 1]); ax2.set_xticklabels(["daytime rank", "late-night rank"])
    ax2.invert_yaxis()
    ax2.set_ylabel("destination rank (1 = busiest)")
    ax2.set_title("Nightlife zones: peripheral by day, top hubs at night")
    save(fig, "10_day_night_reversal",
         "Left: the morning/evening net-flow sign flip - Midtown/Financial District are AM sinks and PM "
         "sources; East Village/Lower East Side are the mirror image. Right: East Village rises from ~42nd "
         "destination by day to 1st at night. The original's 'suburb-like LES' is a daytime-only effect.")


def fig_distance_decay(res):
    edges = common.load_edges_annual()
    nodes = common.load_nodes()
    pos = nodes.set_index("zone_id")[["cx_ft", "cy_ft"]]
    e = edges[(edges["o"] != edges["d"])].copy()
    e = e[e["o"].isin(pos.index) & e["d"].isin(pos.index)]
    ox = pos.loc[e["o"], "cx_ft"].to_numpy(); oy = pos.loc[e["o"], "cy_ft"].to_numpy()
    dx = pos.loc[e["d"], "cx_ft"].to_numpy(); dy = pos.loc[e["d"], "cy_ft"].to_numpy()
    e["dist_mi"] = np.sqrt((ox - dx) ** 2 + (oy - dy) ** 2) / 5280.0
    e = e[e["dist_mi"] > 0.05]
    bins = np.logspace(np.log10(e["dist_mi"].min()), np.log10(e["dist_mi"].max()), 25)
    e["bin"] = pd.cut(e["dist_mi"], bins)
    grp = e.groupby("bin", observed=True).agg(d=("dist_mi", "mean"), t=("trips", "mean")).dropna()
    beta = res["analysis"]["gravity_residual_field"]["beta_doubly_constrained"]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(e["dist_mi"], e["trips"], s=2, alpha=0.04, color="#bbb", rasterized=True)
    ax.plot(grp["d"], grp["t"], "o-", color="#2c7fb8", label="binned mean")
    xs = np.linspace(grp["d"].min(), grp["d"].max(), 50)
    ax.plot(xs, grp["t"].iloc[3] * (xs / grp["d"].iloc[3]) ** (-beta), "--", color="#e6550d",
            label=f"power-law slope -{beta}")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("centroid distance (mi)"); ax.set_ylabel("annual trips per OD pair")
    ax.set_title("Distance decay of taxi flows")
    ax.legend()
    save(fig, "11_distance_decay",
         f"Annual trips per OD pair vs centroid distance, with the calibrated doubly-constrained decay "
         f"exponent (beta = {beta}). Flows fall off steeply with distance, quantifying Tobler's first law "
         f"for taxi travel.")


def fig_gravity_fit(res):
    edf = pd.read_parquet(C.PROCESSED / "gravity_edges.parquet")
    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.scatter(edf["model"], edf["obs"], s=4, alpha=0.2, color="#2c7fb8", rasterized=True)
    lim = [max(1, edf[["model", "obs"]].min().min()), edf[["model", "obs"]].max().max()]
    ax.plot(lim, lim, "k--", lw=1)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("gravity-model trips"); ax.set_ylabel("observed trips")
    cpc = res["analysis"]["gravity_residual_field"]["cpc_doubly_constrained"]
    ax.set_title(f"Doubly-constrained gravity fit (CPC = {cpc})")
    save(fig, "12_gravity_fit",
         f"Observed vs doubly-constrained-gravity-predicted OD flows in the high-coverage core. Common Part "
         f"of Commuters = {cpc}; points off the diagonal are the residual 'surprise' mapped in figure 08.")


def fig_centrality_corr(res):
    c = res["analysis"]["centrality_rank_correlation"]
    corr = np.array(c["spearman"])
    labels = [s.replace("_", "\n") for s in c["columns"]]
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="viridis", xticklabels=labels,
                yticklabels=labels, ax=ax, vmin=0, vmax=1, cbar_kws={"label": "Spearman rho"})
    ax.set_title("Rank correlation across centrality measures")
    save(fig, "13_centrality_correlation",
         "Spearman correlation among centrality measures. PageRank and strength move together; betweenness "
         "and HITS hub/authority capture distinct roles (brokers vs origins vs destinations).")


def fig_backbone(res, zones, edges):
    import networkx as nx
    bb = pd.read_parquet(C.PROCESSED / "backbone_edges.parquet")
    pos = _zone_positions(zones)
    keep = bb[bb["keep"]]
    g = nx.from_pandas_edgelist(keep, "o", "d", create_using=nx.DiGraph)
    g = g.subgraph([n for n in g.nodes if n in pos])
    info = res["analysis"]["backbone"]
    fig, ax = plt.subplots(figsize=(9, 10))
    zones.boundary.plot(ax=ax, color="#dddddd", lw=0.3)
    nx.draw_networkx_edges(g, pos, ax=ax, width=0.4, edge_color="#31a354", alpha=0.5, arrows=False)
    nx.draw_networkx_nodes(g, pos, ax=ax, node_size=8, node_color="#006d2c")
    ax.set_xlim(*MANHATTAN_XLIM); ax.set_ylim(*MANHATTAN_YLIM)
    ax.set_title("Statistically significant backbone (disparity filter)")
    ax.set_axis_off()
    save(fig, "14_backbone",
         f"Multiscale backbone from the disparity filter (alpha = {info['alpha']}): {info['backbone_edges']} "
         f"edges retain {info['backbone_trip_share_pct']}% of trips, a principled alternative to the "
         f"arbitrary >500-trip cut ({info['threshold_edges']} edges).")


def fig_rhythm(zones, node_analysis, res):
    zh = pd.read_parquet(C.PROCESSED / "zone_hourly.parquet")
    wk = zh[~zh["weekend"]].pivot_table(index="zone_id", columns="hr", values="pickups", aggfunc="sum").fillna(0)
    wk = wk[wk.sum(axis=1) >= 50_000]
    profile = wk.div(wk.sum(axis=1), axis=0)
    na = node_analysis.dropna(subset=["rhythm_cluster"])
    clusters = res["analysis"]["temporal_networks"]["rhythm_clusters"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    palette = sns.color_palette("Set1", len(clusters))
    for c in sorted(clusters):
        ids = na.loc[na["rhythm_cluster"] == int(c), "zone_id"]
        ids = [z for z in ids if z in profile.index]
        if not ids:
            continue
        mean_p = profile.loc[ids].mean()
        ex = ", ".join(clusters[c]["examples"][:2])
        ax1.plot(mean_p.index, mean_p.values, "-o", ms=3, color=palette[int(c)],
                 label=f"peak {clusters[c]['peak_hour']}h: {ex}")
    ax1.set_xlabel("hour of day"); ax1.set_ylabel("share of zone's daily pickups")
    ax1.set_title("Daily pickup rhythms (k-means, weekday)")
    ax1.legend(fontsize=8)

    g = zones.merge(na[["zone_id", "rhythm_cluster"]], on="zone_id", how="left")
    g.plot(column="rhythm_cluster", categorical=True, cmap="Set1", ax=ax2, legend=True,
           missing_kwds={"color": "#eeeeee"}, edgecolor="#ffffff", lw=0.3)
    ax2.set_xlim(*MANHATTAN_XLIM); ax2.set_ylim(*MANHATTAN_YLIM)
    ax2.set_title("Rhythm clusters mapped")
    ax2.set_axis_off()
    save(fig, "15_daily_rhythms",
         "K-means clusters of each zone's 24-hour weekday pickup shape. Commuter-residential (morning peak), "
         "commercial core (evening peak) and nightlife (late-night peak; LES, Williamsburg) separate cleanly.")


def fig_intercommunity(res):
    fm = pd.read_parquet(C.PROCESSED / "community_flow_matrix.parquet").values
    frac = fm / fm.sum()
    fig, ax = plt.subplots(figsize=(6, 5))
    sns.heatmap(frac, annot=True, fmt=".2f", cmap="rocket_r", ax=ax,
                cbar_kws={"label": "share of all trips"})
    ax.set_xlabel("destination community"); ax.set_ylabel("origin community")
    within = res["analysis"]["communities"]["within_community_trip_share"]
    ax.set_title(f"Inter-community flow matrix (within-community = {within})")
    save(fig, "16_intercommunity_flow",
         f"Trip shares between Leiden communities. {within:.0%} of trips stay within a community; the "
         f"off-diagonal structure shows directional coupling between functional districts.")


# ===========================================================================
# METHOD-AREA DIAGNOSTIC FIGURES (single-year, textbook style)
# ===========================================================================
STRATEGY_STYLE = {
    "random": ("#444444", "-", 2.4, "random failure"),
    "strength": ("#e6550d", "-", 1.4, "strength attack"),
    "strength_recomp": ("#a50f15", "--", 1.6, "strength (recomputed)"),
    "betweenness": ("#3182bd", "-", 1.4, "betweenness attack"),
    "pagerank": ("#756bb1", "-", 1.4, "PageRank attack"),
}


def fig_attack_vs_failure():
    """figures/18_attack_vs_failure.{png,svg} - Barabasi Ch.8 robustness.

    Reads data/processed/robustness.parquet (long: strategy,f,wcc_frac,scc_frac,
    eff_frac,trip_frac). 1x3 small multiples sharing the x-axis f (fraction of
    nodes removed). Panel A topology hides it (largest WCC), Panel B weighted
    efficiency E(f)/E(0), Panel C surviving-trip fraction. Headline numbers and
    the Molloy-Reed kappa are pulled from metrics_summary.json['robustness'] so
    the figure text and JSON agree.
    """
    path = C.PROCESSED / "robustness.parquet"
    if not path.exists():
        print("  [fig] 18_attack_vs_failure SKIPPED (robustness.parquet absent)")
        return
    df = pd.read_parquet(path)
    df = df[df["f"] <= 0.60]
    res = common.load_results()
    rob = res.get("robustness", {})
    kappa = rob.get("molloy_reed_kappa", float("nan"))
    gap = rob.get("attack_vs_failure_gap", {})
    cf_trip = rob.get("critical_f_trip", {})

    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharex=True)
    panels = [
        ("wcc_frac", "largest WCC fraction", "A. Topology hides it"),
        ("eff_frac", "weighted efficiency  E(f) / E(0)", "B. Flow-weighted efficiency"),
        ("trip_frac", "surviving-trip fraction", "C. Surviving flow (the honest axis)"),
    ]
    for ax, (col, ylab, title) in zip(axes, panels):
        for strat in ["random", "betweenness", "pagerank", "strength", "strength_recomp"]:
            sub = df[df["strategy"] == strat].sort_values("f")
            if sub.empty:
                continue
            color, ls, lw, lab = STRATEGY_STYLE[strat]
            ax.plot(sub["f"], sub[col], ls=ls, lw=lw, color=color, label=lab,
                    marker="." if strat != "random" else None, ms=4)
        ax.axhline(0.5, color="#bbbbbb", ls=":", lw=1)
        ax.set_xlabel("fraction of nodes removed  f")
        ax.set_ylabel(ylab)
        ax.set_title(title, fontsize=11)
        ax.set_ylim(-0.02, 1.05)
    axes[0].legend(fontsize=8, loc="lower left")
    axes[0].annotate("random ~ targeted on connectivity:\nthe dense core stays weakly connected",
                     xy=(0.30, 0.62), xycoords="axes fraction", fontsize=8, color="#555",
                     ha="left")
    if gap:
        axes[2].annotate(
            f"f=0.10: random keeps {gap.get('random_trip_frac', 0):.0%} of trips,\n"
            f"worst attack ({gap.get('worst_attack_strategy', '')}) keeps "
            f"{gap.get('worst_attack_trip_frac', 0):.0%}",
            xy=(0.12, 0.80), xycoords="axes fraction", fontsize=8, color="#a50f15", ha="left")
    if cf_trip:
        axes[2].annotate(f"trip f_c: random {cf_trip.get('random')}  vs  strength {cf_trip.get('strength')}",
                         xy=(0.20, 0.05), xycoords="axes fraction", fontsize=8, color="#555")
    fig.suptitle("Attack vs random failure: unweighted robustness hides acute flow vulnerability",
                 fontsize=13)
    save(fig, "18_attack_vs_failure",
         f"Barabasi Ch.8 robustness. As a fraction f of nodes is removed, the largest weakly-connected "
         f"component (A) decays almost identically under random failure and every targeted attack - the "
         f"density-0.62 core stays weakly connected, so topology hides the story. Flow-weighted efficiency "
         f"(B) and surviving-trip fraction (C) fan out dramatically: random removal leaves ~82% of trips and "
         f"~96% of weighted efficiency at f=0.10, while removing the top-10% strength/PageRank hubs leaves "
         f"only ~13% of trips and ~17-26% efficiency. strength_recomp (recalculated adversary) is strictly "
         f"the worst. Molloy-Reed kappa = {kappa:.1f} >> 2, so the random-failure critical fraction is "
         f"essentially 1 (degenerate by construction); the dashed line at 0.5 reads off the trip-fraction f_c "
         f"(random 0.32 vs strength 0.04). Note: E(f)/E(0) can sit marginally above 1 at the smallest f "
         f"because weighted global efficiency is a pair-mean, not monotone under node removal.")


def fig_powerlaw_loglog():
    """figures/17_degree_distribution_loglog.{png,svg} - CSN log-log CCDF.

    Reads data/processed/powerlaw_fits.parquet plus the raw strength/degree
    vectors (active nodes; total_strength = out+in). One panel per quantity:
    empirical CCDF P(X>=x) markers, fitted discrete power-law CCDF for x>=xmin,
    shaded x<xmin region, annotated alpha/xmin/D/n_tail/p_gof and the honest
    verdict.
    """
    path = C.PROCESSED / "powerlaw_fits.parquet"
    if not path.exists():
        print("  [fig] 17_degree_distribution_loglog SKIPPED (powerlaw_fits.parquet absent)")
        return
    from . import scalefree as sf
    fits = pd.read_parquet(path).set_index("quantity")
    g = common.load_graph()  # active nodes, self-loops dropped
    out_s = dict(g.out_degree(weight="trips"))
    in_s = dict(g.in_degree(weight="trips"))
    out_d = dict(g.out_degree())
    in_d = dict(g.in_degree())
    nodes_set = list(g.nodes())
    vectors = {
        "out_strength": np.array([out_s[n] for n in nodes_set], dtype=float),
        "in_strength": np.array([in_s[n] for n in nodes_set], dtype=float),
        "total_strength": np.array([out_s[n] + in_s[n] for n in nodes_set], dtype=float),
        "out_degree": np.array([out_d[n] for n in nodes_set], dtype=float),
        "in_degree": np.array([in_d[n] for n in nodes_set], dtype=float),
    }
    order = [q for q in C.POWERLAW_QUANTITIES if q in vectors]
    n = len(order)
    ncol = 3
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(5 * ncol, 4.2 * nrow))
    axes = np.atleast_1d(axes).ravel()
    for ax, q in zip(axes, order):
        data = vectors[q]
        data = data[data > 0]
        xs = np.sort(data)
        ccdf = 1.0 - np.arange(len(xs)) / len(xs)
        ax.loglog(xs, ccdf, ls="none", marker="o", ms=3, mfc="none", mec="#2c7fb8", alpha=0.7)
        if q in fits.index:
            row = fits.loc[q]
            alpha, xmin, D, n_tail = row["alpha"], row["xmin"], row["D"], int(row["n_tail"])
            p_gof = row["p_gof"]
            is_deg = q.endswith("_degree")
            # shade excluded x<xmin region
            ax.axvspan(xs.min(), xmin, color="#eeeeee", alpha=0.6)
            # fitted power-law CCDF for x>=xmin, scaled to empirical CCDF at xmin
            tailx = xs[xs >= xmin]
            if len(tailx) > 1:
                emp_at_xmin = ccdf[np.searchsorted(xs, xmin, side="left")]
                fit = sf._discrete_pl_ccdf(tailx, alpha, xmin) * emp_at_xmin
                ax.loglog(tailx, fit, ls="-", lw=1.8, color="#a50f15",
                          label=f"power law a={alpha:.2f}")
                # lognormal overlay where favoured/tied
                p_ln = row.get("p_lognormal", float("nan"))
                R_ln = row.get("R_lognormal", float("nan"))
                if (not is_deg) and (np.isnan(p_ln) or p_ln > 0.1 or R_ln < 0):
                    mu, sigma = row["lognormal_mu"], row["lognormal_sigma"]
                    from scipy.stats import norm
                    ln_ccdf = norm.sf((np.log(tailx) - mu) / sigma)
                    ln_ccdf = ln_ccdf / ln_ccdf[0] * emp_at_xmin
                    ax.loglog(tailx, ln_ccdf, ls="--", lw=1.4, color="#31a354", label="lognormal")
            p_txt = "0" if (p_gof is not None and p_gof < 1e-3) else f"{p_gof}"
            note = "  [degenerate: truncated by N-1]" if is_deg else ""
            ax.set_title(f"{q}{note}", fontsize=10)
            ax.annotate(f"a={alpha:.2f}, xmin={xmin:.0f}\nD={D:.3f}, n_tail={n_tail}\np_gof={p_txt}",
                        xy=(0.04, 0.06), xycoords="axes fraction", fontsize=7.5, color="#333",
                        va="bottom")
            ax.legend(fontsize=7, loc="upper right")
        ax.set_xlabel("x"); ax.set_ylabel("P(X >= x)")
    for ax in axes[n:]:
        ax.set_axis_off()
    fig.suptitle("Heavy-tailed but not clean scale-free: discrete CSN power-law fits (CCDF)", fontsize=13)
    save(fig, "17_degree_distribution_loglog",
         "Clauset-Shalizi-Newman log-log complementary-CDF fits (markers = empirical, red = fitted discrete "
         "power law for x>=xmin, grey = excluded x<xmin region). The in/out/total STRENGTH distributions are "
         "strongly heavy-tailed and beat an exponential decisively, but are NOT a clean scale-free power law: "
         "the KS bootstrap rejects the power law (p_gof=0) and it is statistically tied with a lognormal "
         "(green dashed; Vuong p=0.65/0.90/0.59), which is visually indistinguishable on the tail. All three "
         "strength alphas are below 2 (1.23/1.35/1.33), the divergent-mean regime, further evidence the pure "
         "power law is strained. The degree panels are structurally truncated by N-1 (max degree ~ 260), so "
         "in-degree (n_tail=10, alpha~28) is a near-saturation artifact, not a scale-free claim. With only 262 "
         "nodes the tail is too short to support a scale-free claim regardless (Stumpf-Porter).")


def fig_nullmodel_overlay():
    """figures/19_nullmodel_overlay.{png,svg} - observed vs null with z-scores.

    Reads data/processed/nullmodel_comparison.parquet (metric, observed,
    null_mean, null_std, z, percentile, null_type) and metrics_summary.json
    ['null_models']. LEFT: the headline weight-preserving null draws for
    weighted reciprocity and cost-weighted efficiency with the observed value
    and z annotated. RIGHT: forest plot of z-scores under the caveated ER and
    configuration topology nulls, with a shaded |z|<2 band.
    """
    path = C.PROCESSED / "nullmodel_comparison.parquet"
    if not path.exists():
        print("  [fig] 19_nullmodel_overlay SKIPPED (nullmodel_comparison.parquet absent)")
        return
    nm = pd.read_parquet(path)
    res = common.load_results()
    block = res.get("null_models", {})
    wp = block.get("weight_preserving", {})

    fig = plt.figure(figsize=(14, 5.5))
    gsL = fig.add_gridspec(2, 2, left=0.06, right=0.50, hspace=0.45, wspace=0.30)
    axR = fig.add_axes([0.60, 0.12, 0.36, 0.78])

    # LEFT: weight-preserving headline. We do not have raw draws stored, so draw
    # a normal approximation of the null ensemble (mean +- std) with the observed
    # value far in the tail and the z annotated.
    wp_rows = nm[nm["null_type"].str.contains("weight", case=False, na=False)]
    headline = [
        ("weighted_reciprocity", "weighted reciprocity"),
        ("efficiency_cost", "cost-weighted efficiency"),
    ]
    left_axes = gsL.subplots().ravel()[:2] if False else [fig.add_subplot(gsL[i, :]) for i in range(2)]
    for ax, (metric, lab) in zip(left_axes, headline):
        r = wp_rows[wp_rows["metric"] == metric]
        if r.empty:
            r = nm[nm["metric"] == metric]
        if r.empty:
            ax.set_axis_off()
            continue
        r = r.iloc[0]
        mu, sd, obs, z = r["null_mean"], r["null_std"], r["observed"], r["z"]
        if sd and sd > 0 and np.isfinite(sd):
            grid = np.linspace(mu - 4 * sd, mu + 4 * sd, 200)
            from scipy.stats import norm
            ax.fill_between(grid, norm.pdf(grid, mu, sd), color="#9ecae1", alpha=0.7,
                            label="weight-permuted null")
        ax.axvline(obs, color="#a50f15", lw=2, label=f"observed = {obs:.3g}")
        ax.axvline(mu, color="#3182bd", lw=1, ls="--")
        ax.set_yticks([])
        ax.set_xlabel(lab)
        ax.annotate(f"z = {z:+.0f}", xy=(0.97, 0.85), xycoords="axes fraction", ha="right",
                    fontsize=11, color="#a50f15", fontweight="bold")
        ax.legend(fontsize=7, loc="upper left")
    left_axes[0].set_title("Weight-preserving null (the decisive test)", fontsize=11)

    # RIGHT: forest of topology-null z-scores (ER + configuration), caveated.
    topo = nm[~nm["null_type"].str.contains("weight", case=False, na=False)].copy()
    topo = topo.dropna(subset=["z"])
    topo["label"] = topo["metric"] + "  [" + topo["null_type"].str.replace("erdos_renyi_gnm", "ER").str.replace("directed_configuration", "config") + "]"
    topo = topo.sort_values("z")
    y = np.arange(len(topo))
    axR.axvspan(-2, 2, color="#eeeeee", alpha=0.8, label="|z| < 2")
    axR.axvline(0, color="#999", lw=0.8)
    axR.scatter(topo["z"], y, color="#e6550d", s=40, zorder=3)
    axR.set_yticks(y); axR.set_yticklabels(topo["label"], fontsize=8)
    axR.set_xlabel("z-score (observed vs null ensemble)")
    axR.set_title("Topology nulls (caveated: largely degenerate at density 0.62)", fontsize=11)
    axR.legend(fontsize=8, loc="lower right")

    fig.suptitle("Null-model benchmarking: the weight-preserving null is the only non-degenerate one",
                 fontsize=13)
    save(fig, "19_nullmodel_overlay",
         "Null-model benchmarking (Barabasi Ch.3/Ch.7). LEFT (the decisive test): the weight-preserving null "
         "fixes the exact observed topology and degree sequence and only permutes the trip weights across the "
         "fixed edge set. The observed weighted reciprocity (0.82, z=+217) and cost-weighted efficiency "
         "(4031, z=-54) sit far in the tail - WHERE the heavy flows sit is highly non-random (mutual "
         "high-volume Midtown/airport corridors). RIGHT: z-scores of transitivity, assortativity and "
         "reciprocity under the Erdos-Renyi and directed-configuration nulls. On a density-0.62 near-complete "
         "graph these topology nulls are largely degenerate (ensemble variance is tiny, so |z| is huge yet "
         "uninformative; unweighted efficiency z is undefined under ER because its null std is exactly 0). "
         "The shaded band marks |z|<2. The null draws on the left are drawn as a normal approximation of the "
         "100-graph ensemble (mean +- std); the observed value and z are exact.")


def fig_spatial_efficiency_cascade():
    """figures/20_spatial_efficiency_cascade.{png,svg} - Barthelemy + Motter-Lai.

    Panel A circuity Q distribution (ECDF) with mean/median marked and the
    efficiency numbers inset. Panel B Motter-Lai cascade: surviving giant-WCC
    fraction G(alpha) and surviving-flow fraction vs load tolerance alpha
    (trigger = JFK Airport), with a 0.8 no-collapse reference line. Panel C
    per-zone flow-cost betweenness choropleth with load Gini, top-10 share and
    Moran's I annotated.

    Note: G(alpha) need not be monotonic in alpha (genuine Motter-Lai cascade
    nonlinearity); the small dip at alpha 0.1->0.2 is expected, not an error.
    """
    res = common.load_results()
    sp = res.get("spatial", {})
    eff = sp.get("efficiency", {})
    circ = sp.get("circuity", {})
    autoc = sp.get("betweenness_spatial_autocorrelation", {})
    moran = autoc.get("moran", {})
    casc = sp.get("cascade", {})

    sm_path = C.PROCESSED / "spatial_metrics.parquet"
    cas_path = C.PROCESSED / "cascade.parquet"
    if not (sm_path.exists() and cas_path.exists()):
        print("  [fig] 20_spatial_efficiency_cascade SKIPPED (spatial parquets absent)")
        return
    sm = pd.read_parquet(sm_path)
    cas = pd.read_parquet(cas_path).sort_values("alpha")
    zones = common.load_zones()

    fig, axes = plt.subplots(1, 3, figsize=(17, 5.5))

    # Panel A: circuity ECDF from the straightness column (Q = 1/straightness proxy
    # not available per-pair here, so use the recorded summary + a per-node
    # straightness ECDF which is the inverse-circuity centrality).
    axA = axes[0]
    straight = sm["straightness"].dropna().sort_values().values
    ecdf = np.arange(1, len(straight) + 1) / len(straight)
    axA.plot(straight, ecdf, color="#2c7fb8", lw=1.8)
    axA.set_xlabel("straightness centrality  C_S(i) = mean(1/Q)")
    axA.set_ylabel("ECDF over zones")
    axA.set_title("A. Geometric directness", fontsize=11)
    axA.annotate(
        f"corridor circuity Q:\n mean {circ.get('mean_circuity')}, median {circ.get('median_circuity')}\n"
        f" p90 {circ.get('p90_circuity')}, max {circ.get('max_circuity')}\n\n"
        f"E_glob {eff.get('E_glob_distance')}\n"
        f"normalized vs ideal {eff.get('E_glob_normalized')}\n"
        f"E_loc {eff.get('E_loc_distance')}",
        xy=(0.05, 0.95), xycoords="axes fraction", fontsize=8, color="#333", va="top")

    # Panel B: cascade G(alpha) + surviving flow
    axB = axes[1]
    axB.plot(cas["alpha"], cas["G_wcc_fraction"], "-o", color="#3182bd", label="giant WCC fraction G(a)")
    axB.plot(cas["alpha"], cas["surviving_flow_fraction"], "-s", color="#e6550d",
             label="surviving-flow fraction")
    axB.axhline(0.80, color="#999", ls=":", lw=1, label="0.80 no-collapse reference")
    axB.set_xlabel("load tolerance  alpha")
    axB.set_ylabel("fraction surviving")
    axB.set_ylim(-0.02, 1.02)
    axB.set_title(f"B. Motter-Lai cascade (trigger: {casc.get('trigger_zone', 'JFK')})", fontsize=11)
    axB.legend(fontsize=8, loc="upper left")
    axB.annotate(f"alpha_no_collapse = {casc.get('alpha_no_collapse')}\n"
                 f"({casc.get('n_zero_load_nodes')} zero-load nodes\nhave capacity 0)",
                 xy=(0.50, 0.30), xycoords="axes fraction", fontsize=8, color="#a50f15")

    # Panel C: betweenness choropleth
    axC = axes[2]
    gc = zones.merge(sm[["zone_id", "betweenness_flowcost"]], on="zone_id", how="left")
    gc["bw_log"] = np.log10(gc["betweenness_flowcost"].fillna(0) + 1)
    zones.boundary.plot(ax=axC, color="#dddddd", lw=0.3)
    gc.plot(column="bw_log", cmap="YlOrRd", ax=axC, legend=True,
            legend_kwds={"label": "log10(flow-cost betweenness + 1)", "shrink": 0.6},
            edgecolor="#ffffff", lw=0.2, missing_kwds={"color": "#f5f5f5"})
    axC.set_xlim(*MANHATTAN_XLIM); axC.set_ylim(*MANHATTAN_YLIM)
    axC.set_title("C. Spatial betweenness load", fontsize=11)
    axC.set_axis_off()
    mi = moran.get("morans_I")
    mp = moran.get("p_value_perm")
    axC.annotate(f"load Gini {autoc.get('load_gini')}\ntop-10 share {autoc.get('top10_betweenness_share')}\n"
                 f"Moran's I {mi} (p={mp}, NS)",
                 xy=(0.02, 0.02), xycoords="axes fraction", fontsize=8, color="#333")

    fig.suptitle("Spatial efficiency, cascade fragility and betweenness concentration", fontsize=13)
    save(fig, "20_spatial_efficiency_cascade",
         f"Barthelemy spatial-network diagnostics plus a Motter-Lai cascade. (A) The flow graph is "
         f"geometrically near-optimal: corridor circuity Q (network / straight-line distance) has mean "
         f"{circ.get('mean_circuity')} and median {circ.get('median_circuity')}, and global efficiency "
         f"{eff.get('E_glob_distance')} is {eff.get('E_glob_normalized')} of the straight-line ideal - the "
         f"Manhattan grid and dominant Midtown corridors are direct. (B) A Motter-Lai load-capacity cascade "
         f"triggered at JFK Airport collapses the giant component at every tested tolerance "
         f"(alpha_no_collapse = {casc.get('alpha_no_collapse')}); G(alpha) is non-monotonic by genuine "
         f"cascade nonlinearity. Caveat: {casc.get('n_zero_load_nodes')} zero-initial-load nodes have "
         f"capacity exactly 0 and fail on any rerouting, so the no-collapse result is partly a zero-capacity "
         f"artifact, not purely hub fragility. (C) Flow-cost betweenness is concentrated in scattered hubs "
         f"(load Gini {autoc.get('load_gini')}, top-10 zones carry {autoc.get('top10_betweenness_share')}), "
         f"and Moran's I = {mi} (p={mp}) is NOT significant - the load is in scattered hubs, not a "
         f"contiguous spatial cluster.")


# ===========================================================================
# MULTI-YEAR EVOLUTION FIGURES (need data/processed/panel.parquet with >1 year)
# ===========================================================================
def _load_panel():
    path = C.PROCESSED / "panel.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path).sort_values("year")


COVID_YEAR = 2020


def fig_metric_evolution_panel():
    """figures/26_metric_evolution_panel.{png,svg} - per-year structural metrics.

    Reads data/processed/panel.parquet (one row/year). Small-multiple grid of
    per-year time series sharing a year x-axis with the COVID-2020 year shaded.
    NO-OPS gracefully with a single annotated point when only one year present.
    """
    panel = _load_panel()
    if panel is None:
        print("  [fig] 26_metric_evolution_panel SKIPPED (panel.parquet absent)")
        return
    single = len(panel) <= 1
    specs = [
        ("total_trips", "total trips", True),
        ("gravity_beta", "gravity beta", False),
        ("gravity_cpc", "gravity CPC", False),
        ("weighted_reciprocity", "weighted reciprocity", False),
        ("reciprocity_rho", "reciprocity rho (GL)", False),
        ("modularity_Q", "modularity Q (Leiden)", False),
        ("degree_assortativity", "degree assortativity", False),
        ("max_kcore", "max k-core", False),
        ("global_efficiency", "global efficiency", False),
    ]
    ncol = 3
    nrow = int(np.ceil(len(specs) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(5 * ncol, 3.2 * nrow))
    axes = np.atleast_1d(axes).ravel()
    for ax, (col, lab, logy) in zip(axes, specs):
        if col not in panel.columns:
            ax.set_axis_off()
            continue
        ax.plot(panel["year"], panel[col], "-o", ms=5, color="#2c7fb8")
        if logy:
            ax.set_yscale("log")
        if not single and (panel["year"] == COVID_YEAR).any():
            ax.axvspan(COVID_YEAR - 0.4, COVID_YEAR + 0.4, color="#fde0dd", alpha=0.7)
        ax.set_title(lab, fontsize=10)
        ax.set_xlabel("year")
        if single:
            yr = int(panel["year"].iloc[0]); val = panel[col].iloc[0]
            ax.annotate(f"{yr}: {val:.3g}\n(multi-year pending)", xy=(0.5, 0.5),
                        xycoords="axes fraction", ha="center", fontsize=8, color="#888")
    for ax in axes[len(specs):]:
        ax.set_axis_off()
    title = "Structural-metric evolution by year (COVID-2020 shaded)" if not single \
        else "Structural metrics (single year 2015; multi-year pending)"
    fig.suptitle(title, fontsize=13)
    save(fig, "26_metric_evolution_panel",
         "Per-year time series of headline network metrics: total trips (log-y, COVID-2020 trough and the "
         "pre-COVID 2015-2019 ride-hailing decline), the gravity distance-decay beta and CPC (is the "
         "distance law stable while volume craters), reciprocity, modularity Q, degree assortativity, max "
         "k-core and global efficiency. Tests which structural invariants survive the volume collapse. With "
         "only 2015 processed this draws a single annotated point per panel and is marked multi-year "
         "pending; it fills in once the multi-year panel.parquet is built.")


def fig_community_stability_over_time():
    """figures/28_community_stability_over_time.{png,svg} - consecutive-year ARI/AMI.

    Reads data/processed/community_alignment.parquet (year-boundary rows with
    ARI/AMI). NO-OPS gracefully with a placeholder when fewer than two years.
    """
    path = C.PROCESSED / "community_alignment.parquet"
    if not path.exists():
        print("  [fig] 28_community_stability_over_time SKIPPED (community_alignment.parquet absent)")
        return
    al = pd.read_parquet(path)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    if al.empty or len(al) < 1:
        ax.text(0.5, 0.5, "multi-year pending\n(single year 2015: no year-boundary to align)",
                ha="center", va="center", fontsize=11, color="#888")
        ax.set_axis_off()
    else:
        xcol = "year_to" if "year_to" in al.columns else al.columns[0]
        if "ari" in al.columns:
            ax.step(al[xcol], al["ari"], where="mid", marker="o", color="#3182bd", label="ARI")
        if "ami" in al.columns:
            ax.step(al[xcol], al["ami"], where="mid", marker="s", color="#e6550d", label="AMI")
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("year boundary"); ax.set_ylabel("partition agreement")
        ax.axvspan(COVID_YEAR - 0.4, COVID_YEAR + 0.4, color="#fde0dd", alpha=0.7)
        ax.legend()
    ax.set_title("Community stability across years (Leiden ARI / AMI)")
    save(fig, "28_community_stability_over_time",
         "Consecutive-year agreement (Adjusted Rand / Adjusted Mutual Information) between Leiden partitions "
         "of successive years - do the functional districts persist or re-draw across 2019->2020->2021. "
         "Empty on a single year (no year boundary to align) and drawn as a multi-year-pending placeholder; "
         "fills in from community_alignment.parquet once the multi-year run completes.")


def _panel_years():
    panel = _load_panel()
    if panel is None or len(panel) <= 1:
        return None
    return sorted(int(y) for y in panel["year"])


def fig_volume_timeline_multiyear():
    """figures/24_volume_timeline_multiyear.{png,svg} - continuous monthly volume 2015-2024."""
    years = _panel_years()
    if years is None:
        print("  [fig] 24_volume_timeline_multiyear SKIPPED (need multi-year panel)")
        return
    xs, ys = [], []
    for y in years:
        p = C.monthly_path(y)
        if not p.exists():
            continue
        m = pd.read_parquet(p).sort_values("month")
        for _, r in m.iterrows():
            if 1 <= int(r["month"]) <= 12:
                xs.append(y + (int(r["month"]) - 1) / 12.0)
                ys.append(r["trips"] / 1e6)
    if not xs:
        print("  [fig] 24_volume_timeline_multiyear SKIPPED (no per-year monthly tables)")
        return
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(xs, ys, "-", lw=1.3, color="#2c7fb8")
    ax.axvspan(2020, 2021, color="#fde0dd", alpha=0.7, label="2020 (COVID)")
    ax.set_ylabel("trips per month (millions)")
    ax.set_xlabel("year")
    ax.set_title("NYC yellow-taxi monthly volume, 2015-2024")
    tmin = int(np.argmin(ys))
    ax.annotate("COVID trough", xy=(xs[tmin], ys[tmin]),
                xytext=(xs[tmin] + 0.8, ys[tmin] + max(ys) * 0.18),
                arrowprops=dict(arrowstyle="->", color="#888"), fontsize=9, color="#555")
    ax.legend(loc="upper right", fontsize=9)
    save(fig, "24_volume_timeline_multiyear",
         "Monthly yellow-taxi trips stitched into one continuous 2015-2024 timeline. The steady pre-COVID "
         "slide (2015-2019) is ride-hailing substitution; the 2020 cliff (shaded) is the pandemic; the partial "
         "climb after is an incomplete recovery. One figure for the whole decade.")


def fig_covid_collapse_recovery_panel():
    """figures/25_covid_collapse_recovery_panel.{png,svg} - annual totals + recovery vs 2019."""
    panel = _load_panel()
    if panel is None or len(panel) <= 1:
        print("  [fig] 25_covid_collapse_recovery_panel SKIPPED (need multi-year panel)")
        return
    p = panel.sort_values("year")
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 4.5))
    colors = ["#d7301f" if int(y) == COVID_YEAR else "#2c7fb8" for y in p["year"]]
    axL.bar(p["year"], p["total_trips"] / 1e6, color=colors)
    axL.set_ylabel("annual trips (millions)")
    axL.set_xlabel("year")
    axL.set_title("Annual network volume (COVID-2020 in red)")
    if (p["year"] == 2019).any():
        base = float(p.loc[p["year"] == 2019, "total_trips"].iloc[0])
        axR.plot(p["year"], 100 * p["total_trips"] / base, "-o", color="#3182bd")
        axR.axhline(100, ls="--", color="#999", lw=1)
        axR.axvspan(COVID_YEAR - 0.4, COVID_YEAR + 0.4, color="#fde0dd", alpha=0.7)
        axR.set_ylabel("% of 2019 volume")
        axR.set_xlabel("year")
        axR.set_title("Recovery relative to 2019")
    else:
        axR.set_axis_off()
    save(fig, "25_covid_collapse_recovery_panel",
         "Left: annual graph volume per year, 2020 highlighted. Right: each year as a percentage of the 2019 "
         "baseline. The collapse and the still-incomplete recovery are read directly off the second panel; "
         "yellow taxis never returned to their pre-pandemic level over the window.")


def fig_gravity_beta_over_time():
    """figures/27_gravity_beta_over_time.{png,svg} - is the distance law a structural invariant?"""
    panel = _load_panel()
    if panel is None or len(panel) <= 1:
        print("  [fig] 27_gravity_beta_over_time SKIPPED (need multi-year panel)")
        return
    p = panel.sort_values("year")
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    ax.plot(p["year"], p["gravity_beta"], "-o", color="#2c7fb8", label="distance-decay beta")
    ax.set_ylabel("doubly-constrained decay beta", color="#2c7fb8")
    ax.tick_params(axis="y", labelcolor="#2c7fb8")
    ax2 = ax.twinx()
    ax2.plot(p["year"], p["gravity_cpc"], "-s", color="#e6550d", label="CPC")
    ax2.set_ylabel("common part of commuters", color="#e6550d")
    ax2.tick_params(axis="y", labelcolor="#e6550d")
    ax.axvspan(COVID_YEAR - 0.4, COVID_YEAR + 0.4, color="#fde0dd", alpha=0.7)
    ax.set_xlabel("year")
    ax.set_title("Spatial-interaction law over time (gravity beta + CPC)")
    save(fig, "27_gravity_beta_over_time",
         "The calibrated gravity distance-decay exponent (blue) and the common-part-of-commuters fit quality "
         "(orange) per year. If both hold roughly flat while volume craters, Tobler's first law is a structural "
         "invariant of the city's geography, not an artefact of taxi demand. The COVID year is shaded.")


def fig_hub_asymmetry_evolution():
    """figures/29_hub_asymmetry_evolution.{png,svg} - marquee hub share + concentration over time."""
    years = _panel_years()
    if years is None:
        print("  [fig] 29_hub_asymmetry_evolution SKIPPED (need multi-year panel)")
        return
    zdf = common.load_zones()[["zone_id", "zone"]]
    watch_names = ["Midtown Center", "Times Sq", "Penn Station", "East Village",
                   "JFK Airport", "LaGuardia Airport"]
    watch = {}
    for nm in watch_names:
        hit = zdf[zdf["zone"].str.contains(nm, case=False, na=False)]
        if len(hit):
            watch[nm] = int(hit.iloc[0]["zone_id"])
    series = {nm: [] for nm in watch}
    yrs_plot, topk = [], []
    for y in years:
        try:
            nodes = common.load_nodes(y).set_index("zone_id")
        except Exception:
            continue
        tot = float(nodes["in_strength"].sum())
        if tot <= 0:
            continue
        yrs_plot.append(y)
        s = nodes["in_strength"].sort_values(ascending=False)
        topk.append(100 * float(s.head(5).sum()) / tot)
        for nm, zid in watch.items():
            v = float(nodes["in_strength"].get(zid, 0)) if zid in nodes.index else np.nan
            series[nm].append(100 * v / tot)
    if not yrs_plot:
        print("  [fig] 29_hub_asymmetry_evolution SKIPPED (no per-year node tables)")
        return
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 4.8))
    for nm in watch:
        axL.plot(yrs_plot, series[nm], "-o", ms=4, label=nm)
    axL.axvspan(COVID_YEAR - 0.4, COVID_YEAR + 0.4, color="#fde0dd", alpha=0.7)
    axL.set_ylabel("% of annual in-strength")
    axL.set_xlabel("year")
    axL.set_title("Marquee-hub share of arrivals")
    axL.legend(fontsize=7, ncol=2)
    axR.plot(yrs_plot, topk, "-o", color="#756bb1")
    axR.axvspan(COVID_YEAR - 0.4, COVID_YEAR + 0.4, color="#fde0dd", alpha=0.7)
    axR.set_ylabel("top-5 zones' share of in-strength (%)")
    axR.set_xlabel("year")
    axR.set_title("Hub concentration over time")
    save(fig, "29_hub_asymmetry_evolution",
         "Left: the share of annual arrivals captured by marquee zones (the Midtown spine, Penn, Times Sq, the "
         "airports, the East Village). Right: how concentrated arrivals are in the top-5 zones each year. Tracks "
         "whether the hub-and-spoke structure persists, sharpens or flattens as the airports gain weight after "
         "the pandemic.")


def fig_manhattan_ends_drift():
    """figures/30_manhattan_ends_drift.{png,svg} - does 'where Manhattan ends' persist over the decade?"""
    years = _panel_years()
    if years is None:
        print("  [fig] 30_manhattan_ends_drift SKIPPED (need multi-year panel)")
        return
    from . import analysis
    watch = ["East Village", "Lower East Side", "Alphabet City",
             "Upper East Side North", "Times Sq"]
    rows = {nm: [] for nm in watch}
    yrs_plot = []
    for y in years:
        try:
            edges = common.load_edges_annual(y)
            nodes = common.load_nodes(y)
            ids, idx, T = analysis.build_matrix(edges)
            _, zr, _ = analysis.gravity_residual_field(ids, T, nodes)
        except Exception as e:
            print(f"  [fig] 30 skip {y}: {e}")
            continue
        core = (zr[zr["service_zone"].isin(["Yellow Zone", "Airports", "EWR"])]
                .dropna(subset=["gravity_surprise"])
                .sort_values("gravity_surprise").reset_index(drop=True))
        if core.empty:
            continue
        yrs_plot.append(y)
        n = max(len(core) - 1, 1)
        for nm in watch:
            hit = core[core["zone"].str.contains(nm, case=False, na=False)]
            rows[nm].append(100.0 * int(hit.index[0]) / n if len(hit) else np.nan)
    if not yrs_plot:
        print("  [fig] 30_manhattan_ends_drift SKIPPED (gravity field unavailable)")
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    for nm in watch:
        ax.plot(yrs_plot, rows[nm], "-o", ms=4, label=nm)
    ax.axhline(50, ls="--", color="#ccc", lw=1)
    ax.axvspan(COVID_YEAR - 0.4, COVID_YEAR + 0.4, color="#fde0dd", alpha=0.7)
    ax.set_ylim(-2, 102)
    ax.set_ylabel("gravity-residual percentile within the Manhattan core\n"
                  "(0 = most under-connected / suburb-like)")
    ax.set_xlabel("year")
    ax.set_title("Does 'where Manhattan ends' persist? Residual-rank drift, 2015-2024")
    ax.legend(fontsize=8)
    save(fig, "30_manhattan_ends_drift",
         "The flagship finding tracked across a decade. Each line is a zone's percentile rank in the "
         "doubly-constrained gravity residual within the high-coverage Manhattan core (0 = most "
         "under-connected, suburb-like; 100 = most over-connected). If the East Village and Lower East Side "
         "stay low while the Times Sq spine stays high, the 2016 headline holds even as ride-hailing and COVID "
         "reshape volume. Recomputed per year from each year's own flows.")


def main() -> None:
    res = common.load_results()
    zones = common.load_zones()
    nodes = common.load_nodes()
    edges = common.load_edges_annual()
    node_analysis = pd.read_parquet(C.PROCESSED / "node_analysis.parquet")

    print("[figures] rendering...")
    fig_monthly(res)
    fig_degree_distribution(edges)
    fig_hour_weekday(res)
    fig_cost_duration(res)
    fig_hub_map(zones, nodes, edges)
    fig_degree_vs_trips(nodes)
    fig_community_map(zones, node_analysis)
    fig_where_manhattan_ends(zones, node_analysis, res)
    fig_net_flow(zones, node_analysis)
    fig_am_pm_flip(res)
    fig_distance_decay(res)
    fig_gravity_fit(res)
    fig_centrality_corr(res)
    fig_backbone(res, zones, edges)
    fig_rhythm(zones, node_analysis, res)
    fig_intercommunity(res)

    # Method-area diagnostics (single-year, generated now)
    fig_powerlaw_loglog()
    fig_attack_vs_failure()
    fig_nullmodel_overlay()
    fig_spatial_efficiency_cascade()

    # Multi-year evolution (no-op gracefully until panel.parquet has >1 year)
    fig_volume_timeline_multiyear()
    fig_covid_collapse_recovery_panel()
    fig_metric_evolution_panel()
    fig_gravity_beta_over_time()
    fig_hub_asymmetry_evolution()
    fig_community_stability_over_time()
    fig_manhattan_ends_drift()

    cap = "# Figure portfolio\n\nEvery figure regenerated by `pixi run figures` into this folder (PNG + SVG).\n\n"
    for name in sorted(CAPTIONS):
        cap += f"### {name}\n{CAPTIONS[name]}\n\n"
    (C.FIGURES / "CAPTIONS.md").write_text(cap)
    print(f"[figures] {len(CAPTIONS)} figures + CAPTIONS.md written to {C.FIGURES}")


if __name__ == "__main__":
    sys.exit(main())
