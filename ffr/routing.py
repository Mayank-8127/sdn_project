"""Graph algorithms used by the controller to compute paths.

The controller holds a *map* of the network as a weighted graph: switches are
nodes, links are edges, and each edge has a cost (its delay, or 1 per hop).

Main tools:

* :func:`dijkstra` - classic shortest paths from one node to all others.
* :func:`next_hops_to` - for a destination ``d``, the next hop of every node
  on its shortest path to ``d``. This is exactly what destination-based
  forwarding tables need ("for packets to d, go to neighbour X").

All functions accept ``excluded_edges`` / ``excluded_nodes`` so we can ask
"what would the shortest path be *if this link were gone*?" - the core
question of failure recovery.

Ties are broken by node name, so results are deterministic.
"""

from __future__ import annotations

import heapq
from typing import Callable, Iterable

Edge = frozenset  # an undirected edge {a, b}


def edge(a: str, b: str) -> Edge:
    return frozenset((a, b))


class Graph:
    """Undirected weighted graph."""

    def __init__(self) -> None:
        self.adj: dict[str, dict[str, float]] = {}

    def add_node(self, n: str) -> None:
        self.adj.setdefault(n, {})

    def add_edge(self, a: str, b: str, w: float = 1.0) -> None:
        self.add_node(a)
        self.add_node(b)
        self.adj[a][b] = w
        self.adj[b][a] = w

    def remove_edge(self, a: str, b: str) -> None:
        self.adj[a].pop(b, None)
        self.adj[b].pop(a, None)

    def weight(self, a: str, b: str) -> float:
        return self.adj[a][b]

    @property
    def nodes(self) -> list[str]:
        return sorted(self.adj)

    @property
    def edges(self) -> list[Edge]:
        return sorted({edge(a, b) for a in self.adj for b in self.adj[a]}, key=sorted)

    def copy(self) -> "Graph":
        g = Graph()
        g.adj = {n: dict(nb) for n, nb in self.adj.items()}
        return g

    @classmethod
    def from_topology(cls, topo, weight: str | Callable = "delay") -> "Graph":
        """Build from a Topology. ``weight`` is "delay", "hops" or f(LinkSpec)."""
        g = cls()
        for s in topo.switches:
            g.add_node(s)
        for l in topo.links:
            if weight == "delay":
                w = l.delay
            elif weight == "hops":
                w = 1.0
            else:
                w = weight(l)
            g.add_edge(l.a, l.b, w)
        return g


def dijkstra(g: Graph, src: str, excluded_edges: Iterable[Edge] = (),
             excluded_nodes: Iterable[str] = (), weight: Callable | None = None):
    """Shortest distances and predecessors from ``src``.

    Returns ``(dist, prev)`` where ``prev[n]`` is the node before ``n`` on
    the shortest path from ``src``. Unreachable nodes are absent.
    """
    xe = set(excluded_edges)
    xn = set(excluded_nodes)
    if src in xn or src not in g.adj:
        return {}, {}
    dist = {src: 0.0}
    prev: dict[str, str] = {}
    heap = [(0.0, src)]
    done = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        for v in sorted(g.adj[u]):
            if v in xn or edge(u, v) in xe:
                continue
            w = weight(u, v) if weight else g.adj[u][v]
            nd = d + w
            # strict improvement, or equal cost with a lexicographically
            # smaller predecessor => deterministic tie-breaking
            if v not in dist or nd < dist[v] - 1e-12 or (
                    abs(nd - dist[v]) <= 1e-12 and v not in done and u < prev.get(v, u)):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    return dist, prev


def shortest_path(g: Graph, src: str, dst: str, **kw) -> list[str] | None:
    """Node list from ``src`` to ``dst``, or ``None`` if unreachable."""
    dist, prev = dijkstra(g, src, **kw)
    if dst not in dist:
        return None
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    return path[::-1]


def next_hops_to(g: Graph, dst: str, **kw) -> dict[str, str]:
    """For every node that can reach ``dst``: its next hop towards ``dst``.

    Runs Dijkstra *from* the destination (the graph is undirected), so the
    predecessor of ``n`` in that tree is ``n``'s next hop towards ``dst``.
    """
    dist, prev = dijkstra(g, dst, **kw)
    return {n: prev[n] for n in dist if n != dst}


def path_cost(g: Graph, path: list[str]) -> float:
    return sum(g.weight(a, b) for a, b in zip(path, path[1:]))


def path_edges(path: list[str]) -> list[Edge]:
    return [edge(a, b) for a, b in zip(path, path[1:])]


# ----------------------------------------------------------------------
# Disjoint path pairs (for end-to-end path protection)
# ----------------------------------------------------------------------

def _bellman_ford(arcs: dict[tuple, float], nodes: set, src):
    dist = {n: float("inf") for n in nodes}
    prev: dict = {}
    dist[src] = 0.0
    order = sorted(arcs.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))
    for _ in range(len(nodes) - 1):
        changed = False
        for (u, v), w in order:
            if dist[u] + w < dist[v] - 1e-12:
                dist[v] = dist[u] + w
                prev[v] = u
                changed = True
        if not changed:
            break
    return dist, prev


def disjoint_paths(g: Graph, src: str, dst: str, node_disjoint: bool = False,
                   excluded_edges: Iterable[Edge] = ()):
    """Minimum-total-cost pair of disjoint paths (Bhandari's algorithm).

    Returns ``(p1, p2)`` with ``p1`` the cheaper path, or ``(p, None)`` if no
    disjoint second path exists (``(None, None)`` if ``dst`` is unreachable).

    Why not "shortest path, then shortest path avoiding it"? That greedy
    approach can fail even when two disjoint paths exist (the first path may
    block every alternative). Bhandari's algorithm fixes this: after finding
    the first path it lets the second path "cancel" edges of the first by
    walking them backwards at negative cost, then untangles the two.

    ``node_disjoint`` additionally forbids sharing intermediate switches (so
    the backup survives a switch crash). It uses the standard node-splitting
    trick: every node v becomes v_in -> v_out.
    """
    xe = set(excluded_edges)
    arcs: dict[tuple, float] = {}

    def IN(n):
        return (n, "in") if node_disjoint and n not in (src, dst) else (n, "out")

    def OUT(n):
        return (n, "out")

    for a in g.adj:
        if node_disjoint and a not in (src, dst):
            arcs[(IN(a), OUT(a))] = 0.0
        for b, w in g.adj[a].items():
            if edge(a, b) not in xe:
                arcs[(OUT(a), IN(b))] = w
    nodes = {n for arc in arcs for n in arc} | {OUT(src), IN(dst)}
    s, t = OUT(src), IN(dst)

    def path_from(prev, end):
        if end not in prev and end != s:
            return None
        p = [end]
        while p[-1] != s:
            p.append(prev[p[-1]])
        return p[::-1]

    dist, prev = _bellman_ford(arcs, nodes, s)
    p1 = path_from(prev, t) if dist.get(t, float("inf")) < float("inf") else None
    if p1 is None:
        return None, None
    p1_arcs = list(zip(p1, p1[1:]))
    residual = dict(arcs)
    for u, v in p1_arcs:
        residual.pop((u, v), None)
        residual[(v, u)] = -arcs[(u, v)]
    dist2, prev2 = _bellman_ford(residual, nodes, s)
    collapse = lambda p: [n for i, (n, _) in enumerate(p) if i == 0 or n != p[i - 1][0]]
    if dist2.get(t, float("inf")) == float("inf"):
        return collapse(p1), None
    p2 = path_from(prev2, t)
    used = set(p1_arcs)
    for u, v in zip(p2, p2[1:]):
        if (v, u) in used:
            used.discard((v, u))  # interlacing arcs cancel out
        else:
            used.add((u, v))
    nxt: dict = {}
    for u, v in sorted(used, key=str):
        nxt.setdefault(u, []).append(v)
    paths = []
    for _ in range(2):
        p = [s]
        while p[-1] != t:
            p.append(nxt[p[-1]].pop())
        paths.append(collapse(p))
    paths.sort(key=lambda p: (path_cost(g, p), p))
    return paths[0], paths[1]
