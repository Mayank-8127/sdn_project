"""End-to-end: how detection choice changes recovery."""
import pytest

from ffr import topology as T
from ffr.scenario import Scenario


def run(app, detection="los", silent=False, **kw):
    sc = Scenario(T.ring(6).add_host_per_switch(), app=app, weight="hops",
                  net_kw={"detection": detection}, **kw)
    f = sc.flow("hs1", "hs2", start=0.15, stop=0.8)
    sc.fail_link(0.4, "s1", "s2", silent=silent)
    return sc.run(), f


def test_gray_failure_needs_bfd():
    _, f = run("frr-link", "los", silent=True)
    assert f.outage() == float("inf")
    _, f = run("frr-link", "los+bfd", silent=True)
    assert 0.005 <= f.outage() <= 0.013  # ~3 x 3.3 ms


def test_lldp_detection_is_slow_but_works_with_reactive():
    res, f = run("reactive", "none", silent=True, lldp_interval=0.05, lldp_mult=3)
    assert 0.15 <= f.outage() <= 0.3
    assert res.probe_pkts > 0


def test_lldp_does_not_help_fast_failover():
    # FF groups watch *port liveness* in the switch; LLDP only informs the
    # controller, and frr-link does not react to controller events.
    _, f = run("frr-link", "none", silent=True, lldp_interval=0.05)
    assert f.outage() == float("inf")


def crash_ksc(app):
    sc = Scenario(T.abilene().add_host_per_switch(), app=app)
    sc.all_pairs(start=0.15, stop=0.5, hosts=[h for h in sorted(sc.net.hosts) if h != "hKSC"])
    sc.fail_node(0.3, "KSC")
    return sc.run()


def test_switch_crash_needs_node_protection():
    assert crash_ksc("frr-node").broken == 0
    assert crash_ksc("frr-link").broken > 0
    assert crash_ksc("reactive").broken == 0  # slower, but the controller reroutes


def test_probe_overhead_scales_inversely_with_interval():
    counts = []
    for interval in (0.0033, 0.01):
        sc = Scenario(T.ring(6).add_host_per_switch(), app="frr-link",
                      net_kw={"detection": "bfd", "bfd_interval": interval})
        sc.flow("hs1", "hs2", start=0.15, stop=0.8)
        counts.append(sc.run().probe_pkts)
    assert counts[0] == pytest.approx(counts[1] * 0.01 / 0.0033, rel=0.05)
