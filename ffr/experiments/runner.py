"""Run many scenarios (in parallel) and turn each into one row of metrics.

A :class:`Case` is a fully described, picklable experiment: topology name,
app, failures, parameters. :func:`run_case` builds the scenario, runs it and
returns a flat ``dict`` (one CSV row). :func:`run_cases` runs a list of cases
on all CPU cores.
"""

from __future__ import annotations

import csv
import math
import multiprocessing as mp
import os
import time
from dataclasses import dataclass, field

from .. import topology as T
from ..routing import Graph, shortest_path
from ..scenario import Scenario


@dataclass
class Case:
    topo: str
    app: str
    failures: list = field(default_factory=list)
    # ("link", a, b, t, restore_at | None, silent) or ("node", name, t)
    app_kw: dict = field(default_factory=dict)
    net_kw: dict = field(default_factory=dict)
    srlgs: list = field(default_factory=list)  # [(name, [(a, b), ...]), ...]
    length_risk: float = 0.0
    rate: float = 500.0
    start: float = 0.25
    stop: float = 0.8
    exclude_hosts: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)  # extra columns copied to the row
    name: str | None = None  # reported as "app" (e.g. an ablation variant); default: app
    priors: dict | None = None  # {(a, b): failure prior} for the topology's links


def build_topology(case: Case):
    topo = T.get(case.topo).add_host_per_switch()
    for name, links in case.srlgs:
        topo.add_srlg(name, *links)
    if case.length_risk:
        topo.set_length_risk(per_ms=case.length_risk)
    for (a, b), prob in (case.priors or {}).items():
        topo.link(a, b).fail_prob = prob
    return topo


def run_case(case: Case) -> dict:
    t0 = time.perf_counter()
    topo = build_topology(case)
    sc = Scenario(topo, app=case.app, net_kw=case.net_kw, **case.app_kw)
    hosts = [h for h in sorted(topo.hosts) if h not in case.exclude_hosts]
    sc.all_pairs(rate=case.rate, start=case.start, stop=case.stop, hosts=hosts)
    failed_edges, failed_nodes = [], []
    for f in case.failures:
        if f[0] == "link":
            _, a, b, t, restore, silent = f
            sc.fail_link(t, a, b, restore, silent)
            if restore is None:
                failed_edges.append(frozenset((a, b)))
        elif f[0] == "node":
            _, n, t = f
            sc.fail_node(t, n)
            failed_nodes.append(n)
        else:
            raise ValueError(f)
    res = sc.run()

    # path stretch: switches traversed after recovery vs. shortest path in the
    # failed network (only for flows that were affected and recovered)
    g = Graph.from_topology(topo, weight="hops")
    stretches = []
    for f in sc.tm.affected():
        if f.outage() == math.inf or not f.hops:
            continue
        sp = shortest_path(g, topo.hosts[f.src], topo.hosts[f.dst],
                           excluded_edges=failed_edges, excluded_nodes=failed_nodes)
        if sp:
            stretches.append(f.hops[-1] / len(sp))
    outages = sorted(f.outage() for f in sc.tm.affected() if f.outage() != math.inf)

    # link load: flows per switch-switch link on the path of each flow's first
    # and last delivered packet (before the failure / after recovery)
    def max_load(attr):
        load: dict[frozenset, int] = {}
        for f in sc.tm.flows.values():
            path = getattr(f, attr)
            if path:
                for a, b in zip(path, path[1:]):
                    k = frozenset((a, b))
                    load[k] = load.get(k, 0) + 1
        return max(load.values(), default=0)

    row = dict(case.labels)
    row.update(
        topo=case.topo, app=case.name or case.app, sent=res.sent, lost=res.lost,
        loss_pct=100.0 * res.lost / max(1, res.sent), flows=res.flows,
        affected=res.affected, never_recovered=res.broken,
        # outage statistics over flows that recovered; None if none did
        max_outage_ms=(1000 * outages[-1]) if outages else (None if res.broken else 0.0),
        mean_outage_ms=(1000 * sum(outages) / len(outages)) if outages else
        (None if res.broken else 0.0),
        stretch=(sum(stretches) / len(stretches)) if stretches else 1.0,
        ctrl_msgs=res.ctrl_msgs, flow_entries=res.flow_entries,
        group_entries=res.group_entries, probe_pkts=res.probe_pkts,
        peak_flow_entries=sc.net.occupancy["flows_peak"],
        peak_group_entries=sc.net.occupancy["groups_peak"],
        loop_drops=sum(s.stats["ttl"] for s in sc.net.switches.values()),
        looped_pkts=sum(s.stats["looped"] for s in sc.net.switches.values()),
        max_link_flows_before=max_load("first_path"), max_link_flows_after=max_load("last_path"),
        reoptimizations=getattr(sc.ctrl, "reoptimizations", 0),
        mean_path_delay_ms=1000 * sum(f.delays[0] for f in sc.tm.flows.values() if f.delays)
        / max(1, sum(1 for f in sc.tm.flows.values() if f.delays)),
        wall_s=round(time.perf_counter() - t0, 3),
    )
    return row


def run_cases(cases: list[Case], workers: int | None = None, progress: bool = True) -> list[dict]:
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1 or len(cases) == 1:
        return [run_case(c) for c in cases]
    ctx = mp.get_context("fork") if hasattr(os, "fork") else mp.get_context()
    rows = []
    with ctx.Pool(workers) as pool:
        for i, row in enumerate(pool.imap(run_case, cases, chunksize=1), 1):
            rows.append(row)
            if progress and (i % 10 == 0 or i == len(cases)):
                print(f"    {i}/{len(cases)} runs", flush=True)
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
