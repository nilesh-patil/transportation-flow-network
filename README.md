# Transportation Flow Network

A directed, weighted flow network built from NYC yellow-taxi trips. Nodes are
places, edges are annual trip counts between them, and the analysis asks what the
resulting network says about how the city actually moves. The detailed single-year
analysis is anchored on 2015; a longitudinal layer carries the full network-science
panel across every year from 2015 to 2024.

This repository started as a 2016-17 student project (a pile of numbered Jupyter
notebooks). This is a 2021 modernization: one reproducible pipeline, modern
tooling (Pixi, DuckDB, Polars, GeoPandas, NetworkX, igraph), every original figure
regenerated and measured, and a research-grade network-science layer on top
(robustness and percolation, rigorous scale-free testing, null-model benchmarking,
spatial efficiency and cascades, and the ten-year evolution). The original
notebooks, plots, papers and report are preserved under `legacy/`.

## What it finds

- **146 million trips collapse to a small, dense network.** After cleaning,
  142,199,201 trips (97.4% of the raw rows) form a 262-node directed graph with
  42,347 edges. A handful of Midtown zones dominate.
- **Transport hubs are network hubs, with a measurable asymmetry.** Inner-city
  draws (Midtown, Times Sq, Penn Station) pull 17,000-23,000 trips per distinct
  origin zone; the airports pull from many scattered origins (JFK 4,510 per
  source). The original asserted this; here it is quantified.
- **Taxi flows obey a gravity law.** A doubly-constrained spatial-interaction model
  reproduces the flows with a common-part-of-commuters score of 0.82 and a
  distance-decay exponent of 1.15.
- **"Where Manhattan ends," as a model residual.** Mapping each zone's deviation
  from the gravity model shows the East Village and Alphabet City (and the
  residential Upper East and West Sides) as under-connected given their central
  location, while the Times Sq and Midtown spine is over-connected. This turns the
  original's most interesting hunch into a measured result.
- **A day/night reversal the original missed.** The East Village and Lower East
  Side are peripheral by day and the city's top taxi destinations at night (the
  East Village rises from the 42nd-busiest destination by day to 1st late at
  night). Midtown is the mirror image. So "the East Village reads like a suburb" is
  a daytime-only effect.
- **The constant-cost band is explained.** The flat band of trips that cost the
  same regardless of duration is the JFK flat fare ($52, RatecodeID 2), not
  rounded tips.
- **Three to four communities, and they are real.** Leiden, igraph multilevel and a
  seed-stability study agree on four communities (range three to four), modularity
  z-score 13.8 against a null. They cut across borough lines.
- **Robust to random failure, fragile to a hub strike.** Removing 10% of zones at
  random leaves 82% of trips and 96% of weighted efficiency intact; removing the
  top-10% strength or PageRank hubs leaves only ~13% of trips and ~17-26% of
  efficiency. The unweighted connectivity curve hides this completely (random and
  every targeted attack overlap) - the hub-and-spoke fragility only shows up on the
  flow-weighted curves.
- **Heavy-tailed, but not "scale-free."** The zone strength distributions are
  strongly heavy-tailed and beat an exponential decisively, but a discrete
  Clauset-Shalizi-Newman fit rejects a clean power law (p=0) and cannot distinguish
  it from a lognormal; with only 262 zones no scale-free claim is supportable. We
  report the honest verdict rather than the headline.
- **Heavy flows sit in mutual corridors, and the city is geometrically direct.**
  Against a weight-preserving null, weighted reciprocity is far in the tail
  (z=+217): heavy taxi flows organize into round-trip Midtown-airport and
  Midtown-downtown spines. Network routes are near-straight (mean circuity 1.006,
  global efficiency 99.7% of the straight-line ideal), and a Motter-Lai cascade
  triggered at JFK collapses the network at every tolerance tested.
- **A decade of data: the geometry survives a 71% demand collapse.** Across all ten
  years 2015-2024, yellow-taxi volume falls 42% to 2019 (ride-hailing), craters 71%
  into 2020 (COVID), and recovers to only 49% of 2019 by 2024 (volume CV 0.61). Yet
  global efficiency (CV 0.004), the gravity fit (CPC, CV 0.007), the disassortative
  hub-and-spoke sign, and the three-to-four community map all hold nearly constant.
  The community partition does not even re-draw across the COVID boundary
  (2019->2020 ARI 0.94). The spatial structure of taxi travel is an invariant of the
  city, not of how many cabs run. The one thing that moves: the top arrival hub
  flips from the Midtown commercial core to the residential Upper East Side from
  2020 on.

See `MODERNIZATION_NOTES.md` for every measured number, the decisions behind them,
and how they reconcile with the original blog figures. See `docs/paper.md` for the
full writeup and `figures/CAPTIONS.md` for the figure portfolio.

## Reproduce it

The whole pipeline is one command. It downloads ~2 GB of taxi parquet, cleans and
aggregates it out-of-core, builds the graph, runs the analysis and regenerates
every figure.

```bash
pixi install
pixi run pipeline
```

Individual stages (each is resumable and skips finished work):

```bash
pixi run download   # fetch the 12 monthly parquet files into data/raw/ (gitignored)
pixi run geo        # build NYC census tracts + taxi zones in EPSG:2263
pixi run ingest     # clean + aggregate 146M trips to a zone edge list (DuckDB)
pixi run graph      # build the weighted DiGraph; write node/edge tables
pixi run metrics    # degree, hub asymmetry, baseline community
pixi run temporal   # monthly volume, hour x weekday, cost vs duration
pixi run analysis   # gravity, backbone, centralities, communities, temporal nets
pixi run robustness # attack-vs-failure, Molloy-Reed, Schneider R (Barabasi Ch.8)
pixi run scalefree  # discrete CSN power-law fits on strength/degree distributions
pixi run nullmodels # ER / configuration / weight-preserving null benchmarks
pixi run spatial    # Barthelemy efficiency + circuity + Motter-Lai cascade
pixi run figures    # regenerate every figure (PNG + SVG) into figures/
pixi run summary    # print the headline measured numbers to the terminal
```

The single-year `pixi run pipeline` runs all of the above in order. A separate
multi-year pass produces the temporal-evolution panel and figures once all years
are downloaded:

```bash
pixi run pipeline-multiyear   # download + geo + ingest-all + evolution + figures
```

`ingest-all` loops every year in `config.YEARS` (2015-2024) and skips any year
whose 12 raw files are not all present and valid, so it is safe to run while the
multi-year download is still in progress. `evolution` writes a per-year panel into
`data/processed/panel.parquet` and `metrics_summary.json['by_year']`; figures 26
and 28 fill in automatically once the panel has more than one year.

The raw parquet stays in `data/raw/` and is gitignored. Small aggregates
(`data/processed/`) are committed so the figures and analysis can be rebuilt
without re-downloading.

## Project website

A self-contained static site lives under `site/` (Overview, Method, Findings, a
live interactive map, and About), in the Tufte editorial style. The `site/demo.html`
map loads the exported zone geometry and lets you recolor NYC by gravity residual,
community, or net flow by time of day. Serve it locally with:

```bash
cd site && python3 -m http.server   # then open http://localhost:8000
```

The map and findings data are regenerated from the pipeline outputs with
`pixi run python scripts/export_site_data.py`.

## A note on the data

The NYC TLC re-coded its historical trip data. The 2015 yellow parquet on the
official mirror no longer carries pickup/dropoff latitude and longitude; it carries
taxi-zone ids (`PULocationID`/`DOLocationID`). The original lat/long CSVs are no
longer distributed. We therefore use the 263 TLC taxi zones as network nodes. This
is the data's native, census-derived geography, and it already solves the
coordinate-splintering problem the original project had to fix by hand. The full
schema and the implications are documented in `MODERNIZATION_NOTES.md`.

## Layout

```
pixi.toml  pixi.lock  README.md  MODERNIZATION_NOTES.md
data/
  raw/        # downloaded parquet (gitignored)
  processed/  # small aggregates: edges, nodes, metrics summary (committed)
  geo/        # census tracts + taxi zones in EPSG:2263
src/transportation_flow_network/
  download.py geo.py ingest.py graph.py metrics.py temporal.py analysis.py figures.py
  robustness.py scalefree.py nullmodels.py spatial.py evolution.py
  common.py config.py
notebooks/01_overview.ipynb   # one clean narrative notebook over the pipeline
figures/                      # output PNG + SVG + CAPTIONS.md
docs/
  paper.md                    # research-grade writeup
  research/                   # the SOTA methods survey that shaped the design
legacy/                       # original 2016-17 notebooks, plots, map assets, report
Papers/  reports/             # source papers and the original project report
```

## Tooling

Python 3.11 via Pixi (conda-forge). DuckDB and Polars for out-of-core ingest,
GeoPandas/Shapely/pyproj for the spatial work, NetworkX and igraph (with
python-louvain and leidenalg) for the graph science, statsmodels and scikit-learn
for the gravity model and clustering, Matplotlib and seaborn for figures. Exact
pinned versions are in `pixi.lock`.

## Credit

Original analysis and writeup: 2016-17 student project on NYC taxi transportation
networks. Modernization: 2021.
