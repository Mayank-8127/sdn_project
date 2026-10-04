"""Planning backup paths for local fast reroute.

For one destination switch ``d`` we compute, for every other switch ``u``:

* the **primary** next hop ``v`` (from the shortest-path tree towards ``d``),
* the **protected element**: the link ``u-v`` (link protection) or the whole
  switch ``v`` (node protection),
* a **detour**: a path from ``u`` to ``d`` that avoids the protected element.

Detours are taken from the shortest-path tree of the graph *without* the
protected element. That has a useful consequence: all detours that avoid the
same element X and lead to the same destination agree on every switch's next
hop. So a packet only needs to carry a label meaning "I am avoiding X" (like
the not-via addresses of RFC 6981), and one rule per (switch, destination, X)
suffices.
"""

from __future__ import annotations

from dataclasses import dataclass

from .routing import Graph, edge, next_hops_to

Element = tuple  # ("link", frozenset({a, b})) or ("node", name)


def link_element(a: str, b: str) -> Element:
    return ("link", edge(a, b))


def node_element(n: str) -> Element:
    return ("node", n)


def element_name(el: Element) -> str:
    kind, x = el
    return f"link {'-'.join(sorted(x))}" if kind == "link" else f"node {x}"


@dataclass
class HopPlan:
    switch: str
    primary: str               # next-hop switch on the primary path
    protects: Element | None   # what the detour avoids (None: no backup)
    detour: list[str] | None   # [switch, ..., dst]

    @property
    def protected(self) -> bool:
        return self.detour is not None


def _follow(tree: dict[str, str], start: str, dst: str) -> list[str] | None:
    if start == dst:
        return [dst]
    if start not in tree:
        return None
    path = [start]
    while path[-1] != dst:
        path.append(tree[path[-1]])
    return path


def plan_destination(graph: Graph, dst: str, mode: str = "link",
                     excluded_edges=(), excluded_nodes=(), weight=None,
                     detour_exclusions=None) -> dict[str, HopPlan]:
    """Primary next hops and detours towards ``dst`` for every switch.

    ``mode`` is ``"link"`` or ``"node"``. In node mode a switch whose next
    hop *is* the destination falls back to link protection (you cannot avoid
    the destination), as does a switch whose next hop is a cut vertex.

    ``detour_exclusions(element)`` may return extra ``(edges, nodes)`` to
    avoid when computing the detour for ``element`` (v0.6 uses it for
    shared-risk groups); if that leaves no path, plain avoidance is used.
    """
    xe, xn = set(excluded_edges), set(excluded_nodes)
    primary = next_hops_to(graph, dst, excluded_edges=xe, excluded_nodes=xn, weight=weight)
    trees: dict[tuple, dict[str, str]] = {}

    def detour_tree(el: Element, extra=((), ())):
        key = (el, tuple(sorted(map(sorted, extra[0]))), tuple(sorted(extra[1])))
        if key not in trees:
            e2, n2 = set(xe) | set(extra[0]), set(xn) | set(extra[1])
            if el[0] == "link":
                e2.add(el[1])
            else:
                n2.add(el[1])
            trees[key] = next_hops_to(graph, dst, excluded_edges=e2, excluded_nodes=n2,
                                      weight=weight)
        return trees[key]

    def find(el: Element, u: str):
        if detour_exclusions is not None:
            extra = detour_exclusions(el)
            if extra and (extra[0] or extra[1]):
                path = _follow(detour_tree(el, extra), u, dst)
                if path:
                    return path
        return _follow(detour_tree(el), u, dst)

    plans: dict[str, HopPlan] = {}
    for u, v in sorted(primary.items()):
        candidates = []
        if mode == "node" and v != dst:
            candidates.append(node_element(v))
        candidates.append(link_element(u, v))
        chosen, path = None, None
        for el in candidates:
            path = find(el, u)
            if path:
                chosen = el
                break
        plans[u] = HopPlan(u, v, chosen, path)
    return plans


def coverage(plans: dict[str, HopPlan]) -> float:
    """Fraction of switches that have a backup for their primary next hop."""
    if not plans:
        return 1.0
    return sum(p.protected for p in plans.values()) / len(plans)
