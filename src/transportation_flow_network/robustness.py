"""Network robustness and percolation (Barabasi 'Network Science' Ch.8).

Targets the 2015 directed, weighted, spatial taxi-flow graph (262 active TLC
zones, ~42.3k directed edges, self-loops excluded). The central tension on this
object is that it is NOT sparse: mean in-degree is ~161 of 261 possible, density
~0.62. That near-completeness makes RANDOM-failure percolation almost
degenerate. The Molloy-Reed criterion (giant component iff kappa = <k^2>/<k> > 2)
is satisfied by a colossal margin (kappa in the hundreds), so f_c under random
removal is essentially 1: the full graph survives random failure by
construction, and we say so. The scientifically meaningful story is in TARGETED
attack and in the WEIGHT-AWARE curves (surviving-trip fraction, weighted global
efficiency), which collapse far faster than the node-count fraction suggests
because a handful of Midtown/airport hubs carry a disproportionate share of flow.

For each removal STRATEGY we sweep the node-removal fraction f over
config.ROBUSTNESS_FRACTIONS (0.0..0.60) and record four curves:
  - wcc_frac : |largest weakly-connected component| / N0   (reach-at-all)
  - scc_frac : |largest strongly-connected component| / N0  (round-trip reach)
  - eff_frac : weighted global efficiency E(f) / E(0)        (Latora-Marchiori)
  - trip_frac: surviving trips on edges whose BOTH endpoints survive AND lie in
               the giant WCC, divided by total trips (the honest flow x-axis)

N0 is the pre-removal node count: every fraction is normalized by N0, never by
the current (shrinking) node count.

Strategies:
  - random        : averaged over config.N_NULL_GRAPHS seeded shuffles
  - strength      : descending out+in strength, STATIC ranking
  - strength_recomp: descending out+in strength, RECOMPUTED after each removal
                     (Barabasi Ch.8 - the recalculated adversary is strictly
                     more damaging). Strength recompute is O(E) per step so this
                     is cheap on 262 nodes.
  - betweenness   : descending flow-weighted betweenness (weight = 1/trips, so
                    heavy flow => low cost => preferred path), STATIC ranking.
                    Recompute is NOT done for betweenness: all-pairs betweenness
                    every removal step is the only expensive piece; static
                    ranking is the documented choice here.
  - pagerank      : descending PageRank (weight='trips', alpha=0.85), STATIC.

Schneider robustness R = mean over the swept f of the largest-WCC fraction
(reported for SCC too). Higher R = more robust. Critical f_c = first f at which
the giant WCC fraction drops below 0.5.

Writes data/processed/robustness.parquet (long form) and records the headline
numbers via common.record('robustness', ...).
"""
from __future__ import annotations

import sys

import networkx as nx
import numpy as np
import pandas as pd

from . import common, config as C

FT_PER_MILE = 5280.0


# ---------------------------------------------------------------------------
# Graph preparation
# ---------------------------------------------------------------------------
def prepare_graph() -> nx.DiGraph:
    """2015 directed weighted graph with edge cost=1/trips and dist (miles)."""
    g = common.load_graph(drop_selfloops=True)
    for u, v, d in g.edges(data=True):
        trips = float(d.get("trips", 0.0))
        d["cost"] = 1.0 / trips if trips > 0 else np.inf
        cxu, cyu = g.nodes[u].get("cx_ft"), g.nodes[u].get("cy_ft")
        cxv, cyv = g.nodes[v].get("cx_ft"), g.nodes[v].get("cy_ft")
        if None in (cxu, cyu, cxv, cyv):
            d["dist"] = np.nan
        else:
            d["dist"] = float(np.hypot(cxu - cxv, cyu - cyv)) / FT_PER_MILE
    return g


def total_trips(g: nx.DiGraph) -> float:
    return float(sum(d.get("trips", 0.0) for _, _, d in g.edges(data=True)))


# ---------------------------------------------------------------------------
# Array representation (built once) - all curve points are then pure
# numpy/scipy on integer-indexed edge arrays, no per-point networkx rebuild.
# This is what makes the whole module run in seconds: networkx's pure-Python
# all-pairs Dijkstra on this dense graph with cost=1/trips (weights spanning
# ~7 orders of magnitude) costs ~8 s PER call, scipy.csgraph ~0.2 s.
# ---------------------------------------------------------------------------
class GraphArrays:
    """Fixed integer-indexed edge arrays for the full 2015 graph."""

    def __init__(self, g: nx.DiGraph):
        from scipy import sparse  # local import, kept off module top
        self.sparse = sparse
        self.nodes = list(g.nodes)
        self.n = len(self.nodes)
        self.idx = {node: i for i, node in enumerate(self.nodes)}
        u, v, cost, trips = [], [], [], []
        for a, b, d in g.edges(data=True):
            u.append(self.idx[a])
            v.append(self.idx[b])
            c = d.get("cost", np.inf)
            cost.append(c if (c > 0 and np.isfinite(c)) else np.inf)
            trips.append(float(d.get("trips", 0.0)))
        self.u = np.asarray(u)
        self.v = np.asarray(v)
        self.cost = np.asarray(cost, dtype=float)
        self.trips = np.asarray(trips, dtype=float)
        self.total_trips = float(self.trips.sum())

    def _edge_mask(self, alive: np.ndarray) -> np.ndarray:
        """Boolean over edges whose both endpoints survive."""
        return alive[self.u] & alive[self.v]

    def metrics(self, alive: np.ndarray, E0: float, with_eff: bool = True) -> dict:
        """Four curve values for the survivor mask ``alive`` (bool, len n).

        Fractions are normalized by N0 = self.n (the pre-removal count).
        """
        sp = self.sparse
        n = self.n
        em = self._edge_mask(alive)
        eu, ev = self.u[em], self.v[em]
        # --- connectivity on the survivor-induced directed subgraph ---
        if eu.size == 0:
            return {"wcc_frac": 0.0, "scc_frac": 0.0,
                    "eff_frac": (np.nan if not with_eff else 0.0),
                    "trip_frac": 0.0}
        adj = sp.csr_matrix((np.ones(eu.size), (eu, ev)), shape=(n, n))
        n_wcc, lab_w = sp.csgraph.connected_components(adj, directed=True,
                                                       connection="weak")
        n_scc, lab_s = sp.csgraph.connected_components(adj, directed=True,
                                                       connection="strong")
        # only count survivors (isolated removed nodes share a trivial label)
        wmask = alive
        wcc = self._largest_label_count(lab_w, wmask) / n
        scc = self._largest_label_count(lab_s, wmask) / n
        # --- surviving trip fraction: edges inside the giant WCC ---
        giant_w = self._largest_label(lab_w, wmask)
        in_giant = (lab_w == giant_w) & alive
        keep = em & in_giant[self.u] & in_giant[self.v]
        trip = float(self.trips[keep].sum()) / self.total_trips if self.total_trips else 0.0
        # --- weighted global efficiency (flow-cost Dijkstra) ---
        if with_eff:
            cm = sp.csr_matrix((self.cost[em], (eu, ev)), shape=(n, n))
            keep_idx = np.where(alive)[0]
            dist = sp.csgraph.dijkstra(cm, directed=True, indices=keep_idx)
            dist = dist[:, keep_idx]
            with np.errstate(divide="ignore"):
                inv = 1.0 / dist
            inv[~np.isfinite(inv)] = 0.0
            np.fill_diagonal(inv, 0.0)
            ns = keep_idx.size
            E = float(inv.sum()) / (ns * (ns - 1)) if ns > 1 else 0.0
            eff = E / E0 if E0 > 0 else 0.0
        else:
            eff = np.nan
        return {"wcc_frac": wcc, "scc_frac": scc, "eff_frac": eff, "trip_frac": trip}

    @staticmethod
    def _largest_label(labels: np.ndarray, mask: np.ndarray) -> int:
        sub = labels[mask]
        if sub.size == 0:
            return -1
        vals, counts = np.unique(sub, return_counts=True)
        return int(vals[counts.argmax()])

    @staticmethod
    def _largest_label_count(labels: np.ndarray, mask: np.ndarray) -> int:
        sub = labels[mask]
        if sub.size == 0:
            return 0
        _, counts = np.unique(sub, return_counts=True)
        return int(counts.max())


def full_efficiency(ga: "GraphArrays") -> float:
    """E(0): weighted global efficiency of the intact graph (flow-cost)."""
    alive = np.ones(ga.n, dtype=bool)
    m = ga.metrics(alive, E0=1.0, with_eff=True)
    return m["eff_frac"]  # E0=1 => returns raw E


# ---------------------------------------------------------------------------
# Removal orders (return node-id lists in descending importance)
# ---------------------------------------------------------------------------
def strength_order(g: nx.DiGraph) -> list:
    """Nodes by descending out+in strength (trips)."""
    s = {n: 0.0 for n in g.nodes}
    for u, v, d in g.edges(data=True):
        w = d.get("trips", 0.0)
        s[u] += w
        s[v] += w
    return [n for n, _ in sorted(s.items(), key=lambda kv: kv[1], reverse=True)]


def betweenness_order(g: nx.DiGraph) -> list:
    """Descending flow-weighted betweenness (weight='cost' = 1/trips).

    Single static ranking computed once on the intact graph; networkx
    betweenness with these wide-range weights is the one slow centrality but is
    only evaluated once here (not recomputed per removal step).
    """
    bt = nx.betweenness_centrality(g, weight="cost", normalized=True)
    return [n for n, _ in sorted(bt.items(), key=lambda kv: kv[1], reverse=True)]


def pagerank_order(g: nx.DiGraph) -> list:
    pr = nx.pagerank(g, weight="trips", alpha=0.85)
    return [n for n, _ in sorted(pr.items(), key=lambda kv: kv[1], reverse=True)]


# ---------------------------------------------------------------------------
# Sweeps (operate on the GraphArrays survivor mask)
# ---------------------------------------------------------------------------
def _row(metrics: dict, strategy: str, f: float) -> dict:
    r = dict(metrics)
    r.update({"strategy": strategy, "f": f})
    return r


def sweep_static(ga: GraphArrays, order: list, fractions: list, E0: float,
                 strategy: str, with_eff: bool = True) -> list:
    """Remove the first round(f*N0) nodes from a fixed (static) ranking."""
    N0 = ga.n
    order_idx = [ga.idx[n] for n in order]
    rows = []
    for f in fractions:
        k = int(round(f * N0))
        alive = np.ones(N0, dtype=bool)
        if k:
            alive[order_idx[:k]] = False
        rows.append(_row(ga.metrics(alive, E0, with_eff), strategy, f))
    return rows


def sweep_recomputed_strength(full: nx.DiGraph, ga: GraphArrays,
                              fractions: list, E0: float) -> list:
    """Recompute out+in strength on the surviving subgraph after each removal.

    Barabasi Ch.8: the recalculated attack is the correct, strictly-more-
    damaging adversary. Strength recompute is O(E), so all removals up to the
    max fraction are cheap. We build the one-at-a-time removal sequence on the
    networkx copy, then sample the (array-based) curve at the requested
    fractions.
    """
    max_f = max(fractions)
    k_max = int(round(max_f * ga.n))
    removed_at = {}
    H = full.copy()
    for step in range(k_max):
        if H.number_of_nodes() == 0:
            break
        victim = strength_order(H)[0]
        removed_at[victim] = step
        H.remove_node(victim)
    seq = [n for n, _ in sorted(removed_at.items(), key=lambda kv: kv[1])]
    return sweep_static(ga, seq, fractions, E0, "strength_recomp")


def sweep_random(ga: GraphArrays, fractions: list, E0: float,
                 n_reps: int, eff_reps: int = 20) -> list:
    """Random failure averaged over ``n_reps`` seeded shuffles.

    Connectivity (WCC/SCC) and surviving-trip curves are averaged over ALL
    ``n_reps`` seeds. The weighted-efficiency curve (all-pairs Dijkstra per
    point) is averaged over only the first ``eff_reps`` seeds; random-removal
    efficiency is strongly self-averaging on a dense graph, and the cap is
    recorded in the payload.
    """
    N0 = ga.n
    acc = {f: {"wcc_frac": [], "scc_frac": [], "eff_frac": [], "trip_frac": []}
           for f in fractions}
    for rep in range(n_reps):
        rng = np.random.default_rng(C.SEED + rep)
        perm = rng.permutation(N0)
        want_eff = rep < eff_reps
        for f in fractions:
            k = int(round(f * N0))
            alive = np.ones(N0, dtype=bool)
            if k:
                alive[perm[:k]] = False
            m = ga.metrics(alive, E0, with_eff=want_eff)
            for key in acc[f]:
                if key == "eff_frac" and not want_eff:
                    continue
                acc[f][key].append(m[key])
    rows = []
    for f in fractions:
        pt = {key: float(np.nanmean(vals)) for key, vals in acc[f].items()}
        rows.append(_row(pt, "random", f))
    return rows


# ---------------------------------------------------------------------------
# Headline statistics
# ---------------------------------------------------------------------------
def molloy_reed_kappa(g: nx.DiGraph) -> float:
    """kappa = <k^2>/<k> on the total (in+out) degree sequence (undirected
    projection sense). kappa > 2 => giant component (Molloy-Reed). On this dense
    graph kappa is in the hundreds, so f_c -> 1 under random removal: the
    criterion is essentially degenerate here and we report it as a reference
    only.
    """
    degs = np.array([g.in_degree(n) + g.out_degree(n) for n in g.nodes],
                    dtype=float)
    k = degs.mean()
    return float((degs ** 2).mean() / k) if k > 0 else float("nan")


def schneider_R(df_strategy: pd.DataFrame, col: str) -> float:
    """R = mean over the swept f of the giant-component fraction (Schneider).

    Strictly Schneider integrates over q=1..N; here we report the mean of the
    sampled curve over config.ROBUSTNESS_FRACTIONS (a uniform-f estimator of the
    same area). Higher = more robust.
    """
    return float(df_strategy.sort_values("f")[col].mean())


def critical_f(df_strategy: pd.DataFrame, col: str = "wcc_frac",
               thresh: float = 0.5) -> float:
    """First f at which the giant-component fraction drops below ``thresh``.

    Returns NaN if it never drops below within the swept range (i.e. the network
    keeps a majority giant component throughout - the random-failure case).
    """
    d = df_strategy.sort_values("f")
    below = d[d[col] < thresh]
    return float(below["f"].iloc[0]) if len(below) else float("nan")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run() -> tuple[pd.DataFrame, dict]:
    g = prepare_graph()
    ga = GraphArrays(g)
    N0 = ga.n
    E0 = full_efficiency(ga)
    total = ga.total_trips
    fractions = list(C.ROBUSTNESS_FRACTIONS)

    print(f"[robustness] 2015 graph: {N0} nodes, {g.number_of_edges():,} edges, "
          f"{total:,.0f} trips; E(0)={E0:.6g}")

    kappa = molloy_reed_kappa(g)
    print(f"[robustness] Molloy-Reed kappa = <k^2>/<k> = {kappa:.1f} "
          f"(>> 2: random-failure f_c -> 1, criterion degenerate on dense graph)")

    rows: list[dict] = []

    eff_reps = min(20, C.N_NULL_GRAPHS)
    print(f"[robustness] random failure (connectivity over {C.N_NULL_GRAPHS} seeds, "
          f"efficiency over {eff_reps})...")
    rows += sweep_random(ga, fractions, E0, C.N_NULL_GRAPHS, eff_reps)

    print("[robustness] targeted: out+in strength (static)...")
    rows += sweep_static(ga, strength_order(g), fractions, E0, "strength")

    print("[robustness] targeted: out+in strength (recomputed each removal)...")
    rows += sweep_recomputed_strength(g, ga, fractions, E0)

    print("[robustness] targeted: flow-weighted betweenness, weight=1/trips (static)...")
    rows += sweep_static(ga, betweenness_order(g), fractions, E0, "betweenness")

    print("[robustness] targeted: PageRank weight=trips (static)...")
    rows += sweep_static(ga, pagerank_order(g), fractions, E0, "pagerank")

    df = pd.DataFrame(rows)[["strategy", "f", "wcc_frac", "scc_frac",
                             "eff_frac", "trip_frac"]]

    # headline stats per strategy
    strategies = ["random", "strength", "strength_recomp", "betweenness", "pagerank"]
    R_wcc, R_scc, fc_wcc, fc_trip = {}, {}, {}, {}
    for s in strategies:
        d = df[df["strategy"] == s]
        R_wcc[s] = schneider_R(d, "wcc_frac")
        R_scc[s] = schneider_R(d, "scc_frac")
        fc_wcc[s] = critical_f(d, "wcc_frac", 0.5)
        fc_trip[s] = critical_f(d, "trip_frac", 0.5)

    # "attack vs failure" gap: at a representative small fraction, how much more
    # surviving trip-weight does random failure preserve vs the worst attack.
    probe_f = 0.10
    def at(strategy, col):
        d = df[(df["strategy"] == strategy)]
        i = (d["f"] - probe_f).abs().idxmin()
        return float(d.loc[i, col])
    worst_attack = min(strategies, key=lambda s: at(s, "trip_frac")
                       if s != "random" else 1.0)
    gap = {
        "probe_fraction": probe_f,
        "random_trip_frac": at("random", "trip_frac"),
        "worst_attack_strategy": worst_attack,
        "worst_attack_trip_frac": at(worst_attack, "trip_frac"),
        "trip_frac_gap": at("random", "trip_frac") - at(worst_attack, "trip_frac"),
        "random_eff_frac": at("random", "eff_frac"),
        "worst_attack_eff_frac": at(worst_attack, "eff_frac"),
    }

    payload = {
        "n_nodes": N0,
        "n_edges": g.number_of_edges(),
        "total_trips": total,
        "efficiency_E0": E0,
        "molloy_reed_kappa": kappa,
        "n_random_seeds": C.N_NULL_GRAPHS,
        "n_random_seeds_efficiency": eff_reps,
        "fractions": fractions,
        "schneider_R_wcc": R_wcc,
        "schneider_R_scc": R_scc,
        "critical_f_wcc": fc_wcc,
        "critical_f_trip": fc_trip,
        "attack_vs_failure_gap": gap,
        "recompute_note": ("strength attack run both static and recomputed; "
                           "betweenness/pagerank static only (all-pairs "
                           "betweenness per step is the sole costly piece)."),
        "weighting_note": ("efficiency uses weight=cost=1/trips (flow-resistance "
                           "Dijkstra); trip_frac counts trips inside the giant WCC."),
    }
    return df, payload


def main() -> None:
    df, payload = run()
    out = C.PROCESSED / "robustness.parquet"
    df.to_parquet(out, index=False)
    common.record("robustness", payload)

    R = payload["schneider_R_wcc"]
    fc = payload["critical_f_wcc"]
    gap = payload["attack_vs_failure_gap"]

    print(f"[robustness] wrote {out} ({len(df)} rows)")
    print(f"[robustness] Schneider R (WCC): "
          + ", ".join(f"{k}={v:.3f}" for k, v in R.items()))
    print(f"[robustness] critical f_c (WCC<0.5): "
          + ", ".join(f"{k}={('%.2f'%v) if v==v else 'never'}" for k, v in fc.items()))
    print(f"[robustness] attack-vs-failure at f={gap['probe_fraction']}: "
          f"random keeps {gap['random_trip_frac']:.1%} of trips, "
          f"worst attack ({gap['worst_attack_strategy']}) keeps "
          f"{gap['worst_attack_trip_frac']:.1%} "
          f"(gap {gap['trip_frac_gap']:.1%})")


if __name__ == "__main__":
    sys.exit(main())
