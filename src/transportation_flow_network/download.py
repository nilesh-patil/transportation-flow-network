"""Stage 1: download the full-year 2015 TLC yellow-taxi parquet.

The official CloudFront mirror now serves the *re-coded* historical data: the
2015 yellow parquet carries ``PULocationID``/``DOLocationID`` (taxi-zone ids)
rather than the raw lat/long the 2016-17 project used. The original lat/long
CSVs are no longer distributed (the old ``nyc-tlc`` S3 bucket returns 403). We
therefore work at taxi-zone resolution; see MODERNIZATION_NOTES.md.

Idempotent: a month is skipped when its local size already matches the remote
``Content-Length``. Also fetches the taxi-zone lookup and records the actual
parquet schema to ``data/processed/raw_schema.json``.
"""
from __future__ import annotations

import json
import sys

import requests

from . import config as C


def _remote_size(url: str) -> int | None:
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        if r.status_code == 200 and "Content-Length" in r.headers:
            return int(r.headers["Content-Length"])
    except requests.RequestException:
        return None
    return None


def _download(url: str, dest, expected: int | None) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    if expected is not None and tmp.stat().st_size != expected:
        raise IOError(f"size mismatch for {url}: got {tmp.stat().st_size}, expected {expected}")
    tmp.rename(dest)


def fetch_month(month: str) -> dict:
    url = C.tlc_url(month)
    dest = C.raw_parquet(month)
    remote = _remote_size(url)
    if dest.exists() and remote is not None and dest.stat().st_size == remote:
        return {"month": month, "status": "skip", "bytes": dest.stat().st_size}
    print(f"  downloading {month} -> {url}", flush=True)
    _download(url, dest, remote)
    return {"month": month, "status": "downloaded", "bytes": dest.stat().st_size}


def fetch_zone_lookup() -> None:
    if C.ZONE_LOOKUP_CSV.exists() and C.ZONE_LOOKUP_CSV.stat().st_size > 0:
        return
    try:
        r = requests.get(C.ZONE_LOOKUP_URL, timeout=60)
        r.raise_for_status()
        C.ZONE_LOOKUP_CSV.write_bytes(r.content)
        print(f"  zone lookup -> {C.ZONE_LOOKUP_CSV}", flush=True)
    except requests.RequestException as e:
        print(f"  WARN could not fetch zone lookup ({e}); the shapefile dbf still carries zone/borough.")


def record_schema() -> dict:
    """Read and persist the actual schema of one parquet file."""
    import duckdb

    con = duckdb.connect()
    f = C.raw_parquet(C.MONTHS[0])
    desc = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{f.as_posix()}')"
    ).fetchall()
    schema = {name: dtype for name, dtype, *_ in desc}
    has_latlong = any("longitude" in k.lower() for k in schema)
    out = {
        "file": f.name,
        "columns": schema,
        "has_latlong": has_latlong,
        "geography": "lat/long" if has_latlong else "PULocationID/DOLocationID (taxi zones)",
    }
    C.RAW_SCHEMA_JSON.write_text(json.dumps(out, indent=2))
    return out


def main() -> None:
    print(f"[download] full-year {C.YEAR} TLC yellow parquet -> {C.RAW}")
    results = [fetch_month(m) for m in C.MONTHS]
    fetch_zone_lookup()
    total = sum(r["bytes"] for r in results)
    n_dl = sum(r["status"] == "downloaded" for r in results)
    print(f"[download] {len(results)} months, {n_dl} downloaded, {len(results) - n_dl} cached; {total/1e9:.2f} GB")
    schema = record_schema()
    print(f"[download] schema recorded: geography = {schema['geography']}")
    if schema["has_latlong"]:
        print("[download] NOTE: lat/long present - tract spatial join is possible.")
    else:
        print("[download] NOTE: no lat/long; using taxi-zone (LocationID) geography.")


if __name__ == "__main__":
    sys.exit(main())
