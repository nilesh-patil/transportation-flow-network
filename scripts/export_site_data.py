"""Export compact web data for the project site's interactive map.

Writes site/data/{zones.geojson, top_edges.json, summary.json}.

The map is year-aware (2015-2024). Zone geometry is stored ONCE per zone
(simplified, WGS84); every year-varying scalar lives under
``properties.years["<year>"]`` so the file carries the whole decade without
duplicating polygons. Per year and per zone we record the gravity-model residual
(recomputed from that year's own flows), the annual net-flow index, the in/out
strength, and per-daypart destination volume and net-flow index. Top OD edges are
exported per year for the arc overlay.

The Leiden community is exported as a single static field (the canonical 2015
reference partition, the same one the community names describe). Per-year Leiden
labels are stochastic for the handful of zones that sit on a community boundary,
so coloring them year by year would read as instability that the data does not
support (consecutive-year community agreement averages ARI 0.88; see figure 28).
The community lens therefore shows the stable reference partition and the slider
drives the three quantitative lenses.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd

from transportation_flow_network import analysis, common, config as C

PERIODS = ["am_peak", "midday", "pm_peak", "evening", "late_night_weekend"]
TOP_EDGES_PER_YEAR = 400
OUT = C.ROOT / "site" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def _round_coords(c):
    if isinstance(c, (int, float)):
        return round(c, 5)
    return [_round_coords(x) for x in c]


def available_years() -> list[int]:
    """Years with both an annual edge list and a node table on disk."""
    ys = []
    for y in C.YEARS:
        try:
            if C.edges_path(y).exists() and C.nodes_path(y).exists():
                ys.append(int(y))
        except Exception:
            continue
    if not ys:  # fall back to the primary-year top-level tables
        ys = [int(C.PRIMARY_YEAR)]
    return sorted(ys)


def year_layer(year: int, cent: gpd.GeoDataFrame):
    """Compute every per-zone, year-varying scalar for one year.

    Returns ``(per_zone, edges_records)`` where per_zone maps zone_id -> the small
    property dict the map reads.
    """
    edges = common.load_edges_annual(year)
    edges = edges[edges["o"] != edges["d"]]
    nodes = common.load_nodes(year).set_index("zone_id")
    ep = common.load_edges_period(year)
    ep = ep[ep["o"] != ep["d"]]

    ids, _, T = analysis.build_matrix(edges)

    # gravity residual field, recomputed from this year's own flows
    _, zr, _ = analysis.gravity_residual_field(ids, T, nodes.reset_index())
    surprise = zr.set_index("zone_id")["gravity_surprise"].to_dict()

    # per-daypart out/in strength
    per = {}
    for p in PERIODS:
        s = ep[ep["period"] == p]
        per[p] = (s.groupby("o")["trips"].sum(), s.groupby("d")["trips"].sum())

    per_zone = {}
    all_ids = set(nodes.index) | set(ids) | set(surprise)
    for z in all_ids:
        gs = surprise.get(z)
        rec = {
            "gs": round(float(gs), 2) if gs is not None and np.isfinite(gs) else None,
            "nfa": round(float(nodes.loc[z, "net_flow_index"]), 3) if z in nodes.index else None,
            "ins": int(nodes.loc[z, "in_strength"]) if z in nodes.index else 0,
            "outs": int(nodes.loc[z, "out_strength"]) if z in nodes.index else 0,
            "v": {},
            "nf": {},
        }
        for p in PERIODS:
            o, d = per[p]
            oi, di = float(o.get(z, 0)), float(d.get(z, 0))
            rec["v"][p] = int(di)
            rec["nf"][p] = round((oi - di) / (oi + di), 3) if (oi + di) > 0 else None
        per_zone[z] = rec

    # top OD edges for the arc overlay (with endpoint centroids)
    top = edges.sort_values("trips", ascending=False).head(TOP_EDGES_PER_YEAR)
    erecs = []
    for r in top.itertuples():
        if r.o in cent.index and r.d in cent.index:
            a, b = cent.loc[r.o].geometry.centroid, cent.loc[r.d].geometry.centroid
            erecs.append({"o": int(r.o), "d": int(r.d), "trips": int(r.trips),
                          "from": [round(a.y, 5), round(a.x, 5)],
                          "to": [round(b.y, 5), round(b.x, 5)]})
    return per_zone, erecs


def main() -> None:
    years = available_years()
    print(f"[site] exporting years {years[0]}-{years[-1]} ({len(years)} years)")

    zones = gpd.read_parquet(C.ZONES_PARQUET)
    cent = zones.to_crs(4326).set_index("zone_id")
    zs = zones.copy()
    zs["geometry"] = zs.geometry.simplify(200).buffer(0)
    zs = zs.to_crs(4326)

    # static community = the canonical 2015 reference partition (matches the
    # community names on the map); see the module docstring for why it is not
    # varied year by year.
    na = pd.read_parquet(C.PROCESSED / "node_analysis.parquet").set_index("zone_id")

    # compute every year's quantitative layer
    layers, edges_by_year = {}, {}
    for y in years:
        per_zone, erecs = year_layer(y, cent)
        layers[y] = per_zone
        edges_by_year[str(y)] = erecs
        print(f"  [site] {y}: {len(erecs)} edges, {sum(1 for v in per_zone.values() if v['gs'] is not None)} zones with a residual")

    feats = []
    for r in zs.itertuples():
        z = int(r.zone_id)
        years_obj = {}
        for y in years:
            rec = layers[y].get(z)
            if rec is not None:
                years_obj[str(y)] = rec
        com = na.loc[z, "leiden_community"] if z in na.index and pd.notna(na.loc[z, "leiden_community"]) else None
        props = {
            "zone_id": z, "zone": r.zone, "borough": r.borough,
            "service_zone": r.service_zone,
            "community": int(com) if com is not None else None,
            "years": years_obj,
        }
        geom = json.loads(gpd.GeoSeries([r.geometry], crs=4326).to_json())["features"][0]["geometry"]
        geom["coordinates"] = _round_coords(geom["coordinates"])
        feats.append({"type": "Feature", "properties": props, "geometry": geom})

    gj = {"type": "FeatureCollection", "years": [str(y) for y in years], "features": feats}
    (OUT / "zones.geojson").write_text(json.dumps(gj))
    print(f"zones.geojson: {len(feats)} features x {len(years)} years, {len(json.dumps(gj))//1024} KB")

    edges_out = {"years": [str(y) for y in years], "by_year": edges_by_year}
    (OUT / "top_edges.json").write_text(json.dumps(edges_out))
    print(f"top_edges.json: {sum(len(v) for v in edges_by_year.values())} edges across {len(years)} years")

    (OUT / "summary.json").write_text((C.METRICS_SUMMARY_JSON).read_text())
    print("summary.json written")


if __name__ == "__main__":
    main()
