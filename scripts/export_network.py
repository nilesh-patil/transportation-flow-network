"""Export a pre-baked, community-clustered force-directed layout for the overview
page's network graph (site/data/network.json).

Nodes are the 262 active taxi zones, colored by Leiden community and sized by
total strength. Edges are the disparity-filter backbone (the ~6,190 statistically
significant edges that carry 87.6% of trips). The layout is computed once here so
the browser only renders and handles interaction, which keeps it stable and
reproducible across visits.

Layout: each community is anchored to a point on a circle; nodes start near their
anchor and a weighted spring layout (intra-community edges boosted, inter-community
damped, weights log-compressed) settles them into four visible lobes that still
reflect the real backbone topology.
"""
from __future__ import annotations

import json
import math

import networkx as nx
import numpy as np
import pandas as pd

from transportation_flow_network import config as C

# Same palette + names the live-map community lens uses, so the two views agree.
COMMUNITY_COLORS = ["#a32015", "#1f6db0", "#3f8f4f", "#b8860b"]
COMMUNITY_NAMES = [
    "Midtown commercial core",
    "Outer boroughs + airports",
    "Downtown + Brooklyn",
    "Upper Manhattan + Bronx",
]

OUT = C.ROOT / "site" / "data"


def main() -> None:
    na = pd.read_parquet(C.PROCESSED / "node_analysis.parquet").set_index("zone_id")
    bb = pd.read_parquet(C.PROCESSED / "backbone_edges.parquet")
    bb = bb[bb["keep"]]

    comm = {int(z): (int(c) if pd.notna(c) else 0)
            for z, c in na["leiden_community"].items()}
    active = sorted(comm)
    K = int(max(comm.values())) + 1

    # undirected backbone projection (sum reciprocal trips), among active nodes
    G = nx.Graph()
    G.add_nodes_from(active)
    for r in bb.itertuples():
        o, d, t = int(r.o), int(r.d), float(r.trips)
        if o in comm and d in comm and o != d:
            if G.has_edge(o, d):
                G[o][d]["w"] += t
            else:
                G.add_edge(o, d, w=t)

    # Two-level "group-in-a-box" layout. Community centers are spread on a circle
    # so the four functional districts read as separate lobes (the look chosen for
    # this figure); within each lobe, the community's own backbone subgraph is laid
    # out with a weighted spring layout so the internal structure is real. Inter-
    # community backbone edges are still drawn, so the coupling between lobes shows.
    rng = np.random.default_rng(C.SEED)
    sizes = {c: sum(1 for z in active if comm[z] == c) for c in range(K)}
    nmax = max(sizes.values()) or 1
    # place the community centers on a WIDE ellipse so the four lobes spread
    # across a landscape canvas instead of a square (less wasted side margin)
    rx, ry = 2.7, 1.15
    centers = {c: (rx * math.cos(2 * math.pi * c / K - math.pi / 2),
                   ry * math.sin(2 * math.pi * c / K - math.pi / 2))
               for c in range(K)}

    pos = {}
    for c in range(K):
        members = [z for z in active if comm[z] == c]
        H = G.subgraph(members)
        if len(members) <= 18:
            # small, dense cores (e.g. Midtown) collapse to a line under spring;
            # a circle reads as a clean tight cluster instead
            sub = nx.circular_layout(H)
        elif H.number_of_edges() > 0:
            sub = nx.spring_layout(H, weight="w", k=1.2 / math.sqrt(max(len(members), 2)),
                                   iterations=300, seed=C.SEED)
        else:
            sub = {z: (float(rng.normal(0, 0.3)), float(rng.normal(0, 0.3))) for z in members}
        # normalize this lobe to unit, then scale by sqrt(size) and place at center
        sx = np.array([sub[z][0] for z in members])
        sy = np.array([sub[z][1] for z in members])
        sp = max(sx.max() - sx.min(), sy.max() - sy.min(), 1e-6)
        lobe_r = 0.95 * math.sqrt(sizes[c] / nmax) + 0.12
        ux, uy = centers[c]
        for z in members:
            pos[z] = (ux + (sub[z][0] - (sx.min() + sx.max()) / 2) / sp * 2 * lobe_r,
                      uy + (sub[z][1] - (sy.min() + sy.max()) / 2) / sp * 2 * lobe_r)

    # normalize to [0, 1] preserving aspect ratio
    xs = np.array([pos[n][0] for n in active])
    ys = np.array([pos[n][1] for n in active])
    minx, maxx, miny, maxy = xs.min(), xs.max(), ys.min(), ys.max()
    span = max(maxx - minx, maxy - miny) or 1.0
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    def norm(x, y):
        return (0.5 + (x - cx) / span, 0.5 + (y - cy) / span)

    strength = (na["in_strength"] + na["out_strength"]).to_dict()
    smax = max(float(strength.get(z, 0)) for z in active) or 1.0

    idx = {z: i for i, z in enumerate(active)}
    nodes = []
    for z in active:
        x, y = norm(*pos[z])
        s = float(strength.get(z, 0))
        nodes.append({
            "id": z,
            "zone": str(na.loc[z, "zone"]) if z in na.index else "?",
            "borough": str(na.loc[z, "borough"]) if z in na.index else "",
            "c": comm[z],
            "x": round(x, 4), "y": round(y, 4),
            "r": round(math.sqrt(s / smax), 4),          # 0..1, JS scales to px
            "ins": int(na.loc[z, "in_strength"]) if z in na.index else 0,
            "outs": int(na.loc[z, "out_strength"]) if z in na.index else 0,
            "nfi": round(float(na.loc[z, "net_flow_index"]), 3) if z in na.index else None,
        })

    edges = []
    for u, v, dd in G.edges(data=True):
        edges.append([idx[u], idx[v], int(dd["w"])])
    edges.sort(key=lambda e: e[2])  # light first so heavy edges paint on top

    communities = [{"id": c, "name": COMMUNITY_NAMES[c] if c < len(COMMUNITY_NAMES) else f"Community {c}",
                    "color": COMMUNITY_COLORS[c % len(COMMUNITY_COLORS)],
                    "n": int(sum(1 for z in active if comm[z] == c))}
                   for c in range(K)]

    out = {"nodes": nodes, "edges": edges, "communities": communities,
           "n_nodes": len(nodes), "n_edges": len(edges)}
    (OUT / "network.json").write_text(json.dumps(out))
    print(f"network.json: {len(nodes)} nodes, {len(edges)} backbone edges, "
          f"{K} communities, {len(json.dumps(out))//1024} KB")


if __name__ == "__main__":
    main()
