# The shape of a city in its taxis: a directed flow-network analysis of 142 million NYC yellow-taxi trips

*A 2021 modernization of a 2016-17 student project. House style: no em-dashes.*

## Abstract

We build a directed, weighted flow network from every NYC yellow-taxi trip in 2015
and ask what its structure reveals about how the city moves. After cleaning,
142,199,201 trips collapse onto a 262-node graph whose nodes are TLC taxi zones and
whose edge weights are annual trip counts. We reproduce the original project's
descriptive findings and measure them, then add a research-grade layer: a
doubly-constrained gravity model, a statistically principled network backbone,
directed centralities, rigorous community detection with stability and significance
tests, and a temporal decomposition. Three results stand out. First, taxi flows
obey a gravity law with a distance-decay exponent near 1.15 and a common-part-of-
commuters score of 0.82. Second, mapping each zone's deviation from that model
turns the original's most interesting but unproven claim, that the East Village
reads like a suburb, into a measured residual: the East Village and Alphabet City
are under-connected given their central location. Third, this peripherality is a
daytime effect only. The East Village and Lower East Side are among the city's
least active destinations in the morning and its busiest at night, with a clean
morning-to-evening reversal of net flow that mirrors the central business district
in the opposite direction. We report what reproduces, what diverges, and why.

## 1. Introduction

A taxi trip is a directed edge: it leaves one place and arrives at another. Collapse
a year of trips between the same pair of places into a single weighted edge and the
result is a transportation flow network whose structure encodes the city's
aggregated daily routines. The original 2016-17 project built such a network from
the 2015 yellow-taxi data, computed degree distributions, ran one community
detection pass, and made a set of qualitative observations: transport hubs are
network hubs, the suburbs are underserved, and, most provocatively, the East
Village and Lower East Side "read like suburbs" in taxi usage despite sitting in
the geographic center of the city.

That project was exploratory and honest about its limits. This modernization keeps
its spirit and raises the rigor. We reproduce each descriptive finding and attach a
number to it; then we treat the original as the floor rather than the ceiling and
add the spatial-network methods that a 2021 analyst would reach for: gravity and
spatial-interaction modeling [1, 4, 6], the disparity-filter backbone [11], the
Garlaschelli-Loffredo reciprocity measure [63], weighted rich-club analysis [42],
and modern community detection with the Leiden algorithm [22], the map equation
[19], stability analysis, and explicit null models [66]. The most directly relevant
prior work is Riascos and Mateos [67], who analyze over a billion NYC taxi trips as
a network, and the regionalization literature that redraws administrative maps from
interaction data [31].

## 2. Data

The source is the NYC Taxi and Limousine Commission yellow-taxi trip records for
2015, twelve monthly parquet files totalling about 2 GB. An important practical
finding shaped the whole analysis: the official mirror now serves a re-coded
version of the historical data. The 2015 parquet exposes taxi-zone identifiers
(`PULocationID`, `DOLocationID`) and post-2015 fee columns, but no pickup or
dropoff latitude and longitude. The original lat/long CSVs are no longer
distributed. The coordinate-rounding and tract-binning that the original project
spent considerable effort on, the "Penn Station problem" of a single place
splintering into many near-duplicate nodes, is therefore moot: the TLC now ships
trips pre-aggregated to 263 taxi zones, which are unions of census tracts built for
exactly this purpose.

We adopt the taxi zones as network nodes. To honour the original's spatial method
and to quantify the change, we also build the 2,165 NYC 2010 census tracts by
dissolving the in-repo block shapefile in EPSG:2263 and construct a zone-to-tract
crosswalk: a taxi zone overlaps about 19 census tracts on average, so the node
geography is roughly nineteen times coarser than the original's.

**Cleaning.** Working month by month in DuckDB (so the 146M rows are never held in
memory at once), we keep trips with valid zone ids (1 to 263), a positive duration
in [1, 360] minutes, a fare in [$0.01, $1000], a trip distance in [0, 100] miles,
and a 2015 pickup date. This retains 142,199,201 of 146,039,231 raw rows (97.4%).
Intra-zone trips (self-loops) are 4.5% of the total; we keep them in the edge table
but exclude them from distance-based and centrality analyses, where a zero-length
self-edge is undefined. Per-reason drop counts are in `data/processed/cleaning_stats.json`.

**Coverage caveat.** Yellow-taxi pickups are spatially structured: they concentrate
in the Manhattan core below 96th Street plus the two airports. Outer-borough zones
are dropoff-dominated and under-sampled. Any statement about a zone being
"under-connected" is therefore conditional on yellow-taxi observation, not a claim
about total travel demand. We restrict the residual and anomaly analyses to the
high-coverage core (the TLC Yellow Zone plus airports), where the observation rate
is roughly uniform.

## 3. Methods

All graph work uses the directed weighted network G with nodes = zones and edge
weight w_ij = annual trips from i to j.

**Centralities.** Weighted PageRank [34], hub and authority scores via the singular
value decomposition of the OD matrix [33], betweenness on the distance graph (edge
length 1/w_ij), and eigenvector centrality. We report the Spearman rank-correlation
matrix among them to separate measures that agree from measures that capture
distinct roles.

**Structure.** Garlaschelli-Loffredo reciprocity rho [63], per-edge flow imbalance,
degree assortativity [50], k-core decomposition, and the weighted rich-club
coefficient [42] normalised against a weight-reshuffling null.

**Spatial interaction.** We estimate a distance-decay exponent with an unconstrained
Poisson gravity regression (trips on log origin mass, log destination mass, and log
distance), reported only as a descriptive exponent because origin and destination
masses are taxi-activity totals and so the model reconstructs more than it explains.
The residual field instead uses a doubly-constrained gravity model fit by the
Furness iterative-proportional-fitting procedure [1], which conditions only on each
zone's own out- and in-marginals and on distance and is therefore non-circular. The
decay function f(d) = d^(-beta) is calibrated so the modeled mean trip distance
equals the observed 2.25 miles. Goodness of fit is the common part of commuters,
CPC = 2 sum min(obs, pred) / (sum obs + sum pred), which is the right metric for
flows [6]. Per-edge deviance residuals, scoped to the high-coverage core and a
matched volume floor, define the "surprise" field; aggregated to zones they give the
"where Manhattan ends" map.

**Backbone.** The disparity filter [11] keeps an edge if its weight is improbably
large under a null that distributes a node's strength uniformly across its links,
applied with the directed OR rule. We compare its backbone to the arbitrary
500-trips-per-year cut the original used.

**Communities.** We run the Leiden algorithm [22] (which guarantees connected
communities), igraph multilevel (the original's method) [no-ref], the map-equation
Infomap [19], and networkx greedy-modularity and label-propagation as cross-checks.
We sweep the resolution parameter, measure seed stability over 100 runs with the
adjusted Rand and adjusted mutual information indices [28], test modularity
significance against a weight-reshuffle null (the meaningful null for a
near-complete weighted graph), and compare the partition to borough and TLC
service-zone geography.

**Temporal.** We slice the trips into dayparts (AM peak, midday, PM peak, evening,
weekend late-night) before annual collapse, build a graph per slice, and track how
hub identity and per-zone net flow shift between morning and night. We cluster each
zone's 24-hour weekday pickup profile with k-means to recover daily-rhythm types.

Everything runs in a Pixi environment (Python 3.11, conda-forge) with DuckDB,
Polars, GeoPandas, NetworkX, igraph, python-louvain, leidenalg, statsmodels and
scikit-learn. The pipeline is one command and each stage is resumable.

## 4. Results

### 4.1 The network is small, dense and Midtown-centric

142,199,201 trips form 42,347 directed edges over 262 active zones; filtering to
edges above 500 trips per year leaves 7,945 edges over 228 zones. The graph is
near-complete among the busy zones (max k-core 147) and strongly disassortative
(degree assortativity -0.18), the hub-and-spoke signature of a system organised
around a few dominant attractors. Reciprocity is high: 82% of flow has a return leg
and the Garlaschelli-Loffredo rho is 0.515.

### 4.2 Hubs, and the asymmetry between them

Ranking zones by trips per distinct origin reproduces and sharpens the original's
finding. The Midtown draws pull enormous volume from a limited Manhattan origin
set: Midtown Center 22,929 trips per source, Times Sq 18,664, Penn Station 17,399.
The airports pull comparable or larger total volume from many scattered origins, so
their trips-per-source is far lower: LaGuardia 7,289, JFK 4,510. The smaller this
ratio, the more dispersed and (in the original's framing) the more peripheral the
zone's catchment.

### 4.3 Taxi flows obey a gravity law

The unconstrained Poisson gravity fit has a deviance pseudo R-squared of 0.94 and a
Euclidean distance-decay exponent of 0.72 (0.85 when distance is measured by mean
on-trip miles rather than straight-line centroid distance). The non-circular
doubly-constrained model, calibrated to the observed 2.25-mile mean trip, has a
decay exponent of 1.15 and reproduces the flows with CPC = 0.82. Flows fall off
steeply with distance, a quantitative statement of Tobler's first law for taxi
travel.

### 4.4 Where Manhattan ends, as a residual

The deviance residual of each high-coverage zone from the doubly-constrained model
is the analysis's flagship. Over-connected zones (more trips than mass and distance
predict) are the Times Sq and Midtown spine: Times Sq +9.4, Midtown South +6.3,
Garment District +4.6. Under-connected zones are the residential cores: Upper East
Side North -20.3, Upper West Side South -16.3, and, crucially for the original's
claim, the East Village -5.1 (29th percentile of the core) and Alphabet City -4.3
(35th). The Lower East Side itself is near neutral (+0.8), a partial divergence we
report rather than smooth over. The original asserted that the East Village and
Lower East Side read like suburbs; the model confirms it for the East Village and
Alphabet City and qualifies it for the Lower East Side.

### 4.5 The day/night reversal

The peripherality of these neighborhoods is a daytime artifact. Slicing by daypart,
the East Village's net-flow index runs +0.49 in the morning peak (a strong net
source, people leaving home) and -0.17 in the evening peak (a net sink, people
arriving), exactly the residential pattern. The central business district is the
mirror image: Midtown Center is -0.57 in the morning (a sink) and +0.13 in the
evening (a source). Ranking zones by destination volume, the East Village rises
from the 42nd-busiest destination by day to the 1st at night; the Lower East Side
from 51st to 6th; Clinton East from 22nd to 2nd. The morning and late-night top-15
hub sets overlap by only 0.20. The original saw a static suburb; the dynamic
picture is a neighborhood that is residential by day and the city's busiest
nightlife destination after dark. This is the finding the original could not see and
the one the blog should adopt.

### 4.6 Daily rhythms

Clustering each zone's weekday pickup shape recovers four interpretable types:
commuter-residential with a morning peak (Upper East and West Sides, Murray Hill),
outer commuter with an earlier peak (Astoria, Harlem, Brooklyn Heights), a
commercial core peaking in the evening (Midtown, Union Sq, Times Sq), and a
nightlife type peaking near midnight (Lower East Side, Williamsburg, Park Slope).
The nightlife cluster is the spatial counterpart of the day/night reversal.

### 4.7 Communities are few, stable and real

Leiden and igraph multilevel both return four communities with modularity 0.19; a
100-run seed-stability study gives a modal count of four (range three to four) with
mean adjusted Rand index 0.75 (minimum 0.42 over all 4,950 run pairs). The
resolution sweep shows the count climbing from four at resolution 1.0 to seventeen
at 0.5, the expected sensitivity, so "about three" from the original is reproduced
as "three to four, resolution dependent." The partition concentrates flow well
beyond chance: against a weight-reshuffle null with the partition fixed, the
observed modularity has a z-score of 13.8. Compared to administrative geography the
communities are only loosely aligned with boroughs (AMI 0.39), confirming that taxi
connectivity redraws the city along functional rather than administrative lines [31]. The Infomap flow
method collapses to a single module, which is itself informative: the network is so
densely and reciprocally connected that a random walker does not get trapped in
sub-regions.

### 4.8 A principled backbone

The disparity filter retains 6,190 of 42,347 edges and 87.6% of all trips, a more
defensible sparsification than the original's arbitrary 500-trip cut (7,945 edges,
98.6% of trips) because it keeps an edge based on its local statistical salience
rather than a single global threshold.

### 4.9 Temporal volume and the cost band, reproduced and explained

Monthly volume peaks in March and runs 11.8% lower across June to December. We flag
the same confounder the original did not rule out: ride-hailing grew through 2015,
so the mid-year decline is not cleanly attributable to weather. The hour-by-weekday
heatmap reproduces the weekday morning commute and weekend late-night bands. The
"constant-cost band" the original guessed was rounded tips is the JFK flat fare: 92.7%
of trips in the $49-53 fare band are flat-fare trips (RatecodeID 2, a fixed $52).

## 5. Discussion

The through-line is that a flow network lets qualitative urban intuitions be tested.
The original looked at a hairball and inferred that the East Village was suburb-like;
the gravity residual measures it, the daypart slices explain it, and the rhythm
clusters locate it. The same machinery distinguishes the two kinds of hub the
original lumped together, the concentrated Midtown draw and the dispersed airport,
and gives the seasonal and cost observations a verified cause rather than a guess.

Where we diverge from the original we say so. The Lower East Side does not read as
under-connected in the gravity residual the way the East Village does, and the node
and edge counts are not comparable to the blog's because the geography changed from
census tracts to taxi zones and the underlying file was re-coded.

## 6. Limitations

Yellow taxis are a biased sample of travel. They over-observe Manhattan and the
airports and barely see the outer boroughs, where green taxis and for-hire vehicles
carry the load. Every residual and "under-connected" statement is conditional on
that observation process, which is why we scope those claims to the high-coverage
core. The gravity residual field depends on the decay function being correctly
specified; a misspecified f(d) manufactures anomalies, so we calibrate it to the
observed mean trip distance and report the fit (CPC 0.82) rather than asserting it.
Community counts are resolution and seed dependent, which we characterise rather
than hide. Distances are straight-line centroid distances, which understate the
real road, bridge and tunnel cost; the trip-distance variant of the decay fit
partially addresses this. And the whole analysis is a single year, so it cannot
separate seasonal effects from the secular growth of ride-hailing.

## 7. Reproducibility

`pixi install && pixi run pipeline` downloads the data, cleans and aggregates it
out-of-core, builds the graph, runs the analysis and regenerates every figure.
Small aggregates are committed so the analysis and figures rebuild without the 2 GB
download. Every measured number in this paper is written to
`data/processed/metrics_summary.json` and was independently re-derived by an
adversarial multi-agent audit.

## References

A consolidated, de-duplicated list (the methods survey that produced it is in
`docs/research/analysis_spec.md`).

1. Wilson, A. G. (1967). A statistical theory of spatial distribution models. *Transportation Research* 1(3):253-269.
4. Simini, F., Gonzalez, M. C., Maritan, A. & Barabasi, A.-L. (2012). A universal model for mobility and migration patterns. *Nature* 484:96-100.
6. Lenormand, M., Bassolas, A. & Ramasco, J. J. (2016). Systematic comparison of trip distribution laws and models. *J. Transport Geography* 51:158-169.
11. Serrano, M. A., Boguna, M. & Vespignani, A. (2009). Extracting the multiscale backbone of complex weighted networks. *PNAS* 106(16):6483-6488.
19. Rosvall, M. & Bergstrom, C. T. (2008). Maps of random walks on complex networks reveal community structure. *PNAS* 105(4):1118-1123.
22. Traag, V. A., Waltman, L. & van Eck, N. J. (2019). From Louvain to Leiden: guaranteeing well-connected communities. *Scientific Reports* 9:5233.
28. Meila, M. (2007). Comparing clusterings, an information based distance. *J. Multivariate Analysis* 98(5):873-895.
31. Ratti, C., Sobolevsky, S., Calabrese, F., et al. (2010). Redrawing the map of Great Britain from a network of human interactions. *PLoS ONE* 5(12):e14248.
33. Kleinberg, J. M. (1999). Authoritative sources in a hyperlinked environment. *J. ACM* 46(5):604-632.
34. Page, L., Brin, S., Motwani, R. & Winograd, T. (1999). The PageRank citation ranking. Stanford InfoLab.
42. Opsahl, T., Colizza, V., Panzarasa, P. & Ramasco, J. J. (2008). Prominence and control: the weighted rich-club effect. *Phys. Rev. Lett.* 101:168702.
50. Newman, M. E. J. (2003). Mixing patterns in networks. *Phys. Rev. E* 67:026126.
56. Roth, C., Kang, S. M., Batty, M. & Barthelemy, M. (2011). Structure of urban movements: polycentric activity and entangled hierarchical flows. *PLoS ONE* 6(1):e15923.
63. Garlaschelli, D. & Loffredo, M. I. (2004). Patterns of link reciprocity in directed networks. *Phys. Rev. Lett.* 93:268701.
66. Lancichinetti, A., Radicchi, F. & Ramasco, J. J. (2010). Statistical significance of communities in networks. *Phys. Rev. E* 81:046110.
67. Riascos, A. P. & Mateos, J. L. (2020). Networks and long-range mobility in cities: a study of more than one billion taxi trips in New York City. *Scientific Reports* 10:4022.
68. Xie, Yu, Zheng, Wang & Jiang (2021). Revealing spatiotemporal travel demand and community structure with taxi trip data: a case study of New York City. *PLoS ONE* 16(11):e0259694.
70. Tobler, W. (1970). A computer movie simulating urban growth in the Detroit region. *Economic Geography* 46:234-240.
71. Dash Nelson, G. & Rae, A. (2016). An economic geography of the United States: from commutes to megaregions. *PLoS ONE* 11(11):e0166083.
