"""The running network: links, ports, hosts and OpenFlow switches.

:class:`Network` takes a :class:`~ffr.topology.Topology` (the plan) and builds
live objects inside a :class:`~ffr.sim.Simulator`.

How a packet travels::

    Host.send -> Link.transmit --(link delay)--> Switch.receive
              -> flow table lookup -> actions (e.g. Output(2))
              -> Link.transmit --(delay)--> next Switch ... -> Host.receive
"""

from __future__ import annotations

from typing import Callable

from .openflow import (ALL, FAST_FAILOVER, INDIRECT, Bucket, Drop, FlowEntry,
                       FlowMod, FlowTable, Group, GroupEntry, GroupMod, Output,
                       PacketIn, PacketOut, PopTag, PortStatus, SetTag,
                       ToController)
from .detection import make_detectors
from .packet import Packet
from .sim import Simulator
from .topology import LinkSpec, Topology

HOST_LINK_DELAY = 1e-5  # 10 microseconds: hosts sit right next to their switch


class Link:
    """A full-duplex cable between two (node, port) endpoints."""

    def __init__(self, sim: Simulator, a, a_port: int, b, b_port: int,
                 delay: float, capacity: float = float("inf"), spec: LinkSpec | None = None):
        self.sim = sim
        self.a, self.a_port = a, a_port
        self.b, self.b_port = b, b_port
        self.delay = delay
        self.capacity = capacity
        self.spec = spec
        self.up = True        # physical signal present (what loss-of-signal sees)
        self.silent = False   # gray failure: signal present but frames dropped
        # Incremented on every failure. A packet that left before a failure
        # and would arrive after it is lost ("in flight" on the cut fibre).
        self.epoch = 0
        self.delivered = 0
        self.dropped = 0
        self.listeners: list[Callable[["Link"], None]] = []

    @property
    def name(self) -> str:
        return f"{self.a.name}-{self.b.name}"

    def other(self, node):
        """Return (node, port) at the opposite end from ``node``."""
        if node is self.a:
            return self.b, self.b_port
        if node is self.b:
            return self.a, self.a_port
        raise ValueError(f"{node.name} is not on link {self.name}")

    @property
    def working(self) -> bool:
        return self.up and not self.silent

    def transmit(self, sender, pkt: Packet) -> None:
        if not self.working:
            self.dropped += 1
            return
        node, port = self.other(sender)
        self.sim.schedule(self.delay, self._arrive, node, port, pkt, self.epoch)

    def _arrive(self, node, port: int, pkt: Packet, epoch: int) -> None:
        if epoch != self.epoch or not self.working:
            self.dropped += 1
            return
        self.delivered += 1
        node.receive(pkt, port)

    # -- failures --------------------------------------------------------
    def fail(self, silent: bool = False) -> None:
        """Break the link.

        ``silent=False``: a cut; the signal disappears, so hardware notices.
        ``silent=True``: a *gray failure*; the link looks fine to the
        hardware but drops every frame (e.g. a faulty line card, a
        misconfigured filter). Only active probing can detect it.
        """
        if not self.working:
            return
        if silent:
            self.silent = True
        else:
            self.up = False
        self.epoch += 1
        self._notify()

    def restore(self) -> None:
        if not self.working:
            self.up = True
            self.silent = False
            self._notify()

    def _notify(self) -> None:
        for cb in list(self.listeners):
            cb(self)

    def __repr__(self) -> str:
        state = "up" if self.working else ("SILENT" if self.up else "DOWN")
        return f"Link({self.name}, {state})"


class Port:
    """A switch port.

    ``live`` is the switch's *belief* about the port. It is not the same as
    ``link.up``: after a cable is cut, the switch needs some time (the
    detection time) before it notices and flips ``live`` to False.
    """

    def __init__(self, number: int, link: Link, peer: str):
        self.number = number
        self.link = link
        self.peer = peer  # name of the node at the other end
        self.live = True


class Host:
    """An end system with one network interface (port 0)."""

    def __init__(self, sim: Simulator, name: str):
        self.sim = sim
        self.name = name
        self.link: Link | None = None
        self.received = 0
        self.handlers: list[Callable[[Packet], None]] = []

    def send(self, pkt: Packet) -> None:
        pkt.created = self.sim.now
        self.link.transmit(self, pkt)

    def receive(self, pkt: Packet, port: int) -> None:
        if pkt.dst != self.name:
            return  # not for us (e.g. misdelivered); silently ignore
        self.received += 1
        for h in self.handlers:
            h(pkt)


class Switch:
    """An OpenFlow switch: a flow table plus a connection to a controller.

    The switch is deliberately dumb. Everything it does is dictated by the
    rules the controller installed.
    """

    def __init__(self, sim: Simulator, name: str, rule_install_time: float = 0.001):
        self.sim = sim
        self.name = name
        self.ports: dict[int, Port] = {}
        self.table = FlowTable()
        self.groups: dict[int, GroupEntry] = {}
        self.controller = None  # set by Controller.attach
        self.alive = True
        self.rule_install_time = rule_install_time
        self._busy_until = 0.0
        self.stats = {"rx": 0, "tx": 0, "miss": 0, "ttl": 0, "dead": 0, "no_port": 0,
                      "rules_installed": 0, "group_drop": 0}
        # Local agents handling control packets addressed to the switch itself
        # (e.g. BFD hellos, LLDP probes), by packet kind.
        self.agents: dict[str, Callable[[Packet, int], None]] = {}

    # ------------------------------------------------------------ data plane
    def receive(self, pkt: Packet, in_port: int) -> None:
        if not self.alive:
            self.stats["dead"] += 1
            return
        agent = self.agents.get(pkt.kind)
        if agent is not None:
            agent(pkt, in_port)
            return
        self.stats["rx"] += 1
        pkt.ttl -= 1
        if pkt.ttl <= 0:
            self.stats["ttl"] += 1
            return
        pkt.trace.append(self.name)
        self.process(pkt, in_port)

    def process(self, pkt: Packet, in_port: int | None) -> None:
        entry = self.table.lookup(pkt, in_port)
        if entry is None:
            self.stats["miss"] += 1  # table miss => drop
            return
        entry.packets += 1
        self.execute(pkt, entry.actions, in_port)

    def execute(self, pkt: Packet, actions, in_port: int | None) -> None:
        """Apply an action list in order (OpenFlow "apply-actions")."""
        for act in actions:
            if isinstance(act, Output):
                self.output(pkt.copy(), act.port)
            elif isinstance(act, SetTag):
                pkt.tag = act.tag
            elif isinstance(act, PopTag):
                pkt.tag = None
            elif isinstance(act, ToController):
                if self.controller is not None:
                    self.controller.from_switch(PacketIn(self.name, in_port, pkt.copy()))
            elif isinstance(act, Group):
                self.execute_group(pkt, act.group_id, in_port)
            elif isinstance(act, Drop):
                return
            else:
                raise TypeError(f"unknown action {act!r}")

    def is_live(self, watch) -> bool:
        """Is a watched port alive (from this switch's point of view)?"""
        port = self.ports.get(watch)
        return port is not None and port.live

    def execute_group(self, pkt: Packet, gid: int, in_port: int | None) -> None:
        group = self.groups.get(gid)
        if group is None:
            self.stats["group_drop"] += 1
            return
        if group.type == FAST_FAILOVER:
            for b in group.buckets:
                if b.watch_port is None or self.is_live(b.watch_port):
                    b.packets += 1
                    self.execute(pkt, b.actions, in_port)
                    return
            self.stats["group_drop"] += 1  # no live bucket
        elif group.type == ALL:
            for b in group.buckets:
                b.packets += 1
                self.execute(pkt.copy(), b.actions, in_port)
        elif group.type == INDIRECT:
            group.buckets[0].packets += 1
            self.execute(pkt, group.buckets[0].actions, in_port)
        else:
            raise ValueError(f"unknown group type {group.type}")

    def output(self, pkt: Packet, port_no: int) -> None:
        port = self.ports.get(port_no)
        if port is None:
            self.stats["no_port"] += 1
            return
        self.stats["tx"] += 1
        port.link.transmit(self, pkt)

    # --------------------------------------------------------- control plane
    def handle_message(self, msg) -> None:
        """A message from the controller has arrived over the control channel."""
        if not self.alive:
            return
        if isinstance(msg, PacketOut):
            self.output(msg.packet, msg.port)
            return
        # Table updates are applied one after another, each taking
        # rule_install_time (hardware TCAM updates are slow).
        start = max(self.sim.now, self._busy_until)
        self._busy_until = start + self.rule_install_time
        self.sim.at(self._busy_until, self._apply, msg)

    def _apply(self, msg) -> None:
        if not self.alive:
            return
        self.stats["rules_installed"] += 1
        if isinstance(msg, FlowMod):
            if msg.command == "add":
                self.table.add(FlowEntry(msg.match, tuple(msg.actions), msg.priority, msg.cookie))
            elif msg.command == "delete":
                self.table.delete(match=msg.match, cookie=msg.cookie if msg.cookie else None,
                                  priority=None)
            else:
                raise ValueError(msg.command)
        elif isinstance(msg, GroupMod):
            if msg.command == "add":
                self.groups[msg.group_id] = GroupEntry(
                    msg.group_id, msg.type,
                    [Bucket(tuple(b.actions), b.watch_port) for b in msg.buckets])
            elif msg.command == "delete":
                self.groups.pop(msg.group_id, None)
            else:
                raise ValueError(msg.command)
        else:
            raise TypeError(f"unknown message {msg!r}")

    def set_port_live(self, port_no: int, live: bool) -> None:
        """Change our belief about a port and report it (PORT_STATUS)."""
        port = self.ports[port_no]
        if port.live == live or not self.alive:
            return
        port.live = live
        if self.controller is not None:
            self.controller.from_switch(PortStatus(self.name, port_no, port.peer, live))

    def port_to(self, peer: str) -> int | None:
        for p in self.ports.values():
            if p.peer == peer:
                return p.number
        return None

    def dump_table(self) -> str:
        lines = [f"{self.name}: {e}" for e in self.table]
        lines += [f"{self.name}: {g}" for _, g in sorted(self.groups.items())]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"Switch({self.name})"


class Network:
    """All live objects for one topology."""

    def __init__(self, topo: Topology, sim: Simulator | None = None,
                 rule_install_time: float = 0.001, detection: str = "los",
                 los_delay: float = 0.001, bfd_interval: float = 0.0033, bfd_mult: int = 3,
                 seed: int = 0):
        self.topo = topo
        self.sim = sim or Simulator()
        self.switches: dict[str, Switch] = {
            s: Switch(self.sim, s, rule_install_time) for s in topo.switches}
        self.hosts: dict[str, Host] = {}
        self.links: dict[frozenset, Link] = {}
        self.host_links: dict[str, Link] = {}

        for spec in topo.links:
            a, b = self.switches[spec.a], self.switches[spec.b]
            pa, pb = self._next_port(a), self._next_port(b)
            link = Link(self.sim, a, pa, b, pb, spec.delay, spec.capacity, spec)
            a.ports[pa] = Port(pa, link, b.name)
            b.ports[pb] = Port(pb, link, a.name)
            self.links[spec.key] = link

        for hname, sname in topo.hosts.items():
            h, s = Host(self.sim, hname), self.switches[sname]
            ps = self._next_port(s)
            link = Link(self.sim, h, 0, s, ps, HOST_LINK_DELAY)
            h.link = link
            s.ports[ps] = Port(ps, link, hname)
            self.hosts[hname] = h
            self.host_links[hname] = link

        # Failure detection running in the switches (see detection.py).
        self.detectors = make_detectors(self, detection, los_delay, bfd_interval, bfd_mult, seed)
        for d in self.detectors:
            self.sim.at(0.0, d.start)

    def detector(self, name: str):
        return next((d for d in self.detectors if d.name == name), None)

    @property
    def probe_packets(self) -> int:
        return sum(d.overhead_packets for d in self.detectors)

    @staticmethod
    def _next_port(sw: Switch) -> int:
        return max(sw.ports, default=0) + 1

    def link(self, a: str, b: str) -> Link:
        try:
            return self.links[frozenset((a, b))]
        except KeyError:
            raise KeyError(f"no link {a}-{b}") from None

    # -- failure injection (used by experiments) ---------------------------
    def fail_link(self, a: str, b: str, silent: bool = False) -> None:
        self.link(a, b).fail(silent)

    def restore_link(self, a: str, b: str) -> None:
        self.link(a, b).restore()

    def fail_node(self, name: str) -> None:
        """Crash a switch: it stops forwarding and its links go dark.

        Neighbours see loss of signal on the links towards it. (Restarting a
        crashed switch is not modelled: it would come back with empty tables.)
        """
        sw = self.switches[name]
        sw.alive = False
        for port in sw.ports.values():
            port.link.fail()

    def schedule_link_failure(self, t: float, a: str, b: str, restore_at: float | None = None,
                              silent: bool = False):
        self.sim.at(t, self.fail_link, a, b, silent)
        if restore_at is not None:
            self.sim.at(restore_at, self.restore_link, a, b)
