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
    g = zones.merge(node_analysis[["zone_id", "gravity_surprise"]], on="zone_id", how="left")
    core = g.dropna(subset=["gravity_surprise"])
    vmax = np.nanpercentile(np.abs(core["gravity_surprise"]), 98)
    fig, ax = plt.subplots(figsize=(9, 10))
    zones.boundary.plot(ax=ax, color="#dddddd", lw=0.3)
    core.plot(column="gravity_surprise", cmap="RdBu_r", ax=ax, legend=True, vmin=-vmax, vmax=vmax,
              edgecolor="#ffffff", lw=0.3,
              legend_kwds={"label": "gravity surprise (blue = under-connected, red = over-connected)",
                           "shrink": 0.6})
    ax.set_xlim(*MANHATTAN_XLIM); ax.set_ylim(*MANHATTAN_YLIM)
    ax.set_title("Where Manhattan ends: connectivity residual vs a\ndoubly-constrained gravity model")
    ax.set_axis_off()
    save(fig, "08_where_manhattan_ends",
         "Flagship figure. Per-zone mean deviance residual from a doubly-constrained gravity model "
         "(controls for each zone's own volume and distance). Blue zones (East Village/Alphabet City, "
         "Upper East/West Side) are under-connected given their location - functionally peripheral despite "
         "central geography. Red (Times Sq/Midtown) are over-connected. Scoped to the high-coverage core.")


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

    cap = "# Figure portfolio\n\nEvery figure regenerated by `pixi run figures` into this folder (PNG + SVG).\n\n"
    for name in sorted(CAPTIONS):
        cap += f"### {name}\n{CAPTIONS[name]}\n\n"
    (C.FIGURES / "CAPTIONS.md").write_text(cap)
    print(f"[figures] {len(CAPTIONS)} figures + CAPTIONS.md written to {C.FIGURES}")


if __name__ == "__main__":
    sys.exit(main())
