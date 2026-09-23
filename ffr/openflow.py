"""OpenFlow concepts: matches, actions, flow entries, flow tables, messages.

This module models the *meaning* of OpenFlow (version 1.3 style), not its
binary wire format.

A switch's flow table is a list of rules. Each rule says:

    "if a packet MATCHES these header values, do these ACTIONS"

and has a PRIORITY to resolve overlaps. Header fields left out of a match are
wildcards.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from .packet import Packet


class _Any:
    """Wildcard marker: "this field may have any value"."""

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "*"


ANY: Any = _Any()


@dataclass(frozen=True)
class Match:
    """Which packets a rule applies to. Unset fields are wildcards.

    ``tag=None`` is *not* a wildcard: it means "only untagged packets".
    """

    in_port: Any = ANY
    src: Any = ANY
    dst: Any = ANY
    tag: Any = ANY

    def matches(self, pkt: Packet, in_port: int | None) -> bool:
        return ((self.in_port is ANY or self.in_port == in_port)
                and (self.src is ANY or self.src == pkt.src)
                and (self.dst is ANY or self.dst == pkt.dst)
                and (self.tag is ANY or self.tag == pkt.tag))

    def __str__(self) -> str:
        parts = [f"{k}={getattr(self, k)}" for k in ("in_port", "src", "dst", "tag")
                 if getattr(self, k) is not ANY]
        return ",".join(parts) or "*"


# ---------------------------------------------------------------- actions
@dataclass(frozen=True)
class Output:
    """Send the packet out of a port."""
    port: int


@dataclass(frozen=True)
class Drop:
    """Discard the packet explicitly."""


@dataclass(frozen=True)
class ToController:
    """Send the packet to the controller as a PACKET_IN."""


@dataclass(frozen=True)
class SetTag:
    """Put a label on the packet (like pushing a VLAN/MPLS label)."""
    tag: int


@dataclass(frozen=True)
class PopTag:
    """Remove the label."""


# ------------------------------------------------------------ flow entries
_order = itertools.count()


@dataclass
class FlowEntry:
    match: Match
    actions: tuple
    priority: int = 100
    cookie: int = 0
    packets: int = 0  # counter
    order: int = field(default_factory=lambda: next(_order))

    def __str__(self) -> str:
        acts = ", ".join(map(repr, self.actions))
        return f"prio={self.priority:<5} match[{self.match}] -> {acts}  (pkts={self.packets})"


class FlowTable:
    """A single OpenFlow table.

    Lookup returns the matching entry with the highest priority (ties: the
    one installed first). Entries are indexed by destination so lookups stay
    fast even with many rules.
    """

    def __init__(self) -> None:
        self._by_dst: dict[Any, list[FlowEntry]] = {}
        self.misses = 0

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_dst.values())

    def __iter__(self):
        entries = [e for v in self._by_dst.values() for e in v]
        return iter(sorted(entries, key=lambda e: (-e.priority, e.order)))

    def add(self, entry: FlowEntry) -> None:
        """Add a rule. An existing rule with identical match+priority is replaced."""
        bucket = self._by_dst.setdefault(entry.match.dst, [])
        for i, e in enumerate(bucket):
            if e.match == entry.match and e.priority == entry.priority:
                entry.order = e.order
                bucket[i] = entry
                return
        bucket.append(entry)
        bucket.sort(key=lambda e: (-e.priority, e.order))

    def delete(self, match: Match | None = None, cookie: int | None = None,
               priority: int | None = None) -> int:
        """Delete rules with this exact match and/or cookie. Returns how many."""
        removed = 0
        for dst in list(self._by_dst):
            keep = []
            for e in self._by_dst[dst]:
                hit = ((match is None or e.match == match)
                       and (cookie is None or e.cookie == cookie)
                       and (priority is None or e.priority == priority))
                if hit:
                    removed += 1
                else:
                    keep.append(e)
            if keep:
                self._by_dst[dst] = keep
            else:
                del self._by_dst[dst]
        return removed

    def lookup(self, pkt: Packet, in_port: int | None) -> FlowEntry | None:
        best = None
        for bucket in (self._by_dst.get(pkt.dst), self._by_dst.get(ANY)):
            if not bucket:
                continue
            for e in bucket:  # sorted by priority, so first hit is best here
                if e.match.matches(pkt, in_port):
                    if best is None or (e.priority, -e.order) > (best.priority, -best.order):
                        best = e
                    break
        if best is None:
            self.misses += 1
        return best


# ---------------------------------------------------------------- messages
@dataclass
class FlowMod:
    """Controller -> switch: add or delete a flow rule."""
    command: str  # "add" | "delete"
    match: Match | None = None
    actions: tuple = ()
    priority: int = 100
    cookie: int = 0


@dataclass
class PacketIn:
    """Switch -> controller: a packet the switch wants the controller to see."""
    switch: str
    in_port: int | None
    packet: Packet


@dataclass
class PacketOut:
    """Controller -> switch: send this packet out of a port."""
    packet: Packet
    port: int
