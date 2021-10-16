"""Spatial-network diagnostics: efficiency, circuity, betweenness clustering, cascades.

Reference frame: Barthelemy "Spatial Networks" (efficiency vs the ideal spatial
graph, route factor / detour, spatial distribution of betweenness), Latora-Marchiori
global/local efficiency, Moran's I spatial autocorrelation, and the Motter-Lai
load-capacity cascade (with the Peterson-Rajan NYC injector/absorber framing via
net_flow_index).

The 2015 graph is a directed, weighted, SPATIAL graph: taxi zones are nodes,
annual trip counts are edge weights, and zone centroids (cx_ft, cy_ft in EPSG:2263
US feet) give Euclidean distances in miles. Self-loops (intra-zone trips) are
excluded from every metric here (build_digraph drops them by default). The graph is
NOT sparse (~262 nodes, density ~0.62), so two facts shape the analysis:

  - Geometric efficiency is high and the unweighted topology is near-degenerate;
    the honest, discriminating views are WEIGHT/DISTANCE-aware, so we report a
    distance-weighted graph (cost = Euclidean miles) for the geometric efficiency/
    circuity story and a flow-cost graph (cost = 1/trips) for the betweenness/
    bottleneck/cascade story.
  - Betweenness on a dense graph is dominated by a few hubs; most nodes carry ~0
    load (capacity ~0), so the Motter-Lai cascade is hub-driven. We report the load
    Gini up front so the cascade is interpretable.

Outputs:
  data/processed/spatial_metrics.parquet  (per-zone betweenness, straightness, load,
                                            capacity ladder, net_flow_index)
  data/processed/cascade.parquet          (the Motter-Lai G(alpha) curve)
  common.record('spatial', {...})         (E_glob, normalized efficiency, mean
                                            circuity, Moran's I + p, cascade curve)

main() runs the module end to end and prints headline numbers, mirroring analysis.py.
"""
from __future__ import annotations

import sys
import warnings

import networkx as nx
import numpy as np
import pandas as pd

from . import common, config as C

warnings.filterwarnings("ignore")
rng = np.random.default_rng(C.SEED)

FT_PER_MILE = 5280.0


# ---------------------------------------------------------------------------
# Graph builders: distance-weighted and flow-cost views
# ---------------------------------------------------------------------------
def _attach_geometry(g: nx.DiGraph) -> nx.DiGraph:
    """Add edge attrs ``dist`` (Euclidean miles between centroids) and ``cost``
    (1/trips, the flow-resistance weight) to a digraph that already carries
    cx_ft/cy_ft node attributes. Edges whose endpoints lack geometry get dist=NaN.
    """
    for u, v, d in g.edges(data=True):
        ux, uy = g.nodes[u].get("cx_ft"), g.nodes[u].get("cy_ft")
        vx, vy = g.nodes[v].get("cx_ft"), g.nodes[v].get("cy_ft")
        if None in (ux, uy, vx, vy) or any(pd.isna(z) for z in (ux, uy, vx, vy)):
            d["dist"] = np.nan
        else:
            d["dist"] = float(np.hypot(ux - vx, uy - vy)) / FT_PER_MILE
        trips = d.get("trips", 0)
        d["cost"] = 1.0 / trips if trips > 0 else np.inf
    return g


def _geo_subgraph(g: nx.DiGraph) -> nx.DiGraph:
    """Subgraph induced on nodes that have valid centroid geometry. Distance-based
    methods need finite coordinates, so the 3 flow-only zones without centroids are
    dropped here (reported in the results)."""
    keep = [n for n in g.nodes
            if g.nodes[n].get("cx_ft") is not None
            and not pd.isna(g.nodes[n].get("cx_ft"))]
    return g.subgraph(keep).copy()


# ---------------------------------------------------------------------------
# Latora-Marchiori efficiency (distance-weighted) + Barthelemy normalization
# ---------------------------------------------------------------------------
def _euclid_matrix(nodes_xy: dict, ids: list) -> np.ndarray:
    xy = np.array([nodes_xy[z] for z in ids], dtype=float)
    dx = xy[:, 0][:, None] - xy[:, 0][None, :]
    dy = xy[:, 1][:, None] - xy[:, 1][None, :]
    return np.hypot(dx, dy) / FT_PER_MILE


def global_efficiency_weighted(g: nx.DiGraph, weight: str) -> float:
    """E_glob = mean over ordered pairs of 1/d_ij, d_ij = weighted shortest path.
    Unreachable pairs contribute 0. Directed graph -> ordered pairs (i != j)."""
    n = g.number_of_nodes()
    if n < 2:
        return 0.0
    total = 0.0
    sp = dict(nx.all_pairs_dijkstra_path_length(g, weight=weight))
    for i, dmap in sp.items():
        for j, d in dmap.items():
            if i != j and d > 0:
                total += 1.0 / d
    return total / (n * (n - 1))


def local_efficiency_weighted(g: nx.DiGraph, weight: str) -> float:
    """E_loc = mean over nodes of the global efficiency of the subgraph induced on
    each node's successors+predecessors (the directed neighborhood)."""
    n = g.number_of_nodes()
    if n == 0:
        return 0.0
    total = 0.0
    for node in g.nodes:
        neigh = set(g.successors(node)) | set(g.predecessors(node))
        if len(neigh) < 2:
            continue
        sub = g.subgraph(neigh)
        total += global_efficiency_weighted(sub, weight)
    return total / n


def efficiency_block(gd: nx.DiGraph) -> dict:
    """Latora-Marchiori global/local efficiency on the distance-weighted graph,
    plus Barthelemy's normalized (ideal) efficiency.

    The ideal spatial graph is the COMPLETE graph on the same node positions with
    each edge equal to the straight-line distance: E_ideal = mean(1/d_eucl). The
    normalized efficiency E_glob / E_ideal lies in (0, 1]; 1 means every pair is
    reached along a path as short as the straight line.
    """
    ids = list(gd.nodes)
    nodes_xy = {z: (gd.nodes[z]["cx_ft"], gd.nodes[z]["cy_ft"]) for z in ids}
    De = _euclid_matrix(nodes_xy, ids)

    e_glob = global_efficiency_weighted(gd, "dist")
    e_loc = local_efficiency_weighted(gd, "dist")

    # ideal: complete spatial graph, edge length = straight-line distance
    iu = ~np.eye(len(ids), dtype=bool)
    e_ideal = np.mean(1.0 / De[iu])

    # flow-cost efficiency (1/trips weight): a bottleneck/resistance view, unitless
    e_glob_cost = global_efficiency_weighted(gd, "cost")

    return {
        "n_nodes_geo": len(ids),
        "E_glob_distance": round(float(e_glob), 5),
        "E_glob_ideal_complete_spatial": round(float(e_ideal), 5),
        "E_glob_normalized": round(float(e_glob / e_ideal), 4),
        "E_loc_distance": round(float(e_loc), 5),
        "E_glob_flowcost": round(float(e_glob_cost), 6),
        "note": "distance weight = Euclidean miles between EPSG:2263 centroids; "
                "ideal = complete graph with straight-line edges (Barthelemy); "
                "flow-cost weight = 1/trips.",
    }


# ---------------------------------------------------------------------------
# Circuity / detour (Barthelemy route factor) + straightness centrality
# ---------------------------------------------------------------------------
def circuity_block(gd: nx.DiGraph) -> tuple[dict, pd.DataFrame]:
    """For connected ordered pairs, Q_ij = network shortest-path distance /
    straight-line distance (>= 1). Reports the distribution and the most
    circuitous corridors, plus per-node straightness centrality
    C_S(i) = mean_j d_eucl_ij / d_net_ij (in (0,1], 1 = all paths straight).
    """
    ids = list(gd.nodes)
    pos = {z: i for i, z in enumerate(ids)}
    nodes_xy = {z: (gd.nodes[z]["cx_ft"], gd.nodes[z]["cy_ft"]) for z in ids}
    De = _euclid_matrix(nodes_xy, ids)

    sp = dict(nx.all_pairs_dijkstra_path_length(gd, weight="dist"))
    n = len(ids)
    Q = np.full((n, n), np.nan)
    for i, dmap in sp.items():
        ii = pos[i]
        for j, d_net in dmap.items():
            if i == j:
                continue
            jj = pos[j]
            d_eucl = De[ii, jj]
            if d_eucl > 0 and d_net > 0:
                Q[ii, jj] = d_net / d_eucl

    finite = Q[np.isfinite(Q)]
    # per-node straightness: mean of (d_eucl / d_net) = 1/Q over reachable targets
    with np.errstate(divide="ignore", invalid="ignore"):
        straight = np.nanmean(1.0 / Q, axis=1)

    nd = common.load_nodes().set_index("zone_id")

    # most circuitous corridors (largest Q), with a meaningful distance floor so a
    # 0.1-mile adjacent pair does not dominate on a ratio basis
    floor_mi = 0.5
    rows = []
    for i in range(n):
        for j in range(n):
            if np.isfinite(Q[i, j]) and De[i, j] >= floor_mi:
                rows.append((ids[i], ids[j], Q[i, j], De[i, j],
                             De[i, j] * Q[i, j]))
    cdf = pd.DataFrame(rows, columns=["o", "d", "circuity", "dist_mi", "net_mi"])
    cdf = cdf.sort_values("circuity", ascending=False)
    top = []
    for _, r in cdf.head(8).iterrows():
        oz = nd.loc[r["o"], "zone"] if r["o"] in nd.index else "?"
        dz = nd.loc[r["d"], "zone"] if r["d"] in nd.index else "?"
        top.append({"o": oz, "d": dz, "circuity": round(float(r["circuity"]), 3),
                    "straight_mi": round(float(r["dist_mi"]), 2)})

    straight_df = pd.DataFrame({"zone_id": ids, "straightness": straight})

    block = {
        "n_pairs": int(finite.size),
        "mean_circuity": round(float(np.mean(finite)), 4),
        "median_circuity": round(float(np.median(finite)), 4),
        "p90_circuity": round(float(np.percentile(finite, 90)), 4),
        "max_circuity": round(float(np.max(finite)), 3),
        "mean_straightness_centrality": round(float(np.nanmean(straight)), 4),
        "most_circuitous_corridors": top,
        "note": "Q = network shortest-path distance / straight-line distance (>=1); "
                "corridors filtered to straight-line >= 0.5 mi so tiny adjacent "
                "pairs do not dominate the ratio.",
    }
    return block, straight_df


# ---------------------------------------------------------------------------
# Spatial autocorrelation of betweenness (Moran's I, k-NN adjacency)
# ---------------------------------------------------------------------------
def _gini(x: np.ndarray) -> float:
    x = np.sort(np.asarray(x, dtype=float))
    n = x.size
    if n == 0 or x.sum() == 0:
        return 0.0
    idx = np.arange(1, n + 1)
    return float((2 * (idx * x).sum() - (n + 1) * x.sum()) / (n * x.sum()))


def morans_i(values: np.ndarray, coords: np.ndarray, k: int = 6,
             n_perm: int = 999) -> dict:
    """Moran's I with a row-standardized k-nearest-neighbour spatial weight matrix.

    I = (n / S0) * (sum_ij w_ij z_i z_j) / (sum_i z_i^2), z = value - mean.
    Significance via a permutation null (shuffle the values over fixed positions),
    p = (#{I_perm >= I_obs} + 1) / (n_perm + 1), two-sided reported via |I|.
    """
    n = len(values)
    z = values - values.mean()
    # k-NN adjacency from Euclidean centroid distances
    dx = coords[:, 0][:, None] - coords[:, 0][None, :]
    dy = coords[:, 1][:, None] - coords[:, 1][None, :]
    D = np.hypot(dx, dy)
    np.fill_diagonal(D, np.inf)
    W = np.zeros((n, n))
    for i in range(n):
        nn = np.argsort(D[i])[:k]
        W[i, nn] = 1.0
    # row-standardize
    rs = W.sum(1, keepdims=True)
    rs[rs == 0] = 1.0
    W = W / rs

    def I_of(zv):
        num = float(zv @ W @ zv)
        den = float((zv * zv).sum())
        return (n / W.sum()) * (num / den) if den > 0 else 0.0

    I_obs = I_of(z)
    expected = -1.0 / (n - 1)
    perm = np.empty(n_perm)
    for b in range(n_perm):
        zp = rng.permutation(z)
        perm[b] = I_of(zp)
    # two-sided permutation p relative to the expected value
    ge = np.sum(np.abs(perm - expected) >= abs(I_obs - expected))
    p = (ge + 1) / (n_perm + 1)
    return {
        "morans_I": round(float(I_obs), 4),
        "expected_I": round(float(expected), 5),
        "p_value_perm": round(float(p), 4),
        "n_permutations": n_perm,
        "k_neighbours": k,
    }


# ---------------------------------------------------------------------------
# Motter-Lai cascade on the flow-cost graph
# ---------------------------------------------------------------------------
def _betweenness_load(g: nx.DiGraph) -> dict:
    """Unnormalized flow-cost betweenness = load (number of shortest paths through
    a node). weight='cost' (= 1/trips) so paths follow heavy flow."""
    return nx.betweenness_centrality(g, weight="cost", normalized=False)


def cascade(gd: nx.DiGraph, tolerances: list) -> tuple[dict, pd.DataFrame]:
    """Motter-Lai load-capacity cascade (synchronous update).

      load_i(0)  = unnormalized flow-cost betweenness on the full graph
      capacity_i = (1 + alpha) * load_i(0)            (FIXED for the whole run)
      trigger    = remove the single highest-load node
      step       = recompute load on the surviving subgraph; any node whose
                   current load exceeds its fixed capacity FAILS; remove all such
                   nodes at once; repeat until a pass produces no new failures.
      outcome    = surviving largest-WCC fraction G(alpha), cascade size, and the
                   surviving FLOW fraction.

    N=262 keeps recomputed betweenness fast (<1s/step), so no k-sampling is needed;
    the whole sweep runs in a few seconds. Cascades are bounded to N steps as a
    guard. We label each FAILED node as a flow-injector or flow-absorber by the
    sign of its net_flow_index (Peterson-Rajan congestion framing).
    """
    N0 = gd.number_of_nodes()
    load0 = _betweenness_load(gd)

    # total flow on edges (for surviving-flow fraction)
    total_flow = sum(d["trips"] for _, _, d in gd.edges(data=True))
    nfi = common.load_nodes().set_index("zone_id")["net_flow_index"].to_dict()

    trigger = max(load0, key=load0.get)
    nd = common.load_nodes().set_index("zone_id")
    trigger_zone = nd.loc[trigger, "zone"] if trigger in nd.index else "?"

    rows = []
    detail = {}
    for alpha in tolerances:
        capacity = {node: (1.0 + alpha) * load0[node] for node in gd.nodes}
        H = gd.copy()
        H.remove_node(trigger)
        failed = {trigger}
        steps = 0
        while steps < N0:
            steps += 1
            if H.number_of_nodes() == 0:
                break
            load = _betweenness_load(H)
            newly = [n for n in H.nodes if load[n] > capacity[n]]
            if not newly:
                break
            H.remove_nodes_from(newly)
            failed.update(newly)
        # outcome on survivors
        if H.number_of_nodes() > 0:
            wccs = list(nx.weakly_connected_components(H))
            g_frac = max(len(c) for c in wccs) / N0
        else:
            g_frac = 0.0
        surv_flow = sum(d["trips"] for _, _, d in H.edges(data=True))
        flow_frac = surv_flow / total_flow if total_flow else 0.0
        # injector vs absorber among the failed nodes (net_flow_index sign)
        inj = sum(1 for z in failed if nfi.get(z, 0) > 0)
        absb = sum(1 for z in failed if nfi.get(z, 0) < 0)
        rows.append({
            "alpha": alpha,
            "G_wcc_fraction": round(float(g_frac), 4),
            "cascade_size_nodes": int(len(failed)),
            "cascade_size_fraction": round(len(failed) / N0, 4),
            "surviving_flow_fraction": round(float(flow_frac), 4),
            "n_failed_injectors": int(inj),
            "n_failed_absorbers": int(absb),
            "cascade_steps": int(steps),
        })

    cdf = pd.DataFrame(rows)
    # tolerance at which cascades stop being catastrophic: smallest alpha with
    # surviving giant WCC >= 0.8 of the network (a conventional "no collapse" line)
    safe = cdf[cdf["G_wcc_fraction"] >= 0.8]
    alpha_safe = float(safe["alpha"].min()) if len(safe) else None

    block = {
        "trigger_node": int(trigger),
        "trigger_zone": str(trigger_zone),
        "trigger_load_rank": "highest flow-cost betweenness",
        "load_gini": round(_gini(np.array(list(load0.values()))), 4),
        "n_zero_load_nodes": int(sum(1 for v in load0.values() if v == 0)),
        "tolerances": list(tolerances),
        "G_alpha_curve": [
            {"alpha": r["alpha"], "G": r["G_wcc_fraction"],
             "cascade_fraction": r["cascade_size_fraction"],
             "surviving_flow_fraction": r["surviving_flow_fraction"]}
            for r in rows],
        "alpha_no_collapse": alpha_safe,
        "no_collapse_criterion": "smallest alpha with surviving giant WCC >= 0.80 N0",
        "note": "synchronous update; capacity fixed at (1+alpha)*load0; load = "
                "unnormalized flow-cost betweenness recomputed each step. Most nodes "
                "carry ~0 load (see load_gini / n_zero_load_nodes) so the cascade is "
                "hub-driven. Failed nodes labelled injector/absorber by net_flow_index "
                "sign (Peterson-Rajan). CAVEAT: the n_zero_load_nodes zero-initial-load "
                "nodes have capacity exactly (1+alpha)*0 = 0, so the moment any flow "
                "reroutes through one post-trigger it overloads and fails on any alpha; "
                "the 'alpha_no_collapse=None' conclusion is therefore partly a "
                "zero-capacity artifact of peripheral nodes, not purely hub fragility.",
    }
    return block, cdf


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> None:
    edges = common.load_edges_annual()
    zones = common.load_zones()
    g = common.attach_zone_attrs(common.build_digraph(edges), zones)
    g = _attach_geometry(g)
    gd = _geo_subgraph(g)
    n_dropped = g.number_of_nodes() - gd.number_of_nodes()
    print(f"[spatial] active network: {g.number_of_nodes()} nodes, "
          f"{g.number_of_edges():,} directed edges "
          f"({gd.number_of_nodes()} with geometry; {n_dropped} flow-only zones dropped "
          f"from distance metrics)")

    print("[spatial] A. Latora-Marchiori efficiency (distance + flow-cost) + Barthelemy normalization...")
    eff = efficiency_block(gd)

    print("[spatial] B. circuity / detour + straightness centrality...")
    circ, straight_df = circuity_block(gd)

    print("[spatial] C. flow-cost betweenness + Moran's I spatial autocorrelation...")
    load0 = _betweenness_load(gd)
    ids = list(gd.nodes)
    betw = np.array([load0[z] for z in ids])
    coords = np.array([[gd.nodes[z]["cx_ft"], gd.nodes[z]["cy_ft"]] for z in ids])
    moran = morans_i(betw, coords, k=6, n_perm=999)
    betw_gini = _gini(betw)
    # share of betweenness carried by the top-10 zones
    top10_share = float(np.sort(betw)[::-1][:10].sum() / betw.sum()) if betw.sum() else 0.0

    print("[spatial] D. Motter-Lai cascade sweep...")
    casc, cdf = cascade(gd, C.CASCADE_TOLERANCES)

    # ---- assemble per-zone spatial table ----
    nd = common.load_nodes().set_index("zone_id")
    spatial_df = pd.DataFrame({"zone_id": ids})
    spatial_df["betweenness_flowcost"] = betw
    spatial_df["load0"] = betw
    spatial_df = spatial_df.merge(straight_df, on="zone_id", how="left")
    spatial_df["net_flow_index"] = spatial_df["zone_id"].map(
        nd["net_flow_index"].to_dict())
    spatial_df["zone"] = spatial_df["zone_id"].map(nd["zone"].to_dict())
    spatial_df["borough"] = spatial_df["zone_id"].map(nd["borough"].to_dict())
    spatial_df["service_zone"] = spatial_df["zone_id"].map(nd["service_zone"].to_dict())
    for alpha in C.CASCADE_TOLERANCES:
        spatial_df[f"capacity_a{alpha}"] = spatial_df["load0"] * (1.0 + alpha)
    spatial_df.to_parquet(C.PROCESSED / "spatial_metrics.parquet", index=False)
    cdf.to_parquet(C.PROCESSED / "cascade.parquet", index=False)

    # ---- record ----
    betweenness_block = {
        "load_gini": round(float(betw_gini), 4),
        "top10_betweenness_share": round(float(top10_share), 4),
        "moran": moran,
    }
    common.record("spatial", {
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "n_nodes_without_geometry": int(n_dropped),
        "efficiency": eff,
        "circuity": circ,
        "betweenness_spatial_autocorrelation": betweenness_block,
        "cascade": casc,
    })

    # ---- console highlights ----
    print(f"[spatial] E_glob (distance) = {eff['E_glob_distance']}, "
          f"normalized vs ideal = {eff['E_glob_normalized']}, "
          f"E_loc = {eff['E_loc_distance']}")
    print(f"[spatial] circuity: mean {circ['mean_circuity']}, median {circ['median_circuity']}, "
          f"p90 {circ['p90_circuity']}; mean straightness {circ['mean_straightness_centrality']}")
    print(f"[spatial] betweenness Gini = {betw_gini:.3f} "
          f"(top-10 zones carry {top10_share*100:.1f}% of load); "
          f"Moran's I = {moran['morans_I']} (p={moran['p_value_perm']})")
    print(f"[spatial] cascade trigger = {casc['trigger_zone']}; "
          f"no-collapse tolerance alpha >= {casc['alpha_no_collapse']}")
    print("[spatial] cascade G(alpha):")
    for r in casc["G_alpha_curve"]:
        print(f"    alpha={r['alpha']:<5} G={r['G']:.3f}  cascade={r['cascade_fraction']:.3f}  "
              f"surviving_flow={r['surviving_flow_fraction']:.3f}")
    print("[spatial] most circuitous corridors:")
    for r in circ["most_circuitous_corridors"][:5]:
        print(f"    {r['o']:28s} -> {r['d']:28s}  Q={r['circuity']:.2f}  ({r['straight_mi']} mi straight)")


if __name__ == "__main__":
    sys.exit(main())
