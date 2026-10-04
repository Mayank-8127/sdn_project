"""Local fast reroute with OpenFlow fast-failover groups.

Everything is installed *before* any failure (protection, not restoration).
For every destination host ``h`` (on switch ``d``) and every other switch
``u`` with primary next hop ``v``:

* switch ``u`` gets a FAST_FAILOVER group::

      bucket 1: watch port(u->v)  -> Output(port(u->v))               # primary
      bucket 2: watch port(u->w)  -> SetTag(T), Output(port(u->w))    # detour

  and a rule ``dst=h -> Group``.
* ``T`` is the label of the protected element X (link u-v, or node v). Every
  switch on the detour gets a higher-priority rule
  ``dst=h, tag=T -> Output(next hop on detour)``.
* the egress switch ``d`` removes the tag before delivering to the host.

When ``u`` notices that port u->v died, the very next packet takes bucket 2:
recovery time = detection time. The controller is not involved at all.

``frr-link`` protects links; ``frr-node`` protects the next-hop switch (so it
also survives switch crashes) and falls back to link protection when a node
detour is impossible.
"""

from __future__ import annotations

from ..openflow import Bucket, Group, Match, Output, PopTag, SetTag
from ..protection import Element, HopPlan, coverage, plan_destination
from .static import PRIMARY, PRIO_PRIMARY, StaticRouting

DETOUR = 2  # cookie for detour rules
PRIO_DETOUR = 200


class LocalFRR(StaticRouting):
    name = "frr-link"
    mode = "link"

    def __init__(self, net, **kw):
        super().__init__(net, **kw)
        self.tags: dict[Element, int] = {}
        self.gids: dict[tuple[str, str], int] = {}
        self.plans: dict[str, dict[str, HopPlan]] = {}  # host -> plans

    # -- identifiers -----------------------------------------------------------
    def tag_for(self, el: Element) -> int:
        if el not in self.tags:
            self.tags[el] = len(self.tags) + 1
        return self.tags[el]

    def gid_for(self, switch: str, host: str) -> int:
        key = (switch, host)
        if key not in self.gids:
            self.gids[key] = 1 + sum(1 for s, _ in self.gids if s == switch)
        return self.gids[key]

    # -- installation ----------------------------------------------------------
    def plan(self, host: str, hsw: str) -> dict[str, HopPlan]:
        return plan_destination(self.graph, hsw, self.mode, excluded_edges=self.down_links)

    def install_all_routes(self) -> None:
        for host, hsw in sorted(self.host_switch.items()):
            plans = self.plan(host, hsw)
            self.plans[host] = plans
            self.install_destination(host, hsw, plans)

    def install_destination(self, host: str, hsw: str, plans: dict[str, HopPlan]) -> None:
        # egress: strip any detour tag and deliver
        self.install(hsw, Match(dst=host), [PopTag(), Output(self.port(hsw, host))],
                     PRIO_PRIMARY, PRIMARY)
        detour_rules: dict[tuple[str, int], str] = {}
        for u, hp in sorted(plans.items()):
            p = self.port(u, hp.primary)
            buckets = [Bucket((Output(p),), watch_port=p)]
            if hp.protected:
                t = self.tag_for(hp.protects)
                w = hp.detour[1]
                q = self.port(u, w)
                buckets.append(Bucket((SetTag(t), Output(q)), watch_port=q))
                for x, y in zip(hp.detour[1:-1], hp.detour[2:]):
                    prev = detour_rules.setdefault((x, t), y)
                    assert prev == y, "detours for the same element must agree"
            gid = self.gid_for(u, host)
            self.install_group(u, gid, buckets)
            self.install(u, Match(dst=host), [Group(gid)], PRIO_PRIMARY, PRIMARY)
        for (x, t), y in sorted(detour_rules.items()):
            self.install(x, Match(dst=host, tag=t), [Output(self.port(x, y))],
                         PRIO_DETOUR, DETOUR)

    def coverage(self) -> float:
        cov = [coverage(p) for p in self.plans.values()]
        return sum(cov) / len(cov) if cov else 1.0


class NodeFRR(LocalFRR):
    name = "frr-node"
    mode = "node"
