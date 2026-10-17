"""Failure-Aware Fast Reroute as a real OpenFlow 1.3 controller (OS-Ken / Ryu).

This is the testbed port of ``ffr.apps.fa_frr``. It drives real switches
(Open vSwitch in Mininet) and reuses the *same* planning code as the emulator
(``ffr.protection``, ``ffr.risk``, ``ffr.routing``). Only the southbound part
changes: abstract rules become OpenFlow messages.

Mapping from the emulator to OpenFlow 1.3:

=====================  =====================================================
emulator               OpenFlow 1.3 / OVS
=====================  =====================================================
``Match(dst=h)``       ``eth_type=IPv4, ipv4_dst=<ip of h>``
``SetTag(T)``          ``push_vlan(0x8100), set_field(vlan_vid=T|PRESENT)``
``Match(tag=T)``       ``vlan_vid=T|PRESENT``
``PopTag()``           ``pop_vlan`` (only on the tagged egress rule)
FF group               ``OFPGT_FF`` group, buckets with ``watch_port``
``Barrier``            ``OFPBarrierRequest`` / ``EventOFPBarrierReply``
``PortStatus``         ``EventOFPPortStatus`` (OFPPS_LINK_DOWN)
LOS / BFD              OVS port carrier, or OVS BFD (``bfd:enable=true``)
=====================  =====================================================

Run (see ``testbed/README.md``)::

    FFR_TOPO=/tmp/ffr_topo.json osken-manager testbed/ffr_osken_app.py
    # or with Ryu: ryu-manager testbed/ffr_osken_app.py  (import fallback below)

The topology file is written by ``testbed/mininet_ffr.py``.
"""

from __future__ import annotations

import json
import os
import sys
import time

try:  # OS-Ken (maintained fork) first, then classic Ryu
    from os_ken.base import app_manager
    from os_ken.controller import ofp_event
    from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from os_ken.lib import hub
    from os_ken.ofproto import ofproto_v1_3
except ImportError:  # pragma: no cover
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from ryu.lib import hub
    from ryu.ofproto import ofproto_v1_3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ffr.protection import plan_destination  # noqa: E402
from ffr.risk import RiskModel  # noqa: E402
from ffr.routing import Graph, edge  # noqa: E402
from ffr.topology import Topology  # noqa: E402

PRIO_EGRESS_TAGGED = 110
PRIO_PRIMARY = 100
PRIO_DETOUR = 200
COOKIE_PRIMARY = 1
DETOUR_BASE = 1000
ETH_IPV4 = 0x0800


def load_topology(path: str):
    """Read the JSON written by mininet_ffr.py.

    Returns (Topology, dpid by switch, port map {(sw, peer): port}, host info).
    """
    with open(path) as fh:
        spec = json.load(fh)
    topo = Topology(spec.get("name", "testbed"))
    for s in spec["switches"]:
        topo.add_switch(s["name"])
    ports = {}
    for l in spec["links"]:
        topo.add_link(l["a"], l["b"], delay=l.get("delay", 0.001),
                      fail_prob=l.get("fail_prob", 0.0))
        ports[(l["a"], l["b"])] = l["a_port"]
        ports[(l["b"], l["a"])] = l["b_port"]
    for name, links in spec.get("srlgs", {}).items():
        topo.add_srlg(name, *[tuple(x) for x in links])
    hosts = {}
    for h in spec["hosts"]:
        topo.add_host(h["name"], h["switch"])
        ports[(h["switch"], h["name"])] = h["port"]
        hosts[h["name"]] = h
    dpids = {s["name"]: int(s["dpid"]) for s in spec["switches"]}
    return topo, dpids, ports, hosts


class FailureAwareFRRApp(app_manager.OSKenApp if hasattr(app_manager, "OSKenApp")
                         else app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, topo_path: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        path = topo_path or os.environ.get("FFR_TOPO", "/tmp/ffr_topo.json")
        self.topo, self.dpids, self.ports, self.hosts = load_topology(path)
        self.names = {d: n for n, d in self.dpids.items()}
        self.graph = Graph.from_topology(self.topo)
        self.risk = RiskModel(self.topo, half_life=float(os.environ.get("FFR_HALF_LIFE", 60)))
        self.lam = float(os.environ.get("FFR_LAMBDA", 5))
        self.base_holddown = float(os.environ.get("FFR_HOLDDOWN", 5))
        self.datapaths = {}
        self.down: set = set()
        self.held: dict = {}
        self.generation = 0
        self.gen_switches: dict[int, set[str]] = {}
        self.groups_installed: set[tuple[str, int]] = set()
        self.primary_done: set[tuple[str, str]] = set()
        self.gids: dict[tuple[str, str], int] = {}
        self.tags: dict[tuple, int] = {}
        self.barriers: dict[int, tuple[set, object]] = {}
        self._barrier_seq = 0
        self.plans = {}
        self.started = False

    # ------------------------------------------------------------ helpers
    def now(self) -> float:
        return time.time()

    def tag_for(self, key) -> int:
        k = (key, self.generation)
        if k not in self.tags:
            self.tags[k] = (len(self.tags) % 4000) + 2  # VLAN ids 2..4001
        return self.tags[k]

    def gid_for(self, sw: str, host: str) -> int:
        return self.gids.setdefault((sw, host), len(self.gids) + 1)

    def send(self, sw: str, msg) -> None:
        self.datapaths[sw].send_msg(msg)

    def flow(self, sw, match, actions, priority, cookie=0):
        dp = self.datapaths[sw]
        ofp, p = dp.ofproto, dp.ofproto_parser
        inst = [p.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        self.send(sw, p.OFPFlowMod(dp, cookie=cookie, priority=priority, match=match,
                                   instructions=inst, command=ofp.OFPFC_ADD))

    def delete_cookie(self, sw, cookie):
        dp = self.datapaths[sw]
        ofp, p = dp.ofproto, dp.ofproto_parser
        self.send(sw, p.OFPFlowMod(dp, cookie=cookie, cookie_mask=0xFFFFFFFFFFFFFFFF,
                                   table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
                                   out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY))

    def barrier(self, switches, callback):
        live = [s for s in switches if s in self.datapaths]
        if not live:
            callback()
            return
        pending = set()
        for s in live:
            dp = self.datapaths[s]
            req = dp.ofproto_parser.OFPBarrierRequest(dp)
            dp.set_xid(req)
            pending.add((dp.id, req.xid))
            dp.send_msg(req)
        self._barrier_seq += 1
        self.barriers[self._barrier_seq] = (pending, callback)

    # ------------------------------------------------------------ planning
    def unusable(self):
        return set(self.down) | set(self.held)

    def weight(self):
        now = self.now()
        return lambda u, v: self.risk.weight(edge(u, v), now, self.lam)

    def srlg_exclusions(self, el):
        if el[0] == "link":
            return self.risk.shared_risk(el[1]), ()
        risky = set()
        for nb in self.graph.adj[el[1]]:
            risky |= self.risk.shared_risk(edge(el[1], nb))
        return risky, ()

    def plan_all(self):
        return {h: plan_destination(self.graph, s, "node", excluded_edges=self.unusable(),
                                    weight=self.weight(), detour_exclusions=self.srlg_exclusions)
                for h, s in sorted(self.topo.hosts.items())}

    # ------------------------------------------------------------ installing
    def reoptimize(self):
        self.generation += 1
        gen = self.generation
        cookie = DETOUR_BASE + gen
        self.plans = self.plan_all()
        touched = set()
        for host, plans in self.plans.items():
            ip = self.hosts[host]["ip"]
            rules = {}
            for u, hp in plans.items():
                if hp.protected:
                    t = self.tag_for(hp.tag_key)
                    for x, y in zip(hp.detour[1:-1], hp.detour[2:]):
                        rules[(x, t)] = y
            for (x, t), y in sorted(rules.items()):
                dp = self.datapaths[x]
                p, ofp = dp.ofproto_parser, dp.ofproto
                m = p.OFPMatch(vlan_vid=(t | ofp.OFPVID_PRESENT), eth_type=ETH_IPV4, ipv4_dst=ip)
                self.flow(x, m, [p.OFPActionOutput(self.ports[(x, y)])], PRIO_DETOUR, cookie)
                touched.add(x)
        self.gen_switches[gen] = touched
        self.logger.info("FA-FRR gen %d: unusable=%s", gen, sorted(map(sorted, self.unusable())))
        self.barrier(touched, lambda: self.switch_groups(gen))

    def switch_groups(self, gen):
        if gen != self.generation:
            return
        for host, plans in self.plans.items():
            ip, hsw = self.hosts[host]["ip"], self.topo.hosts[host]
            if (hsw, host) not in self.primary_done:
                dp = self.datapaths[hsw]
                p, ofp = dp.ofproto_parser, dp.ofproto
                out = p.OFPActionOutput(self.ports[(hsw, host)])
                self.flow(hsw, p.OFPMatch(eth_type=ETH_IPV4, ipv4_dst=ip), [out],
                          PRIO_PRIMARY, COOKIE_PRIMARY)
                tagged = p.OFPMatch(vlan_vid=(ofp.OFPVID_PRESENT, ofp.OFPVID_PRESENT),
                                    eth_type=ETH_IPV4, ipv4_dst=ip)
                self.flow(hsw, tagged, [p.OFPActionPopVlan(), out], PRIO_EGRESS_TAGGED,
                          COOKIE_PRIMARY)
                self.primary_done.add((hsw, host))
            for u, hp in sorted(plans.items()):
                dp = self.datapaths[u]
                p, ofp = dp.ofproto_parser, dp.ofproto
                prim = self.ports[(u, hp.primary)]
                buckets = [p.OFPBucket(watch_port=prim, watch_group=ofp.OFPG_ANY,
                                       actions=[p.OFPActionOutput(prim)])]
                if hp.protected:
                    q = self.ports[(u, hp.detour[1])]
                    t = self.tag_for(hp.tag_key)
                    buckets.append(p.OFPBucket(watch_port=q, watch_group=ofp.OFPG_ANY, actions=[
                        p.OFPActionPushVlan(0x8100),
                        p.OFPActionSetField(vlan_vid=(t | ofp.OFPVID_PRESENT)),
                        p.OFPActionOutput(q)]))
                gid = self.gid_for(u, host)
                cmd = ofp.OFPGC_MODIFY if (u, gid) in self.groups_installed else ofp.OFPGC_ADD
                self.send(u, p.OFPGroupMod(dp, cmd, ofp.OFPGT_FF, gid, buckets))
                self.groups_installed.add((u, gid))
                if (u, host) not in self.primary_done:
                    self.flow(u, p.OFPMatch(eth_type=ETH_IPV4, ipv4_dst=ip),
                              [p.OFPActionGroup(gid)], PRIO_PRIMARY, COOKIE_PRIMARY)
                    self.primary_done.add((u, host))
        self.barrier(list(self.datapaths), lambda: self.cleanup(gen))

    def cleanup(self, gen):
        for old in sorted(g for g in self.gen_switches if g < gen):
            for sw in sorted(self.gen_switches.pop(old)):
                if sw in self.datapaths:
                    self.delete_cookie(sw, DETOUR_BASE + old)
        self.logger.info("FA-FRR gen %d active", gen)

    # ------------------------------------------------------------ events
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def on_features(self, ev):
        dp = ev.msg.datapath
        name = self.names.get(dp.id)
        if name is None:
            self.logger.warning("unknown datapath %s", dp.id)
            return
        self.datapaths[name] = dp
        self.logger.info("switch %s connected (%d/%d)", name, len(self.datapaths),
                         len(self.dpids))
        if not self.started and len(self.datapaths) == len(self.dpids):
            self.started = True
            self.reoptimize()

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def on_barrier(self, ev):
        key = (ev.msg.datapath.id, ev.msg.xid)
        for token, (pending, cb) in list(self.barriers.items()):
            if key in pending:
                pending.discard(key)
                if not pending:
                    del self.barriers[token]
                    cb()
                return

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def on_port_status(self, ev):
        msg = ev.msg
        ofp = msg.datapath.ofproto
        sw = self.names.get(msg.datapath.id)
        peer = next((n for (s, n), p in self.ports.items()
                     if s == sw and p == msg.desc.port_no), None)
        if peer is None or peer not in self.graph.adj:
            return
        down = bool(msg.desc.state & ofp.OFPPS_LINK_DOWN) or msg.reason == ofp.OFPPR_DELETE
        self.link_change(edge(sw, peer), not down)

    def link_change(self, e, live: bool):
        now = self.now()
        if not live:
            if e in self.down:
                return
            self.down.add(e)
            self.risk.record_failure(e, now)
            timer = self.held.pop(e, None)
            if timer is not None:
                timer.cancel()
                return
            self.logger.info("link %s DOWN: data plane already rerouted, re-optimising",
                             "-".join(sorted(e)))
            self.reoptimize()
        else:
            if e not in self.down:
                return
            self.down.discard(e)
            hd = self.risk.holddown(e, now, self.base_holddown)
            self.logger.info("link %s UP: hold-down %.1fs", "-".join(sorted(e)), hd)
            self.held[e] = hub.spawn_after(hd, self.release, e)

    def release(self, e):
        if self.held.pop(e, None) is not None and e not in self.down:
            self.logger.info("link %s stable: back in service", "-".join(sorted(e)))
            self.reoptimize()
