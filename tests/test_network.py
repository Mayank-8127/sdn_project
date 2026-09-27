import pytest

from ffr import topology as T
from ffr.network import Network
from ffr.openflow import FlowEntry, Match, Output, SetTag, PopTag
from ffr.traffic import TrafficManager


def wire_linear3():
    """h1 - s1 - s2 - s3 - h3 with hand-written rules for h1 -> h3."""
    topo = T.linear(3)
    topo.add_host("h1", "s1")
    topo.add_host("h3", "s3")
    net = Network(topo)
    s1, s2, s3 = (net.switches[n] for n in ("s1", "s2", "s3"))
    s1.table.add(FlowEntry(Match(dst="h3"), (Output(s1.port_to("s2")),)))
    s2.table.add(FlowEntry(Match(dst="h3"), (Output(s2.port_to("s3")),)))
    s3.table.add(FlowEntry(Match(dst="h3"), (Output(s3.port_to("h3")),)))
    return net


def test_ports_are_numbered_from_one():
    net = Network(T.linear(3).add_host_per_switch())
    s2 = net.switches["s2"]
    assert sorted(s2.ports) == [1, 2, 3]
    assert {p.peer for p in s2.ports.values()} == {"s1", "s3", "hs2"}


def test_packet_follows_rules_and_link_delays():
    net = wire_linear3()
    tm = TrafficManager(net)
    f = tm.add_flow("h1", "h3", rate=1000, start=0.0, stop=0.01)
    net.sim.run()
    assert f.sent == 10 and f.received == 10 and f.lost == 0
    assert f.hops[0] == 3  # traversed s1, s2, s3
    # 2 switch links of 1 ms + 2 host links of 10 us
    assert f.delays[0] == pytest.approx(0.002 + 2e-5)


def test_table_miss_drops():
    net = wire_linear3()
    tm = TrafficManager(net)
    f = tm.add_flow("h3", "h1", start=0.0, stop=0.005)  # no rules for h1
    net.sim.run()
    assert f.received == 0
    assert net.switches["s3"].stats["miss"] == 5


def test_link_failure_loses_packets_including_in_flight():
    net = wire_linear3()
    tm = TrafficManager(net)
    f = tm.add_flow("h1", "h3", rate=1000, start=0.0, stop=0.1)
    net.schedule_link_failure(0.0505, "s2", "s3", restore_at=0.0705)
    net.sim.run()
    assert 0 < f.lost < 30
    assert net.link("s2", "s3").dropped == f.lost
    assert f.outage() == pytest.approx(f.lost / 1000)  # one contiguous run


def test_tags():
    topo = T.ring(3)
    topo.add_host("h", "s1")
    topo.add_host("g", "s2")
    net = Network(topo)
    s1, s2, s3 = (net.switches[n] for n in ("s1", "s2", "s3"))
    # Tag at s1, take the long way round via s3, pop the tag at s2.
    s1.table.add(FlowEntry(Match(dst="g"), (SetTag(5), Output(s1.port_to("s3")))))
    s3.table.add(FlowEntry(Match(dst="g", tag=5), (Output(s3.port_to("s2")),)))
    s2.table.add(FlowEntry(Match(dst="g", tag=5), (PopTag(), Output(s2.port_to("g")))))
    tm = TrafficManager(net)
    f = tm.add_flow("h", "g", start=0.0, stop=0.003)
    net.sim.run()
    assert f.received == 3 and f.hops[0] == 3


def test_ttl_stops_forwarding_loops():
    topo = T.ring(3)
    topo.add_host("h", "s1")
    topo.add_host("g", "s2")
    net = Network(topo)
    for a, b in (("s1", "s3"), ("s3", "s2"), ("s2", "s1")):  # a loop for dst g
        sw = net.switches[a]
        sw.table.add(FlowEntry(Match(dst="g"), (Output(sw.port_to(b)),)))
    tm = TrafficManager(net)
    f = tm.add_flow("h", "g", start=0.0, stop=0.001)
    net.sim.run()
    assert f.received == 0
    assert sum(s.stats["ttl"] for s in net.switches.values()) == 1
