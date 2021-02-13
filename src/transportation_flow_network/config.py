"""Shared configuration: paths, projections, cleaning bounds, analysis constants.

Every module imports from here so that a single edit changes the whole pipeline.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (anchored at the repository root, two levels up from this file)
# ---------------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parents[1]  # src/transportation_flow_network/ -> repo root

DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
GEO = DATA / "geo"
FIGURES = ROOT / "figures"
LEGACY = ROOT / "legacy"

for _d in (RAW, PROCESSED, GEO, FIGURES):
    _d.mkdir(parents=True, exist_ok=True)

# In-repo NYC 2010 census-block shapefile (offline, deterministic tract source).
NYC_BLOCKS_SHP = GEO / "nycMap" / "nycb2010.shp"

# TLC taxi-zone shapefile (the data's NATIVE geography; 263 zones, EPSG:2263).
TAXI_ZONES_SHP = GEO / "taxi_zones" / "taxi_zones.shp"
ZONE_LOOKUP_CSV = GEO / "taxi_zone_lookup.csv"
ZONE_LOOKUP_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"

# ---------------------------------------------------------------------------
# Canonical geo + processed output paths
# ---------------------------------------------------------------------------
TRACTS_PARQUET = GEO / "nyc_tracts_2263.parquet"        # dissolved census tracts
ZONES_PARQUET = GEO / "zones_2263.parquet"              # zone polygons + centroids + attrs
CROSSWALK_PARQUET = PROCESSED / "zone_tract_crosswalk.parquet"

EDGES_PERIOD_PARQUET = PROCESSED / "edges_by_period.parquet"  # (o,d,period)->trips
EDGES_PARQUET = PROCESSED / "edges.parquet"                   # annual (o,d)->weight
NODES_PARQUET = PROCESSED / "nodes.parquet"                   # node table w/ attrs+metrics
MONTHLY_PARQUET = PROCESSED / "monthly_volume.parquet"
HOUR_WEEKDAY_PARQUET = PROCESSED / "hour_weekday.parquet"
COST_DUR_HIST_PARQUET = PROCESSED / "cost_duration_hist.parquet"
TRIP_SAMPLE_PARQUET = PROCESSED / "trip_sample.parquet"
CLEANING_STATS_JSON = PROCESSED / "cleaning_stats.json"
METRICS_SUMMARY_JSON = PROCESSED / "metrics_summary.json"
RAW_SCHEMA_JSON = PROCESSED / "raw_schema.json"
PARTIAL_DIR = PROCESSED / "_partial"  # per-month ingest partials (resumable)

# ---------------------------------------------------------------------------
# Taxi zones: valid LocationID range. 264 = "Unknown", 265 = "Outside of NYC".
# ---------------------------------------------------------------------------
VALID_ZONE_MIN = 1
VALID_ZONE_MAX = 263
INVALID_ZONE_IDS = (264, 265)

# ---------------------------------------------------------------------------
# Data source
# ---------------------------------------------------------------------------
YEAR = 2015
TLC_BASE = "https://d37ci6vzurychx.cloudfront.net/trip-data"
MONTHS = [f"{m:02d}" for m in range(1, 13)]


def raw_parquet(month: str) -> Path:
    return RAW / f"yellow_tripdata_{YEAR}-{month}.parquet"


def tlc_url(month: str) -> str:
    return f"{TLC_BASE}/yellow_tripdata_{YEAR}-{month}.parquet"


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------
WGS84 = "EPSG:4326"          # raw lat/long
NY_STATE_PLANE = "EPSG:2263"  # NY State Plane Long Island, US feet (areas/distances)

# ---------------------------------------------------------------------------
# Cleaning bounds (generous NYC + immediate surroundings bounding box).
# Points outside any tract are dropped by the spatial join itself; this bbox
# is a cheap pre-filter that removes obvious garbage (0,0), Null Island, etc.
# ---------------------------------------------------------------------------
NYC_BBOX = {  # lon/lat
    "min_lon": -74.30,
    "max_lon": -73.65,
    "min_lat": 40.45,
    "max_lat": 40.95,
}

# Sanity bounds for cleaning (drop implausible trips).
MIN_DURATION_MIN = 1.0      # at least 1 minute
MAX_DURATION_MIN = 360.0    # at most 6 hours
MIN_FARE = 0.01             # positive fare
MAX_FARE = 1000.0           # drop absurd fares
MAX_TRIP_DISTANCE = 100.0   # miles

# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
EDGE_WEIGHT_THRESHOLD = 500  # "frequent" edges: > 500 trips/year (faithful to the original)

# ---------------------------------------------------------------------------
# NYC county FIPS (for building a federal 11-digit tract GEOID from BoroCode)
# BoroCode -> (county FIPS, borough name)
# ---------------------------------------------------------------------------
BORO_TO_FIPS = {
    "1": ("061", "Manhattan"),      # New York County
    "2": ("005", "Bronx"),          # Bronx County
    "3": ("047", "Brooklyn"),       # Kings County
    "4": ("081", "Queens"),         # Queens County
    "5": ("085", "Staten Island"),  # Richmond County
}
STATE_FIPS = "36"  # New York

# ---------------------------------------------------------------------------
# Temporal period definitions (for time-sliced network analysis).
# (label -> predicate over weekday[0=Mon..6=Sun] and hour[0..23])
# ---------------------------------------------------------------------------
PERIODS = ["am_peak", "midday", "pm_peak", "evening", "late_night_weekend", "other"]


def period_of(weekday: int, hour: int) -> str:
    """Classify a (weekday, hour) into a travel period."""
    weekend = weekday >= 5  # Sat/Sun
    if weekend and (hour >= 22 or hour < 4):
        return "late_night_weekend"
    if not weekend and 6 <= hour < 10:
        return "am_peak"
    if not weekend and 16 <= hour < 20:
        return "pm_peak"
    if 10 <= hour < 16:
        return "midday"
    if 20 <= hour < 24 or 4 <= hour < 6:
        return "evening"
    return "other"


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
SEED = 42

# ---------------------------------------------------------------------------
# Blog headline figures to reconcile against (original 2016-17 project)
# ---------------------------------------------------------------------------
BLOG_HEADLINE = {
    "total_trips": 146_112_990,
    "raw_nodes_pre_merge": 40_000,
    "tract_nodes": 580,
    "top_edges": 1275,
    "communities": 3,
}
