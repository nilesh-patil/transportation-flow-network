"""Stage 5: faithful core metrics (the original findings 3, 7, 8, 9).

* degree / strength distribution summaries (full vs filtered)
* hub asymmetry: trips-per-source for the top hubs (Penn/MSG high, JFK/LGA low)
* "where Manhattan ends" - the simple in-degree-to-trips ratio ranking
  (the model-based gravity-residual version lives in analysis.py)
* baseline single-seed Louvain community count (the 2016 method, reproduced)

Writes ``processed/hub_asymmetry.parquet`` and ``processed/manhattan_ends.parquet``
and records scalars to the results store.
"""
from __future__ import annotations

import sys

import community as community_louvain
import networkx as nx
import numpy as np
import pandas as pd

from . import common, config as C


def _undirected_projection(g: nx.DiGraph) -> nx.Graph:
    u = nx.Graph()
    for a, b, d in g.edges(data=True):
        w = d.get("trips", 1)
        if u.has_edge(a, b):
            u[a][b]["weight"] += w
        else:
            u.add_edge(a, b, weight=w)
    return u


def hub_asymmetry(nodes: pd.DataFrame) -> pd.DataFrame:
    """trips-per-source = in-strength / number of distinct origin zones."""
    df = nodes.copy()
    df["trips_per_source"] = df["in_strength"] / df["in_degree"].replace(0, np.nan)
    df = df.sort_values("in_strength", ascending=False)
    df.to_parquet(C.PROCESSED / "hub_asymmetry.parquet", index=False)

    def find(sub: str) -> pd.Series | None:
        hit = df[df["zone"].str.contains(sub, case=False, na=False)]
        return hit.iloc[0] if len(hit) else None

    named = {}
    for label, sub in [("penn_station", "Penn"), ("midtown_center", "Midtown Center"),
                       ("times_sq", "Times Sq"), ("jfk", "JFK"), ("laguardia", "LaGuardia"),
                       ("east_village", "East Village"), ("lower_east_side", "Lower East Side")]:
        s = find(sub)
        if s is not None:
            named[label] = {
                "zone": s["zone"], "in_strength": int(s["in_strength"]),
                "in_degree": int(s["in_degree"]),
                "trips_per_source": round(float(s["trips_per_source"]), 1),
            }
    return df, named


def manhattan_ends(nodes: pd.DataFrame) -> pd.DataFrame:
    """Rank zones by trips-per-source; low = peripheral / 'suburb-like'."""
    df = nodes.copy()
    df["trips_per_source"] = df["in_strength"] / df["in_degree"].replace(0, np.nan)
    # restrict to zones with meaningful volume so 1-source noise can't dominate
    active = df[df["in_strength"] >= 1000].copy()
    active["periphery_rank"] = active["trips_per_source"].rank(method="min")
    active["periphery_pct"] = active["trips_per_source"].rank(pct=True)
    active = active.sort_values("trips_per_source")
    active.to_parquet(C.PROCESSED / "manhattan_ends.parquet", index=False)
    return active


def baseline_community(g_filtered: nx.DiGraph) -> dict:
    u = _undirected_projection(g_filtered)
    part = community_louvain.best_partition(u, weight="weight", random_state=C.SEED)
    q = community_louvain.modularity(part, u, weight="weight")
    n_comm = len(set(part.values()))
    return {"method": "python-louvain (single seed, undirected projection)",
            "seed": C.SEED, "n_communities": n_comm, "modularity_Q": round(q, 4),
            "n_nodes": u.number_of_nodes(), "n_edges": u.number_of_edges()}


def main() -> None:
    edges = common.load_edges_annual()
    nodes = common.load_nodes()
    zones = common.load_zones()

    g_filt = common.attach_zone_attrs(
        common.build_digraph(edges, threshold=C.EDGE_WEIGHT_THRESHOLD), zones)

    # degree/strength summaries
    deg_summary = {
        "full_in_degree_max": int(nodes["in_degree"].max()),
        "full_out_degree_max": int(nodes["out_degree"].max()),
        "full_mean_in_degree": round(float(nodes["in_degree"].mean()), 1),
        "filtered_edges": g_filt.number_of_edges(),
        "filtered_nodes": g_filt.number_of_nodes(),
    }

    _, hub_named = hub_asymmetry(nodes)
    me = manhattan_ends(nodes)
    comm = baseline_community(g_filt)

    # locate East Village / LES in the periphery ranking
    ev = me[me["zone"].str.contains("East Village|Lower East Side|Alphabet", case=False, na=False)]
    ev_summary = [{"zone": r["zone"], "trips_per_source": round(float(r["trips_per_source"]), 1),
                   "periphery_pct": round(float(r["periphery_pct"]), 3)} for _, r in ev.iterrows()]

    common.record("metrics", {
        "degree_summary": deg_summary,
        "hub_asymmetry": hub_named,
        "baseline_community": comm,
        "manhattan_ends_examples": ev_summary,
        "manhattan_ends_most_peripheral": [
            {"zone": r["zone"], "trips_per_source": round(float(r["trips_per_source"]), 1)}
            for _, r in me.head(8).iterrows()],
    })

    print("[metrics] hub asymmetry (trips per source):")
    for k, v in hub_named.items():
        print(f"    {v['zone']:32s} {v['trips_per_source']:8.1f}  (in={v['in_strength']:,} from {v['in_degree']} sources)")
    print(f"[metrics] baseline Louvain: {comm['n_communities']} communities, Q={comm['modularity_Q']}")
    print("[metrics] most 'suburb-like' (lowest trips/source) zones:")
    for r in me.head(6).itertuples():
        print(f"    {r.zone:32s} {r.trips_per_source:8.1f}")


if __name__ == "__main__":
    sys.exit(main())
