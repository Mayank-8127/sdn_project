"""Reactive restoration: recompute and reinstall routes after a failure.

This is how a "plain" SDN controller handles failures:

1. the switch next to the failure notices it (loss of signal) and sends a
   PORT_STATUS message to the controller (``ctrl_delay``),
2. the controller marks the link down and recomputes shortest paths on the
   remaining graph (``compute_time``),
3. it compares the new routes with the installed ones and sends a FLOW_MOD
   for every rule that must change (``ctrl_delay`` each, in parallel),
4. each switch installs its updates one by one (``rule_install_time`` each).

Expected outage ≈ detection + 2·ctrl_delay + compute_time + k·rule_install_time,
where k is the number of rules the busiest affected switch must rewrite.

When the link comes back, the same procedure moves traffic back to the
(shorter) original paths.
"""

from __future__ import annotations

from ..openflow import Match, Output
from .static import PRIMARY, PRIO_PRIMARY, StaticRouting


class ReactiveRouting(StaticRouting):
    name = "reactive"

    def __init__(self, net, **kw):
        super().__init__(net, **kw)
        self.installed: dict[tuple[str, str], int] = {}  # (switch, host) -> port
        self._recompute_pending = False
        self.recomputations = 0

    def install_all_routes(self) -> None:
        self.reroute()

    def on_link_change(self, e, live: bool) -> None:
        if self._recompute_pending:
            return  # a recomputation is already queued; it will see this change
        self._recompute_pending = True
        self.sim.schedule(self.compute_time, self.reroute)

    def reroute(self) -> None:
        """Compute routes on the current view and push only the differences."""
        self._recompute_pending = False
        self.recomputations += 1
        wanted: dict[tuple[str, str], int] = {}
        for host, hsw in sorted(self.host_switch.items()):
            for sw, port in self.route_ports(host, hsw, excluded_edges=self.down_links).items():
                wanted[(sw, host)] = port
        updates = 0
        for key, port in sorted(wanted.items()):
            if self.installed.get(key) != port:
                sw, host = key
                self.install(sw, Match(dst=host), [Output(port)], PRIO_PRIMARY, PRIMARY)
                updates += 1
        for key in sorted(set(self.installed) - set(wanted)):
            sw, host = key  # destination unreachable from sw: remove the stale rule
            self.remove(sw, Match(dst=host))
            updates += 1
        self.installed = wanted
        self.note(f"reroute #{self.recomputations}: {updates} rule updates")
