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
            "affected_flows": round(sum(r["affected"] for r in rs) / n, 2),
            "peak_flow_entries": round(sum(r.get("peak_flow_entries", 0) for r in rs) / n),
            "looped_pkts": round(sum(r.get("looped_pkts", 0) for r in rs) / n, 2),
            "max_link_flows_before": round(sum(r.get("max_link_flows_before", 0) for r in rs) / n, 1),
            "max_link_flows_after": round(sum(r.get("max_link_flows_after", 0) for r in rs) / n, 1),
            "mean_path_delay_ms": round(sum(r.get("mean_path_delay_ms", 0) for r in rs) / n, 3),
            "flows_hit_last": round(sum(r.get("flows_hit_last", 0) for r in rs) / n, 2),
            "pkts_lost_last": round(sum(r.get("pkts_lost_last", 0) for r in rs) / n, 1),
        })
    return out


# Strategy variants: (reported name, app, app options). The fa-frr-* entries
# are ablations that switch off one FA-FRR mechanism each.
VARIANTS = {
    "reactive": ("reactive", {}),
    "frr-link": ("frr-link", {}),
    "frr-node": ("frr-node", {}),
    "frr-srlg": ("frr-srlg", {}),
    "e2e": ("e2e", {}),
    "e2e-srlg": ("e2e-srlg", {}),
    "fa-frr": ("fa-frr", {}),
    "fa-frr-nosrlg": ("fa-frr", {"srlg_aware": False}),
    "fa-frr-noreopt": ("fa-frr", {"reoptimize": False}),
    "fa-frr-unordered": ("fa-frr", {"ordered_update": False}),
    "fa-frr-nopin": ("fa-frr", {"pin_backups": False}),
    "fa-frr-fixedhold": ("fa-frr", {"adaptive_holddown": False}),
    "fa-frr-nohold": ("fa-frr", {"holddown": 0.0}),
    "fa-frr-lam0": ("fa-frr", {"lam": 0.0}),
    "fa-frr-lam20": ("fa-frr", {"lam": 20.0}),
}


def vcase(topo, variant, failures, **kw) -> Case:
    app, opts = VARIANTS[variant]
    app_kw = {**opts, **kw.pop("app_kw", {})}
    return Case(topo, app, failures, app_kw=app_kw, name=variant, **kw)


# ------------------------------------------------------------- experiments
MAIN_TOPOS = ["abilene", "nsfnet", "grid5x5"]


def exp_single_link(quick=False, workers=None) -> Experiment:
    topos = ["abilene"] if quick else MAIN_TOPOS
    cases = [Case(t, app, [link_fail(a, b)], labels={"failure": f"{a}-{b}"})
             for t in topos for app in APPS
             for a, b in sample(links_of(t), 4 if quick else (None if t != "grid5x5" else 20))]
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


def srlg_pairs(topo_name: str, k: int | None, seed: int = 3, kind: str = "incident"):
    """Pairs of links whose joint failure leaves the network connected.

    ``incident``: the two links meet at a switch (a duct leaving one PoP).
    ``remote``: the two links share no switch (two links crossing the same
    right-of-way somewhere else).
    """
    topo = T.get(topo_name)
    pairs = []
    if kind == "incident":
        for n in topo.switches:
            inc = sorted(tuple(sorted((n, m))) for m in topo.neighbors(n))
            for l1, l2 in itertools.combinations(inc, 2):
                if connected_without(topo_name, edges=[frozenset(l1), frozenset(l2)]):
                    pairs.append((l1, l2))
    else:
        for l1, l2 in itertools.combinations(links_of(topo_name), 2):
            if set(l1) & set(l2):
                continue
            if connected_without(topo_name, edges=[frozenset(l1), frozenset(l2)]):
                pairs.append((l1, l2))
    return sample(pairs, k, seed)


SRLG_APPS = ["reactive", "frr-node", "e2e", "fa-frr"]
SRLG_VARIANTS = ["reactive", "frr-node", "frr-srlg", "e2e", "e2e-srlg", "fa-frr", "fa-frr-nosrlg"]


def exp_srlg(quick=False, workers=None) -> Experiment:
    topos = ["abilene"] if quick else MAIN_TOPOS
    cases = []
    for t in topos:
        for kind in ["incident", "remote"]:
            for l1, l2 in srlg_pairs(t, 4 if quick else 15, kind=kind):
                for v in SRLG_VARIANTS:
                    cases.append(vcase(t, v, [link_fail(*l1), link_fail(*l2)],
                                       srlgs=[("duct", [l1, l2])],
                                       labels={"kind": kind,
                                               "failure": f"{'-'.join(l1)}+{'-'.join(l2)}"}))
    rows = run_cases(cases, workers)
    return Experiment(
        "srlg", "Correlated (SRLG) double failures",
        "Two links that share a risk group (declared in the topology) fail at the same "
        "instant. Incident pairs meet at a switch; remote pairs share no switch.",
        rows, aggregate(rows, by=("topo", "kind", "app")))


SEQ_VARIANTS = ["reactive", "frr-node", "e2e", "fa-frr", "fa-frr-noreopt"]


def sequential_pairs(t: str, k: int | None):
    pairs = [(l1, l2) for l1, l2 in itertools.permutations(links_of(t), 2)
             if connected_without(t, edges=[frozenset(l1), frozenset(l2)])]
    return sample(pairs, k, seed=11)


def exp_sequential(quick=False, workers=None) -> Experiment:
    topos = ["abilene"] if quick else MAIN_TOPOS
    cases = []
    for t in topos:
        for l1, l2 in sequential_pairs(t, 4 if quick else 20):
            for v in SEQ_VARIANTS:
                cases.append(vcase(t, v, [link_fail(*l1), link_fail(*l2, t=T_FAIL + 0.2)],
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
    cases = [vcase("abilene", v, flaps(a, b), stop=1.1, labels={"failure": f"{a}-{b}"})
             for v in ["reactive", "frr-node", "fa-frr", "fa-frr-nopin", "fa-frr-fixedhold",
                       "fa-frr-nohold"]
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
            delays, fails, load = [], [], {}
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
                    for a, b in zip(path, path[1:]):
                        load[edge(a, b)] = load.get(edge(a, b), 0) + 1
            rows.append({"topo": t, "lam": lam,
                         "mean_path_delay_ms": round(1000 * sum(delays) / len(delays), 3),
                         "mean_path_fail_prob_pct": round(100 * sum(fails) / len(fails), 3),
                         "max_link_paths": max(load.values()),
                         "links_used": len(load)})
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


def exp_loops(quick=False, workers=None) -> Experiment:
    """Transient forwarding loops during re-optimisation, ordered vs unordered."""
    cases = []
    topos = ["ring6", "abilene"] if quick else ["ring6", "grid3x3", "abilene", "nsfnet"]
    for jitter in [0.0, 0.02]:
        for t in topos:
            for a, b in links_of(t):
                for restore in [None, T_FAIL + 0.2]:
                    for v in ["reactive", "fa-frr-unordered", "fa-frr"]:
                        cases.append(vcase(
                            t, v, [link_fail(a, b, restore=restore)], stop=1.0,
                            app_kw={**({"holddown": 0.05} if v != "reactive" else {}),
                                    "ctrl_jitter": jitter, "jitter_seed": len(cases)},
                            labels={"jitter_ms": int(1000 * jitter),
                                    "event": "cut" if restore is None else "cut+restore",
                                    "failure": f"{a}-{b}"}))
    rows = run_cases(cases, workers)
    summary = []
    for jitter in sorted({r["jitter_ms"] for r in rows}):
        for v in ["reactive", "fa-frr-unordered", "fa-frr"]:
            rs = [r for r in rows if r["jitter_ms"] == jitter and r["app"] == v]
            summary.append({"jitter_ms": jitter, "app": v, "runs": len(rs),
                            "runs_with_loops": sum(r["looped_pkts"] > 0 for r in rs),
                            "looped_pkts": sum(r["looped_pkts"] for r in rs),
                            "lost_pkts": sum(r["lost"] for r in rs)})
    return Experiment(
        "loops", "Transient loops during updates",
        "Every link of four topologies is cut (and, separately, cut and restored 200 ms "
        "later, hold-down 50 ms); the controller channel has no jitter or up to 20 ms. A "
        "packet that visits a switch twice with the same tag is counted as looped.",
        rows, summary)


GAPS_MS = [10, 20, 40, 60, 80, 100, 120, 150, 200, 300, 400, 500]
GAP_T0 = 1.0  # later first failure, so that slow rule installation has finished
GAP_VARIANTS = ["frr-node", "fa-frr", "fa-frr-unordered", "fa-frr-slowrules"]


def exp_gap(quick=False, workers=None) -> Experiment:
    """Sequential double failures with the second failure 10-200 ms after the first."""
    gaps = [20, 100, 200] if quick else GAPS_MS
    topos = ["abilene"] if quick else ["abilene", "nsfnet"]
    cases = []
    for t in topos:
        for l1, l2 in sequential_pairs(t, 3 if quick else 10):
            for g in gaps:
                for v in GAP_VARIANTS:
                    net_kw = {}
                    if v == "fa-frr-slowrules":  # 5 ms per rule instead of 1 ms
                        vv, net_kw = "fa-frr", {"rule_install_time": 0.005}
                    else:
                        vv = v
                    c = vcase(t, vv, [link_fail(*l1, t=GAP_T0),
                                      link_fail(*l2, t=GAP_T0 + g / 1000)],
                              start=0.8, stop=2.5, net_kw=net_kw,
                              labels={"gap_ms": g, "failure": f"{'-'.join(l1)} then {'-'.join(l2)}"})
                    c.name = v
                    cases.append(c)
    rows = run_cases(cases, workers)
    return Experiment(
        "gap", "Time between two failures",
        "A second, independent link fails 10-500 ms after the first (first failure at 1 s, "
        "traffic 0.8-2.5 s). fa-frr-slowrules installs each rule in 5 ms instead of 1 ms.",
        rows, aggregate(rows, by=("topo", "app", "gap_ms")))


FLAP_PATTERNS = {
    # name: (down ms, up ms, flaps)
    "fast (40/40 ms)": (40, 40, 5),
    "slow (40/300 ms)": (40, 300, 5),
}


def exp_flapping_long(quick=False, workers=None) -> Experiment:
    """Flapping links over several seconds, so that hold-downs expire."""
    cases = []
    for pname, (down, up, n) in FLAP_PATTERNS.items():
        def flaps(a, b):
            period = (down + up) / 1000
            return [link_fail(a, b, T_FAIL + period * i, T_FAIL + period * i + down / 1000)
                    for i in range(n)]
        stop = T_FAIL + n * (down + up) / 1000 + 1.5
        for v in ["reactive", "frr-node", "fa-frr", "fa-frr-nopin", "fa-frr-fixedhold",
                  "fa-frr-nohold", "fa-frr-lam0"]:
            for a, b in sample(links_of("abilene"), 4 if quick else None):
                cases.append(vcase("abilene", v, flaps(a, b), stop=stop,
                                   labels={"pattern": pname, "failure": f"{a}-{b}"}))
    rows = run_cases(cases, workers)
    return Experiment(
        "flapping_long", "Flapping links over several seconds",
        "A link flaps five times, then stays up; traffic runs 1.5 s past the last flap so that "
        "hold-downs expire. Fixed hold-down uses 200 ms after every flap; adaptive grows "
        "with the link's recent instability.",
        rows, aggregate(rows, by=("pattern", "app")))


def heterogeneous_priors(topo_name: str, seed: int = 5) -> dict:
    """The seeded link failure priors also used by the analytic risk study."""
    rng = random.Random(seed)
    return {tuple(sorted(l.key)): rng.choice([0.005, 0.005, 0.01, 0.02, 0.05, 0.15])
            for l in T.get(topo_name).links}


def exp_risk_dynamic(quick=False, workers=None) -> Experiment:
    """Risk-aware primaries in simulation: links fail in proportion to their prior."""
    cases = []
    for t in (["abilene"] if quick else ["abilene", "nsfnet"]):
        priors = heterogeneous_priors(t)
        links = sorted(priors)
        rng = random.Random(13)
        failures = rng.choices(links, weights=[priors[l] for l in links], k=6 if quick else 30)
        for i, (a, b) in enumerate(failures):
            for v in ["fa-frr-lam0", "fa-frr", "fa-frr-lam20"]:
                cases.append(vcase(t, v, [link_fail(a, b)], priors=priors,
                                   labels={"failure": f"{i}:{a}-{b}"}))
    rows = run_cases(cases, workers)
    return Experiment(
        "risk_dynamic", "Risk-aware primaries under failures drawn from the priors",
        "Heterogeneous priors (0.5-15 %, seed 5); 30 link failures per topology drawn with "
        "probability proportional to the prior (seed 13). lam=0 routes on delay only.",
        rows, aggregate(rows))


def exp_srlg_followup(quick=False, workers=None) -> Experiment:
    """One link of an SRLG fails, its peer follows 200 ms later."""
    topos = ["abilene"] if quick else ["abilene", "nsfnet"]
    cases = []
    for t in topos:
        for l1, l2 in srlg_pairs(t, 4 if quick else 15):
            for v in ["frr-srlg", "fa-frr-lam0", "fa-frr", "fa-frr-lam20"]:
                cases.append(vcase(t, v, [link_fail(*l1), link_fail(*l2, t=T_FAIL + 0.2)],
                                   srlgs=[("duct", [l1, l2])], stop=1.0,
                                   labels={"failure": f"{'-'.join(l1)} then {'-'.join(l2)}"}))
    rows = run_cases(cases, workers)
    return Experiment(
        "srlg_followup", "Correlated follow-up failures",
        "A link fails; 200 ms later the other link of its declared SRLG fails too. The "
        "first failure raises the peer's failure probability (rho*delta), so risk-aware "
        "re-optimisation (lam>0) moves primaries off the peer before it fails.",
        rows, aggregate(rows))


RULE_TIMES_MS = [1, 2.5, 5, 10, 33]
INSTALL_T_FAIL = 12.0


def exp_install_time(quick=False, workers=None) -> Experiment:
    """Re-protection time against per-rule installation time, with and without
    the OpenFlow 1.3 OFPP_IN_PORT groups and rules."""
    import time as _time
    from ..protection import plan_destination
    cases = []
    times = [1, 10] if quick else RULE_TIMES_MS
    for t in (["abilene"] if quick else MAIN_TOPOS):
        links = sample(links_of(t), 3 if quick else (8 if t == "grid5x5" else None))
        for ms in times:
            for of13 in [False, True]:
                for a, b in links:
                    # the cut comes once even the slowest initial installation is done
                    # (about 9 s on the grid at 33 ms per rule); light traffic, long run
                    cases.append(vcase(t, "fa-frr", [link_fail(a, b, t=INSTALL_T_FAIL)],
                                       net_kw={"rule_install_time": ms / 1000},
                                       app_kw={"of13_inport": of13},
                                       start=INSTALL_T_FAIL - 0.2, stop=INSTALL_T_FAIL + 8.0,
                                       rate=10.0,
                                       labels={"rule_ms": ms, "of13": of13,
                                               "failure": f"{a}-{b}"}))
    rows = run_cases(cases, workers)
    summary = []
    for key in sorted({(r["topo"], r["rule_ms"], r["of13"]) for r in rows},
                      key=lambda k: (MAIN_TOPOS.index(k[0]), k[1], k[2])):
        rs = [r for r in rows if (r["topo"], r["rule_ms"], r["of13"]) == key]
        rp = [r["reprotect_ms"] for r in rs if r["reprotect_ms"] is not None]
        summary.append({"topo": key[0], "rule_ms": key[1], "of13_inport": key[2],
                        "runs": len(rs),
                        "initial_install_ms_max": _max(r["initial_install_ms"] for r in rs),
                        "reprotect_ms_mean": _mean(rp),
                        "reprotect_ms_max": _max(rp),
                        "ctrl_msgs": round(sum(r["ctrl_msgs"] for r in rs) / len(rs)),
                        "flow_entries": round(sum(r["flow_entries"] for r in rs) / len(rs)),
                        "groups": round(sum(r["group_entries"] for r in rs) / len(rs))})
    # wall-clock time of planning all destinations (Algorithm 1) in this
    # Python implementation, for comparison with T_comp; machine dependent
    plan_ms = {}
    for t in MAIN_TOPOS:
        g = Graph.from_topology(T.get(t))
        best = float("inf")
        for _ in range(3):
            t0 = _time.perf_counter()
            for d in g.nodes:
                plan_destination(g, d, "node")
            best = min(best, _time.perf_counter() - t0)
        plan_ms[t] = round(1000 * best, 1)
    return Experiment(
        "install_time", "Re-protection time and rule installation time",
        "One link is cut; time from the cut until every group of the new generation is "
        "installed, for 1-33 ms per rule (hardware switches take 2.5-33 ms), with and "
        "without the OpenFlow 1.3 OFPP_IN_PORT groups and rules. Planning wall-clock "
        f"time (all destinations, this machine, Python): {plan_ms}.",
        rows, summary, extra={"plan_ms": plan_ms})


def exp_duct_repair(quick=False, workers=None) -> Experiment:
    """Both links of a duct fail together and are repaired 300 ms later: the
    coincidence window decides whether each is charged once or 1+rho times."""
    cases = []
    for t in (["abilene"] if quick else ["abilene", "nsfnet"]):
        for l1, l2 in srlg_pairs(t, 4 if quick else 15):
            for name, w in [("W=50ms", 0.05), ("W=0", 0.0)]:
                c = vcase(t, "fa-frr", [link_fail(*l1, restore=T_FAIL + 0.3),
                                        link_fail(*l2, restore=T_FAIL + 0.3)],
                          srlgs=[("duct", [l1, l2])], stop=2.0,
                          app_kw={"coincidence": w},
                          labels={"window": name,
                                  "failure": f"{'-'.join(l1)}+{'-'.join(l2)}"})
                cases.append(c)
    rows = run_cases(cases, workers)
    summary = []
    for t in sorted({r["topo"] for r in rows}):
        for name in ["W=50ms", "W=0"]:
            rs = [r for r in rows if r["topo"] == t and r["window"] == name]
            summary.append({"topo": t, "window": name, "runs": len(rs),
                            "holddown_ms_mean": _mean(r["holddown_ms"] for r in rs),
                            "back_in_service_ms": _mean(r["back_in_service_ms"] for r in rs),
                            "lost_pkts": round(sum(r["lost"] for r in rs) / len(rs), 1),
                            "stretch": round(sum(r["stretch"] for r in rs) / len(rs), 3)})
    return Experiment(
        "duct_repair", "Duct cut and repair: the coincidence window",
        "Both links of a declared SRLG fail at once and come back 300 ms later. With "
        "W=50 ms each is charged one penalty; with W=0 each is also charged its peer's "
        "correlated share, so its hold-down is longer.", rows, summary)


def exp_sensitivity(quick=False, workers=None) -> Experiment:
    """Sensitivity to the hand-chosen parameters h0, delta (flapping) and rho, lambda
    (correlated follow-up failures)."""
    cases = []
    down, up, n = FLAP_PATTERNS["slow (40/300 ms)"]
    period = (down + up) / 1000
    stop = T_FAIL + n * period + 1.5
    for h0 in ([0.1, 0.4] if quick else [0.05, 0.1, 0.2, 0.4, 0.8]):
        for delta in ([0.3] if quick else [0.1, 0.3, 0.6]):
            for a, b in sample(links_of("abilene"), 3 if quick else None):
                flaps = [link_fail(a, b, T_FAIL + period * i, T_FAIL + period * i + down / 1000)
                         for i in range(n)]
                c = vcase("abilene", "fa-frr", flaps, stop=stop,
                          app_kw={"holddown": h0, "flap_penalty": delta},
                          labels={"study": "flapping", "h0_ms": int(1000 * h0), "delta": delta,
                                  "failure": f"{a}-{b}"})
                cases.append(c)
    for t in (["abilene"] if quick else ["abilene", "nsfnet"]):
        for l1, l2 in srlg_pairs(t, 3 if quick else 15):
            for rho in ([0.5] if quick else [0.25, 0.5, 1.0]):
                for lam in [5.0, 20.0]:
                    c = vcase(t, "fa-frr", [link_fail(*l1), link_fail(*l2, t=T_FAIL + 0.2)],
                              srlgs=[("duct", [l1, l2])], stop=1.0,
                              app_kw={"correlation": rho, "lam": lam},
                              labels={"study": "follow-up", "rho": rho, "lam": lam,
                                      "failure": f"{'-'.join(l1)} then {'-'.join(l2)}"})
                    cases.append(c)
    rows = run_cases(cases, workers)
    summary = []
    for key in sorted({(r["h0_ms"], r["delta"]) for r in rows if r["study"] == "flapping"}):
        rs = [r for r in rows if r["study"] == "flapping" and (r["h0_ms"], r["delta"]) == key]
        summary.append({"study": "flapping (Abilene, 40/300 ms)", "h0_ms": key[0],
                        "delta": key[1], "runs": len(rs),
                        "lost_pkts": round(sum(r["lost"] for r in rs) / len(rs), 1),
                        "stretch": round(sum(r["stretch"] for r in rs) / len(rs), 3)})
    for key in sorted({(r["topo"], r["rho"], r["lam"]) for r in rows if r["study"] == "follow-up"}):
        rs = [r for r in rows if r["study"] == "follow-up"
              and (r["topo"], r["rho"], r["lam"]) == key]
        summary.append({"study": f"follow-up ({key[0]})", "rho": key[1], "lam": key[2],
                        "runs": len(rs),
                        "flows_hit_last": round(sum(r["flows_hit_last"] for r in rs) / len(rs), 2),
                        "lost_pkts": round(sum(r["lost"] for r in rs) / len(rs), 1)})
    return Experiment(
        "sensitivity", "Sensitivity to the hand-chosen parameters",
        "Base hold-down h0 and flap penalty delta on slow flapping (Abilene); SRLG "
        "correlation rho and risk weight lambda on correlated follow-up failures.",
        rows, summary)


ALL = {
    "timeline": exp_timeline,
    "single_link": exp_single_link,
    "node_crash": exp_node_crash,
    "gray": exp_gray,
    "bfd_tradeoff": exp_bfd_tradeoff,
    "srlg": exp_srlg,
    "sequential": exp_sequential,
    "flapping": exp_flapping,
    "flapping_long": exp_flapping_long,
    "gap": exp_gap,
    "loops": exp_loops,
    "srlg_followup": exp_srlg_followup,
    "risk_dynamic": exp_risk_dynamic,
    "install_time": exp_install_time,
    "duct_repair": exp_duct_repair,
    "sensitivity": exp_sensitivity,
    "state": exp_state,
    "risk_tradeoff": exp_risk_tradeoff,
}
