#!/usr/bin/env python3
"""Run a fast-reroute experiment on a real (emulated) network: Mininet + OVS.

Needs root and Mininet (``sudo apt install mininet`` or the Mininet VM), plus
an OpenFlow 1.3 controller running ``testbed/ffr_osken_app.py``. Typical use,
in two terminals::

    # 1) write the topology file and start the network (it waits for the controller)
    sudo python3 testbed/mininet_ffr.py --topo abilene --fail DEN-KSC --bfd

    # 2) start the controller (OS-Ken; with Ryu use ryu-manager ffr_osken_app.py)
    FFR_TOPO=/tmp/ffr_topo.json python3 testbed/run_controller.py

``testbed/run_experiments.sh`` runs all scenarios this way.

The script then pings between host pairs every 10 ms, cuts the link (or makes
it fail silently with ``--silent``), restores it, and reports per-pair loss
and the longest outage, measured from ICMP sequence numbers, the same metric
as the emulator.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ffr import topology as T  # noqa: E402

try:
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
except ImportError:  # pragma: no cover
    sys.exit("Mininet is not installed (and this script must run as root).")

from topo_export import export  # noqa: E402

PING_INTERVAL = 0.01  # 10 ms between probes -> outage resolution 10 ms


def build(topo, controller_ip, controller_port):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=True,
                  build=False)
    net.addController("c0", controller=RemoteController, ip=controller_ip,
                      port=controller_port)
    sw = {}
    for i, s in enumerate(topo.switches):
        sw[s] = net.addSwitch(f"s{i + 1}", dpid=f"{i + 1:016x}", protocols="OpenFlow13",
                              failMode="secure")
    hosts = {}
    for i, (h, s) in enumerate(sorted(topo.hosts.items())):
        hosts[h] = net.addHost(f"h{i + 1}", ip=f"10.0.0.{i + 1}/24",
                               mac=f"00:00:00:00:00:{i + 1:02x}")
        net.addLink(hosts[h], sw[s])
    links = {}
    for l in topo.links:
        delay_ms = max(0.0, l.delay * 1000)
        links[(l.a, l.b)] = net.addLink(sw[l.a], sw[l.b], delay=f"{delay_ms:.2f}ms")
    net.build()
    return net, sw, hosts, links


def port_of(link, node):
    intf = link.intf1 if link.intf1.node is node else link.intf2
    return node.ports[intf]


def enable_bfd(net, links, min_ms):
    for link in links.values():
        for intf in (link.intf1, link.intf2):
            intf.node.cmd(f"ovs-vsctl set interface {intf.name} bfd:enable=true "
                          f"bfd:min_rx={min_ms} bfd:min_tx={min_ms} bfd:decay_min_rx=0")


def silent_fail(link, on=True):
    """Gray failure: interfaces stay up, every received frame is dropped.

    Uses the ingress hook so it does not disturb the root qdisc TCLink uses
    for the link delay.
    """
    for intf in (link.intf1, link.intf2):
        if on:
            intf.node.cmd(f"tc qdisc add dev {intf.name} handle ffff: ingress")
            intf.node.cmd(f"tc filter add dev {intf.name} parent ffff: matchall action drop")
        else:
            intf.node.cmd(f"tc qdisc del dev {intf.name} handle ffff: ingress")


def stamp():
    """Wall-clock time in the controller log's format, to line events up."""
    t = time.time()
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"


def parse_ping(out: str, count: int):
    seqs = {int(m) for m in re.findall(r"icmp_seq=(\d+)", out)}
    lost = [s for s in range(1, count + 1) if s not in seqs]
    run = best = 0
    prev = None
    for s in lost:
        run = run + 1 if prev == s - 1 else 1
        best = max(best, run)
        prev = s
    return len(lost), best * PING_INTERVAL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topo", default="abilene", choices=sorted(T.BUILTIN))
    ap.add_argument("--fail", default="DEN-KSC",
                    help="link A-B to fail; A-B,C-D fails several links at the same instant")
    ap.add_argument("--silent", action="store_true", help="gray failure instead of a cut")
    ap.add_argument("--bfd", action="store_true", help="enable OVS BFD on switch links")
    ap.add_argument("--bfd-ms", type=int, default=10)
    ap.add_argument("--srlg", action="append", default=[], help="NAME:A-B,C-D")
    ap.add_argument("--pairs", type=int, default=6, help="host pairs to probe")
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--fail-at", type=float, default=2.0)
    ap.add_argument("--restore-at", type=float, default=4.0)
    ap.add_argument("--controller", default="127.0.0.1:6653")
    ap.add_argument("--topo-file", default="/tmp/ffr_topo.json")
    ap.add_argument("--cli", action="store_true", help="drop into the Mininet CLI at the end")
    args = ap.parse_args()

    setLogLevel("info")
    topo = T.get(args.topo).add_host_per_switch()
    for spec in args.srlg:
        name, _, ls = spec.partition(":")
        topo.add_srlg(name, *(tuple(x.split("-")) for x in ls.split(",")))
    ip, _, port = args.controller.partition(":")
    net, sw, hosts, links = build(topo, ip, int(port or 6653))

    def switch_port(a, b):
        link = links.get((a, b)) or links.get((b, a))
        return port_of(link, sw[a])

    def host_port(h):
        link = net.linksBetween(hosts[h], sw[topo.hosts[h]])[0]
        return port_of(link, sw[topo.hosts[h]])

    export(topo, switch_port, host_port, args.topo_file)
    print(f"*** topology written to {args.topo_file}; start the controller now")
    net.start()
    net.staticArp()
    if args.bfd:
        enable_bfd(net, links, args.bfd_ms)
    print("*** waiting for the controller to install rules")
    for _ in range(120):
        if net.pingAll(timeout=1) == 0:
            break
        time.sleep(1)

    failed = [tuple(x.split("-")) for x in args.fail.split(",")]
    failed_links = [links.get((a, b)) or links.get((b, a)) for a, b in failed]
    # probe pairs whose shortest path crosses a failed link (others are unaffected)
    from ffr.routing import Graph, path_edges, shortest_path, edge
    g = Graph.from_topology(topo)
    names = sorted(topo.hosts)
    cut = {edge(a, b) for a, b in failed}
    crossing = [(x, y) for x in names for y in names if x != y and cut &
                set(path_edges(shortest_path(g, topo.hosts[x], topo.hosts[y])))]
    pairs = crossing[:: max(1, len(crossing) // args.pairs)][:args.pairs]
    count = int(args.duration / PING_INTERVAL)
    procs = {}
    for x, y in pairs:
        procs[(x, y)] = hosts[x].popen(
            ["ping", "-n", "-i", str(PING_INTERVAL), "-c", str(count), "-W", "1",
             hosts[y].IP()])
    time.sleep(args.fail_at)
    print(f"*** {stamp()} failing {args.fail} ({'silent' if args.silent else 'cut'})")
    for (a, b), link in zip(failed, failed_links):
        if args.silent:
            silent_fail(link, True)
        else:
            net.configLinkStatus(sw[a].name, sw[b].name, "down")
    time.sleep(args.restore_at - args.fail_at)
    print(f"*** {stamp()} restoring {args.fail}")
    for (a, b), link in zip(failed, failed_links):
        if args.silent:
            silent_fail(link, False)
        else:
            net.configLinkStatus(sw[a].name, sw[b].name, "up")
    print("*** results (outage resolution 10 ms)")
    for (x, y), p in procs.items():
        out = p.communicate()[0].decode()
        lost, outage = parse_ping(out, count)
        print(f"  {x:>5} -> {y:<5} lost={lost:4d}/{count}  longest outage={1000 * outage:.0f} ms")
    if args.cli:
        from mininet.cli import CLI
        CLI(net)
    net.stop()


if __name__ == "__main__":
    main()
