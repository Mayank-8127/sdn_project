"""Command-line interface.

Examples::

    python -m ffr run --topo abilene --app static --fail DEN-KSC@0.4
    python -m ffr run --topo ring6 --app frr-link --tables s1
    python -m ffr run --topo abilene --app fa-frr --srlg duct:DEN-KSC,SNV-DEN \
        --fail DEN-KSC@0.4 --fail SNV-DEN@0.4 -v
    python -m ffr topos
"""

from __future__ import annotations

import argparse
import random
import sys

from . import apps, topology
from .scenario import Scenario


def parse_failure(text: str):
    """``A-B@t`` or ``A-B@t1:t2`` (fail at t1, restore at t2)."""
    link, _, when = text.partition("@")
    a, b = link.split("-")
    if ":" in when:
        t1, t2 = when.split(":")
        return a, b, float(t1), float(t2)
    return a, b, float(when or 0.3), None


def parse_value(text: str):
    for conv in (int, float):
        try:
            return conv(text)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(text.lower(), text)


def cmd_run(args) -> int:
    topo = topology.get(args.topo).add_host_per_switch()
    for spec in args.srlg or []:
        name, _, links = spec.partition(":")
        topo.add_srlg(name, *(tuple(l.split("-")) for l in links.split(",")))
    if args.length_risk:
        topo.set_length_risk(per_ms=args.length_risk)
    app_kw = {"ctrl_delay": args.ctrl_delay, "compute_time": args.compute_time,
              "lldp_interval": args.lldp}
    for opt in args.opt or []:
        k, _, v = opt.partition("=")
        app_kw[k.replace("-", "_")] = parse_value(v)
    net_kw = {"rule_install_time": args.rule_time, "los_delay": args.los_delay,
              "detection": args.detection, "bfd_interval": args.bfd_interval,
              "bfd_mult": args.bfd_mult}
    sc = Scenario(topo, app=args.app, net_kw=net_kw, **app_kw)
    hosts = sorted(topo.hosts)
    if args.flows == "all":
        sc.all_pairs(rate=args.rate, start=args.start, stop=args.stop)
    else:
        rng = random.Random(args.seed)
        pairs = [(a, b) for a in hosts for b in hosts if a != b]
        for a, b in rng.sample(pairs, min(int(args.flows), len(pairs))):
            sc.flow(a, b, args.rate, args.start, args.stop)
    for f in args.fail or []:
        a, b, t1, t2 = parse_failure(f)
        sc.fail_link(t1, a, b, t2)
    for f in args.fail_silent or []:
        a, b, t1, t2 = parse_failure(f)
        sc.fail_link(t1, a, b, t2, silent=True)
    for f in args.fail_node or []:
        n, _, t = f.partition("@")
        sc.fail_node(float(t or 0.3), n)
    res = sc.run()
    print(res.summary())
    if args.verbose:
        for t, text in sc.ctrl.log:
            print(f"  t={1000 * t:8.2f}ms controller: {text}")
        for st in sc.tm.affected():
            print(f"  flow {st.flow_id:3d} {st.src}->{st.dst}: lost={st.lost} "
                  f"outage={1000 * st.outage():.1f}ms")
    for sw in args.tables or []:
        print(sc.net.switches[sw].dump_table())
    return 0


def cmd_experiment(args) -> int:
    from .experiments import run_suite
    from .experiments.suite import ALL
    unknown = [n for n in args.names if n not in ALL]
    if unknown:
        print(f"unknown experiments {unknown}; choose from {list(ALL)}")
        return 2
    run_suite(args.names or None, args.quick, args.out, args.workers)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ffr", description="Failure-aware fast rerouting in SDN")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one scenario")
    r.add_argument("--topo", default="abilene", choices=sorted(topology.BUILTIN))
    r.add_argument("--app", default="static", choices=sorted(apps.APPS))
    r.add_argument("--flows", default="all", help="'all' or a number of random pairs")
    r.add_argument("--rate", type=float, default=1000.0, help="packets/s per flow")
    r.add_argument("--start", type=float, default=0.2, help="traffic start (after rule set-up)")
    r.add_argument("--stop", type=float, default=0.8)
    r.add_argument("--fail", action="append", help="cut link: A-B@t or A-B@t1:t2 (repeatable)")
    r.add_argument("--fail-silent", action="append", help="gray failure: A-B@t[:t2]")
    r.add_argument("--fail-node", action="append", help="crash switch: NAME@t")
    r.add_argument("--detection", default="los", help="los | bfd | los+bfd | none")
    r.add_argument("--bfd-interval", type=float, default=0.0033)
    r.add_argument("--bfd-mult", type=int, default=3)
    r.add_argument("--lldp", type=float, default=None, help="controller LLDP probe interval (s)")
    r.add_argument("--ctrl-delay", type=float, default=0.005, help="one-way controller delay (s)")
    r.add_argument("--rule-time", type=float, default=0.001, help="per-rule install time (s)")
    r.add_argument("--compute-time", type=float, default=0.005, help="controller compute time (s)")
    r.add_argument("--los-delay", type=float, default=0.001, help="loss-of-signal detection (s)")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--srlg", action="append", help="shared risk group NAME:A-B,C-D (repeatable)")
    r.add_argument("--length-risk", type=float, default=0.0,
                   help="failure prior per ms of link delay (e.g. 0.01)")
    r.add_argument("--opt", action="append",
                   help="app option KEY=VALUE, e.g. lam=10 holddown=0.5 reoptimize=false")
    r.add_argument("--tables", nargs="*", help="print the flow tables of these switches")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("experiment", help="run the evaluation suite and write a report")
    e.add_argument("names", nargs="*", help="experiments to run (default: all)")
    e.add_argument("--quick", action="store_true", help="reduced sweeps")
    e.add_argument("--out", default="results")
    e.add_argument("--workers", type=int, default=None)
    e.set_defaults(fn=cmd_experiment)

    t = sub.add_parser("topos", help="list built-in topologies")
    t.set_defaults(fn=lambda a: print("\n".join(f"{n}: {topology.get(n)}" for n in
                                                 sorted(topology.BUILTIN))) or 0)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
