This is a synthesis/critique task — no skill needed. I have everything required in the prompt. Let me produce the adversarial review directly.

# Adversarial Methods Review — NYC Taxi Tract-Level OD Network Spec

## Cross-cutting problems that contaminate multiple analyses

**1. The yellow-taxi coverage bias is treated as a footnote but it structurally invalidates several flagship claims.**
The spec correctly flags that ~95% of pickups are below 96th St + airports, but then proceeds to fit gravity/radiation models and compute source/sink indices on a network where the sampling probability of a trip is a strong, *spatially structured* function of origin. A gravity residual in the Bronx is not "under-connected after controlling for mass and distance" — it is unobserved demand. The "where Manhattan ends" framing (G3) is partly a restatement of "where yellow-taxi service ends." **Correction:** demote the residual map from "operationally defines where functional Manhattan ends" to "identifies over/under-connection *conditional on yellow-taxi observation*," and restrict all residual/anomaly claims to the high-coverage subgraph (Manhattan-below-96 + airports + their first-order neighbors) where coverage is roughly uniform. Quantify coverage per tract (pickups/area or pickups/ACS-pop) and use it as a covariate or a mask, not just prose.

**2. "Mass" for gravity/radiation is endogenous when set to in/out-strength.** G1/G2/G4 propose dest attractiveness = in-strength and O_i = out-strength. Fitting a flow model where the predictors are the flow marginals themselves makes pseudo-R² and CPC meaningless as validation — you are predicting flows from their own row/column sums. Doubly-constrained gravity (G2) is the honest version (it *only* uses marginals and distance, and that's stated), but G1's "pseudo-R²" headline will be inflated. **Correction:** for any model meant to *explain* rather than *reconstruct*, mass must be exogenous (ACS population, employment LEHD/LODES, points-of-interest counts). This makes ACS (and ideally LODES workplace-area employment) a **must-fetch**, not "optional." Without exogenous mass, G1 and the radiation model (G4) cannot be fairly compared — radiation *requires* exogenous population masses to mean anything.

**3. Annual aggregation + Poisson assumption.** Counts at 146M trips over 2165² pairs are massively overdispersed (mixture across 365 days, dayparts, weather). The spec does say "quasi-Poisson φ̂" — good — but a single global φ̂ understates heterogeneity; dispersion itself varies with distance and volume. **Correction:** prefer Negative Binomial (`statsmodels NegativeBinomial` / GLM NB) over quasi-Poisson for the residual field, and check residuals-vs-fitted for remaining structure before ranking "anomalies." Report whether the top residuals are simply the highest-volume pairs (Pearson residuals scale with √T̂, so they over-flag big pairs; deviance residuals are better but still need this check).

**4. Symmetrization is used as a reflex and silently discards the directed signal that's supposedly the whole point.** R2, C3, C7, and rich-club all symmetrize. For a commuting network the in/out asymmetry IS the structure (the spec celebrates this in C1/C2). Symmetrizing for current-flow betweenness and core-periphery is defensible for tractability but must be stated as a known information loss, and at least one directed alternative reported. **Correction:** for C3, note that current-flow betweenness has no standard directed form in networkx; either accept symmetrization explicitly or use directed random-walk betweenness from a different implementation — don't imply it's measuring directed throughput.

---

## Per-analysis findings

### Tier 0
- **R1 (in/out degree laws):** Computable, sound. Caveat: this graph is near-complete after aggregation (2165 nodes, many millions of possible pairs realized), so "degree" (number of distinct partners) may be saturated/uninformative; the *strength* distribution is the real object. The `powerlaw` LR test on **strength** is fine, but do not over-claim "power law" — Clauset's own guidance is that LR tests distinguish among candidates, they don't confirm power-law. Report xmin sensitivity. **Keep, reframe around strength not degree.**
- **R2 (single Louvain instability):** Good rhetorical anchor, cheap, correct. Minor: AMI vs VI both fine; report VI in bits and AMI, since AMI can be misleadingly high when one partition is near-trivial. **Keep.**

### Tier 1 (gravity)
- **G1:** See cross-cutting #2. With origin dummies + log(dest mass) + −β log d, this IS a production-constrained Poisson gravity — correct setup. The fragility worry about SpInt is real; the statsmodels fallback is the simplest correct implementation and should be **primary**, not fallback. Watch d_ij=0 on the diagonal (already dropped) and d→small for adjacent-centroid pairs (log blows up); add a small floor or use the observed-trip-distance variant.
- **G2 (doubly-constrained / Furness):** Correct and the right baseline for residuals. The numpy Furness is the simplest correct impl; calibrating f(d) to match observed mean trip distance is standard. Sanity check: confirm convergence and that masked structural zeros don't break row/col sums.
- **G3 (residual flagship):** Strongest idea, most over-claimed. Beyond cross-cutting #1/#3: Pearson residuals will rank-correlate with volume; "top over-connected pairs" risks being "airport–Midtown is big," which is not a discovery. **Correction:** report residuals at a matched volume floor, show the deviance-residual-vs-distance plot first as a *model-adequacy* diagnostic (if the decay function is wrong, every long pair is a fake "anomaly"), and only then rank. Pair with N1 (mention is made) but note N1 doesn't control distance, so they answer different questions — say which one backs the headline.
- **G4 (radiation):** The prefix-sum s_ij implementation is correct and cheap. But radiation needs exogenous population masses (cross-cutting #2); "mass = taxi activity" radiation is circular and should be dropped or labeled a curiosity. The claim "gravity beats radiation at this scale" is plausibly true (Masucci regime) and confirmable — keep CPC as the metric (good choice, R² is wrong for flows). **Keep gravity-vs-radiation only with ACS/LODES mass.**
- **G5 (Moran's I on residuals):** Right instinct, but Moran's I on *tract-level aggregated* residuals tests node autocorrelation, while the anomalies are *edges*. The real risk is dyadic/network autocorrelation (origin and destination effects), largely absorbed by the doubly-constrained fixed effects already. **Correction:** state that G2's marginal fixing handles most of it; use Moran only as a residual-of-residual check, not the main defense. **Demote to supplementary.**

### Tier 2 (backbone)
- **B1 (disparity filter):** Correct closed form, directed OR-rule is the standard. The degree-1 special case is correctly flagged (disparity is undefined/keeps-all for k=1). Elbow on weight-vs-edge retention is the simplest defensible α. **Keep, must-have.**
- **B2 (multi-filter + consensus):** Genuinely valuable robustness study. Caveat: noise-corrected and marginal-likelihood filters assume an underlying generative null (often a configuration/independence model) that may not suit a near-complete spatial flow matrix; report each filter's null assumption rather than treating them as interchangeable. Matched-retention comparison is the right way to compare. **Keep as strong.**
- **B3, B4:** Optional, fine, low value-per-effort. B4's "backbone changes downstream communities" is almost guaranteed true and not very informative. **Drop B3/B4 from must-have.**

### Tier 3 (centralities / core-periphery)
- **C1 (NFI + trophic level):** NFI = (s_in−s_out)/(s_in+s_out) is well-defined and the AM/PM sign-flip is the single most compelling, robust, directional result in the whole spec — and it's cheap. The trophic/Laplacian solve (MacKay-Johnson-Sansom) is a nice add but requires a connected graph and care with the flow definition; keep as optional within C1. **Promote — this is top-tier value-per-effort.**
- **C2 (HITS / PageRank):** Verify HITS honors weights (it historically did not in some networkx versions — correct flag). On a near-complete graph, PageRank will be dominated by strength and may add little beyond C1; the *divergence in the tail* claim needs a quantified correlation, not assertion. **Keep but expect it to mostly echo strength; report the correlation honestly.**
- **C3 (current-flow betweenness):** See cross-cutting #4 (directedness lost). Also: current-flow betweenness is O(n³)-ish / memory-heavy; at n=2165 on a *dense* graph it may be expensive — must run on a backbone/LCC, not the full matrix. The "low correlation with strength = a result" is fine if it holds. **Keep but run on backbone, state symmetrization.**
- **C4 (Guimerà-Amaral z–P):** Correct, but z-scores are unstable for small modules and the role-boundary thresholds are heuristic (the spec admits this). Propagating partition uncertainty across seeds is the right call. **Keep as strong.**
- **C5 (bridgeness):** Optional, fine. Low marginal value over C4.
- **C6 (rich-club):** Correctly insists on normalized φ and a swap-null ensemble — good, this is the most common error and they avoided it. Weighted Opsahl variant correct. **Keep as strong.** Caveat: the topological rich-club on a near-complete graph may be trivially ~1 (everyone connects to everyone); the *weighted* version is the informative one — lead with it.
- **C7 (cpnet core-periphery + qstest):** Mandatory qstest is correctly required (Kojaku-Masuda showed CP is often spurious). Good. Caveat: cpnet on a dense weighted graph may be slow; the "edge-weight cutoff sweep" is really a backbone in disguise — reconcile with Tier 2 so you're not thresholding two different ways. **Keep as strong.**
- **C8:** Optional, fine. Spearman recommendation is correct for heavy tails.

### Tier 4 (temporal) — *this tier hinges on a data assumption the spec never verifies*
**All of Tier 4 requires timestamped, trip-level OD data before annual collapse.** The scope line says "annual (2015) trip count" as the edge weight and only later mentions building slices "from the same trip-level table." **Critical check:** confirm you actually have the raw trip records (pickup datetime + both tract IDs), not just the pre-aggregated annual matrix. If only the annual matrix exists, T1–T5 are *all uncomputable* and must be cut. This is the single biggest "is it computable" risk in the spec and it's buried.
- **T1 (NTF/PARAFAC):** If trip-level data exists: correct. CORCONDIA + reconstruction elbow + multi-init is the right rank-selection. Sparse 2165×2165×168 tensor is fine memory-wise sparsely; dense is not. The NMF-on-unfolded fallback is the simplest correct impl and probably sufficient. **Keep as strong conditional on data.**
- **T2 (rhythm clustering):** Most robust temporal analysis, cheapest, least assumption-laden. **Promote above T1.**
- **T3, T4, T5:** Optional. T4 (multilayer Mucha/Leiden temporal) is high-effort, ω/γ-sensitive, and the "nightlife detaches" claim is hard to defend rigorously. **Keep optional.** T5 blizzard detection is a fun sanity check, cheap — keep as a validation aside.

### Tier 5 (communities)
- **M1 (Leiden):** Correct upgrade. Directed weighted with both modularity and CPM, multi-seed. CPM weight-normalization caveat noted. **Must-have.**
- **M2 (Infomap):** Theme-appropriate (flow-based, directed). Correct flags. **Must-have.** Note: on a near-complete graph Infomap may collapse to few modules; report codelength savings honestly.
- **M3 (resolution sweep):** Correct, standard. **Strong.**
- **M4 (consensus):** Correct; co-association 2165² ~ 37MB is fine. **Strong.**
- **M5 (AMI/ARI/VI + vs administrative):** This is the measurement backbone and the "taxi redraws NYC" claim lives here. Correct metric choices (AMI over NMI when K differs). **Must-have.** Caveat: comparing functional partition to boroughs/NTAs will *trivially* show deviation — every flow partition differs from admin units. Make the claim quantitative (how much, where) not binary.
- **M6 (space-deflated / Q_Spa):** Best community idea, directly tied to the flagship. Correct that python-louvain can't take a custom null → must implement gain or use spectral on B. Caveat: the directed extension is the author's own construction (honestly flagged) — validate it reduces to standard Q_Spa on a symmetrized graph. **Keep as strong**, but it partly duplicates G3's "non-spatial structure" goal — coordinate the two so the paper doesn't claim the same finding twice.

### Tier 6 (nulls)
- **N1 (DECM via NEMtropy):** Correct and the rigorous version. Caveat: DECM fitting on a 2165-node strength-heterogeneous dense graph can be numerically finicky; the Poisson grand-canonical fallback (⟨w_ij⟩ = s_out_i s_in_j / W) is the simplest correct impl and probably adequate — lead with it, use DECM as the upgrade. **Strong.**
- **N2 (reciprocity):** Garlaschelli-Loffredo ρ computed properly (not raw nx.overall_reciprocity) is correct. The hourly sign-flip story is compelling and cheap if trip-level data exists. **Strong, conditional on timestamps.**
- **N3 (modularity significance + DC-SBM):** Correct and important. graph-tool dependency is the risk (notoriously hard to pip-install in 2021 environments) — the modularity-permutation + consensus fallback is fine. DC-SBM is the principled model-selection answer and worth the install pain at n=2165 (cheap). **Must-have.**
- **N4:** Optional, fine.

---

## What's MISSING (important gaps)

1. **Exogenous mass / land-use data (ACS population + LODES/LEHD employment).** Treated as optional; it is load-bearing for G1, G4, and any non-circular gravity. **This is the most important omission.** Without it, half of Tier 1 cannot validate, only reconstruct.

2. **Coverage/exposure modeling.** No analysis explicitly models the yellow-taxi observation probability. A simple per-tract exposure offset (log pickups or log service-rate) in the gravity GLM, or restricting to the high-coverage core, is needed before any "under-connected" claim. The green-taxi/FHV comparison (even just acknowledging it) would contextualize the outer-borough blind spot.

3. **Distance-decay functional form selection.** The spec fixes power vs exp as a choice but never tests it. The entire residual field depends on f(d) being right; mis-specified decay manufactures anomalies. Add an explicit decay-form comparison (power / exp / the empirical binned f(d) from M6) and use the empirical f(d) as the gold standard.

4. **Fare/trip-distance as an independent signal, not just a robustness weight.** You have fare and trip_distance per trip. Cost-based deterrence (fare or duration) vs straight-line distance is a genuinely novel decay variable and a better cost than Euclidean — elevate it from a robustness footnote to its own decay comparison.

5. **Basic data-quality / GPS-snapping audit.** 2015 yellow-taxi data has known coordinate errors (0,0 points, water/ocean drops, impossible tract assignments). No QA step is specified. Garbage tracts will appear as anomalies in G3 and as singletons in communities. Add a pickup/dropoff-in-valid-tract sanity pass and report the discard rate.

6. **Confidence intervals on the headline numbers.** "Few percent of edges carry 90% of trips," β, CPC — none have stated uncertainty. Bootstrap over trips (or over days) for the key scalars.

---

## Final must-have shortlist (ordered by scientific value-per-effort)

| # | Analysis | Why it ranks here |
|---|----------|-------------------|
| 1 | **C1 — Net-flow index + AM/PM sign-flip** | Cheapest, most robust, genuinely directional; the CBD source↔sink flip is a clean headline. |
| 2 | **R2 — Louvain instability exhibit** | Trivial cost, anchors the "why we upgraded" narrative. |
| 3 | **M1 + M5 — Leiden partition + AMI/ARI/VI vs administrative** | Connected-community guarantee plus the measurable "taxi redraws NYC" claim. Pair them. |
| 4 | **B1 — Disparity filter backbone** | Standard, cheap, enables every dense-graph downstream method (C3, C7, infomap). |
| 5 | **G2 — Doubly-constrained gravity (numpy Furness)** | The only non-circular gravity baseline; foundation for the residual field. |
| 6 | **G3 — Residual field**, *scoped to high-coverage core, NB errors, decay-form-checked* | The flagship — but only after corrections #1/#3/#-decay; otherwise it's an artifact map. |
| 7 | **N3 — Modularity significance + DC-SBM** | Turns "we found communities" into "they're real"; DC-SBM cheap at n=2165. |
| 8 | **M2 — Infomap (directed, flow-based)** | Theme-appropriate, complements M1, gives hierarchy. |
| 9 | **C2 — PageRank/HITS roles** | Cheap directional importance; report its correlation with C1 honestly (may be redundant). |
| 10 | **T2 — Day/night rhythm clustering** *(only if trip-level timestamps exist)* | Highest value-per-effort temporal analysis; least model-dependent. |
| 11 | **C6 (weighted) + C7 (with qstest)** — rich-club / core-periphery | The mesoscale-hierarchy story with the correct nulls already built in. |
| 12 | **G4 — Gravity vs radiation (CPC, ACS/LODES mass)** *(requires exogenous mass fetch)* | Clean confirmable comparative result — conditional on fixing the mass-circularity gap. |

**Gating prerequisites before any of the above:** (i) verify trip-level timestamped OD records exist (else cut all of Tier 4 + N2's hourly story); (ii) fetch ACS + ideally LODES for exogenous mass (else G1/G4 reconstruct rather than explain); (iii) run a GPS/tract-validity QA pass; (iv) fix the decay functional form empirically before trusting any residual.