"""Transportation Flow Network.

A reproducible 2021-era modernization of a 2016-17 student project that builds a
directed, weighted flow network from NYC yellow-taxi trips: nodes are US census
tracts, edges are annual trip counts between an origin and a destination tract.

Pipeline modules (run in order, or via ``pixi run pipeline``):

    download  -> fetch full-year 2015 TLC yellow parquet into data/raw/
    tracts    -> build the NYC 2010 census-tract polygons in EPSG:2263
    ingest    -> clean trips + spatial-join lat/long to tract GEOID (out-of-core)
    graph     -> collapse to a weighted DiGraph; save node/edge tables
    metrics   -> faithful core metrics (degree, hub asymmetry, Manhattan-ends ratio)
    temporal  -> monthly volume, hourly x weekday heatmap, cost-vs-duration
    analysis  -> research-grade layer (gravity, backbone, centralities, communities)
    robustness-> Barabasi Ch.8 attack-vs-failure, Molloy-Reed, Schneider R
    scalefree -> CSN discrete power-law fits on strength/degree distributions
    nullmodels-> ER / configuration / weight-preserving null benchmarks
    spatial   -> Barthelemy efficiency/circuity + Motter-Lai cascade
    evolution -> per-year structural panel (multi-year pass) into by_year/<year>
    figures   -> regenerate every figure to figures/

The four diagnostic modules and ``evolution`` import the shared helpers via
``from transportation_flow_network import common as cm, config as C`` and default
to ``C.PRIMARY_YEAR`` (2015); ``analysis``, ``robustness``, ``scalefree``,
``nullmodels`` and ``spatial`` run on the single primary year, while
``evolution`` is the multi-year driver (``pixi run pipeline-multiyear``).
"""

__version__ = "2021.0.0"
