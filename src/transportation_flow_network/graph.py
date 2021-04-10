"""Stage 4: collapse the period edge list to an annual weighted DiGraph.

Writes:
* ``processed/edges.parquet`` - annual (origin, dest) -> trip count + weighted
  mean trip distance / fare / duration.
* ``processed/nodes.parquet`` - one row per zone with attributes and in/out
  strength + degree (self-loops excluded from strength, reported separately).

Records full-vs-filtered (> 500 trips/yr) node and edge counts to the results
store and reconciles them against the blog's headline figures.
"""
from __future__ import annotations

import sys

import pandas as pd

from . import common, config as C


def build_annual_edges() -> pd.DataFrame:
    ep = common.load_edges_period()
    annual = ep.groupby(["o", "d"], as_index=False).agg(
        trips=("trips", "sum"), sum_dist=("sum_dist", "sum"),
        sum_fare=("sum_fare", "sum"), sum_dur=("sum_dur", "sum"))
    annual["mean_dist"] = annual["sum_dist"] / annual["trips"]
    annual["mean_fare"] = annual["sum_fare"] / annual["trips"]
    annual["mean_dur"] = annual["sum_dur"] / annual["trips"]
    annual.to_parquet(C.EDGES_PARQUET, index=False)
    return annual


def build_node_table(annual: pd.DataFrame) -> pd.DataFrame:
    no_self = annual[annual["o"] != annual["d"]]
    out = no_self.groupby("o").agg(out_strength=("trips", "sum"),
                                   out_degree=("d", "nunique")).rename_axis("zone_id")
    inn = no_self.groupby("d").agg(in_strength=("trips", "sum"),
                                   in_degree=("o", "nunique")).rename_axis("zone_id")
    self_loops = (annual[annual["o"] == annual["d"]]
                  .set_index("o")["trips"].rename("self_trips").rename_axis("zone_id"))

    # Index over geocoded zones UNION active edge endpoints, so flow-only zones
    # (a few TLC island variant ids the shapefile collapses) are not silently
    # dropped from the node table.
    zones = common.load_zones().drop(columns="geometry").set_index("zone_id")
    active = out.index.union(inn.index).union(self_loops.index)
    full_idx = zones.index.union(active)
    nodes = zones.reindex(full_idx)
    nodes.index.name = "zone_id"
    nodes = nodes.join([out, inn, self_loops]).reset_index()
    for col in ["out_strength", "in_strength", "out_degree", "in_degree", "self_trips"]:
        nodes[col] = nodes[col].fillna(0).astype(int)
    nodes["total_trips"] = nodes["out_strength"] + nodes["in_strength"]
    # net-flow index: +1 pure source, -1 pure sink
    denom = (nodes["out_strength"] + nodes["in_strength"]).replace(0, 1)
    nodes["net_flow_index"] = (nodes["out_strength"] - nodes["in_strength"]) / denom
    nodes.to_parquet(C.NODES_PARQUET, index=False)
    return nodes


def main() -> None:
    print("[graph] building annual edge list...")
    annual = build_annual_edges()
    nodes = build_node_table(annual)

    no_self = annual[annual["o"] != annual["d"]]
    total_trips = int(annual["trips"].sum())
    self_trips = int(annual.loc[annual["o"] == annual["d"], "trips"].sum())
    filt = no_self[no_self["trips"] > C.EDGE_WEIGHT_THRESHOLD]

    active_nodes = pd.unique(no_self[["o", "d"]].values.ravel())
    filt_nodes = pd.unique(filt[["o", "d"]].values.ravel())

    stats = {
        "total_trips": total_trips,
        "self_loop_trips": self_trips,
        "self_loop_share_pct": round(100.0 * self_trips / total_trips, 3),
        "n_zones_geocoded": int(len(common.load_zones())),
        "n_nodes_active": int(len(active_nodes)),
        "n_nodes_table": int(len(nodes)),
        "n_edges_full": int(len(no_self)),
        "edge_weight_threshold": C.EDGE_WEIGHT_THRESHOLD,
        "n_nodes_filtered": int(len(filt_nodes)),
        "n_edges_filtered": int(len(filt)),
        "blog_tract_nodes": C.BLOG_HEADLINE["tract_nodes"],
        "blog_top_edges": C.BLOG_HEADLINE["top_edges"],
    }
    common.record("graph", stats)
    print(f"[graph] total trips (incl self-loops): {total_trips:,}")
    print(f"[graph] self-loop share: {stats['self_loop_share_pct']}%")
    print(f"[graph] FULL graph : {stats['n_nodes_active']} nodes, {stats['n_edges_full']:,} edges")
    print(f"[graph] FILTERED (>{C.EDGE_WEIGHT_THRESHOLD}/yr): "
          f"{stats['n_nodes_filtered']} nodes, {stats['n_edges_filtered']:,} edges")
    print(f"[graph] (blog: {C.BLOG_HEADLINE['tract_nodes']} tract nodes, "
          f"{C.BLOG_HEADLINE['top_edges']} top edges - different geography)")


if __name__ == "__main__":
    sys.exit(main())
