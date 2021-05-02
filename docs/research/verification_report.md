Don't trigger them proactively unless the user's request clearly maps to their purpose.

# Taxi Flow Network Audit: Consolidated Report

## 1. Verdict Table

| Area | Overall |
|------|---------|
| Ingest + cleaning (ingest.py, config.py) | sound |
| Graph construction (graph.py + common.py) | minor_issues |
| Gravity residual field (analysis.py: furness, gravity_residual_field, decay_exponent) | sound |
| Community detection (analysis.py communities()) | minor_issues |
| Centralities / structure / rich-club (analysis.py) | minor_issues |
| Disparity backbone + temporal networks (analysis.py) | sound |
| metrics_summary.json reconciliation + internal consistency | minor_issues |

No area is `unsound`. There are **no critical issues**. The findings below are all `minor` or `nit`.

## 2. Issues by Severity (with fixes)

### Major / Critical
None.

### Minor issues (action recommended)

**M1 — Orphan zones silently dropped from node table (graph.py: build_node_table)**
Zones 57, 104, 105 appear as edge endpoints but are absent from the zones geometry master, so they vanish from `nodes.parquet` (260 rows vs 262 active graph nodes). The `zones.set_index('zone_id').join([...])` is left-on-zones, so flow-only zones disappear with no warning. Their flows still count in edge aggregates and the 262 figure → graph and node-table cardinalities are internally inconsistent. Volume is trivial (57: 5,847; 105: 487; 104: 3 trips), so headlines are unaffected, but any node-iterating spatial/centrality method under-counts.
*Fix:* Build the node index from the union of zones master AND active edge endpoints (or assert edge-endpoints ⊆ zones), and emit a warning listing flow-present/geometry-missing zone IDs. At minimum document the 262-vs-260 gap.

**M2 — Stochastic community algorithms unseeded (analysis.py communities())**
`community_leiden` and `community_multilevel` are not seeded, while python-louvain calls ARE. Headline Leiden/multilevel modularity, vs-administrative AMI, and within-community trip share are not exactly reproducible (observed Q 0.1868–0.1884 vs recorded 0.1897; borough AMI 0.418 vs 0.402; within-share 0.513 vs 0.479). Stable in magnitude, not bit-reproducible.
*Fix:* Seed igraph's RNG before the stochastic calls (`ig.set_random_number_generator` / `random.seed`) or pass a seed. At minimum average over runs and report mean ± sd.

**M3 — Significance test run on wrong partition (analysis.py communities())**
`modularity_significance.Q_observed` (0.1889) is the MULTILEVEL partition's Q, but the downstream headline partition (`_leiden_membership`, `leiden_modularity.modularity` = 0.1897) is Leiden. The null is run on multilevel.membership, not the partition the rest of the analysis uses.
*Fix:* Run the null on the same (Leiden) partition used downstream, or clearly note the test targets the multilevel partition.

**M4 — Modularity-significance null is non-standard (analysis.py communities())**
The null fixes BOTH topology AND partition and reshuffles edge weights. This tests whether the partition concentrates high-flow edges, NOT whether structure exceeds a degree/configuration-model expectation. z=13.1 should not be read as conventional modularity significance.
*Fix:* Keep the weight-reshuffle null but reframe the z-score explicitly as "weight-concentration significance given fixed partition." Optionally add a degree-preserving (configuration) null for comparison.

**M5 — Rich-club null is not strength-preserving (analysis.py weighted_rich_club())**
The null permutes edge weights but does NOT recompute node strengths from permuted weights, so rich-node membership stays fixed across observed and null. This is not a true Opsahl strength-preserving randomization; it inflates normalised ρ (rich set keeps its high-weight edges by construction while the null spreads weight uniformly). Reported values (4×–82×) overstate rich-club organization.
*Fix:* Use a strength-preserving null (recompute `strength = U_perm.sum(1)` inside `phi_w` per permutation, or a weighted configuration / link-rewiring null). Alternatively report the null type explicitly as a "weight-reshuffle on fixed topology" baseline.

**M6 — `n_nodes_active` (262) > `n_nodes_total` (260) reads as a contradiction (metrics_summary.json)**
Semantic mismatch: "total" = TLC shapefile zones (260), "active" = zones with trip activity (262). The extra active IDs 57/104/105 are TLC variant IDs for the Governors/Ellis/Liberty Island complex that the shapefile collapses into ID 103 (itself inactive). Both correct, but unreconcilable without geography context. (Same root cause as M1.)
*Fix:* Rename to `n_zones_geocoded` (260) / `n_zones_with_trips` (262), or add a note documenting the 103/104/105 island ID multiplicity.

**M7 — `edge_weight_threshold: 500` label implies inclusive, code is strict `>` (graph.py:62)**
Code filters `> 500`, dropping 3 edges at exactly 500. `n_edges_filtered=7945` matches `>500` (`>=500` would be 7948). Value is internally consistent; the label is misleading.
*Fix:* Either change filter to `>=` to match the label, or rename field to `edge_weight_threshold_exclusive: 500` / document the strict comparison.

### Nit issues (optional polish)
- **N1** Drop-reason FILTER counts in cleaning_stats.json overlap (sum 4,484,492 > actual dropped 3,840,030); a naive reader could misadd. Add a `dropped = raw - kept` line or note that reason counts are non-additive.
- **N2** Tagline "146M trips" = raw rows; cleaned graph total is 142.2M (and blog headline 146,112,990 differs from raw 146,039,231). Clarify in docs.
- **N3** `total_trips` column in nodes.parquet = out+in (endpoint-incident, double-counts each trip). Rename to `incident_trips` or add docstring note.
- **N4** `gravity_residual_field` emits "Mean of empty slice" RuntimeWarning from `np.nanmean` on zero-valid-cell zones (result correctly dropped). Wrap in `np.errstate`/`warnings.catch_warnings` or pre-filter.
- **N5** Residual floor applied only on modeled value (`Tm>=20`); 18,320 high-observed/low-model cells excluded from zone surprise — defensible but undocumented. Add a one-line note to the result dict.
- **N6** Seed-stability pairwise sampling covers only runs 0–59 (198 pairs of 100 runs); inflates mean ARI (0.774 windowed vs 0.751 full). Use `itertools.combinations` over all runs and also report min ARI (0.421).
- **N7** `degree_assortativity` is topology-only (unweighted) while the rest of the suite is weighted. Optionally also report a strength-weighted assortativity or note it is topology-only.
- **N8** Disparity OR-rule (`np.minimum`) is more permissive than AND; affects the 6190 count. Document the OR-vs-AND tradeoff for reproducibility-by-intent.
- **N9** `constant_band_is_jfk_pct=92.7` (300k sample, all ratecodes) vs recomputed 91.4 (full RatecodeID==2) — definitional, not an error. Note that the band-is-JFK pct is sample-based.
- **N10** Gravity scalars (β/CPC/obs_mean_dist) are computed on the full geo-restricted O-D matrix; `gravity_edges.parquet` is only the scoped residual-field subset (re-deriving from it gives 0.828/1.91, not 0.816/2.25). Note this in the JSON.

## 3. Confirmed-Correct Highlights
- **Cleaning pipeline is exact and replicable**: raw 146,039,231 and kept 142,199,201 (97.371%) both reproduced exactly, including all 12 per-month values and all 8 filter clauses; daypart SQL CASE matches `config.period_of` for all 168 (weekday×hour) combinations.
- **Self-loops handled correctly**: 6,460,370 trips (4.543%) kept in edges, excluded from node strength, reported separately — not silently dropped.
- **No double counting**: `sum(edges_by_period.trips) == sum(edges.trips) == kept == 142,199,201`; period buckets cleanly partition trips.
- **Furness doubly-constrained model is correct to machine precision**: row/col-sum errors 0.0, mass conserved, β=1.146 reproduces observed mean distance 2.2534 mi exactly. CPC=0.816 (Sørensen-Dice) and Poisson deviance residual formulas verified.
- **Flagship model is non-circular**: residual field routed through the doubly-constrained model (marginals fixed, only distance interaction free); the reconstructive `decay_exponent` is honestly flagged in-code.
- **Centrality suite verified**: weighted PageRank actually uses weights (Spearman 0.92 vs unweighted), SVD-HITS matches nx.hits (hub 0.981, auth 0.933), betweenness uses correct `1/trips` inversion, Garlaschelli-Loffredo ρ=0.515 and weighted reciprocity 0.818 reproduced, assortativity -0.184 (disassortative, as expected for hub-and-spoke), k-core max 147.
- **Disparity backbone is the standard Serrano (2009) filter**: 6,190 edges carry 87.6% of trips; AM/PM net-flow signs flip as claimed (Midtown sink→source, East Village source→sink); East Village day→night destination rank 42→1 confirmed.
- **JFK flat-fare band confirmed**: RatecodeID==2 median fare $52 (99.8% exactly $52), share 2.029%.
- **Cross-section reconciliation**: total trips, self-loop share, n_edges_full, degree maxima, hub asymmetry, reciprocity, backbone, communities, gravity scalars, and temporal monthly stats all reproduce exactly across independent recomputation.

## 4. Numbers Audit

### Numbers that check out (independently reproduced, exact unless noted)
- Raw rows: **146,039,231** | Kept: **142,199,201** (97.371%)
- Self-loop trips: **6,460,370** (4.543%)
- n_edges_full: **42,347** (non-self) | total edge rows 42,608 | self-loop pairs 261
- n_edges_filtered: **7,945** (`>500`) | n_nodes_filtered: **228** | threshold trip share 98.6%
- Backbone: **6,190 edges**, 262 nodes, **87.6%** trip share
- Communities: **4** | within-community share **0.479** (recorded; swings to ~0.51 unseeded)
- β doubly-constrained **1.146** | modeled = observed mean dist **2.2534 mi** | CPC **0.816**
- Reciprocity ρ **0.515** | weighted reciprocity **0.818** | assortativity **-0.184** | max k-core **147**
- Degree maxima: out **260** (zone 148), in **249** (JFK/132)
- JFK ratecode share **2.029%** | East Village destination rank **42→1**
- Temporal: peak Mar, spring mean 12,833,150, Jun–Dec mean 11,321,274, drop 11.8% (within 1-unit rounding)

### Numbers that do NOT reconcile (root cause known, mostly labeling/stochasticity — not data errors)
- **`n_nodes_active` 262 > `n_nodes_total` 260** — labeling/geography (M1/M6). Island variant IDs 57/104/105 vs shapefile.
- **nodes.parquet 260 rows vs 262 active nodes** — 3 orphan zones dropped (M1).
- **Leiden Q 0.1897 (recorded) vs 0.1868–0.1884 (recomputed)**; borough AMI 0.402 vs 0.418; within-share 0.479 vs 0.513 — unseeded stochasticity (M2).
- **modularity_significance Q_observed 0.1889 (multilevel) vs leiden_modularity 0.1897** — significance run on wrong partition (M3).
- **Drop-reason sum 4,484,492 ≠ actual dropped 3,840,030** — overlapping FILTER counts, by design (N1).
- **`gravity_edges.parquet`-derived CPC 0.828 / mean dist 1.91 ≠ recorded 0.816 / 2.25** — scalars use full geo matrix, parquet is scoped subset (N10).
- **constant_band_is_jfk 92.7% (sample) vs 91.4% (full RatecodeID==2)** — definitional (N9).
- **Raw 146,039,231 vs blog headline 146,112,990** (0.05%) — re-coded TLC zone dataset vs original lat/long release; documented.