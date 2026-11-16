import pytest

from ffr import topology as T
from ffr.scenario import Scenario


def abilene_srlg():
    t = T.abilene().add_host_per_switch()
    t.add_srlg("duct", ("DEN", "KSC"), ("SNV", "DEN"))
    return t


def run(app, setup, topo=abilene_srlg, **kw):
    sc = Scenario(topo(), app=app, **kw)
    sc.all_pairs(start=0.2, stop=1.0)
    setup(sc)
    return sc, sc.run()


def srlg_cut(sc):
    sc.fail_link(0.4, "DEN", "KSC")
    sc.fail_link(0.4, "SNV", "DEN")


def test_srlg_double_failure_survived_only_with_risk_disjoint_backups():
    _, plain = run("frr-node", srlg_cut)
    _, fa = run("fa-frr", srlg_cut)
    assert plain.broken > 0
    assert fa.broken == 0
    # LOS + packets in flight on the two cut links (4.5 ms and 7.5 ms)
    assert fa.max_outage <= 0.014


def test_srlg_awareness_is_what_makes_the_difference():
    _, no_srlg = run("fa-frr", srlg_cut, srlg_aware=False, reoptimize=False)
    assert no_srlg.broken > 0


def test_second_failure_is_protected_after_reoptimisation():
    def two(sc):
        sc.fail_link(0.4, "DEN", "KSC")
        sc.fail_link(0.6, "KSC", "HOU")  # lies on DEN-KSC detours
    _, plain = run("frr-node", two)
    sc, fa = run("fa-frr", two)
    _, no_reopt = run("fa-frr", two, reoptimize=False)
    assert plain.broken > 0 and no_reopt.broken > 0
    assert fa.broken == 0 and fa.max_outage < 0.01
    assert sc.ctrl.reoptimizations == 3  # initial + one per failure


def flapping(sc):
    for i in range(5):
        sc.fail_link(0.4 + 0.08 * i, "DEN", "KSC", restore_at=0.44 + 0.08 * i)


def test_flap_damping_avoids_repeated_outages():
    _, plain = run("frr-node", flapping)
    _, fa = run("fa-frr", flapping, holddown=0.2)
    assert fa.lost < plain.lost / 3


@pytest.mark.parametrize("risk_aware", [False, True])
def test_flapping_link_returns_only_after_growing_hold_down(risk_aware):
    sc = Scenario(abilene_srlg(), app="fa-frr", holddown=0.2, half_life=5.0,
                  risk_aware=risk_aware)
    f = sc.flow("hDEN", "hKSC", start=0.2, stop=3.0)
    flapping(sc)
    sc.run()
    released = [t for t, text in sc.ctrl.log if "back in service" in text]
    assert len(released) == 1
    # after 5 failures the hold-down is ~0.2 * (1 + 5) s, counted from the
    # last repair at 0.76 s
    assert 1.8 < released[0] < 2.0
    # initial + first failure + release; with risk-aware routing each later
    # flap (during hold-down) also re-plans, because it makes the link's SRLG
    # peer SNV-DEN riskier and that peer carries traffic
    assert sc.ctrl.reoptimizations == (3 + 4 if risk_aware else 3)
    if risk_aware:
        assert f.hops[-1] == 6  # still distrusted: its learned risk is high
    else:
        assert f.hops[-1] == 2  # back on the direct link


def test_risk_aware_primary_avoids_unreliable_link():
    def topo():
        t = T.ring(6).add_host_per_switch()
        t.link("s1", "s2").fail_prob = 0.5
        return t
    for risk_aware, hops in ((False, 2), (True, 6)):
        sc = Scenario(topo(), app="fa-frr", risk_aware=risk_aware, lam=10.0)
        f = sc.flow("hs1", "hs2", start=0.2, stop=0.3)
        sc.run()
        assert f.hops[-1] == hops


def test_reoptimisation_is_hitless():
    # the make-before-break update must not lose a single extra packet
    def cut(sc):
        sc.fail_link(0.4, "DEN", "KSC")
    _, plain = run("frr-node", cut)
    sc, fa = run("fa-frr", cut)
    assert fa.lost == plain.lost
    assert sum(s.stats["ttl"] + s.stats["miss"] for s in sc.net.switches.values()) == 0


def test_failures_feed_the_risk_model():
    sc, _ = run("fa-frr", flapping)
    from ffr.routing import edge
    risk = sc.ctrl.risk
    assert risk.failures[edge("DEN", "KSC")] == 5
    assert risk.p(edge("DEN", "KSC"), sc.sim.now) > risk.p(edge("SNV", "DEN"), sc.sim.now) > 0
