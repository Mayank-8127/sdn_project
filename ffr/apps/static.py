"""Static shortest-path routing: the "no recovery" baseline.

At start-up the controller computes, for every host ``h``, the shortest-path
tree towards ``h``'s switch and installs one rule per switch:

    match dst=h  ->  output <port towards next hop>

Nothing is ever changed afterwards. When a link on a path fails, packets are
lost until the link comes back. Every other strategy is compared against
this.
"""

from __future__ import annotations

from ..controller import Controller
from ..openflow import Match, Output
from ..routing import next_hops_to

PRIMARY = 1  # cookie for primary-path rules
PRIO_PRIMARY = 100


class StaticRouting(Controller):
    name = "static"

    def on_start(self) -> None:
        self.install_all_routes()

    def install_all_routes(self) -> None:
        for host, hsw in sorted(self.host_switch.items()):
            for sw, port in self.route_ports(host, hsw).items():
                self.install(sw, Match(dst=host), [Output(port)], PRIO_PRIMARY, PRIMARY)

    def route_ports(self, host: str, hsw: str, **kw) -> dict[str, int]:
        """Output port at each switch for traffic to ``host`` (attached to ``hsw``)."""
        ports = {hsw: self.port(hsw, host)}
        for sw, nh in next_hops_to(self.graph, hsw, **kw).items():
            ports[sw] = self.port(sw, nh)
        return ports
