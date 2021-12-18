"""Final summary: print the headline measured numbers to the terminal.

Reads the single source of truth (``data/processed/metrics_summary.json``) so the
summary always matches what the pipeline produced.
"""
from __future__ import annotations

import json
import sys

from . import config as C


def main() -> None:
    r = json.loads(C.METRICS_SUMMARY_JSON.read_text())
    g, m, t, a = r["graph"], r["metrics"], r["temporal"], r["analysis"]
    gr = a["gravity_residual_field"]
    cm = a["communities"]
    tn = a["temporal_networks"]
    hub = m["hub_asymmetry"]

    line = "=" * 72
    print(line)
    print("  TRANSPORTATION FLOW NETWORK - NYC yellow taxis 2015 (final summary)")
    print(line)
    print(f"  Trips kept (cleaned)     : {g['total_trips']:,}  ({r['graph']['self_loop_share_pct']}% self-loops)")
    print(f"  Network                  : {g['n_nodes_active']} zones, {g['n_edges_full']:,} directed edges")
    print(f"  Filtered (>500 trips/yr) : {g['n_nodes_filtered']} zones, {g['n_edges_filtered']:,} edges")
    print(f"  Communities (Leiden)     : {cm['algorithms']['leiden_modularity']['n_communities']} "
          f"(seed range {cm['seed_stability']['community_count_range']}, "
          f"mean ARI {cm['seed_stability']['mean_ARI']}, Q z-score {cm['modularity_significance']['z_score']})")
    print(f"  Gravity model            : decay beta {gr['beta_doubly_constrained']}, CPC {gr['cpc_doubly_constrained']}")
    print(line)
    print("  HUB ASYMMETRY (trips per distinct origin):")
    for k in ["midtown_center", "times_sq", "penn_station", "laguardia", "jfk"]:
        if k in hub:
            h = hub[k]
            print(f"    {h['zone']:32s} {h['trips_per_source']:>9,.0f}")
    print(line)
    print("  WHERE MANHATTAN ENDS (gravity surprise, blue=under-connected):")
    for x in gr["most_underconnected_core_zones"][:4]:
        print(f"    under  {x['zone']:30s} {x['surprise']:+.1f}")
    for x in gr["most_overconnected_core_zones"][:3]:
        print(f"    over   {x['zone']:30s} {x['surprise']:+.1f}")
    print("  Day/night reversal (destination rank day -> night):")
    for z, d in list(tn["nightlife_rank_shift"].items())[:3]:
        print(f"    {z:32s} {d['am_rank']:>3} -> {d['night_rank']:>3}")
    print(line)
    print(f"  JFK flat-fare band       : {t['cost_duration']['constant_band_is_jfk_pct']}% of the "
          f"$49-53 band is RatecodeID 2 (the original guessed 'rounded tips')")
    print(line)
    n_figs = len(list(C.FIGURES.glob("*.svg")))
    print(f"  Figures   : {C.FIGURES}  ({n_figs} figures, PNG + SVG, see CAPTIONS.md)")
    print(f"  Numbers   : {C.METRICS_SUMMARY_JSON}")
    print(f"  Notes     : {C.ROOT / 'MODERNIZATION_NOTES.md'}")
    print(f"  Paper     : {C.ROOT / 'docs' / 'paper.md'}")
    print(line)


if __name__ == "__main__":
    sys.exit(main())
