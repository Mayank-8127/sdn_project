import pytest

from ffr import topology as T


def test_linear_ring_grid_sizes():
    assert len(T.linear(4).links) == 3
    assert len(T.ring(6).links) == 6
    g = T.grid(3, 3)
    assert len(g.switches) == 9 and len(g.links) == 12


def test_research_topologies():
    a = T.abilene()
    assert len(a.switches) == 11 and len(a.links) == 14
    n = T.nsfnet()
    assert len(n.switches) == 14 and len(n.links) == 21
    # Abilene delays come from distances: SNV-LAX is 500 km -> 2.5 ms
    assert a.link("LAX", "SNV").delay == pytest.approx(0.0025)


def test_hosts_and_neighbors():
    t = T.ring(4).add_host_per_switch()
    assert t.hosts["hs1"] == "s1"
    assert sorted(t.neighbors("s1")) == ["s2", "s4"]


def test_validation():
    t = T.linear(2)
    with pytest.raises(ValueError):
        t.add_link("s1", "s2")
    with pytest.raises(ValueError):
        t.add_link("s1", "nope")
    with pytest.raises(KeyError):
        T.get("nope")


def test_srlg_and_risk_priors():
    t = T.abilene()
    t.add_srlg("conduit-1", ("DEN", "KSC"), ("SNV", "DEN"))
    assert {tuple(sorted(l.key)) for l in t.srlg_members("conduit-1")} == {
        ("DEN", "KSC"), ("DEN", "SNV")}
    with pytest.raises(ValueError):
        t.add_srlg("x", ("SEA", "NYC"))
    t.set_length_risk(per_ms=0.01, base=0.001)
    assert t.link("LAX", "HOU").fail_prob == pytest.approx(0.001 + 0.01 * 11)
    assert t.link("IND", "CHI").fail_prob < t.link("LAX", "HOU").fail_prob
