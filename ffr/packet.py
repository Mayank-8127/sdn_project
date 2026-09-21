"""The packet model.

A real packet has many header fields (Ethernet MACs, IP addresses, ports...).
We keep only what our switches look at:

* ``src`` / ``dst``: names of the sending / receiving host (think of them as
  addresses),
* ``tag``: an extra label the network itself may push onto a packet (like a
  VLAN id or MPLS label). ``None`` means untagged. Used for detours later.
* ``ttl``: time-to-live, decremented at each switch; a packet whose TTL hits
  zero is dropped. This stops packets from looping forever.

Everything else (``flow_id``, ``seq``, ``created``) is bookkeeping used to
measure loss and delay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_TTL = 64


@dataclass
class Packet:
    src: str
    dst: str
    flow_id: int | None = None
    seq: int = 0
    kind: str = "data"
    tag: int | None = None
    ttl: int = DEFAULT_TTL
    created: float = 0.0
    payload: Any = None
    trace: list[str] = field(default_factory=list)

    def copy(self) -> "Packet":
        """Independent copy (used when one packet is sent out of several ports)."""
        return Packet(
            self.src, self.dst, self.flow_id, self.seq, self.kind, self.tag,
            self.ttl, self.created, self.payload, list(self.trace),
        )
