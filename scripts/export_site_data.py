"""Export compact web data for the project site's interactive map.

Writes site/data/{zones.geojson, top_edges.json, summary.json}: zone polygons
(simplified, WGS84) with per-zone attributes including per-daypart destination
volume and net-flow index (to power a day/night toggle), the top OD edges with
centroids for an arc overlay, and the headline metrics.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd

from transportation_flow_network import common, config as C

PERIODS = ["am_peak", "midday", "pm_peak", "evening", "late_night_weekend"]
OUT = C.ROOT / "site" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def _round_coords(c):
    if isinstance(c, (int, float)):
        return round(c, 5)
    return [_round_coords(x) for x in c]


def main() -> None:
    zones = gpd.read_parquet(C.ZONES_PARQUET)
    na = pd.read_parquet(C.PROCESSED / "node_analysis.parquet").set_index("zone_id")
    nd = common.load_nodes().set_index("zone_id")
    ep = common.load_edges_period()
    ep = ep[ep["o"] != ep["d"]]
    edges = common.load_edges_annual()
    edges = edges[edges["o"] != edges["d"]]

    # per-zone, per-daypart out/in strength
    per = {}
    for p in PERIODS:
        s = ep[ep["period"] == p]
        per[p] = (s.groupby("o")["trips"].sum(), s.groupby("d")["trips"].sum())

    zs = zones.copy()
    zs["geometry"] = zs.geometry.simplify(200).buffer(0)
    zs = zs.to_crs(4326)

    def gv(idx, frame, col, ndig=None, cast=float):
        if idx not in frame.index or pd.isna(frame.loc[idx, col]):
            return None
        v = frame.loc[idx, col]
        return cast(v) if ndig is None else round(float(v), ndig)

    feats = []
    for r in zs.itertuples():
        z = int(r.zone_id)
        props = {
            "zone_id": z, "zone": r.zone, "borough": r.borough,
            "service_zone": r.service_zone,
            "community": gv(z, na, "leiden_community", cast=int),
            "gravity_surprise": gv(z, na, "gravity_surprise", 2),
            "nfi_annual": gv(z, nd, "net_flow_index", 3),
            "in_strength": int(nd.loc[z, "in_strength"]) if z in nd.index else 0,
            "out_strength": int(nd.loc[z, "out_strength"]) if z in nd.index else 0,
            "rhythm_cluster": gv(z, na, "rhythm_cluster", cast=int),
        }
        for p in PERIODS:
            o, d = per[p]
            oi, di = float(o.get(z, 0)), float(d.get(z, 0))
            props[f"in_{p}"] = int(di)
            props[f"nfi_{p}"] = round((oi - di) / (oi + di), 3) if (oi + di) > 0 else None
        geom = json.loads(gpd.GeoSeries([r.geometry], crs=4326).to_json())["features"][0]["geometry"]
        geom["coordinates"] = _round_coords(geom["coordinates"])
        feats.append({"type": "Feature", "properties": props, "geometry": geom})

    gj = {"type": "FeatureCollection", "features": feats}
    (OUT / "zones.geojson").write_text(json.dumps(gj))
    print(f"zones.geojson: {len(feats)} features, {len(json.dumps(gj))//1024} KB")

    cent = zones.to_crs(4326).set_index("zone_id")
    top = edges.sort_values("trips", ascending=False).head(600)
    ej = []
    for r in top.itertuples():
        if r.o in cent.index and r.d in cent.index:
            a, b = cent.loc[r.o].geometry.centroid, cent.loc[r.d].geometry.centroid
            ej.append({"o": int(r.o), "d": int(r.d), "trips": int(r.trips),
                       "from": [round(a.y, 5), round(a.x, 5)], "to": [round(b.y, 5), round(b.x, 5)]})
    (OUT / "top_edges.json").write_text(json.dumps(ej))
    print(f"top_edges.json: {len(ej)} edges")

    (OUT / "summary.json").write_text((C.METRICS_SUMMARY_JSON).read_text())
    print("summary.json written")


if __name__ == "__main__":
    main()
