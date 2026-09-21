"""Topology descriptions.

A :class:`Topology` is a *plan* of a network (like an architect's drawing):
which switches exist, which pairs are connected and with what delay, and
which hosts hang off which switch. :mod:`ffr.network` turns this plan into
running objects.

Built-in topologies range from toys (``linear``, ``ring``) to research
backbones used throughout the literature (``abilene``, ``nsfnet``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_DELAY = 0.001  # 1 ms
DEFAULT_CAPACITY = 100_000.0  # packets per second


@dataclass
class LinkSpec:
    a: str
    b: str
    delay: float = DEFAULT_DELAY
    capacity: float = DEFAULT_CAPACITY

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.a, self.b))


@dataclass
class Topology:
    name: str = "custom"
    switches: list[str] = field(default_factory=list)
    links: list[LinkSpec] = field(default_factory=list)
    hosts: dict[str, str] = field(default_factory=dict)  # host -> switch

    # -- building -------------------------------------------------------
    def add_switch(self, name: str) -> None:
        if name in self.switches:
            raise ValueError(f"duplicate switch {name}")
        self.switches.append(name)

    def add_link(self, a: str, b: str, **kw) -> LinkSpec:
        for n in (a, b):
            if n not in self.switches:
                raise ValueError(f"unknown switch {n}")
        if a == b:
            raise ValueError("self loops are not allowed")
        if self.link(a, b) is not None:
            raise ValueError(f"duplicate link {a}-{b}")
        spec = LinkSpec(a, b, **kw)
        self.links.append(spec)
        return spec

    def add_host(self, host: str, switch: str) -> None:
        if switch not in self.switches:
            raise ValueError(f"unknown switch {switch}")
        self.hosts[host] = switch

    def add_host_per_switch(self, prefix: str = "h") -> "Topology":
        """Attach one host to every switch: switch ``X`` gets host ``hX``."""
        for s in self.switches:
            self.add_host(f"{prefix}{s}", s)
        return self

    # -- queries ----------------------------------------------------------
    def link(self, a: str, b: str) -> LinkSpec | None:
        key = frozenset((a, b))
        for l in self.links:
            if l.key == key:
                return l
        return None

    def neighbors(self, n: str) -> list[str]:
        out = []
        for l in self.links:
            if l.a == n:
                out.append(l.b)
            elif l.b == n:
                out.append(l.a)
        return out

    def __repr__(self) -> str:
        return (f"Topology({self.name!r}, {len(self.switches)} switches, "
                f"{len(self.links)} links, {len(self.hosts)} hosts)")


# ----------------------------------------------------------------------
# Built-in topologies
# ----------------------------------------------------------------------

def from_edges(name: str, edges, delay: float = DEFAULT_DELAY) -> Topology:
    """Build from ``[(a, b), ...]`` or ``[(a, b, delay), ...]``."""
    t = Topology(name)
    for e in edges:
        for n in e[:2]:
            if n not in t.switches:
                t.add_switch(n)
    for e in edges:
        t.add_link(e[0], e[1], delay=e[2] if len(e) > 2 else delay)
    return t


def linear(n: int, delay: float = DEFAULT_DELAY) -> Topology:
    """s1 - s2 - ... - sn. No redundancy: any failure partitions it."""
    return from_edges(f"linear{n}", [(f"s{i}", f"s{i + 1}") for i in range(1, n)], delay)


def ring(n: int, delay: float = DEFAULT_DELAY) -> Topology:
    """A cycle: the smallest topology that survives any single link failure."""
    edges = [(f"s{i}", f"s{i % n + 1}") for i in range(1, n + 1)]
    return from_edges(f"ring{n}", edges, delay)


def grid(rows: int, cols: int, delay: float = DEFAULT_DELAY) -> Topology:
    def name(r, c):
        return f"s{r}_{c}"

    edges = []
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                edges.append((name(r, c), name(r, c + 1)))
            if r + 1 < rows:
                edges.append((name(r, c), name(r + 1, c)))
    return from_edges(f"grid{rows}x{cols}", edges, delay)


# Speed of light in fibre is ~200,000 km/s => 5 microseconds per km.
_US_PER_KM = 5e-6

# Abilene (Internet2) backbone, 11 PoPs and 14 links, ~2004.
# Distances are approximate great-circle km.
_ABILENE = [
    ("SEA", "SNV", 1100), ("SEA", "DEN", 1650), ("SNV", "LAX", 500),
    ("SNV", "DEN", 1500), ("LAX", "HOU", 2200), ("DEN", "KSC", 900),
    ("KSC", "HOU", 1000), ("KSC", "IND", 730), ("HOU", "ATL", 1130),
    ("IND", "CHI", 260), ("IND", "ATL", 690), ("ATL", "WDC", 870),
    ("CHI", "NYC", 1150), ("NYC", "WDC", 330),
]


def abilene() -> Topology:
    return from_edges("abilene", [(a, b, km * _US_PER_KM) for a, b, km in _ABILENE])


# NSFNET T1 backbone, 14 nodes and 21 links (the variant common in the
# optical / survivability literature).
_NSFNET = [
    (1, 2), (1, 3), (1, 8), (2, 3), (2, 4), (3, 6), (4, 5), (4, 11), (5, 6),
    (5, 7), (6, 10), (6, 14), (7, 8), (8, 9), (9, 10), (9, 12), (9, 13),
    (11, 12), (11, 13), (12, 14), (13, 14),
]


def nsfnet(delay: float = 0.002) -> Topology:
    return from_edges("nsfnet", [(f"n{a}", f"n{b}") for a, b in _NSFNET], delay)


BUILTIN = {
    "linear4": lambda: linear(4),
    "ring6": lambda: ring(6),
    "grid3x3": lambda: grid(3, 3),
    "abilene": abilene,
    "nsfnet": nsfnet,
}


def get(name: str) -> Topology:
    """Look up a built-in topology by name, e.g. ``get("abilene")``."""
    try:
        return BUILTIN[name]()
    except KeyError:
        raise KeyError(f"unknown topology {name!r}; choose from {sorted(BUILTIN)}") from None
