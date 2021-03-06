"""Stage 2: prepare geographies in EPSG:2263.

Produces three artifacts, all in NY State Plane (ft):

* ``data/geo/nyc_tracts_2263.parquet`` - the ~2,165 NYC 2010 census tracts,
  built by dissolving the in-repo ``nycb2010`` block shapefile up to tracts.
  (This is the brief's offline-deterministic tract source; ``pygris`` is the
  documented online alternative. We honour the spatial-join machinery even
  though the trip data is now zone-level.)
* ``data/geo/zones_2263.parquet`` - the 263 TLC taxi zones (the trip data's
  native geography) with centroids, area, borough and service zone.
* ``data/processed/zone_tract_crosswalk.parquet`` - each zone's representative
  census tract (containing its centroid) plus how many tracts it overlaps,
  demonstrating the EPSG:2263 spatial join and quantifying the resolution gap.
"""
from __future__ import annotations

import sys

import geopandas as gpd
import pandas as pd

from . import config as C


# ---------------------------------------------------------------------------
# Census tracts (offline dissolve of NYC 2010 blocks)
# ---------------------------------------------------------------------------
def build_tracts() -> gpd.GeoDataFrame:
    blocks = gpd.read_file(C.NYC_BLOCKS_SHP)
    # The .prj is NY State Plane LI (ftUS) == EPSG:2263; force the code so
    # downstream joins/areas are unambiguous.
    blocks = blocks.set_crs(C.NY_STATE_PLANE, allow_override=True)

    # Build the federal 11-digit tract GEOID: state(2)+county(3)+tract(6).
    fips = blocks["BoroCode"].map(lambda b: C.BORO_TO_FIPS.get(str(b), ("000", "?"))[0])
    boro = blocks["BoroCode"].map(lambda b: C.BORO_TO_FIPS.get(str(b), ("000", "?"))[1])
    blocks["GEOID"] = C.STATE_FIPS + fips + blocks["CT2010"].astype(str).str.zfill(6)
    blocks["borough"] = boro

    tracts = blocks.dissolve(by="GEOID", aggfunc={"borough": "first"}).reset_index()
    tracts["geometry"] = tracts.geometry.buffer(0)  # repair any self-intersections
    cent = tracts.geometry.centroid
    tracts["cx_ft"] = cent.x
    tracts["cy_ft"] = cent.y
    cent_ll = cent.to_crs(C.WGS84)
    tracts["lon"] = cent_ll.x
    tracts["lat"] = cent_ll.y
    tracts["area_sqmi"] = tracts.geometry.area / 27_878_400.0  # sq ft -> sq mi
    tracts = tracts[["GEOID", "borough", "cx_ft", "cy_ft", "lon", "lat", "area_sqmi", "geometry"]]
    tracts.to_parquet(C.TRACTS_PARQUET)
    return tracts


# ---------------------------------------------------------------------------
# Taxi zones (native trip geography)
# ---------------------------------------------------------------------------
def build_zones() -> gpd.GeoDataFrame:
    z = gpd.read_file(C.TAXI_ZONES_SHP).set_crs(C.NY_STATE_PLANE, allow_override=True)
    z = z.rename(columns={"LocationID": "zone_id"})
    z["zone_id"] = z["zone_id"].astype(int)
    z = z[z["zone_id"].between(C.VALID_ZONE_MIN, C.VALID_ZONE_MAX)].copy()
    z["geometry"] = z.geometry.buffer(0)
    # A few zones (Corona, the harbor islands) are stored as multiple rows;
    # dissolve so each LocationID is a single (multi)polygon.
    z = z.dissolve(by="zone_id", aggfunc={"zone": "first", "borough": "first"}).reset_index()

    # service_zone (Yellow Zone / Boro Zone / Airports / EWR) from the lookup
    if C.ZONE_LOOKUP_CSV.exists():
        lk = pd.read_csv(C.ZONE_LOOKUP_CSV)[["LocationID", "service_zone"]]
        lk = lk.rename(columns={"LocationID": "zone_id"})
        z = z.merge(lk, on="zone_id", how="left")
    else:
        z["service_zone"] = None

    cent = z.geometry.centroid
    z["cx_ft"] = cent.x
    z["cy_ft"] = cent.y
    cent_ll = cent.to_crs(C.WGS84)
    z["lon"] = cent_ll.x
    z["lat"] = cent_ll.y
    z["area_sqmi"] = z.geometry.area / 27_878_400.0
    z = z[["zone_id", "zone", "borough", "service_zone", "cx_ft", "cy_ft", "lon", "lat", "area_sqmi", "geometry"]]
    z = z.sort_values("zone_id").reset_index(drop=True)
    z.to_parquet(C.ZONES_PARQUET)
    return z


# ---------------------------------------------------------------------------
# Zone -> tract crosswalk (demonstrates the EPSG:2263 spatial join)
# ---------------------------------------------------------------------------
def build_crosswalk(zones: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame) -> pd.DataFrame:
    # Representative tract = the tract that contains each zone's centroid.
    zc = zones[["zone_id", "geometry"]].copy()
    zc["geometry"] = gpd.points_from_xy(zones["cx_ft"], zones["cy_ft"])
    zc = zc.set_crs(C.NY_STATE_PLANE)
    rep = gpd.sjoin(zc, tracts[["GEOID", "geometry"]], how="left", predicate="within")
    rep = rep[["zone_id", "GEOID"]].rename(columns={"GEOID": "rep_tract"})

    # How many tracts each zone overlaps (resolution-gap evidence).
    ov = gpd.sjoin(
        zones[["zone_id", "geometry"]], tracts[["GEOID", "geometry"]],
        how="left", predicate="intersects",
    )
    n_tracts = ov.groupby("zone_id")["GEOID"].nunique().rename("n_tracts_overlapped")

    cw = rep.merge(n_tracts, on="zone_id", how="left")
    cw["n_tracts_overlapped"] = cw["n_tracts_overlapped"].fillna(0).astype(int)
    cw.to_parquet(C.CROSSWALK_PARQUET, index=False)
    return cw


def main() -> None:
    print("[geo] building NYC census tracts (dissolve of 2010 blocks)...")
    tracts = build_tracts()
    print(f"[geo]   {len(tracts):,} census tracts -> {C.TRACTS_PARQUET.name}")

    print("[geo] building TLC taxi zones...")
    zones = build_zones()
    print(f"[geo]   {len(zones):,} taxi zones -> {C.ZONES_PARQUET.name}")

    print("[geo] building zone -> tract crosswalk (EPSG:2263 spatial join)...")
    cw = build_crosswalk(zones, tracts)
    mean_overlap = cw["n_tracts_overlapped"].mean()
    print(f"[geo]   each taxi zone overlaps {mean_overlap:.1f} census tracts on average")
    print(f"[geo]   -> a taxi zone is ~{mean_overlap:.0f}x coarser than a tract; "
          f"{len(tracts):,} tracts vs {len(zones):,} zones")


if __name__ == "__main__":
    sys.exit(main())
