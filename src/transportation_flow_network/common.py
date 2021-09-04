"""Shared helpers: a results store, data loaders, and graph construction.

Every downstream module records its measured numbers into a single JSON
(``processed/metrics_summary.json``) via :func:`record`, so the README,
MODERNIZATION_NOTES, paper and final terminal summary all read one source of
truth.
"""
from __future__ import annotations

import json
from typing import Any

import geopandas as gpd
import networkx as nx
import pandas as pd

from . import config as C


# ---------------------------------------------------------------------------
# Results store
# ---------------------------------------------------------------------------
def load_results() -> dict:
    if C.METRICS_SUMMARY_JSON.exists():
        return json.loads(C.METRICS_SUMMARY_JSON.read_text())
    return {}


def record(section: str, payload: dict[str, Any]) -> None:
    """Merge ``payload`` into ``results[section]`` and persist."""
    res = load_results()
    res.setdefault(section, {})
    res[section].update(_jsonable(payload))
    C.METRICS_SUMMARY_JSON.write_text(json.dumps(res, indent=2, default=str))


def record_year(section: str, year: int, payload: dict[str, Any]) -> None:
    """Namespace per-year metrics under results['by_year'][str(year)][section].

    Writes into the SAME top-level metrics_summary.json (the source of truth the
    site/summary read) without disturbing the existing top-level ``record``
    sections. Year is coerced to a string key for JSON stability.
    """
    res = load_results()
    by_year = res.setdefault("by_year", {})
    yr = by_year.setdefault(str(year), {})
    yr.setdefault(section, {})
    yr[section].update(_jsonable(payload))
    C.METRICS_SUMMARY_JSON.write_text(json.dumps(res, indent=2, default=str))


def _jsonable(obj):
    import numpy as np
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_zones() -> gpd.GeoDataFrame:
    return gpd.read_parquet(C.ZONES_PARQUET)


def load_edges_period(year: int = C.PRIMARY_YEAR) -> pd.DataFrame:
    return pd.read_parquet(C.edges_period_path(year))


def load_edges_annual(year: int = C.PRIMARY_YEAR) -> pd.DataFrame:
    """Annual (origin, dest) edge list with trip count and weighted means.

    ``year`` defaults to PRIMARY_YEAR, which reads the canonical top-level
    edges.parquet (identical behavior to the original zero-arg call). Any other
    year reads data/processed/by_year/<year>/edges.parquet.
    """
    return pd.read_parquet(C.edges_path(year))


def load_nodes(year: int = C.PRIMARY_YEAR) -> pd.DataFrame:
    return pd.read_parquet(C.nodes_path(year))


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def build_digraph(edges: pd.DataFrame, weight: str = "trips",
                  drop_selfloops: bool = True, threshold: int | None = None) -> nx.DiGraph:
    """Build a weighted DiGraph from an annual edge list.

    Parameters
    ----------
    drop_selfloops : intra-zone (i->i) trips are excluded by default - they
        break distance-based methods (d_ii = 0) and are not network flow.
    threshold : keep only edges with weight strictly greater than this.
    """
    df = edges
    if drop_selfloops:
        df = df[df["o"] != df["d"]]
    if threshold is not None:
        df = df[df[weight] > threshold]
    g = nx.from_pandas_edgelist(
        df, source="o", target="d", edge_attr=True, create_using=nx.DiGraph)
    return g


def attach_zone_attrs(g: nx.DiGraph, zones: gpd.GeoDataFrame) -> nx.DiGraph:
    attrs = zones.set_index("zone_id")[
        ["zone", "borough", "service_zone", "lon", "lat", "cx_ft", "cy_ft", "area_sqmi"]
    ].to_dict("index")
    nx.set_node_attributes(g, {n: attrs.get(n, {}) for n in g.nodes})
    return g


def load_graph(year: int = C.PRIMARY_YEAR, weight: str = "trips",
               drop_selfloops: bool = True, threshold: int | None = None) -> nx.DiGraph:
    """Convenience: load the annual edges for ``year``, build the DiGraph and
    attach zone attributes in one call.

    Geometry/zone attributes are year-invariant (taxi zones are fixed), so the
    same zones_2263 table is used for every year. ``year`` defaults to
    PRIMARY_YEAR (the canonical top-level tables).
    """
    edges = load_edges_annual(year)
    zones = load_zones()
    g = build_digraph(edges, weight=weight, drop_selfloops=drop_selfloops,
                      threshold=threshold)
    return attach_zone_attrs(g, zones)
