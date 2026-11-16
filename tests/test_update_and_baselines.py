"""Loop-free updates, correlated penalties, hold-down fallback and the
SRLG-aware baselines."""

import pytest

from ffr import topology as T
from ffr.experiments.runner import Case, run_case
from ffr.experiments.suite import srlg_pairs
from ffr.risk import RiskModel
from ffr.routing import edge
from ffr.scenario import Scenario


def cut(a, b, t=0.45, restore=None):
    return ("link", a, b, t, restore, False)


# ----------------------------------------------------------- loop-free update
@pytest.mark.parametrize("topo,a,b", [("ring6", "s1", "s2"), ("grid3x3", "s0_0", "s0_1")])
def test_unordered_update_loops_ordered_does_not(topo, a, b):
    unordered = run_case(Case(topo, "fa-frr", [cut(a, b)], app_kw={"ordered_update": False},
                              stop=1.0))
    ordered = run_case(Case(topo, "fa-frr", [cut(a, b)], stop=1.0))
    assert unordered["looped_pkts"] > 0
    assert ordered["looped_pkts"] == 0
    # ordering changes when the network is re-protected, not the loss of the failure
    assert ordered["lost"] == unordered["lost"]


def test_ordered_update_is_loop_free_under_jitter():
    for l in T.get("ring6").links:
        a, b = sorted(l.key)
        row = run_case(Case("ring6", "fa-frr", [cut(a, b, restore=0.65)],
                            app_kw={"holddown": 0.05, "ctrl_jitter": 0.02, "jitter_seed": 3},
                            stop=1.0))
        assert row["looped_pkts"] == 0 and row["never_recovered"] == 0


def test_loop_detector_ignores_frr_u_turns():
    row = run_case(Case("ring6", "frr-link", [cut("s1", "s2")], stop=1.0))
    assert row["affected"] > 0 and row["looped_pkts"] == 0


def test_jitter_keeps_per_switch_order():
    sc = Scenario(T.ring(6).add_host_per_switch(), app="frr-node", ctrl_jitter=0.01)
    sc.all_pairs(rate=100, start=0.3, stop=0.5)
    res = sc.run()
    assert res.lost == 0  # rules arrived in order and everything was installed


# -------------------------------------------------------- correlated penalties
def duct_model(**kw):
    t = T.from_edges("t", [("a", "b"), ("b", "c"), ("c", "d"), ("d", "a")])
    t.add_srlg("duct", ("a", "b"), ("b", "c"), ("c", "d"))
    return RiskModel(t, **kw)


def test_simultaneous_srlg_failure_counts_as_one_event():
    m = duct_model(flap_penalty=0.3, correlation=0.5, half_life=1e9)
    e1, e2, e3 = edge("a", "b"), edge("b", "c"), edge("c", "d")
    m.record_failure(e1, 1.0, down={e1})
    m.record_failure(e2, 1.0, down={e1, e2})
    # each failed link is charged once, not (1 + rho) times
    assert m.penalty(e1, 1.0) == pytest.approx(0.3)
    assert m.penalty(e2, 1.0) == pytest.approx(0.3)
    # the surviving peer gets the correlated share once, not once per failed peer
    assert m.penalty(e3, 1.0) == pytest.approx(0.15)


def test_separate_events_still_accumulate():
    m = duct_model(flap_penalty=0.3, correlation=0.5, half_life=1e9)
    e1, e3 = edge("a", "b"), edge("c", "d")
    m.record_failure(e1, 1.0)
    m.record_failure(e1, 5.0)
    assert m.penalty(e1, 5.0) == pytest.approx(0.6)
    assert m.penalty(e3, 5.0) == pytest.approx(0.3)


def test_p_max_must_be_below_one():
    with pytest.raises(ValueError):
        duct_model(p_max=1.0)


# ----------------------------------------------------------- hold-down fallback
def test_held_link_is_released_when_needed_for_reachability():
    # ring: s1-s2 flaps and is held down; then s3-s4 fails, which would cut
    # the ring in two without s1-s2
    sc = Scenario(T.ring(6).add_host_per_switch(), app="fa-frr", holddown=0.5)
    sc.all_pairs(rate=500, start=0.25, stop=1.2)
    sc.fail_link(0.4, "s1", "s2", 0.45)
    sc.fail_link(0.6, "s3", "s4")
    res = sc.run()
    assert sc.ctrl.holddown_overrides >= 1
    assert res.broken == 0


# ----------------------------------------------------------- SRLG-aware baselines
def test_srlg_aware_baselines_survive_duct_cuts():
    survived = {"frr-node": 0, "frr-srlg": 0, "e2e": 0, "e2e-srlg": 0}
    pairs = srlg_pairs("abilene", 6)
    for l1, l2 in pairs:
        for app in survived:
            row = run_case(Case("abilene", app, [cut(*l1), cut(*l2)], srlgs=[("duct", [l1, l2])]))
            survived[app] += row["never_recovered"] == 0
    assert survived["frr-srlg"] == len(pairs) > survived["frr-node"]
    assert survived["e2e-srlg"] >= survived["e2e"]


def test_variant_name_is_reported():
    row = run_case(Case("ring6", "fa-frr", [cut("s1", "s2")], app_kw={"srlg_aware": False},
                        name="fa-frr-nosrlg", stop=0.8))
    assert row["app"] == "fa-frr-nosrlg"
    assert row["peak_flow_entries"] >= row["flow_entries"]
