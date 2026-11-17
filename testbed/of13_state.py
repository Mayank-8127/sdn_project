#!/usr/bin/env python3
"""Steady-state OpenFlow 1.3 state of the OS-Ken controller, per topology.

    python testbed/of13_state.py            # needs os-ken; no switches, no root

Runs the controller against in-process stub datapaths (every message is
serialised to the OpenFlow 1.3 wire format), answers its barriers, and counts
the flow entries and groups left installed: flows = adds - deletes.
"""

import io
import itertools
import os
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from os_ken.ofproto import ofproto_v1_3 as ofp, ofproto_v1_3_parser as parser  # noqa: E402

from ffr import topology as T  # noqa: E402
from ffr.network import Network  # noqa: E402
from topo_export import export  # noqa: E402

_xid = itertools.count(1)


class StubDP:
    def __init__(self, dpid):
        self.id, self.ofproto, self.ofproto_parser, self.sent = dpid, ofp, parser, []

    def set_xid(self, msg):
        if msg.xid is None:
            msg.xid = next(_xid)

    def send_msg(self, msg):
        self.set_xid(msg)
        msg.serialize()
        self.sent.append(msg)


class Ev:
    def __init__(self, msg):
        self.msg = msg


def state(topo_name):
    topo = T.get(topo_name).add_host_per_switch()
    net = Network(topo)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "topo.json")
        export(topo, lambda a, b: net.switches[a].port_to(b),
               lambda h: net.switches[topo.hosts[h]].port_to(h), path)
        from ffr_osken_app import FailureAwareFRRApp
        with redirect_stdout(io.StringIO()):
            app = FailureAwareFRRApp(topo_path=path)
        app.spawn_after = lambda delay, fn, *args: fn(*args)
        dps = {}
        for name, dpid in app.dpids.items():
            dps[name] = StubDP(dpid)
            app.on_features(Ev(parser.OFPSwitchFeatures(dps[name])))
        answered = set()
        while True:
            todo = [(dp, m) for dp in dps.values() for m in dp.sent
                    if isinstance(m, parser.OFPBarrierRequest) and (dp.id, m.xid) not in answered]
            if not todo:
                break
            for dp, m in todo:
                answered.add((dp.id, m.xid))
                r = parser.OFPBarrierReply(dp)
                r.xid = m.xid
                app.on_barrier(Ev(r))
    flows = groups = 0
    for dp in dps.values():
        for m in dp.sent:
            if isinstance(m, parser.OFPFlowMod):
                flows += {ofp.OFPFC_ADD: 1, ofp.OFPFC_DELETE_STRICT: -1}.get(m.command, 0)
            elif isinstance(m, parser.OFPGroupMod):
                groups += {ofp.OFPGC_ADD: 1, ofp.OFPGC_DELETE: -1}.get(m.command, 0)
    return flows, groups


if __name__ == "__main__":
    print("| topology | OpenFlow 1.3 flow entries | groups |")
    print("|---|---:|---:|")
    for name in sys.argv[1:] or ["ring6", "abilene", "nsfnet", "grid5x5"]:
        f, g = state(name)
        print(f"| {name} | {f} | {g} |")
