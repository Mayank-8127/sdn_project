from ffr import topology as T
from ffr.scenario import Scenario


def test_static_routing_delivers_everything_without_failures():
    sc = Scenario(T.abilene().add_host_per_switch(), app="static")
    sc.all_pairs(rate=200, start=0.1, stop=0.3)
    res = sc.run()
    assert res.flows == 110
    assert res.lost == 0
    # one rule per (switch, host)
    assert res.flow_entries == 11 * 11


def test_packets_follow_shortest_delay_path():
    sc = Scenario(T.abilene().add_host_per_switch(), app="static")
    f = sc.flow("hSEA", "hNYC", start=0.1, stop=0.12)
    sc.run()
    # SEA-DEN-KSC-IND-CHI-NYC is the minimum-distance path
    assert f.received == 20
    assert f.hops[0] == 6


def test_static_never_recovers():
    sc = Scenario(T.ring(4).add_host_per_switch(), app="static", weight="hops")
    f = sc.flow("hs1", "hs2", start=0.1, stop=0.5)
    other = sc.flow("hs3", "hs4", start=0.1, stop=0.5)
    sc.fail_link(0.3, "s1", "s2")
    res = sc.run()
    assert 200 <= f.lost <= 202  # everything after the failure (+ in flight)
    assert other.lost == 0  # flows not using the link are untouched
    assert res.affected >= 1
    assert res.max_outage == float("inf")


def test_rules_arrive_after_control_delay():
    sc = Scenario(T.linear(2).add_host_per_switch(), app="static", ctrl_delay=0.05)
    early = sc.flow("hs1", "hs2", start=0.0, stop=0.04)  # before rules exist
    sc.run()
    assert early.received == 0
