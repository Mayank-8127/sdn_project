"""Command-line interface.

Examples::

    python -m ffr run --topo abilene --app static --fail DEN-KSC@0.3
    python -m ffr run --topo ring6 --app static --tables s1
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


def cmd_run(args) -> int:
    topo = topology.get(args.topo).add_host_per_switch()
    app_kw = {"ctrl_delay": args.ctrl_delay}
    sc = Scenario(topo, app=args.app, net_kw={"rule_install_time": args.rule_time}, **app_kw)
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
    res = sc.run()
    print(res.summary())
    if args.verbose:
        for st in sc.tm.affected():
            print(f"  flow {st.flow_id:3d} {st.src}->{st.dst}: lost={st.lost} "
                  f"outage={1000 * st.outage():.1f}ms")
    for sw in args.tables or []:
        print(sc.net.switches[sw].dump_table())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ffr", description="Failure-aware fast rerouting in SDN")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one scenario")
    r.add_argument("--topo", default="abilene", choices=sorted(topology.BUILTIN))
    r.add_argument("--app", default="static", choices=sorted(apps.APPS))
    r.add_argument("--flows", default="all", help="'all' or a number of random pairs")
    r.add_argument("--rate", type=float, default=1000.0, help="packets/s per flow")
    r.add_argument("--start", type=float, default=0.1)
    r.add_argument("--stop", type=float, default=0.6)
    r.add_argument("--fail", action="append", help="A-B@t or A-B@t1:t2 (repeatable)")
    r.add_argument("--ctrl-delay", type=float, default=0.005)
    r.add_argument("--rule-time", type=float, default=0.001)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--tables", nargs="*", help="print the flow tables of these switches")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)

    t = sub.add_parser("topos", help="list built-in topologies")
    t.set_defaults(fn=lambda a: print("\n".join(f"{n}: {topology.get(n)}" for n in
                                                 sorted(topology.BUILTIN))) or 0)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
