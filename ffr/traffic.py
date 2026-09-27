"""Traffic generation and measurement.

We use constant-bit-rate (CBR) flows: a host sends one packet every
``1/rate`` seconds with an increasing sequence number. On the receiver we
record which sequence numbers arrived and when. From that we compute:

* **lost packets**: sent minus received,
* **outage / recovery time**: the longest run of consecutively lost packets
  times the sending interval. With 1000 packets/s, losing 37 packets in a
  row means a 37 ms outage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .packet import Packet


@dataclass
class FlowStats:
    flow_id: int
    src: str
    dst: str
    rate: float
    sent: int = 0
    received: int = 0
    duplicates: int = 0
    arrivals: list[float] = field(default_factory=list)
    seqs: set[int] = field(default_factory=set)
    hops: list[int] = field(default_factory=list)  # path length per received packet
    delays: list[float] = field(default_factory=list)

    @property
    def lost(self) -> int:
        return self.sent - self.received

    def loss_runs(self) -> list[tuple[int, int]]:
        """Runs of consecutively lost sequence numbers as (first, last)."""
        runs: list[tuple[int, int]] = []
        for seq in range(self.sent):
            if seq in self.seqs:
                continue
            if runs and runs[-1][1] == seq - 1:
                runs[-1] = (runs[-1][0], seq)
            else:
                runs.append((seq, seq))
        return runs

    def outage(self) -> float:
        """Duration of the longest delivery interruption, in seconds.

        Measured on the *sending* side: the longest run of consecutive lost
        packets times the sending interval. With 1000 pkt/s, 37 consecutive
        losses = 37 ms of outage. If the flow is still broken when it stops
        sending, it never recovered and the outage is infinite.
        """
        runs = self.loss_runs()
        if not runs:
            return 0.0
        if runs[-1][1] == self.sent - 1:
            return float("inf")
        return max(b - a + 1 for a, b in runs) / self.rate


class TrafficManager:
    """Creates CBR flows between hosts and collects their statistics."""

    def __init__(self, net):
        self.net = net
        self.sim = net.sim
        self.flows: dict[int, FlowStats] = {}
        self._next_id = 0
        for h in net.hosts.values():
            h.handlers.append(self._on_receive)

    def add_flow(self, src: str, dst: str, rate: float = 1000.0,
                 start: float = 0.1, stop: float = 1.0) -> FlowStats:
        fid = self._next_id
        self._next_id += 1
        st = FlowStats(fid, src, dst, rate)
        self.flows[fid] = st
        host = self.net.hosts[src]
        n = int(round((stop - start) * rate))
        for i in range(n):
            self.sim.at(start + i / rate, self._send, host, st, i)
        return st

    def add_all_pairs(self, rate: float = 1000.0, start: float = 0.1, stop: float = 1.0,
                      hosts: list[str] | None = None) -> list[FlowStats]:
        hosts = hosts or sorted(self.net.hosts)
        return [self.add_flow(a, b, rate, start, stop) for a in hosts for b in hosts if a != b]

    def _send(self, host, st: FlowStats, seq: int) -> None:
        st.sent += 1
        host.send(Packet(st.src, st.dst, flow_id=st.flow_id, seq=seq))

    def _on_receive(self, pkt: Packet) -> None:
        st = self.flows.get(pkt.flow_id)
        if st is None or pkt.kind != "data":
            return
        if pkt.seq in st.seqs:
            st.duplicates += 1
            return
        st.seqs.add(pkt.seq)
        st.received += 1
        st.arrivals.append(self.sim.now)
        st.hops.append(len(pkt.trace))
        st.delays.append(self.sim.now - pkt.created)

    # -- summaries -----------------------------------------------------------
    @property
    def total_sent(self) -> int:
        return sum(f.sent for f in self.flows.values())

    @property
    def total_lost(self) -> int:
        return sum(f.lost for f in self.flows.values())

    def affected(self) -> list[FlowStats]:
        return [f for f in self.flows.values() if f.lost > 0]
