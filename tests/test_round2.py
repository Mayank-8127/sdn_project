"""Exact SRLG-disjoint pairs, tag recycling, hold-down overrides, the
coincidence window and the OpenFlow 1.3 U-turn messages."""

import itertools

import pytest

from ffr import topology as T
from ffr.apps.e2e import SrlgPathProtection
from ffr.experiments.runner import Case, run_case
from ffr.network import Network
from ffr.risk import RiskModel
from ffr.routing import Graph, edge, k_shortest_paths, path_cost, path_edges, shortest_path
from ffr.scenario import Scenario


def cut(a, b, t=0.45, restore=None):
    return ("link", a, b, t, restore, False)


def all_simple_paths(g, s, t, path=None):
    path = path or [s]
    if path[-1] == t:
        yield list(path)
        return
    for n in sorted(g.adj[path[-1]]):
        if n not in path:
            yield from all_simple_paths(g, s, t, path + [n])


def test_k_shortest_paths_in_cost_order_and_complete():
    g = Graph.from_topology(T.abilene())
    yen = list(k_shortest_paths(g, "SEA", "ATL"))
    brute = sorted(all_simple_paths(g, "SEA", "ATL"), key=lambda p: path_cost(g, p))
    assert len(yen) == len(brute) == len({tuple(p) for p in yen})
    assert [round(path_cost(g, p), 12) for p in yen] == \
        [round(path_cost(g, p), 12) for p in brute]


def test_e2e_srlg_pair_is_optimal():
    topo = T.abilene()
    topo.add_srlg("duct", ("DEN", "KSC"), ("SNV", "DEN"))
    net = Network(topo.add_host_per_switch())
    app = SrlgPathProtection(net)
    g, risk = app.graph, app._risk
    for s, t in [("SEA", "KSC"), ("SNV", "IND"), ("SEA", "HOU")]:
        p1, p2 = app._srlg_backup(*__import__("ffr.routing", fromlist=["x"]).disjoint_paths(
            g, s, t, node_disjoint=True))
        # brute force over all node- and SRLG-disjoint pairs
        best = None
        paths = list(all_simple_paths(g, s, t))
        for a, b in itertools.permutations(paths, 2):
            ea, eb = set(path_edges(a)), set(path_edges(b))
            risky = set().union(*(risk.shared_risk(e) for e in ea)) | ea
            if eb & risky or set(a[1:-1]) & set(b[1:-1]):
                continue
            c = path_cost(g, a) + path_cost(g, b)
            best = c if best is None else min(best, c)
        assert path_cost(g, p1) + path_cost(g, p2) == pytest.approx(best)


def test_tags_are_recycled():
    # 20 flaps without hold-down: about 40 generations, but tags stay bounded
    sc = Scenario(T.abilene().add_host_per_switch(), app="fa-frr", holddown=0.0)
    sc.all_pairs(rate=10, start=0.3, stop=9.0)
    for i in range(20):
        sc.fail_link(0.5 + 0.4 * i, "DEN", "KSC", 0.7 + 0.4 * i)
    sc.run()
    assert sc.ctrl.generation > 30
    live = len(sc.ctrl.tags)
    assert sc.ctrl.tags_peak <= 3 * live           # a few generations at most
    assert max(sc.ctrl.tags.values()) <= sc.ctrl.tags_peak


def test_link_that_restores_reachability_skips_hold_down():
    # a linear chain: cutting s2-s3 partitions it, so its return must not wait
    sc = Scenario(T.linear(4).add_host_per_switch(), app="fa-frr", holddown=1.0)
    sc.all_pairs(rate=100, start=0.2, stop=1.0)
    sc.fail_link(0.4, "s2", "s3", 0.5)
    res = sc.run()
    assert sc.ctrl.holddown_skipped == 1
    assert res.broken == 0  # every flow recovered well before the end


def test_override_releases_only_what_is_needed():
    sc = Scenario(T.ring(6).add_host_per_switch(), app="fa-frr", holddown=0.5)
    sc.all_pairs(rate=100, start=0.25, stop=1.2)
    sc.fail_link(0.40, "s1", "s2", 0.45)
    sc.fail_link(0.41, "s4", "s5", 0.46)
    sc.fail_link(0.60, "s3", "s4")   # cuts the ring: one held link suffices
    res = sc.run()
    assert sc.ctrl.holddown_overrides == 1
    assert res.broken == 0


@pytest.mark.parametrize("window,expected", [(0.05, 0.3), (0.0, 0.45)])
def test_coincidence_window(window, expected):
    t = T.from_edges("t", [("a", "b"), ("b", "c"), ("c", "a")])
    t.add_srlg("duct", ("a", "b"), ("b", "c"))
    m = RiskModel(t, half_life=1e9, coincidence=window)
    e1, e2 = edge("a", "b"), edge("b", "c")
    m.record_failure(e1, 1.0, down={e1})
    m.record_failure(e2, 1.0, down={e1, e2})
    assert m.penalty(e2, 1.0) == pytest.approx(expected)  # (1+rho)*delta without the window


def test_of13_inport_messages_add_state_not_loss():
    rows = [run_case(Case("abilene", "fa-frr", [cut("DEN", "KSC")],
                          app_kw={"of13_inport": of})) for of in (False, True)]
    assert rows[0]["lost"] == rows[1]["lost"]
    assert rows[1]["reprotect_ms"] > rows[0]["reprotect_ms"]
    # one extra group per protected (switch, destination); stale ones are deleted
    sc = Scenario(T.abilene().add_host_per_switch(), app="fa-frr", of13_inport=True)
    sc.all_pairs(rate=50, start=0.25, stop=0.8)
    sc.fail_link(0.45, "DEN", "KSC")
    sc.run()
    protected = sum(hp.protected for plans in sc.ctrl.plans.values() for hp in plans.values())
    groups = sum(len(s.groups) for s in sc.net.switches.values())
    assert groups == 110 + protected
    assert protected < 110 == rows[0]["group_entries"]  # some pairs lost their backup


def test_flows_hit_by_the_last_failure():
    srlg = [("duct", [("DEN", "KSC"), ("HOU", "KSC")])]
    fails = [cut("DEN", "KSC"), cut("HOU", "KSC", t=0.65)]
    blind = run_case(Case("abilene", "fa-frr", fails, srlgs=srlg, app_kw={"lam": 0.0}, stop=1.0))
    aware = run_case(Case("abilene", "fa-frr", fails, srlgs=srlg, app_kw={"lam": 20.0}, stop=1.0))
    assert blind["flows_hit_last"] > aware["flows_hit_last"]
