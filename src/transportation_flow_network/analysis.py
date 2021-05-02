"""Stage 7: research-grade network-science layer.

Substantially exceeds the 2016 baseline (degree + one stochastic community
pass). Implemented with the installed stack (networkx, igraph, python-louvain,
scipy, scikit-learn, statsmodels); deliberately avoids fragile deps
(graph-tool, NEMtropy, cpnet, pysal) in favour of robust equivalents.

Sections:
  A. Directed/weighted centralities + rank-correlation matrix
  B. Structure: reciprocity, flow imbalance, assortativity, k-core, rich-club
  C. Spatial interaction: distance-decay exponent + doubly-constrained gravity
     residual field (the flagship "where Manhattan ends" reframing), coverage-scoped
  D. Disparity-filter backbone vs the arbitrary >500 threshold
  E. Rigorous communities: multi-algorithm, resolution sweep, seed stability,
     vs administrative geography, inter-community flow, modularity significance
  F. Temporal networks: per-daypart hubs, AM/PM net-flow flip, rhythm clusters

Writes processed/node_analysis.parquet + processed/edges_analysis.parquet and
records every measured number to the results store.
"""
from __future__ import annotations

import itertools
import random as pyrandom
import sys
import warnings

import community as community_louvain
import igraph as ig
import networkx as nx
import numpy as np
import pandas as pd
from scipy import optimize, stats
from sklearn.cluster import KMeans
from sklearn.metrics import (adjusted_mutual_info_score, adjusted_rand_score)

from . import common, config as C

warnings.filterwarnings("ignore")
rng = np.random.default_rng(C.SEED)

FT_PER_MILE = 5280.0


# ---------------------------------------------------------------------------
# Shared structures
# ---------------------------------------------------------------------------
def build_matrix(edges: pd.DataFrame):
    """Dense OD matrix over active nodes (self-loops dropped)."""
    no_self = edges[edges["o"] != edges["d"]]
    ids = sorted(set(no_self["o"]) | set(no_self["d"]))
    idx = {z: i for i, z in enumerate(ids)}
    n = len(ids)
    T = np.zeros((n, n))
    oi = no_self["o"].map(idx).to_numpy()
    di = no_self["d"].map(idx).to_numpy()
    T[oi, di] = no_self["trips"].to_numpy()
    return ids, idx, T


def undirected_igraph(ids, T):
    """Undirected weighted projection (reciprocal flows summed) as igraph."""
    U = T + T.T
    iu = np.triu_indices_from(U, k=1)
    w = U[iu]
    keep = w > 0
    edges = list(zip(iu[0][keep].tolist(), iu[1][keep].tolist()))
    g = ig.Graph(n=len(ids), edges=edges, directed=False)
    g.es["weight"] = w[keep].tolist()
    return g


def membership_array(part: dict, ids) -> np.ndarray:
    return np.array([part[z] for z in ids])


# ---------------------------------------------------------------------------
# A. Centralities
# ---------------------------------------------------------------------------
def centralities(ids, T, g: nx.DiGraph) -> pd.DataFrame:
    n = len(ids)
    out_s = T.sum(1)
    in_s = T.sum(0)

    pr = nx.pagerank(g, weight="trips", alpha=0.85)
    pagerank = np.array([pr[z] for z in ids])

    # Weighted HITS via SVD of the OD matrix: hubs = left, authorities = right
    U, S, Vt = np.linalg.svd(T)
    hub = np.abs(U[:, 0])
    auth = np.abs(Vt[0, :])

    # Distance-weighted betweenness (shorter == stronger flow)
    gd = g.copy()
    for u, v, d in gd.edges(data=True):
        d["dist"] = 1.0 / d["trips"]
    bet = nx.betweenness_centrality(gd, weight="dist", normalized=True)
    betw = np.array([bet[z] for z in ids])

    try:
        ev = nx.eigenvector_centrality_numpy(g, weight="trips")
        eig = np.array([ev[z] for z in ids])
    except Exception:
        eig = np.full(n, np.nan)

    df = pd.DataFrame({
        "zone_id": ids, "out_strength": out_s, "in_strength": in_s,
        "pagerank": pagerank, "hits_hub": hub, "hits_authority": auth,
        "betweenness": betw, "eigenvector": eig,
    })
    return df


def rank_correlation(df: pd.DataFrame) -> dict:
    cols = ["out_strength", "in_strength", "pagerank", "hits_hub",
            "hits_authority", "betweenness", "eigenvector"]
    corr = df[cols].corr(method="spearman").round(3)
    return {"columns": cols, "spearman": corr.values.tolist()}


# ---------------------------------------------------------------------------
# B. Structure
# ---------------------------------------------------------------------------
def structure(ids, T, g: nx.DiGraph) -> dict:
    n = len(ids)
    W = T.sum()
    # weighted reciprocity: share of flow with a return leg
    recip_w = np.minimum(T, T.T).sum() / W
    # topological reciprocity (Garlaschelli-Loffredo rho)
    A = (T > 0).astype(int)
    L = A.sum()
    r = (A * A.T).sum() / L
    abar = L / (n * (n - 1))
    gl_rho = (r - abar) / (1 - abar)
    # per-edge flow imbalance for reciprocated pairs
    iu = np.triu_indices_from(T, k=1)
    a, b = T[iu], T.T[iu]
    both = (a > 0) & (b > 0)
    imbalance = np.abs(a[both] - b[both]) / (a[both] + b[both])

    # assortativity (directed, unweighted topology)
    assort = nx.degree_assortativity_coefficient(g)

    # k-core on undirected simple projection
    gu = nx.Graph(g.to_undirected())
    gu.remove_edges_from(nx.selfloop_edges(gu))
    core = nx.core_number(gu)
    coreness = np.array([core[z] for z in ids])

    return {
        "weighted_reciprocity": round(float(recip_w), 3),
        "garlaschelli_loffredo_rho": round(float(gl_rho), 3),
        "mean_flow_imbalance": round(float(imbalance.mean()), 3),
        "median_flow_imbalance": round(float(np.median(imbalance)), 3),
        "degree_assortativity": round(float(assort), 3),
        "max_kcore": int(coreness.max()),
        "_coreness": coreness,
    }


def weighted_rich_club(ids, T, n_null: int = 50) -> dict:
    """Opsahl weighted rich-club, normalised by a strength-preserving null.

    The null reshuffles edge weights on the fixed topology AND recomputes node
    strengths (hence rich-set membership) from the permuted weights each time, so
    the rich set is not frozen to the observed high-strength nodes.
    """
    U = T + T.T
    n = U.shape[0]
    iu = np.triu_indices_from(U, k=1)
    w = U[iu]
    pct = [50, 70, 80, 90, 95]

    def phi_curve(weights):
        M = np.zeros((n, n)); M[iu] = weights; M = M + M.T
        s = M.sum(1)
        thr = np.percentile(s, pct)
        sorted_desc = np.sort(weights)[::-1]
        out = []
        for r in thr:
            rich = s >= r
            rich_edge = rich[iu[0]] & rich[iu[1]]
            ne = int(rich_edge.sum())
            if ne == 0:
                out.append(np.nan); continue
            out.append(weights[rich_edge].sum() / sorted_desc[:ne].sum())
        return np.array(out)

    obs = phi_curve(w)
    null = np.array([phi_curve(rng.permutation(w)) for _ in range(n_null)])
    norm = obs / np.nanmean(null, axis=0)
    return {
        "richness_percentiles": pct,
        "rho_weighted_normalised": [round(float(x), 3) for x in norm],
        "null": "strength-preserving weight reshuffle",
    }


# ---------------------------------------------------------------------------
# C. Spatial interaction: distance decay + gravity residual field
# ---------------------------------------------------------------------------
def _distance_matrix(ids, nodes: pd.DataFrame):
    pos = nodes.set_index("zone_id")[["cx_ft", "cy_ft"]]
    xy = np.array([[pos.loc[z, "cx_ft"], pos.loc[z, "cy_ft"]] if z in pos.index else [np.nan, np.nan]
                   for z in ids], dtype=float)
    dx = xy[:, 0][:, None] - xy[:, 0][None, :]
    dy = xy[:, 1][:, None] - xy[:, 1][None, :]
    dist_ft = np.sqrt(dx ** 2 + dy ** 2)
    return dist_ft / FT_PER_MILE, ~np.isnan(xy[:, 0])


def decay_exponent(edges: pd.DataFrame, nodes: pd.DataFrame) -> dict:
    """Unconstrained Poisson gravity on realised edges -> decay exponent beta."""
    import statsmodels.api as sm

    pos = nodes.set_index("zone_id")[["cx_ft", "cy_ft"]]
    e = edges[edges["o"] != edges["d"]].copy()
    e = e[e["o"].isin(pos.index) & e["d"].isin(pos.index)]
    ox = pos.loc[e["o"], "cx_ft"].to_numpy(); oy = pos.loc[e["o"], "cy_ft"].to_numpy()
    dx = pos.loc[e["d"], "cx_ft"].to_numpy(); dy = pos.loc[e["d"], "cy_ft"].to_numpy()
    e["dist_mi"] = np.sqrt((ox - dx) ** 2 + (oy - dy) ** 2) / FT_PER_MILE
    e = e[e["dist_mi"] > 0]
    os_ = e.groupby("o")["trips"].sum()
    ds_ = e.groupby("d")["trips"].sum()
    e["logO"] = np.log(e["o"].map(os_).to_numpy())
    e["logD"] = np.log(e["d"].map(ds_).to_numpy())
    e["logd"] = np.log(e["dist_mi"].to_numpy())
    X = sm.add_constant(e[["logO", "logD", "logd"]])
    m = sm.GLM(e["trips"], X, family=sm.families.Poisson()).fit(scale="X2")
    # also the cost (fare / trip-distance) decay variants
    e["log_meandist"] = np.log(e["mean_dist"].clip(lower=0.1))
    e["log_meanfare"] = np.log(e["mean_fare"].clip(lower=1.0))
    Xc = sm.add_constant(e[["logO", "logD", "log_meandist"]])
    mc = sm.GLM(e["trips"], Xc, family=sm.families.Poisson()).fit(scale="X2")
    dev_expl = 1 - m.deviance / m.null_deviance
    return {
        "beta_euclidean": round(float(-m.params["logd"]), 3),
        "beta_se": round(float(m.bse["logd"]), 4),
        "beta_trip_distance": round(float(-mc.params["log_meandist"]), 3),
        "pseudo_r2_deviance": round(float(dev_expl), 3),
        "n_edges_modelled": int(len(e)),
        "note": "O,D are taxi-activity marginals so this RECONSTRUCTS more than it explains; "
                "the residual field below uses the non-circular doubly-constrained model.",
    }


def furness(T_obs, dist, beta, iters=300, tol=1e-10):
    """Doubly-constrained gravity: row/col sums fixed to observed marginals."""
    O = T_obs.sum(1); D = T_obs.sum(0)
    f = np.zeros_like(dist)
    pos = dist > 0
    f[pos] = dist[pos] ** (-beta)
    A = np.ones_like(O); B = np.ones_like(D)
    mO = O > 0; mD = D > 0
    for _ in range(iters):
        sB = (f * (B * D)[None, :]).sum(1)
        A_new = np.where(mO & (sB > 0), 1.0 / sB, 0.0)
        sA = (f * (A_new * O)[:, None]).sum(0)
        B_new = np.where(mD & (sA > 0), 1.0 / sA, 0.0)
        if np.max(np.abs(A_new - A)) < tol and np.max(np.abs(B_new - B)) < tol:
            A, B = A_new, B_new; break
        A, B = A_new, B_new
    T = (A * O)[:, None] * (B * D)[None, :] * f
    return T


def gravity_residual_field(ids, T, nodes: pd.DataFrame) -> tuple:
    dist, has_geo = _distance_matrix(ids, nodes)
    # restrict to nodes with geometry
    keep = np.where(has_geo)[0]
    Ts = T[np.ix_(keep, keep)]
    ds = dist[np.ix_(keep, keep)]
    sids = [ids[i] for i in keep]
    obs_mean_dist = (Ts * ds).sum() / Ts.sum()

    def gap(beta):
        Tm = furness(Ts, ds, beta)
        return (Tm * ds).sum() / Tm.sum() - obs_mean_dist

    beta = float(optimize.brentq(gap, 0.2, 5.0))
    Tm = furness(Ts, ds, beta)

    cpc = 2 * np.minimum(Ts, Tm).sum() / (Ts.sum() + Tm.sum())
    # deviance residuals (matched volume floor to avoid 1-vs-0 noise)
    floor = 20.0
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(Ts > 0, Ts * np.log(Ts / Tm), 0.0)
        dev = np.sign(Ts - Tm) * np.sqrt(np.maximum(2 * (term - (Ts - Tm)), 0))
    valid = (Tm >= floor)
    dev_v = np.where(valid, dev, np.nan)

    # zone-level surprise = mean incident deviance residual (in + out)
    zone_resid = np.nanmean(np.where(valid, dev, np.nan), axis=1)   # outgoing
    zone_resid_in = np.nanmean(np.where(valid, dev, np.nan), axis=0)  # incoming
    zone_surprise = np.nanmean(np.vstack([zone_resid, zone_resid_in]), axis=0)

    sn = nodes.set_index("zone_id")
    rows = []
    for k, z in enumerate(sids):
        rows.append({"zone_id": z, "gravity_surprise": zone_surprise[k]})
    zr = pd.DataFrame(rows)
    zr = zr.merge(nodes[["zone_id", "zone", "borough", "service_zone"]], on="zone_id", how="left")

    # high-coverage scope = Yellow Zone (Manhattan core) + airports
    hi = zr["service_zone"].isin(["Yellow Zone", "Airports", "EWR"])
    core = zr[hi].dropna(subset=["gravity_surprise"]).sort_values("gravity_surprise")

    # top under/over-connected edges (within scope, matched floor)
    sset = set(zr.loc[hi, "zone_id"])
    edge_rows = []
    for i in range(len(sids)):
        for j in range(len(sids)):
            if valid[i, j] and sids[i] in sset and sids[j] in sset:
                edge_rows.append((sids[i], sids[j], Ts[i, j], Tm[i, j], dev[i, j], ds[i, j]))
    edf = pd.DataFrame(edge_rows, columns=["o", "d", "obs", "model", "dev_resid", "dist_mi"])

    result = {
        "beta_doubly_constrained": round(beta, 3),
        "cpc_doubly_constrained": round(float(cpc), 3),
        "obs_mean_trip_distance_mi": round(float(obs_mean_dist), 2),
        "most_underconnected_core_zones": [
            {"zone": r["zone"], "surprise": round(float(r["gravity_surprise"]), 2)}
            for _, r in core.head(8).iterrows()],
        "most_overconnected_core_zones": [
            {"zone": r["zone"], "surprise": round(float(r["gravity_surprise"]), 2)}
            for _, r in core.tail(8)[::-1].iterrows()],
    }
    # East Village / LES position within the core ranking
    ev = core[core["zone"].str.contains("East Village|Lower East Side|Alphabet|Chinatown|Two Bridges",
                                        case=False, na=False)]
    if len(ev):
        core_sorted = core.reset_index(drop=True)
        result["east_village_les_in_core"] = [
            {"zone": r["zone"], "surprise": round(float(r["gravity_surprise"]), 2),
             "core_percentile": round(float((core_sorted["zone"] == r["zone"]).idxmax() / len(core_sorted)), 3)}
            for _, r in ev.iterrows()]
    return result, zr, edf


# ---------------------------------------------------------------------------
# D. Disparity-filter backbone
# ---------------------------------------------------------------------------
def disparity_backbone(edges: pd.DataFrame, alpha: float = 0.05) -> tuple:
    e = edges[edges["o"] != edges["d"]].copy()
    out_s = e.groupby("o")["trips"].transform("sum")
    in_s = e.groupby("d")["trips"].transform("sum")
    k_out = e.groupby("o")["d"].transform("nunique")
    k_in = e.groupby("d")["o"].transform("nunique")
    p_out = e["trips"] / out_s
    p_in = e["trips"] / in_s
    a_out = np.where(k_out > 1, (1 - p_out) ** (k_out - 1), 0.0)
    a_in = np.where(k_in > 1, (1 - p_in) ** (k_in - 1), 0.0)
    e["alpha"] = np.minimum(a_out, a_in)        # OR rule (keep if significant either way)
    e["keep"] = e["alpha"] < alpha
    bb = e[e["keep"]]
    n_nodes_bb = len(set(bb["o"]) | set(bb["d"]))
    thr = e[e["trips"] > C.EDGE_WEIGHT_THRESHOLD]
    return {
        "alpha": alpha,
        "backbone_edges": int(len(bb)),
        "backbone_nodes": int(n_nodes_bb),
        "backbone_trip_share_pct": round(100.0 * bb["trips"].sum() / e["trips"].sum(), 1),
        "threshold_edges": int(len(thr)),
        "threshold_trip_share_pct": round(100.0 * thr["trips"].sum() / e["trips"].sum(), 1),
        "full_edges": int(len(e)),
    }, e[["o", "d", "trips", "alpha", "keep"]]


# ---------------------------------------------------------------------------
# E. Communities
# ---------------------------------------------------------------------------
def communities(ids, T, nodes: pd.DataFrame) -> dict:
    # Seed igraph's RNG so the stochastic multilevel/Leiden calls are reproducible.
    pyrandom.seed(C.SEED)
    try:
        ig.set_random_number_generator(pyrandom)
    except Exception:
        pass
    gU = undirected_igraph(ids, T)
    # directed weighted igraph for infomap
    no_self_idx = np.argwhere(T > 0)
    gD = ig.Graph(n=len(ids), edges=no_self_idx.tolist(), directed=True)
    gD.es["weight"] = T[T > 0].tolist()

    multilevel = gU.community_multilevel(weights="weight")     # original igraph method
    leiden = gU.community_leiden(objective_function="modularity", weights="weight")
    infomap = gD.community_infomap(edge_weights="weight")
    parts = {
        "igraph_multilevel": multilevel,
        "leiden_modularity": leiden,
        "infomap_directed": infomap,
    }
    summary = {}
    for name, p in parts.items():
        summary[name] = {"n_communities": len(p),
                         "modularity": round(float(gU.modularity(p.membership, weights="weight")), 4)}

    # networkx cross-checks on undirected projection
    gnx = nx.Graph()
    for e in gU.es:
        gnx.add_edge(e.source, e.target, weight=e["weight"])
    greedy = nx.community.greedy_modularity_communities(gnx, weight="weight")
    labelprop = nx.community.label_propagation_communities(gnx)
    summary["nx_greedy_modularity"] = {"n_communities": len(greedy)}
    summary["nx_label_propagation"] = {"n_communities": len(list(labelprop))}

    # resolution sweep (python-louvain)
    gpl = nx.Graph()
    for e in gU.es:
        gpl.add_edge(ids[e.source], ids[e.target], weight=e["weight"])
    sweep = {}
    for res in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
        p = community_louvain.best_partition(gpl, weight="weight", resolution=res, random_state=C.SEED)
        sweep[res] = len(set(p.values()))

    # seed stability (100 runs at resolution 1.0)
    labels = []
    for s in range(100):
        p = community_louvain.best_partition(gpl, weight="weight", random_state=s)
        labels.append(np.array([p[z] for z in ids]))
    aris, amis = [], []
    for i, j in itertools.combinations(range(len(labels)), 2):
        aris.append(adjusted_rand_score(labels[i], labels[j]))
        amis.append(adjusted_mutual_info_score(labels[i], labels[j]))
    counts = [len(set(l.tolist())) for l in labels]

    # leiden membership for downstream use
    leiden_mem = np.array(leiden.membership)
    nd = nodes.set_index("zone_id")
    boro = np.array([str(nd.loc[z, "borough"]) if z in nd.index else "?" for z in ids])
    svc = np.array([str(nd.loc[z, "service_zone"]) if z in nd.index else "?" for z in ids])
    vs_admin = {
        "leiden_vs_borough_AMI": round(float(adjusted_mutual_info_score(leiden_mem, boro)), 3),
        "leiden_vs_borough_ARI": round(float(adjusted_rand_score(leiden_mem, boro)), 3),
        "leiden_vs_servicezone_AMI": round(float(adjusted_mutual_info_score(leiden_mem, svc)), 3),
    }

    # inter-community flow matrix (row-normalised) on leiden partition
    K = len(leiden)
    flow = np.zeros((K, K))
    pos = {z: i for i, z in enumerate(ids)}
    for i in range(len(ids)):
        for j in range(len(ids)):
            if T[i, j] > 0:
                flow[leiden_mem[i], leiden_mem[j]] += T[i, j]
    within = np.trace(flow) / flow.sum()

    # Modularity significance. The undirected projection is near-complete
    # (topology carries little information), so a degree-preserving swap null is
    # uninformative here. The meaningful null keeps the topology AND the observed
    # partition fixed and reshuffles the edge WEIGHTS: does this partition group
    # high-flow edges together more than random weight assignment would?
    q_obs = float(gU.modularity(leiden.membership, weights="weight"))
    base_w = np.array(gU.es["weight"], dtype=float)
    q_null = []
    for _ in range(200):
        gn = gU.copy()
        gn.es["weight"] = rng.permutation(base_w).tolist()
        q_null.append(float(gn.modularity(leiden.membership, weights="weight")))
    q_null = np.array(q_null)
    z = (q_obs - q_null.mean()) / q_null.std()

    return {
        "algorithms": summary,
        "resolution_sweep": {str(k): v for k, v in sweep.items()},
        "seed_stability": {
            "n_runs": 100,
            "community_count_mode": int(stats.mode(counts, keepdims=False).mode),
            "community_count_range": [int(min(counts)), int(max(counts))],
            "mean_ARI": round(float(np.mean(aris)), 3),
            "min_ARI": round(float(np.min(aris)), 3),
            "mean_AMI": round(float(np.mean(amis)), 3),
            "n_pairs": len(aris),
        },
        "vs_administrative": vs_admin,
        "within_community_trip_share": round(float(within), 3),
        "modularity_significance": {
            "null": "weight-concentration: edge weights reshuffled, topology and "
                    "Leiden partition fixed (tests that the partition groups high-flow edges)",
            "Q_observed": round(float(q_obs), 4),
            "Q_null_mean": round(float(q_null.mean()), 4),
            "z_score": round(float(z), 1),
        },
        "_leiden_membership": dict(zip(ids, leiden_mem.tolist())),
        "_flow_matrix": flow.tolist(),
    }


# ---------------------------------------------------------------------------
# F. Temporal networks
# ---------------------------------------------------------------------------
def temporal_networks(nodes: pd.DataFrame) -> tuple:
    ep = common.load_edges_period()
    ep = ep[ep["o"] != ep["d"]]
    nd = nodes.set_index("zone_id")

    def top_hubs(period, k=15):
        sub = ep[ep["period"] == period]
        ins = sub.groupby("d")["trips"].sum().sort_values(ascending=False)
        return [(int(z), nd.loc[z, "zone"] if z in nd.index else "?", int(v))
                for z, v in ins.head(k).items()]

    am = top_hubs("am_peak")
    night = top_hubs("late_night_weekend")
    am_set = {z for z, _, _ in am}
    night_set = {z for z, _, _ in night}
    jaccard = len(am_set & night_set) / len(am_set | night_set)

    # AM vs PM net-flow flip for CBD vs residential/nightlife zones
    def nfi(period):
        sub = ep[ep["period"] == period]
        o = sub.groupby("o")["trips"].sum()
        d = sub.groupby("d")["trips"].sum()
        idx = o.index.union(d.index)
        o = o.reindex(idx, fill_value=0); d = d.reindex(idx, fill_value=0)
        return ((o - d) / (o + d).replace(0, 1))

    nfi_am, nfi_pm = nfi("am_peak"), nfi("pm_peak")
    flip = {}
    for sub in ["Midtown Center", "Financial District", "Penn Station", "East Village",
                "Lower East Side", "Upper East Side", "Times Sq"]:
        hit = nodes[nodes["zone"].str.contains(sub, case=False, na=False)]
        if len(hit):
            z = int(hit.iloc[0]["zone_id"])
            if z in nfi_am.index and z in nfi_pm.index:
                flip[hit.iloc[0]["zone"]] = {"nfi_am": round(float(nfi_am[z]), 3),
                                             "nfi_pm": round(float(nfi_pm[z]), 3)}

    # nightlife rank shift: a zone's destination rank AM vs late-night
    def dest_rank(period):
        sub = ep[ep["period"] == period]
        ins = sub.groupby("d")["trips"].sum().rank(ascending=False)
        return ins
    r_am, r_night = dest_rank("am_peak"), dest_rank("late_night_weekend")
    shifts = {}
    for sub in ["East Village", "Lower East Side", "Greenwich Village", "West Village", "Clinton East"]:
        hit = nodes[nodes["zone"].str.contains(sub, case=False, na=False)]
        if len(hit):
            z = int(hit.iloc[0]["zone_id"])
            if z in r_am.index and z in r_night.index:
                shifts[hit.iloc[0]["zone"]] = {"am_rank": int(r_am[z]), "night_rank": int(r_night[z])}

    # rhythm clustering: weekday 24h pickup profile per zone (active zones only,
    # so sparse outer-borough noise does not create singleton clusters)
    zh = pd.read_parquet(C.PROCESSED / "zone_hourly.parquet")
    wk = zh[~zh["weekend"]].pivot_table(index="zone_id", columns="hr", values="pickups", aggfunc="sum").fillna(0)
    wk = wk[wk.sum(axis=1) >= 50_000]
    profile = wk.div(wk.sum(axis=1), axis=0)  # normalise each zone to a daily shape
    K_R = 4
    km = KMeans(n_clusters=K_R, random_state=C.SEED, n_init=10).fit(profile.values)
    profile_labels = pd.Series(km.labels_, index=profile.index, name="rhythm_cluster")
    # describe clusters by peak hour
    cluster_peak = {}
    for c in range(K_R):
        members = profile.index[km.labels_ == c]
        mean_profile = profile.loc[members].mean()
        peak_hr = int(mean_profile.idxmax())
        # rank members by total volume so examples are recognisable
        vol = wk.loc[members].sum(1).sort_values(ascending=False)
        examples = [nd.loc[z, "zone"] for z in vol.index[:5] if z in nd.index]
        cluster_peak[c] = {"size": int(len(members)), "peak_hour": peak_hr, "examples": examples}

    return {
        "am_peak_top_hubs": [z for _, z, _ in am[:8]],
        "late_night_top_hubs": [z for _, z, _ in night[:8]],
        "am_vs_night_hub_jaccard": round(float(jaccard), 3),
        "am_pm_netflow_flip": flip,
        "nightlife_rank_shift": shifts,
        "rhythm_clusters": cluster_peak,
    }, profile_labels


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> None:
    edges = common.load_edges_annual()
    nodes = common.load_nodes()
    zones = common.load_zones()
    g = common.attach_zone_attrs(common.build_digraph(edges), zones)
    ids, idx, T = build_matrix(edges)
    print(f"[analysis] active network: {len(ids)} nodes, {int((T>0).sum()):,} directed edges")

    print("[analysis] A. centralities...")
    cen = centralities(ids, T, g)
    corr = rank_correlation(cen)

    print("[analysis] B. structure (reciprocity, assortativity, k-core, rich-club)...")
    struct = structure(ids, T, g)
    rc = weighted_rich_club(ids, T)

    print("[analysis] C. distance decay + doubly-constrained gravity residual field...")
    decay = decay_exponent(edges, nodes)
    grav, zr, edf = gravity_residual_field(ids, T, nodes)

    print("[analysis] D. disparity-filter backbone...")
    bb, edge_keep = disparity_backbone(edges)

    print("[analysis] E. communities (multi-algorithm + stability + significance)...")
    comm = communities(ids, T, nodes)

    print("[analysis] F. temporal networks (hub shift + rhythm clusters)...")
    temp, rhythm = temporal_networks(nodes)

    # assemble node-level analysis table
    node_df = cen.copy()
    node_df["coreness"] = struct.pop("_coreness")
    node_df = node_df.merge(zr[["zone_id", "gravity_surprise"]], on="zone_id", how="left")
    node_df["leiden_community"] = node_df["zone_id"].map(comm["_leiden_membership"])
    node_df = node_df.merge(rhythm.reset_index(), on="zone_id", how="left")
    node_df = node_df.merge(nodes[["zone_id", "zone", "borough", "service_zone",
                                   "net_flow_index", "self_trips"]], on="zone_id", how="left")
    node_df.to_parquet(C.PROCESSED / "node_analysis.parquet", index=False)

    edf.to_parquet(C.PROCESSED / "gravity_edges.parquet", index=False)
    edge_keep.to_parquet(C.PROCESSED / "backbone_edges.parquet", index=False)
    pd.DataFrame(comm.pop("_flow_matrix")).to_parquet(C.PROCESSED / "community_flow_matrix.parquet")

    rc.pop("_ranks", None)
    common.record("analysis", {
        "centrality_rank_correlation": corr,
        "structure": struct,
        "rich_club": rc,
        "distance_decay": decay,
        "gravity_residual_field": grav,
        "backbone": bb,
        "communities": {k: v for k, v in comm.items() if not k.startswith("_")},
        "temporal_networks": temp,
    })

    # console highlights
    print(f"[analysis] decay exponent beta = {decay['beta_euclidean']} (Euclidean), "
          f"doubly-constrained beta = {grav['beta_doubly_constrained']}, CPC = {grav['cpc_doubly_constrained']}")
    print(f"[analysis] reciprocity rho = {struct['garlaschelli_loffredo_rho']}, "
          f"assortativity = {struct['degree_assortativity']}")
    print(f"[analysis] backbone: {bb['backbone_edges']} edges keep {bb['backbone_trip_share_pct']}% of trips "
          f"(vs >{C.EDGE_WEIGHT_THRESHOLD} threshold: {bb['threshold_edges']} edges)")
    print(f"[analysis] communities (leiden): {comm['algorithms']['leiden_modularity']['n_communities']}, "
          f"seed-stable count {comm['seed_stability']['community_count_mode']} "
          f"(ARI {comm['seed_stability']['mean_ARI']}), Q z-score {comm['modularity_significance']['z_score']}")
    print(f"[analysis] AM vs late-night hub Jaccard: {temp['am_vs_night_hub_jaccard']}")
    print("[analysis] most under-connected core zones (gravity surprise):")
    for r in grav["most_underconnected_core_zones"][:6]:
        print(f"    {r['zone']:32s} {r['surprise']:+.2f}")


if __name__ == "__main__":
    sys.exit(main())
