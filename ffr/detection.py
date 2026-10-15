"""Failure detection mechanisms that run in the switches.

Fast reroute can only be as fast as failure *detection*: a fast-failover
group keeps using a dead port until the switch believes the port is dead
(``Port.live`` becomes False). This module provides the mechanisms that
change that belief:

* :class:`LossOfSignal` (``"los"``): the transceiver notices the signal
  disappear. Fast (~1 ms) and free, but it **cannot see gray failures**,
  where the link stays "up" yet drops traffic.
* :class:`BFD` (``"bfd"``): Bidirectional Forwarding Detection (RFC 5880).
  Both ends of every link send a small hello every ``interval``; if
  ``mult`` consecutive hellos are missed the session goes down and the port
  is declared dead. Detects *any* failure that stops packets, at the cost of
  ``2 / interval`` packets per second per link.

Controller-based probing (LLDP) lives in the controller
(:mod:`ffr.controller`), since there the *controller* detects the failure,
not the switch.
"""

from __future__ import annotations

import random

from .packet import Packet


class LossOfSignal:
    name = "los"

    def __init__(self, net, delay: float = 0.001):
        self.net = net
        self.delay = delay
        for link in net.links.values():
            link.listeners.append(self._on_change)

    def start(self) -> None:
        pass

    def _on_change(self, link) -> None:
        for sw, port in ((link.a, link.a_port), (link.b, link.b_port)):
            self.net.sim.schedule(self.delay, self._update, sw, port, link)

    @staticmethod
    def _update(sw, port: int, link) -> None:
        # Read the state *now*: the link may have flapped back meanwhile.
        # A silent failure leaves link.up True, so it goes unnoticed here.
        sw.set_port_live(port, link.up)

    @property
    def overhead_packets(self) -> int:
        return 0


class _BfdEnd:
    """One end of a BFD session (one switch port)."""

    __slots__ = ("sw", "port", "link", "up", "last_rx", "timer")

    def __init__(self, sw, port: int, link):
        self.sw, self.port, self.link = sw, port, link
        self.up = False      # session state; becomes Up on the first hello
        self.last_rx = 0.0
        self.timer = None


class BFD:
    name = "bfd"

    def __init__(self, net, interval: float = 0.0033, mult: int = 3, seed: int = 0):
        self.net = net
        self.sim = net.sim
        self.interval = interval
        self.mult = mult
        self.detect_time = interval * mult
        self.sent = 0
        self.detections = 0
        self._rng = random.Random(seed)
        self.ends: dict[tuple[str, int], _BfdEnd] = {}
        for link in net.links.values():
            for sw, port in ((link.a, link.a_port), (link.b, link.b_port)):
                self.ends[(sw.name, port)] = _BfdEnd(sw, port, link)
        for sw in net.switches.values():
            sw.agents["bfd"] = self._make_rx(sw)

    @property
    def overhead_packets(self) -> int:
        return self.sent

    def start(self) -> None:
        for end in self.ends.values():
            # random phase so that sessions do not all fire at once
            self.sim.schedule(self._rng.uniform(0, self.interval), self._tx, end)

    def _tx(self, end: _BfdEnd) -> None:
        if not end.sw.alive:
            return
        peer = end.sw.ports[end.port].peer
        end.link.transmit(end.sw, Packet(end.sw.name, peer, kind="bfd"))
        self.sent += 1
        self.sim.schedule(self.interval, self._tx, end)

    def _make_rx(self, sw):
        def rx(pkt: Packet, in_port: int) -> None:
            end = self.ends.get((sw.name, in_port))
            if end is None:
                return
            end.last_rx = self.sim.now
            if not end.up:
                end.up = True
                sw.set_port_live(in_port, True)
            if end.timer is None:
                end.timer = self.sim.schedule(self.detect_time, self._check, end)
        return rx

    def _check(self, end: _BfdEnd) -> None:
        end.timer = None
        silence = self.sim.now - end.last_rx
        if silence >= self.detect_time - 1e-12:
            end.up = False
            self.detections += 1
            end.sw.set_port_live(end.port, False)
        else:
            end.timer = self.sim.schedule(self.detect_time - silence, self._check, end)


def make_detectors(net, detection, los_delay: float = 0.001, bfd_interval: float = 0.0033,
                   bfd_mult: int = 3, seed: int = 0) -> list:
    """Build detectors from a spec such as ``"los"``, ``"bfd"``, ``"los+bfd"``
    or ``"none"``."""
    names = [] if detection in (None, "none", "") else detection.split("+")
    out = []
    for n in names:
        if n == "los":
            out.append(LossOfSignal(net, los_delay))
        elif n == "bfd":
            out.append(BFD(net, bfd_interval, bfd_mult, seed))
        else:
            raise ValueError(f"unknown detection mechanism {n!r}")
    return out


class _PathEnd:
    __slots__ = ("sw", "path", "logical", "up", "last_rx", "timer")

    def __init__(self, sw, path: list[str], logical: str):
        self.sw, self.path, self.logical = sw, path, logical
        self.up = False
        self.last_rx = 0.0
        self.timer = None


class PathBFD:
    """Multi-hop BFD (RFC 5883) between the two ends of a path.

    Used by end-to-end path protection: the *ingress* switch cannot see a
    failure in the middle of a path, so it runs a BFD session with the
    egress switch *along the primary path*. Each end sends hellos along the
    path (the egress end along the reversed path). If the ingress stops
    hearing hellos, the logical port ``path:<id>`` goes dead and the ingress
    fast-failover group switches to the backup path.

    Modelling note: probes are forwarded hop by hop by a switch agent along
    the recorded path (equivalent to labelling them with the path's tag), so
    they cross exactly the links of the protected path.
    """

    name = "path-bfd"

    def __init__(self, net, interval: float = 0.0033, mult: int = 3, seed: int = 0):
        self.net = net
        self.sim = net.sim
        self.interval = interval
        self.detect_time = interval * mult
        self.sent = 0
        self.detections = 0
        self.sessions: dict[str, tuple[_PathEnd, _PathEnd]] = {}
        self._rng = random.Random(seed)
        for sw in net.switches.values():
            sw.agents["pbfd"] = self._make_agent(sw)

    @property
    def overhead_packets(self) -> int:
        return self.sent

    def add_session(self, path: list[str]) -> str:
        """Monitor ``path``; returns the logical port name used at the ingress."""
        logical = "path:" + ">".join(path)
        if logical in self.sessions:
            return logical
        sw = self.net.switches
        a = _PathEnd(sw[path[0]], list(path), logical)
        b = _PathEnd(sw[path[-1]], list(reversed(path)), "rpath:" + ">".join(path))
        self.sessions[logical] = (a, b)
        for end in (a, b):
            first_port = end.sw.port_to(end.path[1])
            # Down until the first hello arrives (like a BFD session in Init).
            end.sw.logical[end.logical] = (False, first_port)
            self.sim.schedule(self._rng.uniform(0, self.interval), self._tx, end)
        return logical

    def _tx(self, end: _PathEnd) -> None:
        if not end.sw.alive:
            return
        self.sent += 1
        a, b = self.sessions[end.logical if end.logical.startswith("path:")
                             else end.logical[1:]]
        receiver = b if end is a else a
        pkt = Packet(end.sw.name, end.path[-1], kind="pbfd", payload=(receiver, end.path, 0))
        self._forward(end.sw, pkt)
        self.sim.schedule(self.interval, self._tx, end)

    def _forward(self, sw, pkt: Packet) -> None:
        receiver, path, i = pkt.payload
        port = sw.port_to(path[i + 1])
        pkt.payload = (receiver, path, i + 1)
        sw.ports[port].link.transmit(sw, pkt)

    def _make_agent(self, sw):
        def agent(pkt: Packet, in_port: int) -> None:
            receiver, path, i = pkt.payload
            if i < len(path) - 1:
                self._forward(sw, pkt)  # transit switch: pass it on
            else:
                self._rx(receiver)      # reached the far end of the path
        return agent

    def _rx(self, end: _PathEnd) -> None:
        end.last_rx = self.sim.now
        if not end.up:
            end.up = True
            end.sw.logical[end.logical] = (True, end.sw.logical[end.logical][1])
        if end.timer is None:
            end.timer = self.sim.schedule(self.detect_time, self._check, end)

    def _check(self, end: _PathEnd) -> None:
        end.timer = None
        silence = self.sim.now - end.last_rx
        if silence >= self.detect_time - 1e-12:
            end.up = False
            self.detections += 1
            end.sw.logical[end.logical] = (False, end.sw.logical[end.logical][1])
        else:
            end.timer = self.sim.schedule(self.detect_time - silence, self._check, end)
