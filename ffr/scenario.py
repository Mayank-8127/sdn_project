"""Glue for running one experiment.

A *scenario* = topology + controller app + traffic + failure events. It hides
the wiring so that a complete experiment fits in a few lines::

    sc = Scenario(topology.abilene().add_host_per_switch(), app="static")
    sc.all_pairs(rate=1000, start=0.1, stop=0.6)
    sc.fail_link(0.3, "DEN", "KSC")
    res = sc.run()
    print(res.summary())
"""

from __future__ import annotations

from dataclasses import dataclass

from . import apps
from .network import Network
from .sim import Simulator
from .traffic import TrafficManager


@dataclass
class Result:
    app: str
    sent: int
    lost: int
    affected: int
    flows: int
    max_outage: float
    mean_outage: float
    ctrl_msgs: int
    flow_entries: int
    group_entries: int
    events: int

    def summary(self) -> str:
        return (f"[{self.app}] flows={self.flows} sent={self.sent} lost={self.lost} "
                f"({100 * self.lost / max(1, self.sent):.2f}%) affected_flows={self.affected} "
                f"max_outage={_ms(self.max_outage)} mean_outage={_ms(self.mean_outage)} "
                f"ctrl_msgs={self.ctrl_msgs} flow_entries={self.flow_entries} "
                f"groups={self.group_entries}")


def _ms(x: float) -> str:
    return "inf" if x == float("inf") else f"{1000 * x:.1f}ms"


class Scenario:
    def __init__(self, topo, app: str = "static", net_kw: dict | None = None, **app_kw):
        self.sim = Simulator()
        self.net = Network(topo, self.sim, **(net_kw or {}))
        self.ctrl = apps.get(app)(self.net, **app_kw)
        self.tm = TrafficManager(self.net)
        self.first_failure: float | None = None
        self.stop = 0.0

    # -- traffic ---------------------------------------------------------------
    def flow(self, src: str, dst: str, rate: float = 1000.0, start: float = 0.1,
             stop: float = 1.0):
        self.stop = max(self.stop, stop)
        return self.tm.add_flow(src, dst, rate, start, stop)

    def all_pairs(self, rate: float = 1000.0, start: float = 0.1, stop: float = 1.0,
                  hosts=None):
        self.stop = max(self.stop, stop)
        return self.tm.add_all_pairs(rate, start, stop, hosts)

    # -- failures --------------------------------------------------------------
    def _mark(self, t: float) -> None:
        if self.first_failure is None or t < self.first_failure:
            self.first_failure = t

    def fail_link(self, t: float, a: str, b: str, restore_at: float | None = None) -> None:
        self._mark(t)
        self.net.schedule_link_failure(t, a, b, restore_at)

    # -- run -------------------------------------------------------------------
    def run(self, until: float | None = None) -> Result:
        self.ctrl.start(0.0)
        self.sim.run(until if until is not None else self.stop + 0.1)
        return self.result()

    def result(self) -> Result:
        affected = self.tm.affected()
        outages = [f.outage() for f in affected]
        finite = [o for o in outages if o != float("inf")]
        return Result(
            app=self.ctrl.name,
            sent=self.tm.total_sent,
            lost=self.tm.total_lost,
            affected=len(affected),
            flows=len(self.tm.flows),
            max_outage=max(outages, default=0.0),
            mean_outage=(sum(finite) / len(finite)) if finite else
            (float("inf") if outages else 0.0),
            ctrl_msgs=self.ctrl.msgs_sent,
            flow_entries=sum(len(s.table) for s in self.net.switches.values()),
            group_entries=sum(len(s.groups) for s in self.net.switches.values()),
            events=self.sim.events_processed,
        )
