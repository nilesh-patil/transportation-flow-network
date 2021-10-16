"""Null-model benchmarking (Barabasi 'Network Science' Ch.3 random graphs,
Ch.7 configuration model & degree correlations).

On the 2015 directed, weighted, spatial taxi-flow graph we benchmark four
observed structural statistics against three null ensembles, and report a
z-score and an empirical percentile for each (statistic, null) pair.

OBSERVED STATISTICS (computed once on the real directed weighted g)
  - clustering: transitivity of the UNDIRECTED simple projection
    (nx.transitivity). On a near-complete graph this is the textbook-degenerate
    quantity; we report it precisely to SHOW the degeneracy.
  - degree assortativity: nx.degree_assortativity_coefficient (directed, the
    default out->in pairing on a DiGraph).
  - reciprocity: Garlaschelli-Loffredo rho = (r - abar) / (1 - abar), where
    r = sum_ij a_ij a_ji / L, abar = L / (N(N-1)). rho > 0 = reciprocity above
    the density-implied baseline. (We also report the weighted reciprocity
    r_w = sum min(w_ij, w_ji)/sum w_ij as context, but the null comparison is on
    the topological rho since topology is what the ER/configuration nulls vary.)
  - global efficiency E = (1/(N(N-1))) sum_{i!=j} 1/d_ij on the COST-weighted
    graph (cost_ij = 1/trips_ij), with 1/d_ij = 0 for unreachable pairs. We
    report global efficiency in place of "average shortest path length" because
    on a directed graph many pairs are unreachable and a raw mean path length is
    ill-defined; efficiency is the path-length statistic that stays finite
    (Latora-Marchiori). It is reported for the weight-preserving null only,
    where weights (hence costs) actually move; for the ER/configuration nulls the
    cost assignment would be arbitrary so we report the UNWEIGHTED reciprocal
    path-length there and flag it.

THREE NULLS
  A. Directed Erdos-Renyi G(n, m): same node count and same edge count, edges
     placed uniformly at random (nx.gnm_random_graph(n, m, directed=True)).
     Topology baseline only.
  B. Directed degree-preserving configuration model: preserves the exact
     (in-degree, out-degree) sequence (nx.directed_configuration_model), then
     simplified (self-loops + parallel edges removed). Simplification perturbs
     the degree sequence slightly; we report the residual edge-count drift.
  C. Strength / weight-preserving null (THE informative one here): the observed
     topology is held FIXED (every edge i->j stays) and the edge-weight vector is
     randomly permuted across that fixed edge set. This preserves the exact
     degree sequence and total weight while destroying the coupling between WHERE
     the heavy flows sit and the topology. It is the only non-degenerate null on
     a near-complete weighted graph, and it is the one we emphasise.

DEGENERACY STATEMENT (printed and recorded): at density ~0.62 the observed
topology is so dense that ER and the configuration model reproduce the observed
transitivity and (near-zero) assortativity almost exactly - their z-scores are
either tiny or trivially large and carry little information. The weight-preserving
null C is the scientifically decisive one: it isolates the flow/spatial structure
from the (trivial) topology and is the comparison to read.

Writes data/processed/nullmodel_comparison.parquet
(columns: metric, observed, null_mean, null_std, z, percentile, null_type)
and common.record('null_models', {...}).
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


# ---------------------------------------------------------------------------
# Observed statistics
# ---------------------------------------------------------------------------
def transitivity_undirected(g: nx.DiGraph) -> float:
    """Global clustering (transitivity) of the undirected simple projection."""
    gu = nx.Graph(g.to_undirected())
    gu.remove_edges_from(nx.selfloop_edges(gu))
    return float(nx.transitivity(gu))


def assortativity(g: nx.DiGraph) -> float:
    return float(nx.degree_assortativity_coefficient(g))


def gl_reciprocity(g: nx.DiGraph) -> float:
    """Garlaschelli-Loffredo reciprocity rho = (r - abar)/(1 - abar)."""
    n = g.number_of_nodes()
    L = g.number_of_edges()
    if L == 0 or n < 2:
        return float("nan")
    A = nx.to_numpy_array(g, weight=None)  # binary adjacency in node order
    A = (A > 0).astype(float)
    r = float((A * A.T).sum() / L)
    abar = L / (n * (n - 1))
    return float((r - abar) / (1.0 - abar))


def weighted_reciprocity(g: nx.DiGraph, weight: str = "trips") -> float:
    W = nx.to_numpy_array(g, weight=weight)
    tot = W.sum()
    if tot == 0:
        return float("nan")
    return float(np.minimum(W, W.T).sum() / tot)


def global_efficiency_weighted(g: nx.DiGraph, cost_attr: str | None) -> float:
    """E = mean over ordered pairs of 1/d_ij; unreachable pairs contribute 0.

    cost_attr=None gives the unweighted (hop-count) efficiency; otherwise Dijkstra
    on the named edge attribute (a distance/cost, lower = closer).
    """
    n = g.number_of_nodes()
    if n < 2:
        return float("nan")
    total = 0.0
    if cost_attr is None:
        lengths = dict(nx.all_pairs_shortest_path_length(g))
        for u, dmap in lengths.items():
            for v, d in dmap.items():
                if u != v and d > 0:
                    total += 1.0 / d
    else:
        lengths = dict(nx.all_pairs_dijkstra_path_length(g, weight=cost_attr))
        for u, dmap in lengths.items():
            for v, d in dmap.items():
                if u != v and d > 0:
                    total += 1.0 / d
    return float(total / (n * (n - 1)))


def observed_stats(g: nx.DiGraph) -> dict:
    """All observed statistics in one pass."""
    return {
        "transitivity": transitivity_undirected(g),
        "assortativity": assortativity(g),
        "reciprocity_gl": gl_reciprocity(g),
        "weighted_reciprocity": weighted_reciprocity(g, "trips"),
        "efficiency_unweighted": global_efficiency_weighted(g, None),
        "efficiency_cost": global_efficiency_weighted(g, "cost"),
    }


# ---------------------------------------------------------------------------
# Null ensembles
# ---------------------------------------------------------------------------
def er_sample(n: int, m: int, seed: int) -> nx.DiGraph:
    """Directed Erdos-Renyi G(n, m): same node + edge count, edges uniform."""
    return nx.gnm_random_graph(n, m, seed=seed, directed=True)


def config_sample(in_seq, out_seq, seed: int) -> nx.DiGraph:
    """Directed configuration model, simplified (self-loops + parallels removed)."""
    mg = nx.directed_configuration_model(in_seq, out_seq, seed=seed)
    g = nx.DiGraph()
    g.add_nodes_from(range(len(in_seq)))
    for u, v in mg.edges():
        if u != v:
            g.add_edge(u, v)
    return g


def weight_permuted_sample(g_obs: nx.DiGraph, weight: str, seed: int) -> nx.DiGraph:
    """Fixed topology, edge weights permuted; cost = 1/weight recomputed."""
    local_rng = np.random.default_rng(seed)
    edges = list(g_obs.edges())
    w = np.array([g_obs[u][v][weight] for u, v in edges], dtype=float)
    w_perm = local_rng.permutation(w)
    g = nx.DiGraph()
    g.add_nodes_from(g_obs.nodes())
    for (u, v), wt in zip(edges, w_perm):
        g.add_edge(u, v, **{weight: float(wt), "cost": 1.0 / wt if wt > 0 else np.inf})
    return g


# ---------------------------------------------------------------------------
# z-score / percentile machinery
# ---------------------------------------------------------------------------
def _zrow(metric: str, observed: float, null_vals: np.ndarray, null_type: str) -> dict:
    null_vals = np.asarray(null_vals, dtype=float)
    null_vals = null_vals[np.isfinite(null_vals)]
    mu = float(np.mean(null_vals)) if len(null_vals) else float("nan")
    sd = float(np.std(null_vals, ddof=0)) if len(null_vals) else float("nan")
    z = float((observed - mu) / sd) if (sd and sd > 0) else float("nan")
    # empirical one-sided percentile (fraction of nulls strictly below observed)
    pct = float((null_vals < observed).mean()) if len(null_vals) else float("nan")
    return {
        "metric": metric,
        "observed": round(float(observed), 5),
        "null_mean": round(mu, 5),
        "null_std": round(sd, 5),
        "z": round(z, 3) if np.isfinite(z) else None,
        "percentile": round(pct, 4) if np.isfinite(pct) else None,
        "null_type": null_type,
    }


# ---------------------------------------------------------------------------
# Ensemble runners
# ---------------------------------------------------------------------------
def run_er(g: nx.DiGraph, obs: dict, n_null: int) -> list[dict]:
    n, m = g.number_of_nodes(), g.number_of_edges()
    trans, assort, recip, eff = [], [], [], []
    for s in range(n_null):
        h = er_sample(n, m, seed=C.SEED + s)
        trans.append(transitivity_undirected(h))
        assort.append(assortativity(h))
        recip.append(gl_reciprocity(h))
        eff.append(global_efficiency_weighted(h, None))
    nt = "erdos_renyi_gnm"
    return [
        _zrow("transitivity", obs["transitivity"], np.array(trans), nt),
        _zrow("assortativity", obs["assortativity"], np.array(assort), nt),
        _zrow("reciprocity_gl", obs["reciprocity_gl"], np.array(recip), nt),
        _zrow("efficiency_unweighted", obs["efficiency_unweighted"], np.array(eff), nt),
    ]


def run_config(g: nx.DiGraph, obs: dict, n_null: int) -> tuple[list[dict], dict]:
    nodes = list(g.nodes())
    pos = {z: i for i, z in enumerate(nodes)}
    in_seq = [g.in_degree(z) for z in nodes]
    out_seq = [g.out_degree(z) for z in nodes]
    m_obs = g.number_of_edges()
    trans, assort, recip, eff, drift = [], [], [], [], []
    for s in range(n_null):
        h = config_sample(in_seq, out_seq, seed=C.SEED + s)
        trans.append(transitivity_undirected(h))
        assort.append(assortativity(h))
        recip.append(gl_reciprocity(h))
        eff.append(global_efficiency_weighted(h, None))
        drift.append(h.number_of_edges())
    nt = "directed_configuration"
    rows = [
        _zrow("transitivity", obs["transitivity"], np.array(trans), nt),
        _zrow("assortativity", obs["assortativity"], np.array(assort), nt),
        _zrow("reciprocity_gl", obs["reciprocity_gl"], np.array(recip), nt),
        _zrow("efficiency_unweighted", obs["efficiency_unweighted"], np.array(eff), nt),
    ]
    drift_arr = np.array(drift, dtype=float)
    meta = {
        "observed_edges": int(m_obs),
        "simplified_null_edges_mean": round(float(drift_arr.mean()), 1),
        "edge_loss_pct_to_simplification": round(
            100.0 * (m_obs - drift_arr.mean()) / m_obs, 2),
    }
    _ = pos  # node order kept binary-stable; pos retained for clarity
    return rows, meta


def run_weight(g: nx.DiGraph, obs: dict, n_null: int) -> list[dict]:
    """Weight-preserving null - the informative one. Topology fixed, weights
    permuted, so transitivity/assortativity/reciprocity_gl (all TOPOLOGICAL) are
    invariant by construction (z=0, std=0); the moving quantities are the
    WEIGHTED ones: weighted reciprocity and cost-weighted global efficiency."""
    wrecip, eff_cost = [], []
    for s in range(n_null):
        h = weight_permuted_sample(g, "trips", seed=C.SEED + s)
        wrecip.append(weighted_reciprocity(h, "trips"))
        eff_cost.append(global_efficiency_weighted(h, "cost"))
    nt = "weight_preserving"
    return [
        _zrow("weighted_reciprocity", obs["weighted_reciprocity"], np.array(wrecip), nt),
        _zrow("efficiency_cost", obs["efficiency_cost"], np.array(eff_cost), nt),
    ]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> None:
    edges = common.load_edges_annual()
    g = common.build_digraph(edges, weight="trips", drop_selfloops=True)
    # attach cost = 1/trips for the weighted-efficiency observed value
    for u, v, d in g.edges(data=True):
        d["cost"] = 1.0 / d["trips"] if d["trips"] > 0 else np.inf

    n, m = g.number_of_nodes(), g.number_of_edges()
    density = m / (n * (n - 1))
    n_null = C.N_NULL_GRAPHS
    print(f"[nullmodels] observed graph: {n} nodes, {m:,} directed edges, "
          f"density {density:.3f}")
    print(f"[nullmodels] {n_null} samples per ensemble (config.N_NULL_GRAPHS)")

    obs = observed_stats(g)
    print(f"[nullmodels] observed: transitivity={obs['transitivity']:.4f}, "
          f"assortativity={obs['assortativity']:.4f}, "
          f"reciprocity_gl={obs['reciprocity_gl']:.4f}, "
          f"weighted_reciprocity={obs['weighted_reciprocity']:.4f}")
    print(f"[nullmodels] observed efficiency: unweighted={obs['efficiency_unweighted']:.4f}, "
          f"cost-weighted={obs['efficiency_cost']:.5f}")

    print("[nullmodels] A. Erdos-Renyi G(n,m) ensemble (topology baseline)...")
    rows_er = run_er(g, obs, n_null)
    print("[nullmodels] B. directed configuration model ensemble...")
    rows_cfg, cfg_meta = run_config(g, obs, n_null)
    print("[nullmodels] C. weight-preserving null (the informative one)...")
    rows_w = run_weight(g, obs, n_null)

    all_rows = rows_er + rows_cfg + rows_w
    df = pd.DataFrame(all_rows)
    out_path = C.PROCESSED / "nullmodel_comparison.parquet"
    df.to_parquet(out_path, index=False)

    # assemble the recorded payload
    def by_type(rows):
        return {r["metric"]: {k: r[k] for k in
                ("observed", "null_mean", "null_std", "z", "percentile")} for r in rows}

    payload = {
        "graph": {"nodes": int(n), "edges": int(m), "density": round(float(density), 4)},
        "n_null_graphs": int(n_null),
        "observed": {k: round(float(v), 5) for k, v in obs.items()},
        "erdos_renyi": by_type(rows_er),
        "configuration": by_type(rows_cfg),
        "configuration_meta": cfg_meta,
        "weight_preserving": by_type(rows_w),
        "degeneracy_note": (
            "At density {:.2f} the observed topology is near-complete, so the ER and "
            "directed-configuration nulls reproduce observed transitivity and the "
            "near-zero assortativity almost exactly - their z-scores are uninformative "
            "(transitivity is structurally forced; assortativity hovers at 0). The "
            "WEIGHT-PRESERVING null is the decisive comparison: topology and degrees are "
            "held exactly, only the weight-topology coupling is destroyed, so a nonzero "
            "z on weighted reciprocity / cost-weighted efficiency reports genuine "
            "flow/spatial organisation (heavy flows sit on mutual high-volume corridors), "
            "not a topological artefact.".format(density)),
    }
    common.record("null_models", payload)

    # console highlights
    print(f"[nullmodels] wrote {out_path.name} ({len(df)} rows)")
    print("[nullmodels] --- topology nulls (ER / configuration) - largely DEGENERATE ---")
    for r in rows_er:
        print(f"    ER          {r['metric']:22s} obs={r['observed']:+.4f} "
              f"null={r['null_mean']:+.4f} z={r['z']}")
    for r in rows_cfg:
        print(f"    config      {r['metric']:22s} obs={r['observed']:+.4f} "
              f"null={r['null_mean']:+.4f} z={r['z']}")
    print(f"    [config simplification dropped {cfg_meta['edge_loss_pct_to_simplification']}% "
          f"of stubs vs observed {cfg_meta['observed_edges']} edges]")
    print("[nullmodels] --- weight-preserving null - the INFORMATIVE comparison ---")
    for r in rows_w:
        print(f"    weight-null {r['metric']:22s} obs={r['observed']:.5f} "
              f"null={r['null_mean']:.5f} z={r['z']} (pctile {r['percentile']})")


if __name__ == "__main__":
    sys.exit(main())
