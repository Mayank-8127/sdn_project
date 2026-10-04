from ffr import topology as T
from ffr.network import Network
from ffr.openflow import (ALL, FAST_FAILOVER, Bucket, FlowEntry, Group, GroupEntry,
                          Match, Output)
from ffr.traffic import TrafficManager


def triangle():
    """h at s1, g at s2; s1 can reach s2 directly or via s3."""
    topo = T.ring(3)
    topo.add_host("h", "s1")
    topo.add_host("g", "s2")
    net = Network(topo, los_delay=0.001)
    s1, s2, s3 = (net.switches[n] for n in ("s1", "s2", "s3"))
    direct, via = s1.port_to("s2"), s1.port_to("s3")
    s1.groups[1] = GroupEntry(1, FAST_FAILOVER, [
        Bucket((Output(direct),), watch_port=direct),
        Bucket((Output(via),), watch_port=via),
    ])
    s1.table.add(FlowEntry(Match(dst="g"), (Group(1),)))
    s3.table.add(FlowEntry(Match(dst="g"), (Output(s3.port_to("s2")),)))
    s2.table.add(FlowEntry(Match(dst="g"), (Output(s2.port_to("g")),)))
    return net


def test_fast_failover_switches_without_controller():
    net = triangle()
    tm = TrafficManager(net)
    f = tm.add_flow("h", "g", start=0.0, stop=0.1)
    net.schedule_link_failure(0.0505, "s1", "s2", restore_at=0.0805)
    net.sim.run()
    g = net.switches["s1"].groups[1]
    assert g.buckets[1].packets > 0  # backup was used
    # only packets sent during the 1 ms detection time (+ in flight) are lost
    assert 1 <= f.lost <= 3
    # revertive: after repair the primary bucket is used again
    assert f.hops[-1] == 2


def test_fast_failover_all_dead_drops():
    net = triangle()
    tm = TrafficManager(net)
    f = tm.add_flow("h", "g", start=0.0, stop=0.05)
    net.schedule_link_failure(0.01, "s1", "s2")
    net.schedule_link_failure(0.01, "s1", "s3")
    net.sim.run()
    assert net.switches["s1"].stats["group_drop"] > 0
    assert f.received < 15


def test_all_group_duplicates():
    net = triangle()
    s1 = net.switches["s1"]
    s1.groups[2] = GroupEntry(2, ALL, [Bucket((Output(s1.port_to("s2")),)),
                                       Bucket((Output(s1.port_to("s3")),))])
    s1.table.add(FlowEntry(Match(dst="g"), (Group(2),), priority=200))
    tm = TrafficManager(net)
    f = tm.add_flow("h", "g", start=0.0, stop=0.01)
    net.sim.run()
    assert f.received == 10 and f.duplicates == 10
