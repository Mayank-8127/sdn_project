import pytest

from ffr import topology as T
from ffr.scenario import Scenario


def ring_run(**fail):
    sc = Scenario(T.ring(6).add_host_per_switch(), app="e2e", weight="hops")
    f = sc.flow("hs1", "hs3", start=0.15, stop=0.6)  # primary s1 s2 s3
    if fail.get("node"):
        sc.fail_node(0.3, fail["node"])
    else:
        sc.fail_link(0.3, *fail["link"], silent=fail.get("silent", False))
    sc.run()
    return sc, f


def test_ingress_switches_to_disjoint_backup_on_remote_failure():
    sc, f = ring_run(link=("s2", "s3"))
    assert f.outage() < 0.02
    assert f.hops[-1] == 5  # s1 s6 s5 s4 s3
    assert sc.ctrl.paths[("s1", "s3")] == (["s1", "s2", "s3"], ["s1", "s6", "s5", "s4", "s3"])


def test_gray_failures_and_crashes_are_detected_by_path_bfd():
    _, f = ring_run(link=("s2", "s3"), silent=True)
    assert f.outage() < 0.02
    _, f = ring_run(node="s2")
    assert f.outage() < 0.02


def test_first_hop_failure_without_los_still_costs_bfd_timeout():
    sc = Scenario(T.ring(6).add_host_per_switch(), app="e2e", weight="hops",
                  net_kw={"detection": "none"})
    f = sc.flow("hs1", "hs3", start=0.15, stop=0.6)
    sc.fail_link(0.3, "s1", "s2")
    sc.run()
    # without LOS even a failure on the ingress's own link costs the timeout
    assert 0.006 <= f.outage() <= 0.015


def test_every_abilene_link_failure_is_survived():
    for l in T.abilene().links:
        sc = Scenario(T.abilene().add_host_per_switch(), app="e2e")
        sc.all_pairs(rate=500, start=0.15, stop=0.4)
        sc.fail_link(0.3, l.a, l.b)
        res = sc.run()
        assert res.broken == 0, (l.a, l.b)
        # BFD timeout (~10 ms) + failure-to-ingress delay (up to ~25 ms coast
        # to coast) + packets in flight
        assert res.max_outage <= 0.06


def test_probe_overhead_grows_with_switch_pairs():
    sc = Scenario(T.abilene().add_host_per_switch(), app="e2e")
    sc.flow("hSEA", "hNYC", start=0.1, stop=0.2)
    res = sc.run()
    # 110 sessions (ordered pairs), 2 ends, 0.3 s at 3.3 ms
    assert res.probe_pkts == pytest.approx(110 * 2 * 0.3 / 0.0033, rel=0.05)
