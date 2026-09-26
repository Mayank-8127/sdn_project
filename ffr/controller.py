"""The SDN controller.

The controller is the "brain" of an SDN network. It

* holds a map of the topology (a :class:`~ffr.routing.Graph`),
* knows where every host is attached,
* computes paths and pushes flow rules to switches,
* reacts to events reported by switches.

Messages between controller and switch are not instantaneous: each direction
takes ``ctrl_delay`` seconds (the control network may be far away), and every
rule takes ``rule_install_time`` to be written into the switch hardware. These
costs are what makes controller-driven failure recovery slow.

Concrete behaviours ("apps") subclass :class:`Controller` and override the
``on_*`` hooks. See :mod:`ffr.apps`.
"""

from __future__ import annotations

from .openflow import FlowMod, Match, PacketIn, PacketOut
from .routing import Graph


class Controller:
    name = "base"

    def __init__(self, net, ctrl_delay: float = 0.005, compute_time: float = 0.005,
                 weight: str = "delay"):
        self.net = net
        self.sim = net.sim
        self.topo = net.topo
        self.ctrl_delay = ctrl_delay
        self.compute_time = compute_time
        # The controller's view of the network. In a real deployment this map
        # is built by topology discovery (LLDP probes); here we assume
        # discovery has completed and read the topology directly.
        self.graph = Graph.from_topology(net.topo, weight)
        # (switch, neighbour) -> local port number, as LLDP would discover it
        self.ports: dict[tuple[str, str], int] = {
            (s.name, p.peer): p.number for s in net.switches.values() for p in s.ports.values()}
        # host -> switch it is attached to (learned from ARP/PACKET_IN in reality)
        self.host_switch: dict[str, str] = dict(net.topo.hosts)
        self.msgs_sent = 0
        self.msgs_received = 0
        self.log: list[tuple[float, str]] = []
        for sw in net.switches.values():
            sw.controller = self

    # -------------------------------------------------------------- lifecycle
    def start(self, at: float = 0.0) -> None:
        self.sim.at(at, self.on_start)

    # ------------------------------------------------------- southbound API
    def send(self, switch: str, msg) -> None:
        """Send a message to a switch (arrives after ``ctrl_delay``)."""
        self.msgs_sent += 1
        self.sim.schedule(self.ctrl_delay, self.net.switches[switch].handle_message, msg)

    def from_switch(self, msg) -> None:
        """Called by a switch; the message reaches us after ``ctrl_delay``."""
        self.sim.schedule(self.ctrl_delay, self._dispatch, msg)

    def _dispatch(self, msg) -> None:
        self.msgs_received += 1
        if isinstance(msg, PacketIn):
            self.on_packet_in(msg)
        else:
            raise TypeError(f"unexpected message {msg!r}")

    # -- helpers ---------------------------------------------------------------
    def install(self, switch: str, match: Match, actions, priority: int = 100,
                cookie: int = 0) -> None:
        self.send(switch, FlowMod("add", match, tuple(actions), priority, cookie))

    def remove(self, switch: str, match: Match | None = None, cookie: int = 0) -> None:
        self.send(switch, FlowMod("delete", match, (), 0, cookie))

    def packet_out(self, switch: str, pkt, port: int) -> None:
        self.send(switch, PacketOut(pkt, port))

    def port(self, switch: str, neighbour: str) -> int:
        return self.ports[(switch, neighbour)]

    def note(self, text: str) -> None:
        self.log.append((self.sim.now, text))

    # -- hooks for apps --------------------------------------------------------
    def on_start(self) -> None:
        pass

    def on_packet_in(self, msg: PacketIn) -> None:
        pass
