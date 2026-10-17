"""Failure-Aware Fast Reroute (FA-FRR): the main contribution of this project.

FA-FRR keeps the data-plane speed of local fast reroute (v0.3: fast-failover
groups + tagged detours, node protection preferred) and adds a controller
that *knows how the network fails* (:class:`~ffr.risk.RiskModel`):

1. **Risk-aware primaries.** Paths minimise
   ``delay/mean_delay + lam * -ln(1 - p(e))``: a slightly longer path made of
   reliable links beats a short path over a risky one.
2. **SRLG-disjoint, risk-minimising backups.** A detour protecting element X
   also avoids every link that shares a risk group with X (when possible),
   because those links are likely to fail together with X.
3. **Re-optimisation after fast reroute.** FRR handles the first
   milliseconds; then the controller recomputes primaries *and new backups*
   on the surviving graph, so the network is protected again against a
   second failure. Updates are make-before-break, ordered with barriers:
   new detour rules → (barrier) → new groups → (barrier) → delete old rules.
   New detours use fresh tags (one "generation" per re-optimisation), so
   packets in flight on old detours are never misrouted.
4. **Flap damping.** A link that comes back up is not used again until it
   has stayed up for a hold-down time that grows with its recent
   instability. Plain FRR is revertive: every flap costs a new outage.
5. **Learning.** Every failure raises the link's (and its SRLG siblings')
   failure probability, decaying over time, which feeds back into 1 and 2.

Each feature can be switched off (``risk_aware``, ``srlg_aware``,
``reoptimize``, ``holddown=0``) to measure its contribution (ablation).
"""

from __future__ import annotations

from ..openflow import Bucket, Group, Match, Output, PopTag, SetTag
from ..protection import Element, HopPlan, plan_destination
from ..risk import RiskModel
from ..routing import Edge, edge
from .frr import PRIO_DETOUR, LocalFRR
from .static import PRIMARY, PRIO_PRIMARY

DETOUR_BASE = 1000  # detour cookies are DETOUR_BASE + generation


class FailureAwareFRR(LocalFRR):
    name = "fa-frr"
    mode = "node"

    def __init__(self, net, lam: float = 5.0, half_life: float = 5.0,
                 flap_penalty: float = 0.3, correlation: float = 0.5,
                 holddown: float = 0.2, risk_aware: bool = True, srlg_aware: bool = True,
                 reoptimize: bool = True, **kw):
        super().__init__(net, **kw)
        self.risk = RiskModel(net.topo, half_life, flap_penalty, correlation)
        self.lam = lam
        self.base_holddown = holddown
        self.risk_aware = risk_aware
        self.srlg_aware = srlg_aware
        self.reopt_enabled = reoptimize
        self.generation = 0
        self.gen_switches: dict[int, set[str]] = {}
        self.held: dict[Edge, object] = {}  # recovered links in hold-down -> timer
        self._reopt_pending = False
        self._primary_done: set[tuple[str, str]] = set()
        self.reoptimizations = 0

    # -- planning ----------------------------------------------------------------
    def _weight(self):
        if not self.risk_aware:
            return None
        now = self.sim.now
        return lambda u, v: self.risk.weight(edge(u, v), now, self.lam)

    def _srlg_exclusions(self, el: Element):
        if el[0] == "link":
            return self.risk.shared_risk(el[1]), ()
        node = el[1]
        risky: set[Edge] = set()
        for nb in self.graph.adj[node]:
            risky |= self.risk.shared_risk(edge(node, nb))
        return risky, ()

    def unusable(self) -> set[Edge]:
        return set(self.down_links) | set(self.held)

    def plan(self, host: str, hsw: str) -> dict[str, HopPlan]:
        return plan_destination(
            self.graph, hsw, self.mode, excluded_edges=self.unusable(), weight=self._weight(),
            detour_exclusions=self._srlg_exclusions if self.srlg_aware else None)

    def tag_for(self, key: tuple) -> int:
        # fresh tags per generation: in-flight packets on old detours keep
        # following the old rules until those are deleted
        return super().tag_for((key, self.generation))

    # -- installation (make-before-break) ----------------------------------------------
    def install_all_routes(self) -> None:
        self.reoptimize()

    def reoptimize(self) -> None:
        self._reopt_pending = False
        self.generation += 1
        self.reoptimizations += 1
        gen = self.generation
        cookie = DETOUR_BASE + gen
        self.plans = {h: self.plan(h, s) for h, s in sorted(self.host_switch.items())}
        touched: set[str] = set()
        for host, plans in self.plans.items():
            rules: dict[tuple[str, int], str] = {}
            for u, hp in sorted(plans.items()):
                if hp.protected:
                    t = self.tag_for(hp.tag_key)
                    for x, y in zip(hp.detour[1:-1], hp.detour[2:]):
                        prev = rules.setdefault((x, t), y)
                        assert prev == y, "inconsistent detours"
            for (x, t), y in sorted(rules.items()):
                self.install(x, Match(dst=host, tag=t), [Output(self.port(x, y))],
                             PRIO_DETOUR, cookie)
                touched.add(x)
        self.gen_switches[gen] = touched
        self.note(f"reoptimize gen={gen}: unusable={sorted('-'.join(sorted(e)) for e in self.unusable())}")
        # phase 2 only once every new detour rule is in place
        self.barrier(touched, lambda: self._switch_groups(gen))

    def _switch_groups(self, gen: int) -> None:
        if gen != self.generation:
            return  # superseded by a newer re-optimisation
        for host, plans in self.plans.items():
            hsw = self.host_switch[host]
            if (hsw, host) not in self._primary_done:
                self.install(hsw, Match(dst=host), [PopTag(), Output(self.port(hsw, host))],
                             PRIO_PRIMARY, PRIMARY)
                self._primary_done.add((hsw, host))
            for u, hp in sorted(plans.items()):
                p = self.port(u, hp.primary)
                buckets = [Bucket((Output(p),), watch_port=p)]
                if hp.protected:
                    q = self.port(u, hp.detour[1])
                    buckets.append(Bucket((SetTag(self.tag_for(hp.tag_key)), Output(q)),
                                          watch_port=q))
                gid = self.gid_for(u, host)
                self.install_group(u, gid, buckets)
                if (u, host) not in self._primary_done:
                    self.install(u, Match(dst=host), [Group(gid)], PRIO_PRIMARY, PRIMARY)
                    self._primary_done.add((u, host))
        self.barrier(set(self.net.switches), lambda: self._cleanup(gen))

    def _cleanup(self, gen: int) -> None:
        for old in sorted(g for g in self.gen_switches if g < gen):
            for sw in sorted(self.gen_switches.pop(old)):
                self.remove(sw, cookie=DETOUR_BASE + old)
        self.note(f"gen={gen} active")

    # -- reacting to failures ------------------------------------------------------------
    def on_link_change(self, e: Edge, live: bool) -> None:
        now = self.sim.now
        if not live:
            self.risk.record_failure(e, now)
            timer = self.held.pop(e, None)
            if timer is not None:
                # Failed again while on probation. The link carries no traffic
                # (it is excluded from every plan), so nothing to recompute.
                timer.cancel()
                self.note(f"link {'-'.join(sorted(e))} flapped during hold-down")
                return
            self._schedule_reopt()
        else:
            hd = self.risk.holddown(e, now, self.base_holddown)
            if hd <= 0:
                self._schedule_reopt()
                return
            self.held[e] = self.sim.schedule(hd, self._release, e)
            self.note(f"link {'-'.join(sorted(e))} up: hold-down {1000 * hd:.0f} ms")

    def _release(self, e: Edge) -> None:
        if self.held.pop(e, None) is not None and e not in self.down_links:
            self.note(f"link {'-'.join(sorted(e))} stable again: back in service")
            self._schedule_reopt()

    def _schedule_reopt(self) -> None:
        if self.reopt_enabled and not self._reopt_pending:
            self._reopt_pending = True
            self.sim.schedule(self.compute_time, self.reoptimize)
