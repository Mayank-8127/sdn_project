"""The experiment suite: every comparison in the final report.

Each experiment returns an :class:`Experiment` holding raw rows (one per
simulation run) and an aggregated summary table. ``quick=True`` shrinks the
sweeps so the whole suite runs in about a minute (used by tests and CI).
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

from .. import topology as T
from ..risk import RiskModel
from ..routing import Graph, edge, next_hops_to, shortest_path
from ..scenario import Scenario
from .runner import Case, run_cases

APPS = ["static", "reactive", "frr-link", "frr-node", "e2e", "fa-frr"]
T_FAIL = 0.45


@dataclass
class Experiment:
    name: str
    title: str
    question: str
    rows: list[dict]
    summary: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------- helpers
def links_of(topo_name: str) -> list[tuple[str, str]]:
    return [tuple(sorted(l.key)) for l in T.get(topo_name).links]


def sample(items, k, seed=7):
    items = list(items)
    if k is None or k >= len(items):
        return items
    return random.Random(seed).sample(items, k)


def connected_without(topo_name: str, edges=(), nodes=()) -> bool:
    g = Graph.from_topology(T.get(topo_name))
    alive = [n for n in g.nodes if n not in nodes]
    for n in alive[1:]:
        if shortest_path(g, alive[0], n, excluded_edges=edges, excluded_nodes=nodes) is None:
            return False
    return True


def link_fail(a, b, t=T_FAIL, restore=None, silent=False):
    return ("link", a, b, t, restore, silent)


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else "n/a"


def _max(values):
    vals = [v for v in values if v is not None]
    return round(max(vals), 2) if vals else "n/a"


def aggregate(rows, by=("topo", "app")) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(tuple(r[k] for k in by), []).append(r)
    out = []
    for key, rs in groups.items():
        n = len(rs)
        out.append({
            **dict(zip(by, key)),
            "runs": n,
            "survival_pct": round(100.0 * sum(r["never_recovered"] == 0 for r in rs) / n, 1),
            "dead_flows": round(sum(r["never_recovered"] for r in rs) / n, 2),
            "lost_pkts": round(sum(r["lost"] for r in rs) / n, 1),
            "mean_outage_ms": _mean(r["mean_outage_ms"] for r in rs),
            "max_outage_ms": _max(r["max_outage_ms"] for r in rs),
            "stretch": round(sum(r["stretch"] for r in rs) / n, 3),
            "flow_entries": round(sum(r["flow_entries"] for r in rs) / n),
            "groups": round(sum(r["group_entries"] for r in rs) / n),
            "ctrl_msgs": round(sum(r["ctrl_msgs"] for r in rs) / n),
            "probe_pkts": round(sum(r["probe_pkts"] for r in rs) / n),
        })
    return out


# ------------------------------------------------------------- experiments
def exp_single_link(quick=False, workers=None) -> Experiment:
    topos = ["abilene"] if quick else ["abilene", "nsfnet"]
    cases = [Case(t, app, [link_fail(a, b)], labels={"failure": f"{a}-{b}"})
             for t in topos for app in APPS
             for a, b in sample(links_of(t), 4 if quick else None)]
    rows = run_cases(cases, workers)
    return Experiment(
        "single_link", "Single link failures",
        "Every link is cut once (LOS detection). How much traffic does each strategy lose, "
        "how long are outages, how good are paths afterwards and what does it cost?",
        rows, aggregate(rows))


def exp_node_crash(quick=False, workers=None) -> Experiment:
    topos = ["abilene"] if quick else ["abilene", "nsfnet"]
    cases = []
    for t in topos:
        for n in sample(T.get(t).switches, 3 if quick else None):
            if not connected_without(t, nodes=[n]):
                continue
            for app in APPS:
                cases.append(Case(t, app, [("node", n, T_FAIL)], exclude_hosts=[f"h{n}"],
                                  labels={"failure": n}))
    rows = run_cases(cases, workers)
    return Experiment(
        "node_crash", "Switch crashes",
        "Each switch crashes once (flows to/from it are excluded). Link protection's "
        "detours may run through the crashed switch; node protection's may not.",
        rows, aggregate(rows))


GRAY_CONFIGS = [
    ("reactive + LLDP 50ms", "reactive", {"detection": "none"}, {"lldp_interval": 0.05}),
    ("frr-node + LOS", "frr-node", {"detection": "los"}, {}),
    ("frr-node + BFD", "frr-node", {"detection": "los+bfd"}, {}),
    ("e2e (path BFD)", "e2e", {"detection": "los"}, {}),
    ("fa-frr + BFD", "fa-frr", {"detection": "los+bfd"}, {}),
]


def exp_gray(quick=False, workers=None) -> Experiment:
    cases = [Case("abilene", app, [link_fail(a, b, silent=True)], net_kw=nk, app_kw=ak,
                  stop=1.0, labels={"config": label, "failure": f"{a}-{b}"})
             for label, app, nk, ak in GRAY_CONFIGS
             for a, b in sample(links_of("abilene"), 4 if quick else None)]
    rows = run_cases(cases, workers)
    return Experiment(
        "gray", "Gray (silent) failures",
        "Links fail silently: the signal stays up but every packet is dropped. "
        "Which detection mechanisms notice, and how fast?",
        rows, aggregate(rows, by=("config",)))


BFD_INTERVALS_MS = [1, 2, 3.3, 5, 10, 20, 50]


def exp_bfd_tradeoff(quick=False, workers=None) -> Experiment:
    intervals = [1, 3.3, 10, 50] if quick else BFD_INTERVALS_MS
    cases = [Case("abilene", "fa-frr", [link_fail(a, b, silent=True)],
                  net_kw={"detection": "los+bfd", "bfd_interval": ms / 1000},
                  stop=1.0, labels={"bfd_interval_ms": ms, "failure": f"{a}-{b}"})
             for ms in intervals for a, b in sample(links_of("abilene"), 3 if quick else 8)]
    rows = run_cases(cases, workers)
    summary = []
    links = len(T.get("abilene").links)
    for ms in intervals:
        rs = [r for r in rows if r["bfd_interval_ms"] == ms]
        summary.append({
            "bfd_interval_ms": ms,
            "detect_time_ms": round(3 * ms, 1),
            "mean_outage_ms": _mean(r["mean_outage_ms"] for r in rs),
            "lost_pkts": round(sum(r["lost"] for r in rs) / len(rs), 1),
            "bfd_pkts_per_s_per_link": round(2 * 1000 / ms),
            "bfd_pkts_per_s_network": round(2 * 1000 / ms * links),
        })
    return Experiment(
        "bfd_tradeoff", "BFD interval trade-off",
        "Gray failures detected by BFD (detect multiplier 3). Shorter intervals detect faster "
        "but send more hello packets.",
        rows, summary)


def srlg_pairs(topo_name: str, k: int | None, seed: int = 3):
    """Pairs of links meeting at a switch (e.g. sharing a building or duct)
    whose joint failure leaves the network connected."""
    topo = T.get(topo_name)
    pairs = []
    for n in topo.switches:
        inc = sorted(tuple(sorted((n, m))) for m in topo.neighbors(n))
        for l1, l2 in itertools.combinations(inc, 2):
            if connected_without(topo_name, edges=[frozenset(l1), frozenset(l2)]):
                pairs.append((l1, l2))
    return sample(pairs, k, seed)


SRLG_APPS = ["reactive", "frr-node", "e2e", "fa-frr"]


def exp_srlg(quick=False, workers=None) -> Experiment:
    topos = ["abilene"] if quick else ["abilene", "nsfnet"]
    cases = []
    for t in topos:
        for l1, l2 in srlg_pairs(t, 4 if quick else 15):
            for app in SRLG_APPS:
                cases.append(Case(t, app, [link_fail(*l1), link_fail(*l2)],
                                  srlgs=[("duct", [l1, l2])],
                                  labels={"failure": f"{'-'.join(l1)}+{'-'.join(l2)}"}))
    rows = run_cases(cases, workers)
    return Experiment(
        "srlg", "Correlated (SRLG) double failures",
        "Two links that share a risk group (declared in the topology) fail at the same "
        "instant.", rows, aggregate(rows))


def exp_sequential(quick=False, workers=None) -> Experiment:
    topos = ["abilene"] if quick else ["abilene", "nsfnet"]
    cases = []
    for t in topos:
        pairs = [(l1, l2) for l1, l2 in itertools.permutations(links_of(t), 2)
                 if connected_without(t, edges=[frozenset(l1), frozenset(l2)])]
        for l1, l2 in sample(pairs, 4 if quick else 20, seed=11):
            for app in SRLG_APPS:
                cases.append(Case(t, app, [link_fail(*l1), link_fail(*l2, t=T_FAIL + 0.2)],
                                  stop=1.0,
                                  labels={"failure": f"{'-'.join(l1)} then {'-'.join(l2)}"}))
    rows = run_cases(cases, workers)
    return Experiment(
        "sequential", "Sequential double failures",
        "A second, independent link fails 200 ms after the first. Is the network still "
        "protected after the first failure?", rows, aggregate(rows))


def exp_flapping(quick=False, workers=None) -> Experiment:
    def flaps(a, b):
        return [link_fail(a, b, T_FAIL + 0.08 * i, T_FAIL + 0.04 + 0.08 * i) for i in range(5)]
    cases = [Case("abilene", app, flaps(a, b), stop=1.1, labels={"failure": f"{a}-{b}"})
             for app in ["reactive", "frr-node", "fa-frr"]
             for a, b in sample(links_of("abilene"), 4 if quick else None)]
    rows = run_cases(cases, workers)
    return Experiment(
        "flapping", "Flapping links",
        "A link goes down for 40 ms and up for 40 ms, five times in a row.",
        rows, aggregate(rows))


STATE_TOPOS = ["ring6", "grid3x3", "abilene", "nsfnet", "grid4x4", "grid5x5"]


def exp_state(quick=False, workers=None) -> Experiment:
    topos = STATE_TOPOS[:3] if quick else STATE_TOPOS
    cases = [Case(t, app, [], rate=10.0, stop=0.4, labels={"switches": len(T.get(t).switches)})
             for t in topos for app in APPS]
    rows = run_cases(cases, workers)
    summary = [{"topo": r["topo"], "switches": r["switches"], "app": r["app"],
                "flow_entries": r["flow_entries"], "groups": r["group_entries"],
                "ctrl_msgs": r["ctrl_msgs"],
                "probe_pkts_per_s": round(r["probe_pkts"] / (0.4 + 0.1))}
               for r in rows]
    return Experiment(
        "state", "State and control overhead",
        "Flow-table entries, group entries, controller messages at set-up, and monitoring "
        "packets per second (LOS-only detection; e2e includes its path BFD).",
        rows, summary)


def exp_risk_tradeoff(quick=False, workers=None) -> Experiment:
    """Analytic: how risk-aware routing trades latency for reliability."""
    lams = [0, 0.5, 1, 2, 5, 10, 20, 50]
    rows = []
    for t in ["abilene", "nsfnet"]:
        topo = T.get(t)
        # Heterogeneous priors (seeded): most links reliable, a few flaky.
        # (Purely length-based priors would agree with delay, leaving no
        # trade-off to make.)
        rng = random.Random(5)
        for l in topo.links:
            l.fail_prob = rng.choice([0.005, 0.005, 0.01, 0.02, 0.05, 0.15])
        risk = RiskModel(topo)
        g = Graph.from_topology(topo)
        for lam in lams:
            w = lambda u, v: risk.weight(edge(u, v), 0.0, lam)
            delays, fails = [], []
            for d in topo.switches:
                nh = next_hops_to(g, d, weight=w)
                for s in topo.switches:
                    if s == d:
                        continue
                    path = [s]
                    while path[-1] != d:
                        path.append(nh[path[-1]])
                    delays.append(sum(g.weight(a, b) for a, b in zip(path, path[1:])))
                    fails.append(1 - risk.path_survival(path, 0.0))
            rows.append({"topo": t, "lam": lam,
                         "mean_path_delay_ms": round(1000 * sum(delays) / len(delays), 3),
                         "mean_path_fail_prob_pct": round(100 * sum(fails) / len(fails), 3)})
    return Experiment(
        "risk_tradeoff", "Risk-aware routing trade-off",
        "Analytic (no simulation): primary paths minimise delay/mean_delay + λ·(−ln(1−p)) "
        "with seeded heterogeneous link failure priors (0.5%–15%). Larger λ buys "
        "reliability with latency.", rows, rows)


def exp_timeline(quick=False, workers=None) -> Experiment:
    """Per-millisecond delivery of one flow around a failure, for each app."""
    rows = []
    series = {}
    for app in APPS:
        sc = Scenario(T.abilene().add_host_per_switch(), app=app)
        f = sc.flow("hSEA", "hATL", rate=1000, start=0.25, stop=0.7)
        sc.fail_link(T_FAIL, "DEN", "KSC")
        sc.run()
        lo, hi = T_FAIL - 0.02, T_FAIL + 0.08
        bins = [0] * int(round((hi - lo) * 1000))
        for t in f.arrivals:
            if lo <= t < hi:
                bins[int((t - lo) * 1000)] += 1
        series[app] = bins
        rows.append({"app": app, "lost": f.lost, "outage_ms": 1000 * f.outage(),
                     "hops_after": f.hops[-1] if f.hops else 0})
    return Experiment(
        "timeline", "What a failure looks like",
        "One flow (SEA→ATL, 1000 pkt/s) crosses DEN–KSC, which is cut at 450 ms. Packets "
        "delivered per millisecond, per strategy.",
        rows, rows, extra={"series": series, "t0_ms": (T_FAIL - 0.02) * 1000})


ALL = {
    "timeline": exp_timeline,
    "single_link": exp_single_link,
    "node_crash": exp_node_crash,
    "gray": exp_gray,
    "bfd_tradeoff": exp_bfd_tradeoff,
    "srlg": exp_srlg,
    "sequential": exp_sequential,
    "flapping": exp_flapping,
    "state": exp_state,
    "risk_tradeoff": exp_risk_tradeoff,
}
