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


def _valid_parquet(path, min_bytes: int = 1 << 20) -> bool:
    """A locally-present parquet is considered valid if it is larger than
    ``min_bytes`` (default 1 MB) and ends with the PAR1 magic trailer."""
    try:
        if not path.exists() or path.stat().st_size < min_bytes:
            return False
        with open(path, "rb") as fh:
            fh.seek(-4, 2)
            return fh.read(4) == b"PAR1"
    except OSError:
        return False


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


def fetch_month(month: str, year: int = C.YEAR) -> dict:
    url = C.tlc_url(month, year)
    dest = C.raw_parquet(month, year)
    # Skip if a valid file is already on disk (size + PAR1 trailer). If a remote
    # size is available and matches, that is also a skip.
    if _valid_parquet(dest):
        remote = _remote_size(url)
        if remote is None or dest.stat().st_size == remote:
            return {"year": year, "month": month, "status": "skip", "bytes": dest.stat().st_size}
    remote = _remote_size(url)
    print(f"  downloading {year}-{month} -> {url}", flush=True)
    _download(url, dest, remote)
    return {"year": year, "month": month, "status": "downloaded", "bytes": dest.stat().st_size}


def plan_downloads(years=None, months=None) -> list[dict]:
    """Dry-run helper: report which (year, month) files WOULD be downloaded vs
    already present-and-valid, WITHOUT touching the network. Used for validation
    and to scope a multi-year pass before committing to a heavy download.
    """
    years = list(C.YEARS if years is None else years)
    months = list(C.MONTHS if months is None else months)
    plan = []
    for y in years:
        for m in months:
            dest = C.raw_parquet(m, y)
            present = _valid_parquet(dest)
            plan.append({
                "year": y, "month": m, "url": C.tlc_url(m, y),
                "dest": str(dest),
                "status": "present" if present else "would_download",
                "bytes": dest.stat().st_size if dest.exists() else 0,
            })
    return plan


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
    print(f"[download] multi-year TLC yellow parquet ({C.YEARS[0]}-{C.YEARS[-1]}) -> {C.RAW}")
    results = []
    for year in C.YEARS:
        for m in C.MONTHS:
            results.append(fetch_month(m, year))
    fetch_zone_lookup()
    total = sum(r["bytes"] for r in results)
    n_dl = sum(r["status"] == "downloaded" for r in results)
    print(f"[download] {len(results)} files, {n_dl} downloaded, {len(results) - n_dl} cached; {total/1e9:.2f} GB")
    schema = record_schema()
    print(f"[download] schema recorded: geography = {schema['geography']}")
    if schema["has_latlong"]:
        print("[download] NOTE: lat/long present - tract spatial join is possible.")
    else:
        print("[download] NOTE: no lat/long; using taxi-zone (LocationID) geography.")


if __name__ == "__main__":
    sys.exit(main())
