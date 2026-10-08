import pytest

from ffr import topology as T
from ffr.scenario import Scenario


def ring_scenario(**kw):
    sc = Scenario(T.ring(6).add_host_per_switch(), app="reactive", weight="hops", **kw)
    f = sc.flow("hs1", "hs2", start=0.1, stop=0.5)
    return sc, f


def test_reactive_recovers_and_outage_matches_model():
    sc, f = ring_scenario(ctrl_delay=0.005, compute_time=0.005)
    sc.fail_link(0.3, "s1", "s2")
    res = sc.run()
    assert f.received > 0 and f.outage() != float("inf")
    # detection 1 + up 5 + compute 5 + down 5 + a few rule installs (1 ms each)
    assert 0.016 <= f.outage() <= 0.026
    # after recovery the packets go the long way round: s1 s6 s5 s4 s3 s2
    assert f.hops[-1] == 6
    assert res.lost == f.lost


def test_outage_grows_with_controller_distance():
    outs = []
    for d in (0.001, 0.01, 0.05):
        sc, f = ring_scenario(ctrl_delay=d)
        sc.fail_link(0.3, "s1", "s2")
        sc.run()
        outs.append(f.outage())
    assert outs[0] < outs[1] < outs[2]
    assert outs[2] > 0.1  # 2 x 50 ms of control-channel delay alone


def test_traffic_moves_back_after_repair():
    sc, f = ring_scenario()
    sc.fail_link(0.2, "s1", "s2", restore_at=0.3)
    sc.run()
    assert f.hops[-1] == 2  # back on the direct link
    assert sc.ctrl.recomputations == 3  # initial + failure + repair


def test_unreachable_destination_rules_are_removed():
    sc = Scenario(T.linear(3).add_host_per_switch(), app="reactive")
    sc.flow("hs1", "hs3", start=0.1, stop=0.2)
    sc.fail_link(0.15, "s2", "s3")
    sc.run()
    s1 = sc.net.switches["s1"]
    assert all(e.match.dst != "hs3" for e in s1.table)
