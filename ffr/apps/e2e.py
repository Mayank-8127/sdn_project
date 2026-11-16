"""End-to-end path protection (1:1 protection with ingress switch-over).

The classic carrier-grade scheme of Sharma et al. (2013):

* for every (ingress switch, egress switch) pair compute two **disjoint**
  paths with Bhandari's algorithm: a primary and a backup,
* label each path with its own tag; transit switches forward on the tag
  alone (``tag=T -> Output``), like an MPLS label-switched path,
* the ingress switch has a FAST_FAILOVER group per host pair:

      bucket 1: watch logical port "path:<primary>" -> SetTag(T1), Output(...)
      bucket 2: watch first port of backup          -> SetTag(T2), Output(...)

* a multi-hop BFD session (:class:`~ffr.detection.PathBFD`) runs along every
  primary path. When it times out, the logical port dies and the ingress
  switches every flow of that path to the backup.

Pros: the backup is fully disjoint (no shared link, optionally no shared
switch), detours never loop, and the decision is local to the ingress.
Cons: detection always takes the BFD timeout (even for a cut right next to
the ingress, unless it is the very first hop), and monitoring cost grows with
the number of switch *pairs* rather than links.
"""

from __future__ import annotations

from ..detection import PathBFD
from ..openflow import Bucket, Group, Match, Output, PopTag, SetTag
from ..risk import RiskModel
from ..routing import disjoint_paths, edge, path_edges, shortest_path
from .static import PRIMARY, PRIO_PRIMARY, StaticRouting

PRIO_INGRESS = 150
PRIO_TRANSIT = 200
TRANSIT = 3  # cookie


class PathProtection(StaticRouting):
    name = "e2e"

    def __init__(self, net, node_disjoint: bool = True, path_bfd_interval: float = 0.0033,
                 path_bfd_mult: int = 3, srlg_aware: bool = False, **kw):
        super().__init__(net, **kw)
        self.node_disjoint = node_disjoint
        self.srlg_aware = srlg_aware
        self._risk = RiskModel(net.topo)
        self.srlg_backups = 0
        self.monitor = PathBFD(net, path_bfd_interval, path_bfd_mult)
        self.paths: dict[tuple[str, str], tuple[list[str], list[str] | None]] = {}
        self.tags: dict[tuple[str, ...], int] = {}
        self._gid = 0

    def tag_for(self, path: list[str]) -> int:
        return self.tags.setdefault(tuple(path), len(self.tags) + 1)

    @property
    def probe_packets(self) -> int:
        return super().probe_packets + self.monitor.sent

    def install_all_routes(self) -> None:
        switches = sorted(set(self.host_switch.values()))
        # egress delivery (pops the path label)
        for host, hsw in sorted(self.host_switch.items()):
            self.install(hsw, Match(dst=host), [PopTag(), Output(self.port(hsw, host))],
                         PRIO_PRIMARY, PRIMARY)
        transit: dict[tuple[str, int], str] = {}
        for s in switches:
            for t in switches:
                if s == t:
                    continue
                p1, p2 = disjoint_paths(self.graph, s, t, node_disjoint=self.node_disjoint)
                if p2 is None and self.node_disjoint:
                    p1, p2 = disjoint_paths(self.graph, s, t)  # fall back to link-disjoint
                if p1 is None:
                    continue
                if self.srlg_aware:
                    p2 = self._srlg_backup(p1, p2)
                self.paths[(s, t)] = (p1, p2)
                for p in (p1, p2):
                    if p is None:
                        continue
                    tag = self.tag_for(p)
                    for x, y in zip(p[1:-1], p[2:]):
                        transit[(x, tag)] = y
        for (x, tag), y in sorted(transit.items()):
            self.install(x, Match(tag=tag), [Output(self.port(x, y))], PRIO_TRANSIT, TRANSIT)
        for src, s in sorted(self.host_switch.items()):
            for dst, t in sorted(self.host_switch.items()):
                if s == t or (s, t) not in self.paths:
                    continue
                self.install_ingress(src, dst, s, *self.paths[(s, t)])

    def _srlg_backup(self, p1, p2):
        """Replace a backup that shares a risk group with the primary.

        Bhandari's pair is disjoint but SRLG-oblivious. If the backup uses a
        link that shares an SRLG with a primary link, take instead the
        shortest path that avoids the primary's links, their SRLG peers and
        (if node-disjoint) the primary's transit switches. If none exists the
        Bhandari backup is kept. (Exact SRLG-disjoint path pairs are NP-hard
        in general; this two-step heuristic is the usual practical choice.)
        """
        primary = set(path_edges(p1))
        risky = set()
        for e in primary:
            risky |= self._risk.shared_risk(e)
        if p2 is not None and not (set(path_edges(p2)) & risky):
            return p2
        alt = shortest_path(self.graph, p1[0], p1[-1], excluded_edges=primary | risky,
                            excluded_nodes=set(p1[1:-1]) if self.node_disjoint else ())
        if alt is None:
            return p2
        self.srlg_backups += 1
        return alt

    def install_ingress(self, src: str, dst: str, s: str, p1, p2) -> None:
        q1 = self.port(s, p1[1])
        watch = self.monitor.add_session(p1)
        buckets = [Bucket((SetTag(self.tag_for(p1)), Output(q1)), watch_port=watch)]
        if p2 is not None:
            q2 = self.port(s, p2[1])
            buckets.append(Bucket((SetTag(self.tag_for(p2)), Output(q2)), watch_port=q2))
        self._gid += 1
        self.install_group(s, self._gid, buckets)
        self.install(s, Match(src=src, dst=dst), [Group(self._gid)], PRIO_INGRESS, PRIMARY)


class SrlgPathProtection(PathProtection):
    """End-to-end protection whose backup also avoids the primary's SRLG peers."""

    name = "e2e-srlg"

    def __init__(self, net, **kw):
        kw.setdefault("srlg_aware", True)
        super().__init__(net, **kw)
