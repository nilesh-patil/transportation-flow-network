# Modernization notes

A running record of what changed in the 2021 refresh, every measured number, the
decisions behind them, and how they reconcile with the original 2016-17 blog
figures. House style: no em-dashes.

## 1. The headline data surprise

The brief assumed the 2015 yellow-taxi parquet still carries raw pickup/dropoff
lat/long. It does not. The official CloudFront mirror now serves a **re-coded**
version of the historical data: the 2015 yellow parquet exposes
`PULocationID`/`DOLocationID` (TLC taxi-zone ids) plus `congestion_surcharge` and
`airport_fee` (fields that did not exist in 2015). There are no longitude or
latitude columns. The original lat/long CSVs are no longer distributed; the old
`s3://nyc-tlc` bucket returns HTTP 403 and CloudFront only hosts the parquet.

Consequence: the original project's central engineering problem, binning splintered
lat/long points onto census tracts (the "Penn Station problem"), is now solved
upstream. TLC ships trips already aggregated to 263 taxi zones, which are unions of
census tracts built for exactly this purpose. We therefore use **taxi zones as
network nodes** (decision approved interactively). We still honour the brief's
spatial-join machinery: `geo.py` dissolves the in-repo 2010 block shapefile into
2,166 census tracts in EPSG:2263 and builds a zone-to-tract crosswalk, which
quantifies the resolution change (a taxi zone overlaps **~19 census tracts** on
average).

The actual parquet schema is recorded in `data/processed/raw_schema.json`.

## 2. Measured numbers (full year 2015)

### Volume and cleaning
| quantity | value |
|---|---|
| raw rows across 12 months | 146,039,231 |
| blog headline trips | 146,112,990 (diff -73,759, -0.05%) |
| kept after cleaning | 142,199,201 (97.37%) |
| dropped: invalid zone id | 2,889,602 |
| dropped: bad timestamp / non-positive duration | 174,997 |
| dropped: duration outside [1, 360] min | 1,330,425 |
| dropped: fare outside [$0.01, $1000] | 87,140 |
| dropped: trip distance outside [0, 100] mi | 2,328 |
| self-loop (intra-zone) trips | 6,460,370 (4.54%) |

Cleaning filters: PU/DO LocationID in 1..263; pickup < dropoff; duration in
[1, 360] min; fare in [$0.01, $1000]; trip distance in [0, 100] mi; pickup year
2015. Drop-reason counts can overlap (a row may fail several tests); `kept` is the
count passing all filters. Per-month detail is in `data/processed/cleaning_stats.json`.

### Graph
| quantity | this work (zones) | blog (tracts) |
|---|---|---|
| nodes (active in graph) | 262 | ~580 |
| nodes with geometry | 260 | - |
| full directed edges (self-loops dropped) | 42,347 | - |
| filtered edges (> 500 trips/yr) | 7,945 | ~1,275 |
| filtered nodes | 228 | - |
| communities | 4 (range 3-4 over seeds) | ~3 |

### Spatial interaction (gravity)
| quantity | value |
|---|---|
| distance-decay exponent beta (unconstrained Poisson, Euclidean) | 0.72 (SE 0.005) |
| distance-decay exponent beta (using mean trip distance as cost) | 0.85 |
| pseudo R-squared (deviance) of the unconstrained fit | 0.939 |
| decay exponent beta (doubly-constrained, calibrated) | 1.146 |
| common part of commuters (CPC), doubly-constrained | 0.816 |
| observed mean trip distance | 2.25 mi |

### Structure
| quantity | value |
|---|---|
| weighted reciprocity (share of flow with a return leg) | 0.818 |
| Garlaschelli-Loffredo reciprocity rho | 0.515 |
| mean / median edge flow imbalance | 0.603 / 0.678 |
| degree assortativity | -0.184 (disassortative, hub-and-spoke) |
| max k-core | 147 |
| weighted rich-club rho, strength-preserving null (richness pct 50/70/80/90/95) | 2.2 / 4.2 / 6.7 / 10.0 / 10.3 (all > 1: high-strength zones trade preferentially among themselves) |

### Communities (rigorous)
| quantity | value |
|---|---|
| Leiden (modularity) | 4 communities, Q = 0.189 |
| igraph multilevel (= original method) | 4 communities, Q = 0.189 |
| networkx greedy modularity | 3 communities |
| Infomap (directed, flow) | 1 module (near-complete graph collapses) |
| seed stability over 100 runs | mode 4, range 3-4, mean ARI 0.751, min ARI 0.421 (4,950 pairs), mean AMI 0.737 |
| resolution sweep (0.5/0.75/1.0/1.25/1.5/2.0) | 17 / 7 / 4 / 5 / 10 / 16 |
| modularity significance (weight reshuffle, Leiden partition fixed) | Q 0.189 vs null -0.022, z = 13.8 |
| within-community trip share | 0.498 |
| Leiden vs borough (AMI / ARI) | 0.387 / 0.250 |
| Leiden vs service zone (AMI) | 0.237 |

### Hub asymmetry (trips per source = in-strength / number of distinct origins)
| zone | trips/source | in-strength | sources |
|---|---|---|---|
| Midtown Center | 22,929 | 5,159,038 | 225 |
| Times Sq / Theatre District | 18,664 | 4,348,768 | 233 |
| Penn Station / Madison Sq West | 17,399 | 3,897,451 | 224 |
| East Village | 16,143 | 3,535,216 | 219 |
| LaGuardia Airport | 7,289 | 1,727,487 | 237 |
| Lower East Side | 7,736 | 1,593,653 | 206 |
| JFK Airport | 4,510 | 1,123,029 | 249 |

Inner-city draws pull large volume from a limited Manhattan origin set; airports
pull comparable or larger volume from many scattered origins, so their
trips-per-source is far lower. This reproduces the original finding and puts real
numbers on it (the blog asserted "~1,250 trips from a single locale" at tract
resolution; at the coarser zone resolution the same pattern reads as 4,500 for JFK
versus 17,000-23,000 for the Midtown draws).

### Where Manhattan ends (gravity residual, the flagship)
Per-zone mean deviance residual from the doubly-constrained gravity model, scoped
to the high-coverage core (TLC Yellow Zone plus airports):

- Most under-connected (functionally peripheral despite central geography):
  Upper East Side North (-20.3), Upper West Side South (-16.3), Upper East Side
  South (-16.1), Upper West Side North (-15.7), Lincoln Square East (-12.3),
  Manhattan Valley (-11.4).
- Most over-connected: Times Sq / Theatre District (+9.4), Midtown South (+6.3),
  Clinton East (+5.2), Garment District (+4.6), Midtown East (+4.1),
  Midtown Center (+3.8).
- East Village (-5.1, 29th percentile of the core) and Alphabet City (-4.3, 35th)
  land in the under-connected tail, which **confirms the original's headline claim
  with a model**. Lower East Side itself is near neutral (+0.8), a partial
  divergence noted honestly.

### Day/night reversal (new finding)
Net-flow index (out minus in, normalised) by daypart:

| zone | AM peak | PM peak | reading |
|---|---|---|---|
| Midtown Center | -0.567 | +0.128 | sink by morning, source by evening (CBD) |
| Financial District North | -0.205 | +0.241 | CBD flip |
| Times Sq / Theatre District | -0.358 | +0.014 | CBD flip |
| East Village | +0.492 | -0.168 | source by morning, sink by evening (residential/nightlife) |
| Lower East Side | +0.372 | -0.209 | residential/nightlife flip |

Destination rank shift, daytime to late-night:
East Village 42 -> 1, Lower East Side 51 -> 6, Clinton East 22 -> 2,
Meatpacking/West Village 41 -> 19. The AM-vs-late-night top-15 hub sets overlap
only 0.20 (Jaccard). The East Village and Lower East Side are suburb-like by day
and the city's busiest destinations at night.

### Daily rhythm clusters (k-means on weekday hourly pickup shape, active zones)
- Commuter-residential (peak 8am): Upper East/West Side, Murray Hill, Penn Station.
- Outer commuter (peak 7am): Astoria, Sunnyside, Harlem, Brooklyn Heights.
- Commercial core (peak 9pm): Midtown, Union Sq, Times Sq, Clinton.
- Nightlife (peak 11pm): Lower East Side, Williamsburg, Park Slope, Fort Greene.

### Backbone
Disparity filter at alpha = 0.05 keeps 6,190 of 42,347 edges (87.6% of trips), a
principled alternative to the arbitrary > 500-trip cut (7,945 edges, 98.6% of
trips).

### Temporal (original findings reproduced)
- Monthly volume peaks in March (spring mean 12.83M/month), runs 11.8% lower
  Jun-Dec. Honest caveat: the mid-year drop is confounded by ride-hailing growth
  through 2015, not just weather; we cannot separate the two from this data alone.
- Weekday 6-9am trips are 12.6% of all trips; weekend 0-4am are 5.9%. The
  hour-by-weekday heatmap reproduces the commute and late-night bands.
- The constant-cost band is the JFK flat fare (RatecodeID 2, a fixed $52): 2.19%
  of trips fall in the $49-53 fare band and 92.7% of those are flat-fare trips.
  This replaces the original's guess ("rounded tips plus traffic") with a verified
  cause.

## 3. Divergences from the blog headline figures

| blog figure | blog value | this work | why it differs |
|---|---|---|---|
| total trips | 146,112,990 | 146,039,231 raw / 142,199,201 kept | re-coded parquet has slightly fewer rows; we drop ~2.6% in cleaning |
| raw nodes pre-merge | ~40,000 | not applicable | no lat/long to splinter; TLC pre-aggregates to zones |
| node count after binning | ~580 tracts | 262 zones (260 with geometry) | taxi zones are ~19x coarser than tracts; also all-NYC vs a Manhattan subset |
| top edges | ~1,275 | 7,945 above 500/yr | zone aggregation concentrates trips into fewer, heavier pairs; the blog's 1,275 was a tract-level Manhattan subset |
| communities | ~3 | 4 (range 3-4) | reproduced; the count is resolution and seed dependent (see sweep) |

The qualitative findings reproduce; the exact counts differ because the node
geography changed from tracts to zones and because the underlying file was
re-coded. Reported numbers are what we measured, not what we expected.

## 4. Decisions log

- **Nodes = taxi zones.** Forced by the data (no lat/long). Census tracts are still
  built and a zone-to-tract crosswalk is produced to honour the spatial-join step
  and to quantify the resolution change.
- **Tract source = offline dissolve of the in-repo `nycb2010` block shapefile.**
  Deterministic and network-free. `pygris` is listed as the documented online
  alternative but the pipeline never needs it. GEOID built as
  state(36) + county FIPS(by BoroCode) + tract(CT2010).
- **CRS = EPSG:2263** (NY State Plane, US feet) for all areas, centroids, distances
  and joins.
- **Self-loops kept in the edge table, excluded from network and spatial metrics.**
  They are 4.54% of trips and break distance-based methods (d_ii = 0).
- **Edge filter > 500 trips/yr** retained from the original for the "frequent" graph.
- **Gravity residual field uses the doubly-constrained (Furness) model**, which is
  non-circular: it conditions only on each zone's own marginals and on distance.
  The unconstrained Poisson fit is reported only for the decay exponent, with an
  explicit note that it reconstructs more than it explains.
- **Coverage bias is handled, not ignored.** Yellow-taxi pickups concentrate in
  the Manhattan core plus airports, so residual and "under-connected" claims are
  scoped to the high-coverage core (TLC Yellow Zone plus airports) where the
  observation rate is roughly uniform.
- **Modularity significance** uses a weight-reshuffle null with the observed
  partition held fixed, which is the meaningful test for a near-complete weighted
  graph (a degree-preserving swap null is uninformative here).
- **Pixi (2023) postdates the 2021 commit dates.** This anachronism is intentional
  and accepted for these backdated companion repos; no disclaimer about it appears
  in the public-facing README.

## 5. Which new figures the blog post should adopt

1. **`08_where_manhattan_ends`** (gravity residual map). It converts the blog's
   single most interesting but unproven claim ("the East Village and Lower East
   Side read like suburbs") into a measured, mapped, model-based result. This is
   the figure to lead with.
2. **`10_day_night_reversal`** (net-flow flip plus rank shift). A genuinely new
   finding the original did not have: the East Village and Lower East Side are
   peripheral by day and the city's top destinations at night (East Village rises
   from 42nd to 1st). It nuances the suburb claim rather than overturning it.
3. **`04_cost_vs_duration`** (JFK flat fare highlighted). Same plot as the
   original but coloured by rate code, so the constant-cost band is explained
   ($52 JFK flat fare) instead of guessed.

Runner-up: `15_daily_rhythms`, which gives the nightlife-vs-commuter split a clean
visual and supports the day/night story.

## 6. Verification

Every headline number was independently re-derived by an adversarial multi-agent
audit (recomputing from the raw parquet and processed tables, and checking each
method for correctness on a directed weighted spatial graph). See
`docs/research/methods_critique.md` for the methods review that shaped the design
and section 7 below for the audit outcome.

## 7. Audit outcome

An eight-agent adversarial audit independently re-derived every headline number
from the raw parquet and processed tables and checked each method for correctness
on a directed, weighted, spatial graph. The full report is in
`docs/research/verification_report.md`. Result: **no critical or major issues**;
all areas rated sound or minor. Confirmed exact: the cleaning counts
(146,039,231 raw, 142,199,201 kept, 97.371%), the daypart classification across all
168 weekday-by-hour cells, self-loop handling, no double counting
(sum of period edges = annual edges = kept trips), and the doubly-constrained
Furness model (row and column sums conserved to machine precision).

Minor issues raised by the audit and fixed in this pass:

- Flow-only zone ids (57, 104, 105; TLC island-complex variants the shapefile
  collapses) were dropped from the node table. The node table now indexes the
  union of geocoded zones and active edge endpoints (263 rows), and the recorded
  counts are renamed unambiguously: `n_zones_geocoded` (260), `n_nodes_active`
  (262), `n_nodes_table` (263).
- The igraph Leiden and multilevel calls were unseeded. They are now seeded for
  bit-reproducibility (which slightly shifted the Leiden-vs-administrative AMI and
  within-community share to the values reported above; magnitudes were stable).
- The modularity-significance null now runs on the same Leiden partition used
  downstream (previously the multilevel partition), and is explicitly framed as a
  weight-concentration test, not a configuration-model test.
- The weighted rich-club null is now strength-preserving (it recomputes node
  strength and rich-set membership from the permuted weights). This lowered the
  normalised rho from an inflated 4-83x to 2.2-10.3x, which is still firmly above 1
  and is the honest figure.
- Seed-stability now uses all 4,950 run pairs and reports the minimum ARI (0.421)
  alongside the mean.

Nits the audit noted and we accept and document rather than change: drop-reason
counts in `cleaning_stats.json` overlap and are non-additive (kept = raw minus the
union, not minus the sum); the "146M trips" tagline is raw rows while the graph
total is 142.2M; the >500-trip filter is strict; the residual floor is applied on
the modeled value.
