import pytest

from ffr import topology as T
from ffr.protection import coverage, plan_destination
from ffr.routing import Graph
from ffr.scenario import Scenario


@pytest.mark.parametrize("name", ["ring6", "abilene", "nsfnet", "grid3x3"])
@pytest.mark.parametrize("mode", ["link", "node"])
def test_full_single_failure_coverage_on_2_connected_topologies(name, mode):
    g = Graph.from_topology(T.get(name))
    for d in g.nodes:
        plans = plan_destination(g, d, mode)
        assert coverage(plans) == 1.0
        for u, hp in plans.items():
            assert hp.detour[0] == u and hp.detour[-1] == d
            kind, x = hp.protects
            pairs = {frozenset(p) for p in zip(hp.detour, hp.detour[1:])}
            if kind == "link":
                assert x not in pairs
            else:
                assert x not in hp.detour


def test_no_coverage_on_a_line():
    g = Graph.from_topology(T.linear(4))
    assert coverage(plan_destination(g, "s4")) == 0.0


def test_node_mode_falls_back_to_link_next_to_destination():
    g = Graph.from_topology(T.ring(4))
    plans = plan_destination(g, "s1", "node")
    assert plans["s2"].protects == ("link", frozenset({"s1", "s2"}))
    assert plans["s3"].protects[0] == "node"


@pytest.mark.parametrize("a,b", [tuple(sorted(l.key)) for l in T.abilene().links])
def test_every_single_link_failure_recovers_within_detection_plus_flight(a, b):
    sc = Scenario(T.abilene().add_host_per_switch(), app="frr-link")
    sc.all_pairs(rate=1000, start=0.15, stop=0.4)
    sc.fail_link(0.3, a, b)
    res = sc.run()
    link_delay = sc.net.link(a, b).delay
    # los_delay (1 ms) + packets in flight on the cut link + 1 packet granularity
    assert res.max_outage <= 0.001 + link_delay + 0.0011
    assert all(f.outage() != float("inf") for f in sc.tm.flows.values())


def test_frr_reverts_after_repair_and_controller_is_idle():
    sc = Scenario(T.ring(6).add_host_per_switch(), app="frr-link", weight="hops")
    f = sc.flow("hs1", "hs2", start=0.2, stop=0.5)
    sc.fail_link(0.3, "s1", "s2", restore_at=0.4)
    sc.run(until=0.25)
    msgs = sc.ctrl.msgs_sent
    sc.sim.run(0.6)
    assert sc.ctrl.msgs_sent == msgs  # pure data-plane recovery
    assert f.lost <= 3
    assert f.hops[-1] == 2  # back on the primary


def test_detour_through_upstream_switch_does_not_loop():
    # s3 -> s1 traffic normally goes s3 s2 s1. When s2-s1 fails, s2's detour
    # goes back through s3 (upstream). Tagging stops s3 from sending it back.
    sc = Scenario(T.ring(4).add_host_per_switch(), app="frr-link", weight="hops")
    f = sc.flow("hs3", "hs1", start=0.2, stop=0.4)
    sc.fail_link(0.3, "s1", "s2")
    sc.run()
    assert f.outage() < 0.005
    assert sum(s.stats["ttl"] for s in sc.net.switches.values()) == 0


def isolate_ksc(app):
    sc = Scenario(T.abilene().add_host_per_switch(), app=app)
    hosts = [h for h in sc.net.hosts if h != "hKSC"]
    sc.all_pairs(rate=1000, start=0.15, stop=0.5, hosts=hosts)
    for n in ("DEN", "HOU", "IND"):
        sc.fail_link(0.3, "KSC", n)
    sc.run()
    return [f for f in sc.tm.flows.values() if f.outage() == float("inf")]


def test_node_protection_survives_switch_isolation_link_protection_does_not():
    assert isolate_ksc("frr-node") == []
    assert len(isolate_ksc("frr-link")) > 0
