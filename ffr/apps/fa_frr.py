"""Failure-Aware Fast Reroute (FA-FRR): the main contribution of this project.

FA-FRR keeps the data-plane speed of local fast reroute (fast-failover
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
   second failure. The update is make-before-break and loop-free:

   * phase 1: install the new generation's detour rules (fresh tags), then a
     barrier on *every* switch, so that anything an older, superseded update
     sent has also been applied;
   * phase 2: rewrite the fast-failover groups level by level, starting at
     the switches next to each destination and moving outwards along the new
     primary tree, with a barrier between levels. A switch only switches to
     its new next hop once that next hop already forwards on the new tree, so
     no packet can loop between old and new next hops;
   * phase 3: after a drain time (the longest old detour), delete the old
     generation's detour rules by cookie.

   Before all that, as soon as a failure is reported, the groups next to the
   failed link are rewritten to their backup bucket only ("pinning"), so a
   link that comes back during re-optimisation cannot pull traffic back.
4. **Flap damping.** A link that comes back up is not used again until it
   has stayed up for a hold-down time that grows with its recent
   instability. Plain FRR is revertive: every flap costs a new outage. If a
   destination would become unreachable without a held-down link, the link
   is released early.
5. **Learning.** Every failure raises the link's (and its SRLG peers')
   failure probability, decaying over time, which feeds back into 1 and 2.

Each feature can be switched off (``risk_aware``, ``srlg_aware``,
``reoptimize``, ``holddown=0``, ``adaptive_holddown``, ``ordered_update``)
to measure its contribution (ablation).
"""

from __future__ import annotations

from ..openflow import Bucket, Group, Match, Output, PopTag, SetTag
from ..protection import Element, HopPlan, plan_destination
from ..risk import RiskModel
from ..routing import Edge, edge, next_hops_to
from .frr import PRIO_DETOUR, LocalFRR
from .static import PRIMARY, PRIO_PRIMARY

DETOUR_BASE = 1000  # detour cookies are DETOUR_BASE + generation
MAX_TAGS = 4094       # a 12-bit VLAN id (1..4094); tags are recycled per generation
PRIO_IN_PORT = PRIO_PRIMARY + 1  # OpenFlow 1.3 U-turn rules: above primaries, below detours


class FailureAwareFRR(LocalFRR):
    name = "fa-frr"
    mode = "node"

    def __init__(self, net, lam: float = 5.0, half_life: float = 5.0,
                 flap_penalty: float = 0.3, correlation: float = 0.5,
                 holddown: float = 0.2, risk_aware: bool = True, srlg_aware: bool = True,
                 reoptimize: bool = True, adaptive_holddown: bool = True,
                 ordered_update: bool = True, pin_backups: bool = True,
                 p_max: float = 0.99, coincidence: float = 0.05, of13_inport: bool = False,
                 **kw):
        super().__init__(net, **kw)
        self.risk = RiskModel(net.topo, half_life, flap_penalty, correlation, p_max, coincidence)
        # of13_inport: also install the OpenFlow 1.3 OFPP_IN_PORT group and
        # (in_port, dst) rule per protected (switch, destination), as the
        # testbed controller does, so that update timing includes them
        self.of13_inport = of13_inport
        self.vias: dict[tuple[str, str], set[str]] = {}
        self._inport_gids: dict[tuple[str, str, str], int] = {}
        self._free_tags: list[int] = []
        self._next_tag = 1
        self.tags_peak = 0
        self.holddown_skipped = 0
        self.lam = lam
        self.base_holddown = holddown
        self.adaptive_holddown = adaptive_holddown
        self.risk_aware = risk_aware
        self.srlg_aware = srlg_aware
        self.reopt_enabled = reoptimize
        self.ordered_update = ordered_update
        self.pin_backups = pin_backups
        self.pinned = 0
        self.generation = 0
        self.gen_switches: dict[int, set[str]] = {}
        self.gen_drain: dict[int, float] = {}       # longest detour delay per generation
        self.held: dict[Edge, object] = {}  # recovered links in hold-down -> timer
        self.installed: dict[tuple[str, str], tuple] = {}  # (switch, host) -> group content
        self._reopt_pending = False
        self._primary_done: set[tuple[str, str]] = set()
        self.reoptimizations = 0
        self.holddown_overrides = 0
        self.update_rounds = 0
        self.protected_at: dict[int, float] = {}  # generation -> time its groups were all in place

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
        """Tag of (element, SRLG variant) in the current generation.

        Fresh tags per generation, so in-flight packets on old detours keep
        following the old rules until those are deleted. Tags come from a
        pool of MAX_TAGS ids; a generation's tags return to the pool when its
        rules are deleted (phase 3), and the smallest free id is reused first.
        """
        k = (key, self.generation)
        t = self.tags.get(k)
        if t is None:
            import heapq
            if self._free_tags:
                t = heapq.heappop(self._free_tags)
            else:
                t = self._next_tag
                self._next_tag += 1
                if t > MAX_TAGS:
                    raise RuntimeError("out of detour tags")
            self.tags[k] = t
            self.tags_peak = max(self.tags_peak, len(self.tags))
        return t

    def _free_generation_tags(self, gen: int) -> None:
        import heapq
        for k in [k for k in self.tags if k[1] == gen]:
            heapq.heappush(self._free_tags, self.tags.pop(k))

    def _reachable(self, excluded) -> int:
        """Number of (switch, destination switch) pairs connected without ``excluded``."""
        return sum(len(next_hops_to(self.graph, hsw, excluded_edges=excluded))
                   for hsw in set(self.host_switch.values()))

    def _release_held_if_needed(self) -> None:
        """Release held-down links, least risky first, while some destination needs them."""
        if not self.held:
            return
        target = self._reachable(set(self.down_links))
        now = self.sim.now
        order = sorted(self.held, key=lambda e: (self.risk.penalty(e, now), sorted(e)))
        for e in order:
            if self._reachable(self.unusable()) >= target:
                break
            self.held.pop(e).cancel()
            self.holddown_overrides += 1
            self.note(f"link {'-'.join(sorted(e))}: hold-down overridden (needed for reachability)")

    # -- installation (make-before-break) ----------------------------------------------
    def install_all_routes(self) -> None:
        self.reoptimize()

    def reoptimize(self) -> None:
        self._reopt_pending = False
        self._release_held_if_needed()
        self.generation += 1
        self.reoptimizations += 1
        gen = self.generation
        cookie = DETOUR_BASE + gen
        self.plans = {h: self.plan(h, s) for h, s in sorted(self.host_switch.items())}
        touched: set[str] = set()
        drain = 0.0
        for host, plans in self.plans.items():
            rules: dict[tuple[str, int], str] = {}
            for u, hp in sorted(plans.items()):
                if hp.protected:
                    t = self.tag_for(hp.tag_key)
                    drain = max(drain, sum(self.graph.weight(a, b)
                                           for a, b in zip(hp.detour, hp.detour[1:])))
                    for x, y in zip(hp.detour[1:-1], hp.detour[2:]):
                        prev = rules.setdefault((x, t), y)
                        assert prev == y, "inconsistent detours"
            for (x, t), y in sorted(rules.items()):
                self.install(x, Match(dst=host, tag=t), [Output(self.port(x, y))],
                             PRIO_DETOUR, cookie)
                touched.add(x)
        self.gen_switches[gen] = touched
        self.gen_drain[gen] = drain
        self.note(f"reoptimize gen={gen}: unusable={sorted('-'.join(sorted(e)) for e in self.unusable())}")
        # Phase 2 starts once every new detour rule is in place *and* every
        # message of an older (possibly superseded) update has been applied.
        self.barrier(set(self.net.switches), lambda: self._switch_groups(gen))

    def _group_content(self, u: str, host: str, hp: HopPlan) -> tuple:
        p = self.port(u, hp.primary)
        if hp.protected:
            return (p, self.port(u, hp.detour[1]), self.tag_for(hp.tag_key))
        return (p, None, None)

    def _levels(self) -> list[list[tuple[str, str]]]:
        """(switch, host) group updates grouped into loop-free update rounds.

        A group whose primary next hop does not change can be rewritten at
        any time (only its backup changes), so it goes in the first round.
        A switch whose next hop changes goes in round k = the number of
        switches with a changed next hop on its *new* primary path to the
        destination, itself included. So every changed switch downstream of
        it on the new path has already switched when it does, and the
        unchanged ones forward the same way in the old and new trees: a packet
        that reaches a switched node follows the new tree to the destination,
        and one that does not follows old-tree edges, which also cannot loop.
        """
        rounds: dict[int, list[tuple[str, str]]] = {}
        for host, plans in self.plans.items():
            hsw = self.host_switch[host]
            # A switch without a group for this destination yet drops on a table
            # miss, so it cannot be part of a loop: only next-hop *changes* are
            # ordered (the very first installation is a single round).
            changed = {u: (u, host) in self.installed
                       and self.installed[(u, host)][0] != self.port(u, hp.primary)
                       for u, hp in plans.items()}
            count = {hsw: 0}

            def c(u):
                if u not in count:
                    count[u] = changed[u] + c(plans[u].primary)
                return count[u]

            for u in sorted(plans):
                k = c(u) if (changed[u] and self.ordered_update) else 1
                rounds.setdefault(k, []).append((u, host))
        return [rounds[k] for k in sorted(rounds)]

    def _switch_groups(self, gen: int) -> None:
        if gen != self.generation:
            return  # superseded by a newer re-optimisation
        for host in self.plans:
            hsw = self.host_switch[host]
            if (hsw, host) not in self._primary_done:
                self.install(hsw, Match(dst=host), [PopTag(), Output(self.port(hsw, host))],
                             PRIO_PRIMARY, PRIMARY)
                self._primary_done.add((hsw, host))
        self._run_rounds(gen, self._levels())

    def _run_rounds(self, gen: int, rounds: list) -> None:
        if gen != self.generation:
            return
        if not rounds:
            if self.ordered_update:
                # every round ended with a barrier: all groups are confirmed
                self._protected(gen)
            else:
                self.barrier(set(self.net.switches), lambda: self._protected(gen))
            return
        self.update_rounds += 1
        touched = set()
        for u, host in rounds[0]:
            hp = self.plans[host][u]
            content = self._group_content(u, host, hp)
            p, q, t = content
            buckets = [Bucket((Output(p),), watch_port=p)]
            if q is not None:
                buckets.append(Bucket((SetTag(t), Output(q)), watch_port=q))
            gid = self.gid_for(u, host)
            self.install_group(u, gid, buckets)
            if (u, host) not in self._primary_done:
                self.install(u, Match(dst=host), [Group(gid)], PRIO_PRIMARY, PRIMARY)
                self._primary_done.add((u, host))
            self.installed[(u, host)] = content
            touched.add(u)
        if self.of13_inport:
            for u, host in rounds[0]:
                self._install_inport(u, host)
        rest = rounds[1:]
        if self.ordered_update:
            self.barrier(touched, lambda: self._run_rounds(gen, rest))
        else:
            self._run_rounds(gen, rest)

    def _inport_buckets(self, u: str, host: str, pinned: bool = False):
        p, q, t = self.installed[(u, host)]
        buckets = [] if pinned else [Bucket((Output(p),), watch_port=p)]
        if q is not None:
            buckets.append(Bucket((SetTag(t), Output(q)), watch_port=q))
        return buckets

    def _install_inport(self, u: str, host: str, pinned: bool = False) -> None:
        """OpenFlow 1.3 U-turn support: a packet arriving from the backup's first
        hop must leave through OFPP_IN_PORT, so it gets its own FF group selected
        by an (in_port, dst) rule. Vias of earlier generations keep being
        updated so that their rules never point at a stale group. (The emulator
        lets a packet leave through its ingress port, so this only adds the
        messages and state of a real switch.)"""
        hp = self.plans[host][u]
        vias = self.vias.setdefault((u, host), set())
        if hp.protected:
            vias.add(hp.detour[1])
        for via in sorted(vias):
            gid = self._inport_gids.get((u, host, via))
            new = gid is None
            if new:
                gid = self._inport_gids[(u, host, via)] = 100000 + len(self._inport_gids)
            # the group first: a rule must never point at a missing group
            self.install_group(u, gid, self._inport_buckets(u, host, pinned))
            if new:
                self.install(u, Match(dst=host, in_port=self.port(u, via)), [Group(gid)],
                             PRIO_IN_PORT, PRIMARY)

    def _remove_stale_inport(self) -> None:
        """Delete U-turn rules and groups for neighbours that are no longer a
        backup's first hop (rule first, so it never points at a missing group)."""
        for (u, host), vias in sorted(self.vias.items()):
            hp = self.plans.get(host, {}).get(u)
            current = hp.detour[1] if hp is not None and hp.protected else None
            for via in sorted(vias - {current}):
                self.remove(u, Match(dst=host, in_port=self.port(u, via)))
                self.remove_group(u, self._inport_gids.pop((u, host, via)))
                vias.discard(via)

    def _protected(self, gen: int) -> None:
        if gen != self.generation:
            return
        self.protected_at[gen] = self.sim.now
        self.note(f"gen={gen} groups installed: network protected again")
        # phase 3, once packets already on an old detour have reached their destination
        drain = max((self.gen_drain.get(g, 0.0) for g in self.gen_switches if g < gen),
                    default=0.0)
        self.sim.schedule(drain, self._cleanup, gen)

    def _cleanup(self, gen: int) -> None:
        if gen != self.generation:
            return  # a newer generation will clean up (it also deletes ours)
        for old in sorted(g for g in self.gen_switches if g < gen):
            for sw in sorted(self.gen_switches.pop(old)):
                self.remove(sw, cookie=DETOUR_BASE + old)
            self.gen_drain.pop(old, None)
            self._free_generation_tags(old)
        self._remove_stale_inport()
        self.note(f"gen={gen} active")

    # -- reacting to failures ------------------------------------------------------------
    def on_link_change(self, e: Edge, live: bool) -> None:
        now = self.sim.now
        if not live:
            self.risk.record_failure(e, now, down=self.down_links)
            timer = self.held.pop(e, None)
            if timer is not None:
                # Failed again while on probation (its hold-down release timer
                # is cancelled). The link itself carries no traffic, but its
                # SRLG peers just became riskier: re-plan if that can matter.
                timer.cancel()
                self.note(f"link {'-'.join(sorted(e))} flapped during hold-down")
                peers_in_use = self.risk.shared_risk(e) - self.unusable()
                if peers_in_use and self.risk_aware and self.lam > 0 and self.risk.correlation > 0:
                    self._schedule_reopt()
                return
            self._pin_backups(e)
            self._schedule_reopt()
        else:
            if self.adaptive_holddown:
                hd = self.risk.holddown(e, now, self.base_holddown)
            else:
                hd = self.base_holddown
            if hd > 0 and self._reachable(self.unusable()) > self._reachable(self.unusable() | {e}):
                # the link reconnects a destination that is unreachable now:
                # use it at once instead of holding it down
                self.holddown_skipped += 1
                self.note(f"link {'-'.join(sorted(e))} up: needed for reachability, no hold-down")
                hd = 0
            if hd <= 0:
                self._schedule_reopt()
                return
            self.held[e] = self.sim.schedule(hd, self._release, e)
            self.note(f"link {'-'.join(sorted(e))} up: hold-down {1000 * hd:.0f} ms")

    def _pin_backups(self, e: Edge) -> None:
        """Make the backups of the two switches next to a failed link sticky.

        Their fast-failover groups already send traffic to the backup, but FF
        groups are revertive: if the link comes back before re-optimisation
        has rewritten them, traffic would return to the unstable link. So,
        right away, the controller rewrites those groups with the backup
        bucket only (a few messages to two switches). Packets were already on
        that backup, so this changes nothing else.
        """
        if not self.pin_backups:
            return
        a, b = sorted(e)
        for (u, host), (p, q, t) in sorted(self.installed.items()):
            if q is None or u not in (a, b) or p != self.port(u, b if u == a else a):
                continue
            self.install_group(u, self.gid_for(u, host), [Bucket((SetTag(t), Output(q)),
                                                                 watch_port=q)])
            if self.of13_inport and (u, host) in self.vias:
                for via in sorted(self.vias[(u, host)]):
                    self.install_group(u, self._inport_gids[(u, host, via)],
                                       self._inport_buckets(u, host, pinned=True))
            self.pinned += 1

    def _release(self, e: Edge) -> None:
        if self.held.pop(e, None) is not None and e not in self.down_links:
            self.note(f"link {'-'.join(sorted(e))} stable again: back in service")
            self._schedule_reopt()

    def _schedule_reopt(self) -> None:
        if self.reopt_enabled and not self._reopt_pending:
            self._reopt_pending = True
            self.sim.schedule(self.compute_time, self.reoptimize)
