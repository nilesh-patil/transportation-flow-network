"""Stage 3: clean trips and aggregate to zone-level tables (out-of-core, DuckDB).

Processes one month at a time. For each month we materialise a cleaned table in
DuckDB (which spills to disk, so peak RAM stays bounded - we never hold 146M rows
in Python memory) and emit small aggregates:

* edges by (origin, destination, daypart) with trip count + summed distance/fare/duration
* per-zone hourly pickup/dropoff profiles (for temporal rhythm clustering)
* monthly volume, hour x weekday counts, a 2D cost/duration histogram
* a ~300k random trip sample (for scatter figures, keeps RatecodeID)
* cleaning statistics (kept vs dropped, by reason)

Resumable: a month whose ``_done`` marker exists is skipped. The final combine
step sums the per-month partials into the canonical processed/ tables.
"""
from __future__ import annotations

import json
import sys

import duckdb
import pandas as pd

from . import config as C

# SQL fragment classifying a (weekday, hour) into a daypart. Mirrors
# config.period_of exactly (isodow: 1=Mon..7=Sun -> wd 0..6).
_PERIOD_CASE = """
CASE
  WHEN wd >= 5 AND (hr >= 22 OR hr < 4) THEN 'late_night_weekend'
  WHEN wd < 5 AND hr >= 6 AND hr < 10   THEN 'am_peak'
  WHEN wd < 5 AND hr >= 16 AND hr < 20  THEN 'pm_peak'
  WHEN hr >= 10 AND hr < 16             THEN 'midday'
  WHEN (hr >= 20 AND hr < 24) OR (hr >= 4 AND hr < 6) THEN 'evening'
  ELSE 'other'
END
"""


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("PRAGMA memory_limit='6GB'")
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA disable_progress_bar")
    con.execute(f"PRAGMA temp_directory='{(C.PROCESSED / '_duckdb_tmp').as_posix()}'")
    return con


def process_month(month: str) -> None:
    out = C.PARTIAL_DIR / f"{C.YEAR}-{month}"
    if (out / "_done").exists():
        print(f"  [{month}] cached, skipping")
        return
    out.mkdir(parents=True, exist_ok=True)
    f = C.raw_parquet(month).as_posix()
    con = _con()

    # --- cleaning statistics over the RAW file (drop reasons may overlap) ---
    stats = con.execute(f"""
        SELECT
          count(*) AS raw_rows,
          count(*) FILTER (WHERE PULocationID IS NULL OR DOLocationID IS NULL
                             OR PULocationID NOT BETWEEN {C.VALID_ZONE_MIN} AND {C.VALID_ZONE_MAX}
                             OR DOLocationID NOT BETWEEN {C.VALID_ZONE_MIN} AND {C.VALID_ZONE_MAX}) AS bad_zone,
          count(*) FILTER (WHERE tpep_pickup_datetime IS NULL OR tpep_dropoff_datetime IS NULL
                             OR tpep_dropoff_datetime <= tpep_pickup_datetime) AS bad_time,
          count(*) FILTER (WHERE date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime)/60.0
                             NOT BETWEEN {C.MIN_DURATION_MIN} AND {C.MAX_DURATION_MIN}) AS bad_duration,
          count(*) FILTER (WHERE fare_amount NOT BETWEEN {C.MIN_FARE} AND {C.MAX_FARE}) AS bad_fare,
          count(*) FILTER (WHERE trip_distance NOT BETWEEN 0 AND {C.MAX_TRIP_DISTANCE}) AS bad_distance,
          count(*) FILTER (WHERE year(tpep_pickup_datetime) <> {C.YEAR}) AS out_of_year
        FROM read_parquet('{f}')
    """).fetchdf().iloc[0].to_dict()

    # --- materialise the cleaned rows once (DuckDB spills to disk) ---
    con.execute(f"""
        CREATE TEMP TABLE clean AS
        SELECT
          PULocationID::INT AS o,
          DOLocationID::INT AS d,
          date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime)/60.0 AS dur,
          fare_amount AS fare, total_amount AS total, trip_distance AS dist, tip_amount AS tip,
          RatecodeID::INT AS rate,
          (isodow(tpep_pickup_datetime) - 1)::INT AS wd,
          hour(tpep_pickup_datetime)::INT AS hr,
          month(tpep_pickup_datetime)::INT AS mo
        FROM read_parquet('{f}')
        WHERE PULocationID BETWEEN {C.VALID_ZONE_MIN} AND {C.VALID_ZONE_MAX}
          AND DOLocationID BETWEEN {C.VALID_ZONE_MIN} AND {C.VALID_ZONE_MAX}
          AND tpep_pickup_datetime IS NOT NULL AND tpep_dropoff_datetime IS NOT NULL
          AND tpep_dropoff_datetime > tpep_pickup_datetime
          AND date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime)/60.0
              BETWEEN {C.MIN_DURATION_MIN} AND {C.MAX_DURATION_MIN}
          AND fare_amount BETWEEN {C.MIN_FARE} AND {C.MAX_FARE}
          AND trip_distance BETWEEN 0 AND {C.MAX_TRIP_DISTANCE}
          AND year(tpep_pickup_datetime) = {C.YEAR}
    """)
    stats["kept"] = con.execute("SELECT count(*) FROM clean").fetchone()[0]

    # --- edges by (o, d, daypart) ---
    con.execute(f"""
        COPY (
          SELECT o, d, {_PERIOD_CASE} AS period,
                 count(*) AS trips, sum(dist) AS sum_dist,
                 sum(fare) AS sum_fare, sum(dur) AS sum_dur
          FROM clean GROUP BY o, d, period
        ) TO '{(out / 'edges.parquet').as_posix()}' (FORMAT parquet)
    """)

    # --- per-zone hourly profiles (pickups and dropoffs) ---
    con.execute(f"""
        COPY (
          SELECT o AS zone_id, (wd >= 5) AS weekend, hr, count(*) AS pickups
          FROM clean GROUP BY o, weekend, hr
        ) TO '{(out / 'zh_pickup.parquet').as_posix()}' (FORMAT parquet)
    """)
    con.execute(f"""
        COPY (
          SELECT d AS zone_id, (wd >= 5) AS weekend, hr, count(*) AS dropoffs
          FROM clean GROUP BY d, weekend, hr
        ) TO '{(out / 'zh_dropoff.parquet').as_posix()}' (FORMAT parquet)
    """)

    # --- monthly volume ---
    con.execute(f"""
        COPY (
          SELECT mo AS month, count(*) AS trips, sum(fare) AS sum_fare,
                 sum(total) AS sum_total, sum(dist) AS sum_dist, sum(dur) AS sum_dur
          FROM clean GROUP BY mo
        ) TO '{(out / 'monthly.parquet').as_posix()}' (FORMAT parquet)
    """)

    # --- hour x weekday ---
    con.execute(f"""
        COPY (
          SELECT wd, hr, count(*) AS trips FROM clean GROUP BY wd, hr
        ) TO '{(out / 'hour_weekday.parquet').as_posix()}' (FORMAT parquet)
    """)

    # --- 2D cost/duration histogram (1-min x $1 bins, capped at 120) ---
    con.execute(f"""
        COPY (
          SELECT least(floor(dur), 120)::INT AS dur_bin,
                 least(floor(fare), 120)::INT AS fare_bin, count(*) AS n
          FROM clean GROUP BY dur_bin, fare_bin
        ) TO '{(out / 'cost_hist.parquet').as_posix()}' (FORMAT parquet)
    """)

    # --- random trip sample (reservoir), keeps RatecodeID for fare-band proof ---
    con.execute(f"""
        COPY (
          SELECT dur AS duration_min, fare AS fare_amount, total AS total_amount,
                 dist AS trip_distance, tip AS tip_amount, rate AS ratecode,
                 o AS pu, d AS do, wd AS weekday, hr AS hour, mo AS month
          FROM clean USING SAMPLE 25000 ROWS
        ) TO '{(out / 'sample.parquet').as_posix()}' (FORMAT parquet)
    """)

    (out / "stats.json").write_text(json.dumps({k: int(v) for k, v in stats.items()}, indent=2))
    con.close()
    (out / "_done").write_text("ok")
    kept_pct = 100.0 * stats["kept"] / stats["raw_rows"]
    print(f"  [{month}] raw={stats['raw_rows']:,} kept={stats['kept']:,} ({kept_pct:.1f}%)")


def _read_all(name: str) -> pd.DataFrame:
    parts = [pd.read_parquet(C.PARTIAL_DIR / f"{C.YEAR}-{m}" / name) for m in C.MONTHS]
    return pd.concat(parts, ignore_index=True)


def combine() -> dict:
    print("[ingest] combining per-month partials...")

    edges = _read_all("edges.parquet")
    edges = edges.groupby(["o", "d", "period"], as_index=False).agg(
        trips=("trips", "sum"), sum_dist=("sum_dist", "sum"),
        sum_fare=("sum_fare", "sum"), sum_dur=("sum_dur", "sum"))
    edges.to_parquet(C.EDGES_PERIOD_PARQUET, index=False)

    zh_p = _read_all("zh_pickup.parquet").groupby(["zone_id", "weekend", "hr"], as_index=False)["pickups"].sum()
    zh_d = _read_all("zh_dropoff.parquet").groupby(["zone_id", "weekend", "hr"], as_index=False)["dropoffs"].sum()
    zh = zh_p.merge(zh_d, on=["zone_id", "weekend", "hr"], how="outer").fillna(0)
    zh[["pickups", "dropoffs"]] = zh[["pickups", "dropoffs"]].astype(int)
    zh.to_parquet(C.PROCESSED / "zone_hourly.parquet", index=False)

    monthly = _read_all("monthly.parquet").groupby("month", as_index=False).sum()
    monthly = monthly[monthly["month"].between(1, 12)].sort_values("month")
    monthly.to_parquet(C.MONTHLY_PARQUET, index=False)

    hw = _read_all("hour_weekday.parquet").groupby(["wd", "hr"], as_index=False)["trips"].sum()
    hw.to_parquet(C.HOUR_WEEKDAY_PARQUET, index=False)

    ch = _read_all("cost_hist.parquet").groupby(["dur_bin", "fare_bin"], as_index=False)["n"].sum()
    ch.to_parquet(C.COST_DUR_HIST_PARQUET, index=False)

    sample = _read_all("sample.parquet")
    sample.to_parquet(C.TRIP_SAMPLE_PARQUET, index=False)

    # cleaning stats
    per_month = {m: json.loads((C.PARTIAL_DIR / f"{C.YEAR}-{m}" / "stats.json").read_text()) for m in C.MONTHS}
    totals: dict[str, int] = {}
    for d in per_month.values():
        for k, v in d.items():
            totals[k] = totals.get(k, 0) + int(v)
    stats_out = {"per_month": per_month, "totals": totals,
                 "kept_pct": round(100.0 * totals["kept"] / totals["raw_rows"], 3)}
    C.CLEANING_STATS_JSON.write_text(json.dumps(stats_out, indent=2))

    print(f"[ingest] total raw rows  : {totals['raw_rows']:,}")
    print(f"[ingest] total kept trips: {totals['kept']:,} ({stats_out['kept_pct']}%)")
    print(f"[ingest] distinct OD x daypart edges: {len(edges):,}")
    return stats_out


def main() -> None:
    C.PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[ingest] cleaning + aggregating {len(C.MONTHS)} months (month by month)...")
    for m in C.MONTHS:
        process_month(m)
    combine()


if __name__ == "__main__":
    sys.exit(main())
