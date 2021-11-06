"""Stage: multi-year evolving-network analysis (Barabasi Ch.6 framing).

The single-year stages dissect one snapshot. This stage treats the taxi-flow
network as a TIME-EVOLVING object and asks the Barabasi Ch.6 questions: which
structural invariants persist as the system grows or contracts, and which break.
The narrative the recorded numbers are built to surface:

  - the ride-hailing-driven volume decline 2015 -> 2019 (yellow-taxi share eroding
    as FHV/Uber/Lyft take trips, even before any shock),
  - the 2020 COVID collapse (which metrics crater - volume, hub strength - and
    which hold - density, reciprocity, modularity, the community geography),
  - the 2021 -> 2024 recovery and whether the network re-formed the SAME
    communities and the SAME hubs (year-over-year Leiden ARI/AMI on shared zones).

Per available year it computes one compact panel row of network-science
diagnostics, all on the directed, weighted, spatial graph with self-loops
excluded (the repo convention). It REUSES the single-year machinery in
``analysis.py`` (build_matrix, furness/gravity beta+CPC, structure, communities'
undirected projection) so the per-year numbers are defined identically to the
flagship 2015 numbers.

ROBUSTNESS / SELF-TEST: only 2015 is guaranteed present. The module discovers
which years actually have BOTH edges.parquet and nodes.parquet on disk (the
by_year directory may exist but be empty) and runs cleanly on whatever exists,
even a single year. It never fabricates a year it cannot read.

Outputs:
  data/processed/panel.parquet                (one row per available year)
  data/processed/community_alignment.parquet  (consecutive-year Leiden ARI/AMI)
  common.record('evolution', {...})

Run:
  python -m transportation_flow_network.evolution
"""
from __future__ import annotations

import random as pyrandom
import sys
import warnings

import igraph as ig
import networkx as nx
import numpy as np
import pandas as pd
from scipy import optimize
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score

from . import analysis, common, config as C

warnings.filterwarnings("ignore")
rng = np.random.default_rng(C.SEED)

FT_PER_MILE = 5280.0


# ---------------------------------------------------------------------------
# Year discovery
# ---------------------------------------------------------------------------
def available_years() -> list[int]:
    """Years that have BOTH an edges and a nodes table actually on disk.

    PRIMARY_YEAR resolves to the canonical top-level tables; other years live
    under by_year/<year>/. A by_year directory can exist but be empty (the heavy
    multi-year ingest is the human's job), so we test the files, not the dir.
    If nothing at all is found we fall back to PRIMARY_YEAR so the module still
    runs (it should always find 2015).
    """
    years = []
    for y in C.YEARS:
        if C.edges_path(y).exists() and C.nodes_path(y).exists():
            years.append(y)
    if not years and C.EDGES_PARQUET.exists() and C.NODES_PARQUET.exists():
        years = [C.PRIMARY_YEAR]
    return sorted(years)


# ---------------------------------------------------------------------------
# Per-year graph-level metrics that are NOT already factored in analysis.py
# ---------------------------------------------------------------------------
def _gravity_beta_cpc(ids, T, nodes: pd.DataFrame) -> tuple[float, float, float]:
    """Doubly-constrained (Furness) gravity: calibrate beta to the observed mean
    trip distance, then report CPC. Reuses analysis.furness / the same geometry
    convention so the per-year beta is the SAME quantity as the flagship 2015
    beta_doubly_constrained.
    """
    dist, has_geo = analysis._distance_matrix(ids, nodes)
    keep = np.where(has_geo)[0]
    Ts = T[np.ix_(keep, keep)]
    ds = dist[np.ix_(keep, keep)]
    if Ts.sum() == 0:
        return float("nan"), float("nan"), float("nan")
    obs_mean_dist = (Ts * ds).sum() / Ts.sum()

    def gap(beta):
        Tm = analysis.furness(Ts, ds, beta)
        return (Tm * ds).sum() / Tm.sum() - obs_mean_dist

    try:
        beta = float(optimize.brentq(gap, 0.2, 5.0))
    except ValueError:
        # observed mean distance not bracketed by beta in [0.2, 5]; report NaN
        return float("nan"), float("nan"), float(obs_mean_dist)
    Tm = analysis.furness(Ts, ds, beta)
    cpc = 2 * np.minimum(Ts, Tm).sum() / (Ts.sum() + Tm.sum())
    return beta, float(cpc), float(obs_mean_dist)


def _leiden_partition(ids, T) -> dict[int, int]:
    """Leiden (modularity) partition on the undirected weighted projection,
    returned as {zone_id -> community}. Same construction as analysis.communities
    so year-over-year alignment compares like with like. RNG seeded for
    reproducibility.
    """
    pyrandom.seed(C.SEED)
    try:
        ig.set_random_number_generator(pyrandom)
    except Exception:
        pass
    gU = analysis.undirected_igraph(ids, T)
    leiden = gU.community_leiden(objective_function="modularity", weights="weight")
    q = float(gU.modularity(leiden.membership, weights="weight"))
    mem = dict(zip(ids, list(leiden.membership)))
    return mem, len(leiden), q


def _schneider_R_random(g: nx.DiGraph, n0: int, n_seeds: int = 20,
                        step_every: int = 5) -> float:
    """Schneider robustness R under RANDOM node removal, averaged over seeds.

    R = (1/N) * sum_q S(q/N) where S is the largest-SCC fraction after q removals
    (normalised by n0, the pre-removal count). For speed on the (tiny) graph we
    sample the removal curve every ``step_every`` nodes and average across
    ``n_seeds`` orderings - random failure is near-flat on this dense graph so a
    coarse curve is faithful and SCC recompute stays sub-second. We use the giant
    SCC (round-trip reachability), the strict directed connectivity notion.
    """
    nodes = list(g.nodes())
    n = len(nodes)
    if n == 0:
        return float("nan")
    Rs = []
    for s in range(n_seeds):
        order = list(nodes)
        np.random.default_rng(C.SEED + s).shuffle(order)
        acc = 0.0
        n_steps = 0
        for q in range(0, n, step_every):
            survivors = order[q:]
            H = g.subgraph(survivors)
            if H.number_of_nodes() == 0:
                scc = 0
            else:
                scc = max((len(c) for c in nx.strongly_connected_components(H)),
                          default=0)
            acc += scc / n0
            n_steps += 1
        Rs.append(acc / n_steps)
    return float(np.mean(Rs))


def _global_efficiency_weighted(g: nx.DiGraph, nodes: pd.DataFrame) -> float:
    """Latora-Marchiori global efficiency on the distance-weighted directed graph.

    E_glob = (1/(N(N-1))) sum_{i!=j} 1/d_ij, d_ij = Euclidean centroid distance
    (miles, EPSG:2263) summed along the shortest path (Dijkstra). Unreachable
    pairs contribute 0. N=262 so all-pairs Dijkstra is trivial.
    """
    pos = nodes.set_index("zone_id")[["cx_ft", "cy_ft"]].dropna()
    gd = g.copy()
    drop = []
    for u, v, d in gd.edges(data=True):
        if u in pos.index and v in pos.index:
            dxy = ((pos.loc[u, "cx_ft"] - pos.loc[v, "cx_ft"]) ** 2 +
                   (pos.loc[u, "cy_ft"] - pos.loc[v, "cy_ft"]) ** 2) ** 0.5
            # coincident centroids would give a 0-cost edge (Dijkstra is fine
            # with 0 but it is unphysical); floor at a tiny positive distance.
            d["dmi"] = max(float(dxy) / FT_PER_MILE, 1e-9)
        else:
            drop.append((u, v))
    # edges without geometry on either end cannot carry a spatial cost: drop them
    # (a NaN weight breaks Dijkstra). N stays the full node count for the
    # normalisation, so those nodes just become harder to reach (efficiency=0).
    gd.remove_edges_from(drop)
    N = gd.number_of_nodes()
    if N < 2:
        return float("nan")
    total = 0.0
    for src, lengths in nx.all_pairs_dijkstra_path_length(gd, weight="dmi"):
        for dst, dij in lengths.items():
            if dst != src and dij and not np.isnan(dij) and dij > 0:
                total += 1.0 / dij
    return float(total / (N * (N - 1)))


def panel_row(year: int) -> dict:
    """Compute one compact panel row of diagnostics for ``year``."""
    edges = common.load_edges_annual(year)
    nodes = common.load_nodes(year)
    zones = common.load_zones()
    g = common.attach_zone_attrs(
        common.build_digraph(edges, weight="trips", drop_selfloops=True), zones)
    ids, idx, T = analysis.build_matrix(edges)

    n_nodes = g.number_of_nodes()
    n_edges = g.number_of_edges()
    total_trips = int(T.sum())  # self-loops already excluded by build_matrix
    self_trips = int(edges.loc[edges["o"] == edges["d"], "trips"].sum())

    # mean trip distance over realised (non-self) edges, trip-weighted on the
    # taximeter mean distance (mean_dist column), not the centroid distance.
    e_ns = edges[edges["o"] != edges["d"]]
    w = e_ns["trips"].to_numpy()
    md = e_ns["mean_dist"].to_numpy()
    mean_trip_distance = float((md * w).sum() / w.sum()) if w.sum() else float("nan")

    density = n_edges / (n_nodes * (n_nodes - 1)) if n_nodes > 1 else float("nan")

    # structure (reciprocity rho, assortativity, max k-core) - reuse analysis
    struct = analysis.structure(ids, T, g)

    # gravity
    beta, cpc, obs_md_centroid = _gravity_beta_cpc(ids, T, nodes)

    # communities
    mem, n_comm, modQ = _leiden_partition(ids, T)

    # robustness + efficiency
    R_rand = _schneider_R_random(g, n0=n_nodes)
    eff = _global_efficiency_weighted(g, nodes)

    # top-3 hubs by in-strength (the absorption hubs: Midtown spine + airports)
    nd = nodes.set_index("zone_id")
    in_s = T.sum(0)
    order = np.argsort(in_s)[::-1]
    top_hubs = []
    for k in order[:3]:
        z = ids[k]
        name = str(nd.loc[z, "zone"]) if z in nd.index else "?"
        top_hubs.append({"zone_id": int(z), "zone": name, "in_strength": int(in_s[k])})

    row = {
        "year": int(year),
        "n_nodes": int(n_nodes),
        "n_edges": int(n_edges),
        "density": round(float(density), 4),
        "total_trips": total_trips,
        "self_trips": self_trips,
        "mean_trip_distance_mi": round(mean_trip_distance, 3),
        "gravity_beta": round(beta, 3) if np.isfinite(beta) else None,
        "gravity_cpc": round(cpc, 3) if np.isfinite(cpc) else None,
        "degree_assortativity": struct["degree_assortativity"],
        "reciprocity_rho": struct["garlaschelli_loffredo_rho"],
        "weighted_reciprocity": struct["weighted_reciprocity"],
        "modularity_Q": round(float(modQ), 4),
        "n_communities": int(n_comm),
        "max_kcore": struct["max_kcore"],
        "global_efficiency": round(float(eff), 4) if np.isfinite(eff) else None,
        "schneider_R_random": round(float(R_rand), 4) if np.isfinite(R_rand) else None,
        "top_hubs": top_hubs,
    }
    return row, mem


# ---------------------------------------------------------------------------
# Year-to-year community stability
# ---------------------------------------------------------------------------
def community_alignment(memberships: dict[int, dict[int, int]]) -> pd.DataFrame:
    """Align CONSECUTIVE years' Leiden partitions on their shared zones via
    ARI/AMI. High ARI = the same functional districts re-formed; a dip on the
    2019->2020 or 2020->2021 boundary would say COVID re-drew the community map.
    """
    years = sorted(memberships)
    rows = []
    for a, b in zip(years[:-1], years[1:]):
        ma, mb = memberships[a], memberships[b]
        shared = sorted(set(ma) & set(mb))
        if len(shared) < 2:
            rows.append({"year_from": a, "year_to": b, "n_shared_zones": len(shared),
                         "ari": None, "ami": None})
            continue
        la = np.array([ma[z] for z in shared])
        lb = np.array([mb[z] for z in shared])
        rows.append({
            "year_from": a, "year_to": b,
            "n_shared_zones": len(shared),
            "ari": round(float(adjusted_rand_score(la, lb)), 4),
            "ami": round(float(adjusted_mutual_info_score(la, lb)), 4),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Narrative summary derived from the panel
# ---------------------------------------------------------------------------
def _evolution_story(panel: pd.DataFrame) -> dict:
    """Distil the panel into the headline evolution numbers, computed only from
    the years actually present (no fabrication)."""
    p = panel.set_index("year")
    yrs = list(p.index)
    story = {"years_processed": yrs, "n_years": len(yrs)}

    def vol(y):
        return float(p.loc[y, "total_trips"]) if y in p.index else None

    # ride-hailing-era decline 2015 -> 2019
    if 2015 in p.index and 2019 in p.index and vol(2015):
        story["volume_change_2015_2019_pct"] = round(100.0 * (vol(2019) - vol(2015)) / vol(2015), 1)
    # COVID collapse: 2019 -> 2020
    if 2019 in p.index and 2020 in p.index and vol(2019):
        story["covid_collapse_2019_2020_pct"] = round(100.0 * (vol(2020) - vol(2019)) / vol(2019), 1)
    # recovery: 2020 -> last available year, and recovery ratio vs 2019
    last = yrs[-1]
    if 2020 in p.index and last != 2020 and vol(2020):
        story["recovery_2020_to_%d_pct" % last] = round(100.0 * (vol(last) - vol(2020)) / vol(2020), 1)
    if 2019 in p.index and last in p.index and vol(2019):
        story["volume_vs_2019_at_%d_pct" % last] = round(100.0 * vol(last) / vol(2019), 1)

    # which structural metrics hold vs break: coefficient of variation across years
    invariants = {}
    for col in ["density", "degree_assortativity", "reciprocity_rho",
                "weighted_reciprocity", "modularity_Q", "n_communities",
                "max_kcore", "gravity_beta", "gravity_cpc", "global_efficiency"]:
        if col in p.columns:
            vals = p[col].dropna().astype(float)
            if len(vals) >= 2 and vals.abs().mean() > 0:
                cv = float(vals.std() / vals.abs().mean())
                invariants[col] = {"mean": round(float(vals.mean()), 4),
                                   "cv": round(cv, 4),
                                   "min": round(float(vals.min()), 4),
                                   "max": round(float(vals.max()), 4)}
    story["structural_metric_variation"] = invariants
    # volume CV for contrast (the thing that DOES move)
    vvals = p["total_trips"].dropna().astype(float)
    if len(vvals) >= 2 and vvals.mean() > 0:
        story["total_trips_cv"] = round(float(vvals.std() / vvals.mean()), 4)
    return story


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> None:
    years = available_years()
    print(f"[evolution] discovered years on disk: {years}")
    if not years:
        print("[evolution] no per-year tables found; nothing to do.")
        return

    rows = []
    memberships: dict[int, dict[int, int]] = {}
    for y in years:
        print(f"[evolution] processing {y} ...")
        row, mem = panel_row(y)
        rows.append(row)
        memberships[y] = mem
        print(f"    {y}: {row['n_nodes']} nodes / {row['n_edges']:,} edges, "
              f"{row['total_trips']:,} trips, beta={row['gravity_beta']}, "
              f"Q={row['modularity_Q']} ({row['n_communities']} comms), "
              f"max k-core={row['max_kcore']}, E_glob={row['global_efficiency']}")

    panel = pd.DataFrame(rows).sort_values("year").reset_index(drop=True)
    # top_hubs is a list-of-dicts; parquet handles it, but stringify for safety
    panel_out = panel.copy()
    panel_out["top_hubs"] = panel_out["top_hubs"].apply(
        lambda hs: "; ".join(f"{h['zone']}({h['in_strength']})" for h in hs))
    panel_out.to_parquet(C.PROCESSED / "panel.parquet", index=False)

    align = community_alignment(memberships)
    align.to_parquet(C.PROCESSED / "community_alignment.parquet", index=False)

    story = _evolution_story(panel)

    # record into the single source of truth. The top-level 'evolution' section
    # holds the cross-year story; record_year mirrors each panel row under
    # by_year/<year>/evolution so the per-year site/summary can pick it up.
    common.record("evolution", {
        "panel": panel.to_dict(orient="records"),
        "community_alignment": align.to_dict(orient="records"),
        "story": story,
        "notes": "Per-year diagnostics on the directed/weighted/spatial taxi-flow "
                 "graph (self-loops excluded). beta/CPC are the doubly-constrained "
                 "Furness gravity (same definition as analysis.gravity_residual_field). "
                 "Leiden on the undirected weighted projection. Schneider R is "
                 "random-failure only (giant SCC, seed-averaged, coarse-stepped) - "
                 "random failure is near-flat on this dense graph; targeted-attack "
                 "robustness lives in the single-year robustness module.",
    })
    for r in rows:
        common.record_year("evolution", r["year"], r)

    # console headline
    print("\n[evolution] === panel ===")
    cols = ["year", "n_nodes", "n_edges", "total_trips", "mean_trip_distance_mi",
            "gravity_beta", "gravity_cpc", "reciprocity_rho", "degree_assortativity",
            "modularity_Q", "n_communities", "max_kcore", "global_efficiency",
            "schneider_R_random"]
    print(panel[cols].to_string(index=False))
    if len(align):
        print("\n[evolution] === consecutive-year community alignment (Leiden ARI/AMI) ===")
        print(align.to_string(index=False))
    print("\n[evolution] === story ===")
    for k, v in story.items():
        if k not in ("structural_metric_variation",):
            print(f"    {k}: {v}")
    if len(years) == 1:
        print(f"[evolution] only {years[0]} present - single-year self-test run; "
              "the COVID/recovery story activates once the multi-year ingest lands.")


if __name__ == "__main__":
    sys.exit(main())
