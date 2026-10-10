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

from .openflow import (FAST_FAILOVER, Bucket, FlowMod, GroupMod, Match, PacketIn,
                       PacketOut, PortStatus)
from .packet import Packet
from .routing import Edge, Graph, edge


class Controller:
    name = "base"

    def __init__(self, net, ctrl_delay: float = 0.005, compute_time: float = 0.005,
                 weight: str = "delay", lldp_interval: float | None = None,
                 lldp_mult: int = 3):
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
        # Links the controller currently believes are down.
        self.down_links: set[Edge] = set()
        self.msgs_sent = 0
        self.msgs_received = 0
        self.log: list[tuple[float, str]] = []
        for sw in net.switches.values():
            sw.controller = self
        # Optional controller-driven failure detection by LLDP probing.
        self.lldp_interval = lldp_interval
        self.lldp_mult = lldp_mult
        self.lldp_sent = 0
        self._lldp_seen: dict[Edge, float] = {}
        if lldp_interval:
            for sw in net.switches.values():
                sw.agents["lldp"] = self._lldp_punt(sw)

    # -------------------------------------------------------------- lifecycle
    def start(self, at: float = 0.0) -> None:
        self.sim.at(at, self.on_start)
        if self.lldp_interval:
            for e in self.graph.edges:
                self._lldp_seen[e] = at
            self.sim.at(at, self._lldp_round)

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
            if msg.packet.kind == "lldp":
                self._lldp_received(msg)
            else:
                self.on_packet_in(msg)
        elif isinstance(msg, PortStatus):
            if msg.peer not in self.graph.adj:
                return  # a host-facing port; not part of the switch graph
            self.link_event(msg.switch, msg.peer, msg.live,
                            f"port_status {msg.switch}:{msg.port}->{msg.peer}")
        else:
            raise TypeError(f"unexpected message {msg!r}")

    def link_event(self, a: str, b: str, live: bool, source: str) -> None:
        """Update our belief about link a-b; notify the app if it changed."""
        e = edge(a, b)
        changed = (e in self.down_links) if live else (e not in self.down_links)
        if live:
            self.down_links.discard(e)
        else:
            self.down_links.add(e)
        self.note(f"{source} {'UP' if live else 'DOWN'}{'' if changed else ' (dup)'}")
        if changed:
            self.on_link_change(e, live)

    # -- LLDP-based monitoring -------------------------------------------------
    # Every lldp_interval the controller asks each switch to send a probe out
    # of each port (PACKET_OUT). The neighbour punts the probe back to the
    # controller (PACKET_IN). A link whose probes have not come back for
    # lldp_mult intervals is declared down. Simple and switch-independent,
    # but slow: detection takes several intervals *plus* control-channel delays.
    def _lldp_round(self) -> None:
        for (sw, peer), port in sorted(self.ports.items()):
            if peer in self.graph.adj:
                self.lldp_sent += 1
                self.packet_out(sw, Packet(sw, peer, kind="lldp", payload=(sw, port)), port)
        now = self.sim.now
        limit = self.lldp_mult * self.lldp_interval
        for e, seen in sorted(self._lldp_seen.items(), key=lambda kv: sorted(kv[0])):
            if now - seen > limit and e not in self.down_links:
                a, b = sorted(e)
                self.link_event(a, b, False, f"lldp {a}-{b}")
        self.sim.schedule(self.lldp_interval, self._lldp_round)

    def _lldp_punt(self, sw):
        def punt(pkt, in_port):
            self.from_switch(PacketIn(sw.name, in_port, pkt))
        return punt

    def _lldp_received(self, msg: PacketIn) -> None:
        a, b = msg.packet.payload[0], msg.switch
        e = edge(a, b)
        self._lldp_seen[e] = self.sim.now
        if e in self.down_links:
            self.link_event(a, b, True, f"lldp {'-'.join(sorted(e))}")

    @property
    def probe_packets(self) -> int:
        return self.lldp_sent

    # -- helpers ---------------------------------------------------------------
    def install(self, switch: str, match: Match, actions, priority: int = 100,
                cookie: int = 0) -> None:
        self.send(switch, FlowMod("add", match, tuple(actions), priority, cookie))

    def remove(self, switch: str, match: Match | None = None, cookie: int = 0) -> None:
        self.send(switch, FlowMod("delete", match, (), 0, cookie))

    def install_group(self, switch: str, gid: int, buckets: list[Bucket],
                      type: str = FAST_FAILOVER) -> None:
        self.send(switch, GroupMod("add", gid, type, tuple(buckets)))

    def remove_group(self, switch: str, gid: int) -> None:
        self.send(switch, GroupMod("delete", gid))

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

    def on_link_change(self, e: Edge, live: bool) -> None:
        """Our belief about link ``e`` changed (from PORT_STATUS or LLDP)."""
        pass
