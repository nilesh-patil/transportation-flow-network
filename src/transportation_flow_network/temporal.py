"""Stage 6: temporal exploratory analysis (original findings 2, 4, 5).

* monthly volume - peak months and the mid-year drop (with the honest
  ride-hailing-growth confounder noted in the writeups)
* hour x weekday density - the AM commute and weekend late-night bands
* cost vs duration - the constant-cost band, here *explained* (not guessed)
  as the JFK flat fare (RatecodeID == 2)

Records numbers to the results store; figures.py draws the plots.
"""
from __future__ import annotations

import sys

import pandas as pd

from . import common, config as C

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def monthly() -> dict:
    m = pd.read_parquet(C.MONTHLY_PARQUET).sort_values("month")
    trips = m.set_index("month")["trips"]
    peak_month = int(trips.idxmax())
    spring = trips.loc[3:5].mean()          # Mar-May
    summer_fall = trips.loc[6:12].mean()    # Jun-Dec
    drop_pct = 100.0 * (spring - summer_fall) / spring
    return {
        "by_month": {_MONTHS[int(k) - 1]: int(v) for k, v in trips.items()},
        "peak_month": _MONTHS[peak_month - 1],
        "spring_mean": int(spring),
        "jun_dec_mean": int(summer_fall),
        "spring_to_rest_drop_pct": round(drop_pct, 1),
    }


def hour_weekday() -> dict:
    hw = pd.read_parquet(C.HOUR_WEEKDAY_PARQUET)
    mat = hw.pivot(index="wd", columns="hr", values="trips").fillna(0)
    # weekday (Mon-Fri = wd 0..4) morning commute 6-9
    wk_morning = mat.loc[0:4, 6:9].sum().sum()
    # weekend (Sat/Sun = wd 5,6) late night 0-4
    we_latenight = mat.loc[5:6, 0:4].sum().sum()
    total = mat.values.sum()
    busiest = mat.stack().idxmax()
    return {
        "weekday_morning_6_9_share_pct": round(100.0 * wk_morning / total, 2),
        "weekend_latenight_0_4_share_pct": round(100.0 * we_latenight / total, 2),
        "busiest_cell": {"weekday": int(busiest[0]), "hour": int(busiest[1])},
    }


def cost_duration() -> dict:
    s = pd.read_parquet(C.TRIP_SAMPLE_PARQUET)
    n = len(s)
    # JFK flat fare == RatecodeID 2 (a fixed $52 metered fare regardless of time)
    jfk = s[s["ratecode"] == 2]
    band = s[(s["fare_amount"] >= 49) & (s["fare_amount"] <= 53)]
    band_jfk_share = 100.0 * (band["ratecode"] == 2).mean() if len(band) else 0.0
    return {
        "sample_size": int(n),
        "jfk_flatfare_share_pct": round(100.0 * len(jfk) / n, 3),
        "jfk_fare_median": round(float(jfk["fare_amount"].median()), 2) if len(jfk) else None,
        "jfk_fare_iqr": [round(float(jfk["fare_amount"].quantile(0.25)), 2),
                         round(float(jfk["fare_amount"].quantile(0.75)), 2)] if len(jfk) else None,
        "constant_band_49_53_share_pct": round(100.0 * len(band) / n, 3),
        "constant_band_is_jfk_pct": round(float(band_jfk_share), 1),
    }


def main() -> None:
    mo = monthly()
    hw = hour_weekday()
    cd = cost_duration()
    common.record("temporal", {"monthly": mo, "hour_weekday": hw, "cost_duration": cd})

    print(f"[temporal] peak month: {mo['peak_month']}; spring->rest drop: {mo['spring_to_rest_drop_pct']}%")
    print(f"[temporal] weekday 6-9AM share: {hw['weekday_morning_6_9_share_pct']}%; "
          f"weekend 0-4AM share: {hw['weekend_latenight_0_4_share_pct']}%")
    print(f"[temporal] constant-cost band ($49-53): {cd['constant_band_49_53_share_pct']}% of trips, "
          f"{cd['constant_band_is_jfk_pct']}% of them JFK flat-fare (RatecodeID=2)")


if __name__ == "__main__":
    sys.exit(main())
