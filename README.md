# Transportation Flow Network

A directed, weighted flow network built from every NYC yellow-taxi trip in 2015.
Nodes are places, edges are annual trip counts between them, and the analysis asks
what the resulting network says about how the city actually moves.

This repository started as a 2016-17 student project (a pile of numbered Jupyter
notebooks). This is a 2021 modernization: one reproducible pipeline, modern
tooling (Pixi, DuckDB, Polars, GeoPandas, NetworkX, igraph), every original figure
regenerated and measured, and a research-grade network-science layer on top. The
original notebooks, plots, papers and report are preserved under `legacy/`.

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
pixi run figures    # regenerate every figure (PNG + SVG) into figures/
pixi run summary    # print the headline measured numbers to the terminal
```

The raw parquet stays in `data/raw/` and is gitignored. Small aggregates
(`data/processed/`) are committed so the figures and analysis can be rebuilt
without re-downloading.

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
