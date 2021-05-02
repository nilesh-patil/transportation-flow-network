This is a substantial synthesis task. I have all the findings I need in the prompt; no tool calls are required. I'll produce the analysis spec directly.

# NYC Yellow-Taxi Tract-Level OD Network — Research-Grade Analysis Spec

**Scope.** Directed, weighted OD graph G: nodes = ~2,165 NYC 2010 census tracts (5 boroughs), edge weight w_ij = annual (2015) yellow-taxi trip count from tract i to tract j; 146M+ trips. Geometry in EPSG:2263 (centroids, areas). Optional ACS tract population. Tooling: 2021-era Python (networkx, python-louvain, leidenalg/python-igraph, infomap, numpy, scipy, scikit-learn, geopandas, statsmodels, matplotlib; plus pip packages netbone, cpnet, NEMtropy, tensorly, powerlaw).

**Design conventions used throughout (decide once, state once in the paper):**
- **Self-loops** (i==j intra-tract trips): keep them as a separately reported quantity but **drop the diagonal** from all distance-based, decay, and centrality analyses (d_ii=0 breaks power decay). Report self-loop share as a headline descriptive.
- **Minimum-volume floor:** for residual/anomaly and significance claims, require w_ij ≥ a stated floor (e.g. ≥ 10–20 annual trips) so 1-vs-0 noise on tiny pairs cannot dominate.
- **Distance d_ij:** Euclidean centroid distance in EPSG:2263 as default; **observed mean trip_distance per OD pair** as the primary robustness variant (Euclidean understates Manhattan-grid/bridge/tunnel cost).
- **Coverage caveat (state once, cite everywhere):** ~95% of yellow pickups are below 96th St + JFK/LGA; outer-borough tracts are drop-off-dominated. Report this as a sampling artifact, never as pure demand.
- **Time slices:** keep a canonical 6-daypart × {weekday, weekend} = 12-slice decomposition plus an AM-peak / PM-peak pair, all built from the same trip-level table before annual collapse.

---

## TIER 0 — Faithful Reproduction (anchor and rebut the 2016 baseline)

### R1. Degree / strength distributions, directed
- **Claim:** The 2016 degree finding holds, but in-degree and out-degree are *different-shaped* distributions, exposing source/sink asymmetry the baseline missed.
- **Method/impl:** `G.in_degree(weight='weight')`, `G.out_degree(weight='weight')` (and unweighted degree). Plot complementary CDFs (numpy). Fit candidate laws with the `powerlaw` package: test in-degree ~ stretched-exponential vs out-degree ~ power-law-with-cutoff (Riascos & Mateos 2020) via Clauset-style likelihood-ratio comparison.
- **Inputs:** directed weighted edge list only.
- **Improves on:** the baseline's single undirected degree pass.
- **Figure:** Fig R1 — overlaid in/out weighted-degree CCDFs (log-log) with fitted-law annotations.
- **Tier:** must-have.

### R2. Single stochastic community pass, reproduced and stress-tested
- **Claim:** A single Louvain pass (as in 2016) is non-reproducible and can return disconnected "regions"; we reproduce it, then quantify its instability.
- **Method/impl:** `community.best_partition` (python-louvain) on the symmetrized graph, 1 seed (the baseline), then 50–100 seeds; report Q and the cross-seed AMI/VI spread; check each returned community's induced-subgraph connectivity with `networkx.connected_components` (test the Traag et al. 25%/16% disconnection claim).
- **Inputs:** edge list; symmetrized weights.
- **Improves on:** the baseline's one igraph community pass — this becomes the "why we upgraded" exhibit.
- **Figure:** Fig R2 — (a) baseline partition map; (b) histogram of cross-seed AMI with the baseline; (c) count of disconnected communities per run.
- **Tier:** must-have.

---

## TIER 1 — Spatial Interaction / Gravity (FLAGSHIP: "where Manhattan ends" as residuals)

This is the centerpiece. The deliverable is a **mapped residual ("surprise") field**: tract pairs and tracts that are over/under-connected after controlling for size and distance.

### G1. Production-constrained Poisson gravity with estimated decay
- **Claim:** Taxi destination choice falls off with separation at a calibrated exponent β (or λ); origin out-totals are reproduced exactly by construction.
- **Method/impl:** PySAL `spint.gravity.Production(flows, origins, dest_attr_cols, cost, 'pow'|'exp', Quasi=True)`. Fallback (preferred if SpInt install is fragile in 2021): `statsmodels.api.GLM(y, X, family=Poisson())` with **origin dummy variables** + `log(dest_attr_j)` + `−β log(d_ij)`; long-format OD list, diagonal dropped, volume floor applied. Read β, pseudo-R², SRMSE, SSI. Use **quasi-Poisson dispersion φ̂** for SEs.
- **Inputs:** long OD list; centroid distance matrix; O_i = weighted out-strength; dest attractiveness = in-strength and/or ACS population and/or area.
- **Improves on:** adds a calibrated, comparable behavioral parameter — nothing in the baseline.
- **Figure:** Fig G1 — observed vs fitted flow scatter (log-log, hexbin) with β, CPC, pseudo-R² in panel.
- **Tier:** must-have.

### G2. Doubly-constrained gravity (Furness/IPF) → balancing factors A_i, B_j
- **Claim:** After fixing *both* marginals, residual structure is pure spatial deduction; A_i (how hard to leave) and B_j (how hard to reach) are competition-adjusted per-tract indices.
- **Method/impl:** Route (1) SpInt `Doubly(...)` (origin+dest fixed effects, Poisson GLM). Route (2) classic vectorized Furness in numpy: T_ij = A_i O_i B_j D_j f(d_ij); iterate A_i = 1/Σ_j(B_j D_j f(d_ij)), B_j = 1/Σ_i(A_i O_i f(d_ij)) to convergence; calibrate f(d) so modeled mean trip distance = observed. Mask structural-zero blocks; normalize A_i, B_j before comparing.
- **Inputs:** O_i, D_j from weighted out/in strength; distance matrix; chosen decay form.
- **Improves on:** yields the cleanest residual baseline ("beyond size + distance") for the flagship map.
- **Figure:** Fig G2 — choropleths of A_i and B_j across tracts.
- **Tier:** must-have.

### G3. Over/under-connection residual field (FLAGSHIP)
- **Claim:** A small, mappable set of OD pairs is anomalously over-connected (airport↔Midtown, nightlife corridors) or under-connected after controlling for mass + distance — this *operationally defines where functional "Manhattan" ends*.
- **Method/impl:** From the doubly-constrained fit (primary) and production-constrained fit (secondary), compute per-edge **Pearson residual** r_ij = (T_obs − T̂)/√T̂ and **deviance residual** d_ij = sign(·)√(2(T_obs log(T_obs/T̂) − (T_obs − T̂))); divide by √φ̂ for quasi-Poisson calibration (`GLM.resid_deviance`, `.resid_pearson`). Rank edges; aggregate residuals to tract and borough level; plot **deviance residual vs distance band** (tail-failure diagnostic). Build a directed residual graph and run community detection/centrality on residuals (not raw flow).
- **Inputs:** fitted T̂, observed counts, φ̂.
- **Improves on:** converts the descriptive graph into a hypothesis-testing tool — the single biggest leap over degree + one community pass.
- **Figure:** Fig G3 — (a) map of top over- (red) / under- (blue) connected OD pairs as arcs; (b) tract-level mean-residual choropleth; (c) deviance-residual-vs-distance-band plot.
- **Tier:** must-have.

### G4. Radiation model benchmark + CPC head-to-head
- **Claim (testable):** At NYC tract resolution, the 1-parameter gravity model beats the parameter-free radiation model (Masucci 2013 regime) — a confirmable result.
- **Method/impl:** ~30-line numpy: per origin i, s_ij = Σ_{k≠i,j, d_ik<d_ij} m_k via sorted-distance prefix sums; T_ij = O_i · m_i m_j /((m_i+s_ij)(m_i+m_j+s_ij)). Implement the **production-constrained (normalized) radiation** variant (Lenormand 2016) for fair row-sum matching. Compare all models with **CPC = 2 Σ min(T_obs, T_pred)/(ΣT_obs+ΣT_pred)** as the primary metric (not R²/RMSE). Test mass = ACS population AND mass = taxi activity; report both.
- **Inputs:** tract masses (ACS population is where external fetch pays off; plus taxi-activity proxy), distance matrix, O_i.
- **Improves on:** provides a citable modern alternative and a clean comparative result.
- **Figure:** Fig G4 — bar chart of CPC across {production gravity, doubly gravity, radiation-pop, radiation-activity}.
- **Tier:** strong.

### G5. Residual autocorrelation control (credibility guard)
- **Claim:** Anomaly claims survive network/spatial autocorrelation — they are not artifacts of neighboring-pair correlation.
- **Method/impl:** Moran's I on tract-level residuals (PySAL `esda.Moran` with a contiguity/`libpysal` weights matrix); optionally eigenvector spatial filtering on the OD residuals before claiming significance. Report anomalies qualitatively if autocorrelation is strong.
- **Inputs:** tract residual field + tract adjacency.
- **Improves on:** preempts the "spurious anomaly" critique.
- **Figure:** Fig G5 — Moran scatterplot of residuals (can be a supplementary panel).
- **Tier:** strong.

---

## TIER 2 — Backbone Extraction (principled replacement for weight-thresholding)

### B1. Disparity filter (directed) — canonical baseline
- **Claim:** A few percent of edges carry ~90%+ of all trips while preserving most tracts (multiscale skeleton), beating a hard weight threshold.
- **Method/impl:** Directed closed form: α_out_ij = (1−w_ij/s_out_i)^{k_out_i−1}, α_in_ij from destination side; keep if min(α_in,α_out)<α (OR rule, inclusive). Use `aekpalakorn/python-backbone-network` or `netbone`. Sweep α∈[0.001,0.5]; pick by elbow on the **fraction-of-weight vs fraction-of-edges** retention curve. Special-case degree-1 tracts explicitly.
- **Inputs:** directed weighted edge list.
- **Improves on:** replaces the baseline's implicit/absent thresholding with a literature-standard, comparable filter.
- **Figure:** Fig B1 — retention curve (weight retained vs edges retained), with chosen α marked; inset backbone map.
- **Tier:** must-have.

### B2. Multi-filter comparison + consensus core corridors
- **Claim:** Filter choice systematically biases which edges survive; a consensus "core corridor" set is robust to that choice.
- **Method/impl:** Run via `netbone` (one API): Disparity, Noise-Corrected (Coscia-Neffke), Marginal-Likelihood (Dianati; `scipy.stats.binom.sf` + Benjamini-Hochberg FDR via `statsmodels.stats.multitest`), LANS (nonparametric ECDF), and Pólya-urn (Marcaccioli-Livan, sweep a). Optionally ECM via `NEMtropy` as the rigorous validation tier. At **matched edge-retention**, compare: (a) retained-vs-discarded weight distributions (quantify the Yassin 2023 high-weight bias); (b) giant-component size / tracts kept connected (test the Dianati "larger sparser GC" claim vs hard threshold). Build the **intersection** (consensus core) and **symmetric difference** (method-dependent edges).
- **Inputs:** directed weighted integer edge list; strengths, degrees, T.
- **Improves on:** turns "just threshold the weights" into a measurable, defensible robustness study.
- **Figure:** Fig B2 — (a) connected-tracts-vs-edges-retained curves per filter (incl. hard threshold); (b) consensus-core corridor map.
- **Tier:** strong.

### B3. Pólya vs disparity self-reinforcement contrast
- **Claim:** Corridors surviving disparity but dying under Pólya are the rich-get-richer (airport/Midtown) flows; those surviving both are surprising beyond popularity.
- **Method/impl:** Match α; diff the two backbones; annotate edges in the difference set geographically.
- **Inputs:** the two backbones from B2.
- **Improves on:** an interpretable, publishable contrast.
- **Figure:** Fig B3 — map coloring edges by {both, disparity-only, Pólya-only}.
- **Tier:** optional.

### B4. Backbone → downstream community stability
- **Claim:** Mesoscale partition depends on backbone choice (cross-filter AMI quantifies it).
- **Method/impl:** Run Leiden/Infomap on each backbone; pairwise AMI between partitions.
- **Inputs:** backbones (B2) + Tier-5 community code.
- **Figure:** Fig B4 — heatmap of cross-backbone partition AMI.
- **Tier:** optional.

---

## TIER 3 — Directed Centralities + Core-Periphery / Rich-Club

### C1. Net-flow source/sink index (attractor vs distributor ground truth)
- **Claim:** A continuous source↔sink axis ranks tracts; annual aggregation cancels commute directionality, exposed only by AM/PM splits.
- **Method/impl:** s_out = A.sum(axis=1), s_in = A.sum(axis=0); NFI_i = (s_in−s_out)/(s_in+s_out)∈[−1,1]. Compute annual AND per AM/PM slice (timestamps). Optional flow-hierarchy/"trophic level" via Laplacian solve L h = (s_in−s_out) (`scipy.sparse.linalg.spsolve`, MacKay-Johnson-Sansom 2020). Fare-weighted variant as robustness.
- **Inputs:** directed weighted adjacency; centroids for mapping; AM/PM slices.
- **Improves on:** directional role axis vs baseline undirected degree.
- **Figure:** Fig C1 — NFI choropleth (annual) beside AM and PM choropleths showing CBD sign-flip.
- **Tier:** must-have.

### C2. HITS hubs/authorities + weighted PageRank on G and G.reverse()
- **Claim:** Distributor (hub / reverse-PageRank) and attractor (authority / PageRank) roles are separable; methods agree on top attractors but diverge in the tail.
- **Method/impl:** `networkx.hits` (verify weights honored in your version; else sparse power iteration a = AᵀAa, h = AAᵀh via `scipy.sparse.linalg.eigs`). `networkx.pagerank(G, weight='weight')` and on `G.reverse()`; sweep α∈{0.7,0.85,0.95}; optional ACS-population `personalization`. Restrict to giant SCC. Cross-correlate authority−hub vs reverse-PR−PR vs NFI.
- **Inputs:** directed weighted adjacency (giant SCC); optional ACS population.
- **Improves on:** recursive, direction-aware importance vs raw degree.
- **Figure:** Fig C2 — (hub, authority) scatter, tracts colored by borough, top tracts labeled; quadrant role boundaries.
- **Tier:** must-have.

### C3. Current-flow (random-walk) betweenness — throughput connectors
- **Claim:** Pass-through "connector" tracts (bridge/tunnel-adjacent, Midtown corridors) are distinct from high-strength endpoints (low correlation = a result).
- **Method/impl:** Symmetrize (w_ij+w_ji), largest connected component, `networkx.current_flow_betweenness_centrality(weight='weight', normalized=True)`. Report the symmetrization choice (sum). Correlate with in/out-strength to prove specificity.
- **Inputs:** symmetrized weighted adjacency (LCC).
- **Improves on:** a genuinely new ranking vs degree.
- **Figure:** Fig C3 — current-flow-betweenness choropleth + scatter vs strength.
- **Tier:** strong.

### C4. Guimera-Amaral functional roles (z within-module × P participation)
- **Claim:** Airports emerge as high-participation **connector** hubs; Midtown tracts as **provincial/connector** hubs of the Manhattan basin — a 2D role coordinate per tract.
- **Method/impl:** On a Tier-5 partition: z_i = (k_i^intra − μ_module)/σ_module; P_i = 1 − Σ_s (k_is/k_i)². Use weighted strengths; compute P separately for in/out links. `bctpy` (module_degree_zscore, participation_coef) or ~30 lines numpy. Propagate partition uncertainty (multiple seeds). Plot z–P plane with Guimera-Amaral boundaries as descriptive heuristics.
- **Inputs:** a partition + weighted adjacency.
- **Improves on:** operationalizes airport-vs-Midtown as coordinates, not anecdote.
- **Figure:** Fig C4 — z–P scatter with role regions; role choropleth.
- **Tier:** strong.

### C5. Bridgeness (Rao-Stirling diversity over partition)
- **Claim:** Top inter-community bridges (bridge/tunnel/airport connectors) rank low on degree — new information vs the degree baseline.
- **Method/impl:** bridgeness_i = 1 − Σ_c p_ic² where p_ic = fraction of i's edge weight to community c (pandas group-bys on edge list joined to partition). Validate against degree/betweenness to prove specificity. Report across resolutions/seeds; prefer a flow (Infomap) partition.
- **Inputs:** weighted adjacency + partition; centroids.
- **Figure:** Fig C5 — bridgeness choropleth; scatter bridgeness vs degree.
- **Tier:** optional.

### C6. Rich-club: topological (normalized) + weighted + rich-multipolarization
- **Claim:** Whether dominant tracts form an exclusive club — and whether they hoard strong ties (rich-club) or route heavy flow to the periphery (rich-multipolarization); topological and weighted answers may oppose.
- **Method/impl:** Topological: `networkx.rich_club_coefficient(G_u, normalized=True, Q=100)` on undirected, self-loop-free projection; build your own 100–1000 `double_edge_swap` ensemble for a confidence band — **never report unnormalized φ(k)**. Weighted (numpy, Opsahl): rank by strength, φ_w(r) = (weight within top-r club)/(sum of r(r−1) largest weights), null via directed local out-weight reshuffle; ρ_w(r). Fare-weighted variant.
- **Inputs:** edge list (topological); directed weighted edge list (weighted); node strengths.
- **Improves on:** rigorous hub-club test vs a raw degree distribution; the topological-vs-weighted contrast is a finding.
- **Figure:** Fig C6 — ρ(k) (topological) and ρ_w(r) (weighted) curves with null bands.
- **Tier:** strong.

### C7. Core-periphery: cpnet (Rombach + Rossa + KM_config) with q-s test; k-core / rich-core
- **Claim:** NYC taxi flow has a statistically significant dense core (or *multiple* CP pairs: Midtown/Downtown/airports), with directional in-core (sinks) vs out-core (sources).
- **Method/impl:** `cpnet`: Rombach, Rossa, KM_config (multiple pairs); **always** run `cpnet.qstest(...)` (Kojaku-Masuda — mandatory). k-core via `networkx.core_number` on undirected simple graph; in/out-coreness via G and G.reverse(); report across a few edge-weight cutoffs (the full matrix is near-complete). Rich-core (Ma-Mondragon): σ+(r) argmax boundary in numpy. Cross-check core membership across methods (convergent = robust).
- **Inputs:** weighted (symmetrized) adjacency; tract polygons; edge-weight cutoff sweep.
- **Improves on:** a fitted, significance-tested mesoscale model vs a single community pass.
- **Figure:** Fig C7 — coreness choropleth (Rombach x) + in-core vs out-core maps.
- **Tier:** strong.

### C8. Directed degree/strength assortativity + knn(k)
- **Claim:** The network is disassortative (transport fingerprint); combined with a positive rich-club it signals a hierarchical "oligarchy."
- **Method/impl:** `networkx.degree_assortativity_coefficient` for all four directed pairs (x,y∈{in,out}) and weighted; `average_neighbor_degree` for knn(k). Report Spearman rank assortativity too (Pearson unstable on heavy tails).
- **Inputs:** directed (weighted) edge list.
- **Figure:** Fig C8 — knn(k) curve + table of four directed r coefficients.
- **Tier:** optional.

---

## TIER 4 — Temporal / Dynamic Networks

### T1. Non-negative tensor factorization (CP/PARAFAC) of O×D×time
- **Claim:** A handful of latent space-time modes (AM residential→Midtown commute; late-night nightlife return; airport runs) explain most flow, recovering communities and rhythms jointly.
- **Method/impl:** Build sparse tensor (2165×2165×T), T = 168 (hour-of-week) or 12 (6 dayparts × weekday/weekend). `tensorly.decomposition.non_negative_parafac` (sparse backend), rank R≈5–20 chosen by reconstruction-error elbow + CORCONDIA; multiple random inits for stability. Memory-saving alternative: `sklearn.decomposition.NMF` on the unfolded (OD-edge × time) matrix. L1-normalize loadings to read as flow shares. Restrict to non-trivial-volume pairs; consider separate night-rank fit so commute modes don't swamp nightlife.
- **Inputs:** trip-level (origin tract, dest tract, time bin) counts before annual collapse; centroids for mapping.
- **Improves on:** joint community+rhythm recovery — far beyond a static pass.
- **Figure:** Fig T1 — per-component panels: origin-loading map, dest-loading map, temporal-activation curve.
- **Tier:** strong.

### T2. Day-vs-night district-role signatures (temporal-profile clustering)
- **Claim:** Tracts cluster into ~3–4 reproducible rhythms (residential/CBD/nightlife/gateway); net-flux sign-flip between AM and PM peaks defines role-flipping tracts.
- **Method/impl:** Per tract, L1-normalized vector [pickups_per_bin ‖ dropoffs_per_bin]; `sklearn.cluster.KMeans`/`AgglomerativeClustering` (k by silhouette) or `NMF` for soft rhythm memberships. f_i(t) = pickups−dropoffs; flag AM→PM sign change. Map clusters (geopandas).
- **Inputs:** per-tract per-bin pickup/dropoff marginals; polygons; optional ACS population (per-capita).
- **Improves on:** interpretive ground-truth layer validating T1 and the source/sink story.
- **Figure:** Fig T2 — rhythm-cluster choropleth + mean profile per cluster; role-flip tract map.
- **Tier:** strong.

### T3. Time-sliced Guimera-Amaral role trajectories
- **Claim:** Hub *type* shifts across the day — a tract that is a provincial hub at 8am becomes a connector hub at midnight.
- **Method/impl:** Per slice: Leiden partition → (z,P) per tract; stack into per-tract role trajectories; mask tracts below a min trip count (noisy late-night z). Fix resolution; consensus over seeds.
- **Inputs:** per-slice directed weighted graphs + partitions.
- **Figure:** Fig T3 — selected tracts' trajectories in the z–P plane across dayparts.
- **Tier:** optional.

### T4. Multilayer (Mucha) dynamic communities + node flexibility
- **Claim:** Nightlife districts detach from their daytime community at night; "flexibility" = fraction of slices a tract switches community is a clean dynamic metric.
- **Method/impl:** `leidenalg.find_partition_temporal` (slices-to-layers, interslice coupling ω) optimizing CPM/RBConfiguration; sweep γ≈1, ω∈[0.1,1.0]; flexibility = fraction of consecutive slices with label change (numpy). Prefer directed modularity.
- **Inputs:** per-slice directed graphs (all 2165 nodes in every layer); ω, γ.
- **Figure:** Fig T4 — flexibility choropleth; alluvial/Sankey of community membership across dayparts.
- **Tier:** optional.

### T5. Year-long reproducibility / anomaly detection
- **Claim:** Weekday hourly slices repeat stably across 52 weeks; the Jan-2015 blizzard travel ban appears as a detectable dip in temporal activation vectors.
- **Method/impl:** Cross-week AMI of partitions / correlation of temporal-activation vectors (T1); flag outlier days.
- **Inputs:** weekly slices; T1 activations.
- **Figure:** Fig T5 — week-over-week stability curve with blizzard annotation.
- **Tier:** optional.

---

## TIER 5 — Rigorous Communities (replace single stochastic pass)

### M1. Leiden as primary partitioner (modularity AND CPM), directed + weighted
- **Claim:** Every detected region is internally connected (Leiden guarantee), unlike Louvain.
- **Method/impl:** `leidenalg` on directed weighted igraph; `RBConfigurationVertexPartition` (modularity) and `CPMVertexPartition` (resolution-limit-free; log-transform/normalize weights, log γ grid), `n_iterations=-1`, 50–100 seeds. `cdlib` wraps if preferred.
- **Inputs:** directed weighted edge list.
- **Improves on:** strict upgrade over the 2016 Louvain/igraph pass (pairs with R2).
- **Figure:** Fig M1 — Leiden partition map (chosen robust resolution).
- **Tier:** must-have.

### M2. Infomap (map equation) flow-based communities
- **Claim:** Flow-based communities respect edge direction and recover a borough→neighborhood hierarchy; they differ materially from modularity (NMI < ~0.7 would be a finding).
- **Method/impl:** `infomap` (`--directed --two-level --num-trials 50`); read `get_modules()` and `tree` (hierarchy); report `codelength` and savings vs one-module baseline. Ablation: `--undirected`; report tau robustness. Drop self-loops.
- **Inputs:** directed weighted edge list (raw counts as flow).
- **Improves on:** the theme-appropriate method the baseline lacked.
- **Figure:** Fig M2 — Infomap hierarchical partition map; codelength table.
- **Tier:** must-have.

### M3. Resolution sweep + multiscale stability
- **Claim:** 2–3 robust scales exist (borough-level, neighborhood-level); single-γ modularity provably merges small real regions (Fortunato-Barthelemy).
- **Method/impl:** γ on `np.logspace(-1,1,25)`; Leiden multi-seed per γ; record num_communities and cross-seed AMI/VI; plateaus = robust scales. `leidenalg.Optimiser().resolution_profile` for CPM; optional Markov-stability via `PyGenStability`. Directed (Leicht-Newman) null.
- **Inputs:** directed weighted edge list (transition matrix for Markov variant).
- **Figure:** Fig M3 — num-communities-vs-γ + stability curve, robust plateaus shaded.
- **Tier:** strong.

### M4. Consensus clustering → single reproducible partition
- **Claim:** Consensus is more stable *and* more accurate than any single run; the co-association matrix is itself a soft "do these tracts belong together" map.
- **Method/impl:** N=100 partitions → co-association D (2165×2165 ~37MB); threshold τ (report {0.3,0.5,0.7}); re-cluster D with Leiden; iterate to fixed point. Run separately per robust resolution. `cdlib` consensus utility available.
- **Inputs:** ensemble of partitions.
- **Figure:** Fig M4 — ordered co-association matrix heatmap + consensus partition map.
- **Tier:** strong.

### M5. Partition comparison: AMI / ARI / VI (the measurement backbone)
- **Claim:** Functional taxi regions deviate from administrative boundaries (boroughs/NTAs/community districts) — "taxi flows redraw the map of NYC."
- **Method/impl:** `sklearn.metrics.adjusted_mutual_info_score` (prefer AMI over NMI when cluster counts differ), `adjusted_rand_score`; VI = H(A)+H(B)−2I(A,B) via `mutual_info_score` + `scipy.stats.entropy` (normalize by log n). Use for: cross-seed stability, Leiden-mod vs Leiden-CPM vs Infomap agreement, and consensus-partition vs administrative codes (from the TIGER/census shapefiles already used).
- **Inputs:** aligned label vectors; tract→borough/NTA/CD codes.
- **Improves on:** makes the whole study measurable, not anecdotal.
- **Figure:** Fig M5 — matrix of pairwise AMI/VI across methods + a bar of partition-vs-administrative distance.
- **Tier:** must-have.

### M6. Space-deflated communities (Expert Q_Spa)
- **Claim:** Naive communities mostly rediscover geography; after dividing out an empirical deterrence f(d), space-independent communities (airport↔Midtown) emerge.
- **Method/impl:** B_ij = A_ij − s_i^out s_j^in f(d_ij), with f(d) empirically binned (30–50 log bins; f(d) = Σ_bin A_ij / Σ_bin s_i^out s_j^in). Optimize Q_Spa via Newman leading-eigenvector on B (signed modularity matrix) — python-louvain won't accept a custom null, so implement the gain directly or use a spectral/greedy optimizer on B. Compare to the plain-null partition via AMI; also compare to k-means on centroids (does it just mirror geography?). State the directed extension as your own construction.
- **Inputs:** directed weighted adjacency; centroids; optional ACS population for N_i.
- **Improves on:** isolates the genuinely interesting non-spatial structure — directly tied to the flagship "where Manhattan ends."
- **Figure:** Fig M6 — side-by-side plain-null vs space-deflated partition maps.
- **Tier:** strong.

---

## TIER 6 — Null-Model Validation (avoid spurious-structure claims)

### N1. Edge significance via maximum-entropy directed weighted configuration null
- **Claim:** Specific OD edges/reciprocal pairs occur far more/less than chance given each tract's in/out totals.
- **Method/impl:** `NEMtropy` directed weighted configuration model (DECM) fit to (s_out, s_in) [+ optional (k_out, k_in)]; per-pair ⟨w_ij⟩, σ_ij → z_ij; Benjamini-Hochberg FDR over pairs. Closed-form fallback: Poisson grand-canonical ⟨w_ij⟩ = s_out_i s_in_j / W with Poisson variance → analytic z-test. Scale weights; verify fitted strengths reproduce observed. State soft-vs-hard constraint choice (nonequivalence for heterogeneous nets).
- **Inputs:** directed weighted edge list (strengths/degrees derived).
- **Improves on:** defensible significance vs raw counts.
- **Figure:** Fig N1 — distribution of edge z-scores; map of FDR-significant over/under edges (complements G3 — note G3 controls for distance, N1 does not).
- **Tier:** strong.

### N2. Reciprocity (null-corrected) + weighted reciprocity decomposition
- **Claim:** The annual graph looks near-balanced yet is strongly imbalanced (sign-flipping) every hour; naive reciprocity is uninformative.
- **Method/impl:** Garlaschelli-Loffredo ρ = (r − ā)/(1 − ā) (compute yourself, not just `nx.overall_reciprocity`); weighted decomposition W↔ = Σ min(w_ij,w_ji), W→, W← vs weighted-configuration expectation (NEMtropy). Compute per hour-of-day. Map NFI (links to C1).
- **Inputs:** directed weighted adjacency; timestamps for hourly stratification.
- **Figure:** Fig N2 — ρ and reciprocated-strength share by hour-of-day.
- **Tier:** strong.

### N3. Modularity significance + DC-SBM model selection
- **Claim:** Detected communities beat a configuration null (z-score/p), and a degree-corrected SBM independently selects the community count — guarding against modularity finding structure in noise.
- **Method/impl:** Q_obs vs ≥1000 directed configuration rewirings (`networkx.directed_configuration_model` preserving k_in/k_out), z = (Q_obs − μ)/σ; stability via consensus (M4). DC-SBM: `graph-tool.minimize_blockmodel_dl(deg_corr=True)` (cheap at 2k nodes) for MDL-based K; cross-check blocks vs modularity communities via AMI. Fallback if graph-tool not installable: modularity + permutation null + consensus.
- **Inputs:** directed weighted edge list.
- **Improves on:** turns "we found communities" into "the communities are statistically real."
- **Figure:** Fig N3 — Q_obs vs null Q distribution; AMI(DC-SBM, modularity) reported.
- **Tier:** must-have.

### N4. Soft-vs-hard constraint sanity check
- **Claim:** For a strength-heterogeneous network, canonical and microcanonical nulls can give different verdicts on hub edges.
- **Method/impl:** Compare DECM (soft) z-scores vs a microcanonical/Monte-Carlo null on a handful of hub edges.
- **Inputs:** N1 outputs.
- **Figure:** supplementary table.
- **Tier:** optional.

---

## Suggested minimum publishable set (the "must-haves")
R1, R2 (anchor) → **G1, G2, G3** (flagship residual map) → B1 (backbone) → C1, C2 (directed roles) → M1, M2, M5 (rigorous communities + measurement) → N3 (significance). Everything in "strong" deepens it toward paper-grade; "optional" items are robustness/extension panels.

---

## Consolidated Reference List (de-duplicated, real citations)

**Spatial interaction / gravity / radiation**
1. Wilson, A. G. (1967). A statistical theory of spatial distribution models. *Transportation Research* 1(3):253–269. https://doi.org/10.1016/0041-1647(67)90035-4
2. Flowerdew, R. & Aitkin, M. (1982). A method of fitting the gravity model based on the Poisson distribution. *Journal of Regional Science* 22(2):191–202.
3. Flowerdew, R. & Lovett, A. (1988). Fitting constrained Poisson regression models to interurban migration flows. *Geographical Analysis* 20(4):297–307.
4. Simini, F., González, M. C., Maritan, A. & Barabási, A.-L. (2012). A universal model for mobility and migration patterns. *Nature* 484:96–100.
5. Masucci, A. P., Serras, J., Johansson, A. & Batty, M. (2013). Gravity versus radiation models: on the importance of scale and heterogeneity in commuting flows. *Phys. Rev. E* 88:022812.
6. Lenormand, M., Bassolas, A. & Ramasco, J. J. (2016). Systematic comparison of trip distribution laws and models. *J. Transport Geography* 51:158–169.
7. Oshan, T. M. (2016). A primer for working with the Spatial Interaction modeling (SpInt) module in PySAL. *REGION* 3(2):R11–R23.
8. Liu, Y., Gong, L., Gong, J. & Liu, Y. (2015). Delineating intra-urban spatial connectivity patterns by travel-activities: a case study of Beijing. arXiv:1407.4194.
9. Dearmon, J. & Smith, T. E. (2016). Gaussian process regression and Bayesian model averaging: predictive limitations of spatial interaction models. (PMC7566590).
10. Barbosa, H., Barthelemy, M., Ghoshal, G., et al. (2018). Human mobility: models and applications. *Physics Reports* 734:1–74.

**Backbone extraction**
11. Serrano, M. Á., Boguñá, M. & Vespignani, A. (2009). Extracting the multiscale backbone of complex weighted networks. *PNAS* 106(16):6483–6488 (arXiv:0904.2389).
12. Coscia, M. & Neffke, F. M. H. (2017). Network backboning with noisy data. *IEEE ICDE 2017*:425–436 (arXiv:1701.07336).
13. Marcaccioli, R. & Livan, G. (2019). A Pólya urn approach to information filtering in complex networks. *Nature Communications* 10:745.
14. Dianati, N. (2016). Unwinding the hairball graph: pruning algorithms for weighted complex networks. *Phys. Rev. E* 93:012304.
15. Foti, N. J., Hughes, J. M. & Rockmore, D. N. (2011). Nonparametric sparsification of complex multiscale networks (LANS). *PLoS ONE* 6(2):e16431.
16. Gemmetto, V., Cardillo, A. & Garlaschelli, D. (2017). Irreducible network backbones: unbiased graph filtering via maximum entropy. arXiv:1706.00230.
17. Neal, Z. P. (2022). backbone: an R package to extract network backbones. *PLoS ONE* 17(5):e0269137.
18. Yassin, A., et al. (2023). Evaluation of network backbone extraction techniques (netbone). *Scientific Reports* 13.

**Communities / regionalization / partition comparison**
19. Rosvall, M. & Bergstrom, C. T. (2008). Maps of random walks on complex networks reveal community structure. *PNAS* 105(4):1118–1123.
20. Rosvall, M., Axelsson, D. & Bergstrom, C. T. (2009). The map equation. *Eur. Phys. J. Special Topics* 178:13–23 (arXiv:0906.1405).
21. Edler, D., Holmgren, A., Rosvall, M., et al. (2024). Community detection with the map equation and Infomap. arXiv:2311.04036.
22. Traag, V. A., Waltman, L. & van Eck, N. J. (2019). From Louvain to Leiden: guaranteeing well-connected communities. *Scientific Reports* 9:5233.
23. Traag, V. A., Van Dooren, P. & Nesterov, Y. (2011). Narrow scope for resolution-limit-free community detection (CPM). *Phys. Rev. E* 84:016114.
24. Fortunato, S. & Barthélemy, M. (2007). Resolution limit in community detection. *PNAS* 104(1):36–41.
25. Lambiotte, R., Delvenne, J.-C. & Barahona, M. (2014). Random walks, Markov processes and the multiscale modular organization of complex networks. *IEEE TNSE* (arXiv:1502.04381).
26. Leicht, E. A. & Newman, M. E. J. (2008). Community structure in directed networks. *Phys. Rev. Lett.* 100:118703.
27. Lancichinetti, A. & Fortunato, S. (2012). Consensus clustering in complex networks. *Scientific Reports* 2:336.
28. Meilă, M. (2007). Comparing clusterings—an information based distance. *J. Multivariate Analysis* 98(5):873–895.
29. Expert, P., Evans, T. S., Blondel, V. D. & Lambiotte, R. (2011). Uncovering space-independent communities in spatial networks. *PNAS* 108(19):7663–7668.
30. Sarzynska, M., Leicht, E. A., Chowell, G. & Porter, M. A. (2016). Null models for community detection in spatially embedded, temporal networks. *J. Complex Networks* 4(3):363–406.
31. Ratti, C., Sobolevsky, S., Calabrese, F., Andris, C., Strogatz, S., et al. (2010). Redrawing the map of Great Britain from a network of human interactions. *PLoS ONE* 5(12):e14248.
32. Cazabet, R., Borgnat, P. & Jensen, P. (2017). Using degree-constrained gravity null-models to understand the structure of journeys' networks in bicycle sharing systems. *ESANN 2017*.

**Centralities / roles / source-sink**
33. Kleinberg, J. M. (1999). Authoritative sources in a hyperlinked environment. *J. ACM* 46(5):604–632.
34. Page, L., Brin, S., Motwani, R. & Winograd, T. (1999). The PageRank citation ranking. Stanford InfoLab.
35. Newman, M. E. J. (2005). A measure of betweenness centrality based on random walks. *Social Networks* 27(1):39–54.
36. Brandes, U. & Fleischer, D. (2005). Centrality measures based on current flow. *STACS 2005*, LNCS 3404:533–544.
37. Guimerà, R. & Amaral, L. A. N. (2005). Functional cartography of complex metabolic networks. *Nature* 433:895–900.
38. Jensen, P., Morini, M., Karsai, M., et al. (2016). Detecting global bridges in networks. *J. Complex Networks* (arXiv:1509.08295).
39. Nepusz, T., Petróczi, A., Négyessy, L. & Bazsó, F. (2008). Fuzzy communities and the concept of bridgeness in complex networks. *Phys. Rev. E* 77:016107.
40. MacKay, R. S., Johnson, S. & Sansom, B. (2020). How directed is a directed network? *Royal Society Open Science* 7:201138.

**Core-periphery / rich-club / assortativity**
41. Colizza, V., Flammini, A., Serrano, M. Á. & Vespignani, A. (2006). Detecting rich-club ordering in complex networks. *Nature Physics* 2:110–115.
42. Opsahl, T., Colizza, V., Panzarasa, P. & Ramasco, J. J. (2008). Prominence and control: the weighted rich-club effect. *Phys. Rev. Lett.* 101:168702.
43. Serrano, M. Á. (2008). Rich-club vs rich-multipolarization phenomena in weighted networks. *Phys. Rev. E* 78:026101.
44. Alstott, J., Panzarasa, P., Rubinov, M., Bullmore, E. T. & Vértes, P. E. (2014). A unifying framework for measuring weighted rich clubs. *Scientific Reports* 4:7258.
45. Ma, A. & Mondragón, R. J. (2015). Rich-cores in networks. *PLoS ONE* 10(3):e0119678.
46. Kong, Y.-X., Shi, G.-Y., Wu, R.-J., et al. (2019). k-core: theories and applications. *Physics Reports* 832:1–32.
47. Rombach, P., Porter, M. A., Fowler, J. H. & Mucha, P. J. (2017). Core-periphery structure in networks (revisited). *SIAM Review* 59(3):619–646.
48. Della Rossa, F., Dercole, F. & Piccardi, C. (2013). Profiling core-periphery network structure by random walkers. *Scientific Reports* 3:1467.
49. Kojaku, S. & Masuda, N. (2017). Finding multiple core-periphery pairs in networks. *Phys. Rev. E* 96:052313. — and Kojaku & Masuda (2018). Core-periphery structure requires something else in the network. *New J. Phys.* 20:043012.
50. Newman, M. E. J. (2003). Mixing patterns in networks. *Phys. Rev. E* 67:026126.
51. Foster, J. G., Foster, D. V., Grassberger, P. & Paczuski, M. (2010). Edge direction and the structure of networks. *PNAS* 107(24):10815–10820.
52. Hanson, H., Vandell, et al. (2020). Spatial super-spreaders and super-susceptibles in human movement networks. arXiv:2005.05063.

**Temporal / tensor**
53. Gauvin, L., Panisson, A. & Cattuto, C. (2014). Detecting the community structure and activity patterns of temporal networks: a non-negative tensor factorization approach. *PLoS ONE* 9(1):e86028.
54. Sun, L. & Axhausen, K. W. (2016). Understanding urban mobility patterns with a probabilistic tensor factorization framework. *Transportation Research Part B* 91:511–524.
55. Mucha, P. J., Richardson, T., Macon, K., Porter, M. A. & Onnela, J.-P. (2010). Community structure in time-dependent, multiscale, and multiplex networks. *Science* 328(5980):876–878.
56. Roth, C., Kang, S. M., Batty, M. & Barthélemy, M. (2011). Structure of urban movements: polycentric activity and entangled hierarchical flows. *PLoS ONE* 6(1):e15923.
57. Sun, L., Axhausen, K. W., Lee, D.-H. & Huang, X. (2013). Understanding metropolitan patterns of daily encounters. *PNAS* 110(34):13774–13779.
58. Louf, R. & Barthelemy, M. (2013). Modeling the polycentric transition of cities. *Phys. Rev. Lett.* 111:198702.

**Null models / max-entropy / NYC taxi**
59. Squartini, T. & Garlaschelli, D. (2011). Analytical maximum-likelihood method to detect patterns in real networks. *New J. Phys.* 13:083001.
60. Cimini, G., Squartini, T., Saracco, F., Garlaschelli, D., Gabrielli, A. & Caldarelli, G. (2019). The statistical physics of real-world networks. *Nature Reviews Physics* 1:58–71.
61. Squartini, T. & Garlaschelli, D. (2017). *Maximum-Entropy Networks: Pattern Detection, Network Reconstruction and Graph Combinatorics.* Springer.
62. Vallarano, N., Bruno, M., Marchese, E., Squartini, T., et al. (2021). Fast and scalable likelihood maximization for exponential random graph models (NEMtropy). *Scientific Reports* 11.
63. Garlaschelli, D. & Loffredo, M. I. (2004). Patterns of link reciprocity in directed networks. *Phys. Rev. Lett.* 93:268701.
64. Squartini, T., Picciolo, F., Ruzzenenti, F. & Garlaschelli, D. (2013). Reciprocity of weighted networks. *Scientific Reports* 3:2729.
65. Karrer, B. & Newman, M. E. J. (2011). Stochastic blockmodels and community structure in networks. *Phys. Rev. E* 83:016107.
66. Lancichinetti, A., Radicchi, F. & Ramasco, J. J. (2010). Statistical significance of communities in networks. *Phys. Rev. E* 81:046110.
67. Riascos, A. P. & Mateos, J. L. (2020). Networks and long-range mobility in cities: a study of more than one billion taxi trips in New York City. *Scientific Reports* 10:4022.
68. Wang / Xie, Yu, Zheng, Wang & Jiang (2021). Revealing spatiotemporal travel demand and community structure characteristics with taxi trip data: a case study of New York City. *PLoS ONE* 16(11):e0259694.

Files relevant to this task: none created (analysis spec delivered inline above). The working directory `/Users/nilesh-patil/versioned-projects/Github-personal.tmp/tfn-modernization/transportation-flow-network` was not read or modified.