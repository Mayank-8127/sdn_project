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
U-turn to the sender   ``OFPP_IN_PORT`` in a per-ingress-port FF group
``Barrier``            ``OFPBarrierRequest`` / ``EventOFPBarrierReply``
``PortStatus``         ``EventOFPPortStatus`` (OFPPS_LINK_DOWN)
LOS / BFD              OVS port carrier, or OVS BFD (``bfd:enable=true``)
=====================  =====================================================

Run (see ``testbed/README.md``)::

    FFR_TOPO=/tmp/ffr_topo.json python3 testbed/run_controller.py
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
from ffr.routing import Graph, edge, next_hops_to  # noqa: E402
from ffr.topology import Topology  # noqa: E402

PRIO_EGRESS_TAGGED = 110
PRIO_PRIMARY = 100
PRIO_PRIMARY_IN_PORT = 101
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
        self.ports_down: set[tuple[str, str]] = set()
        self.held: dict = {}
        self.generation = 0
        self.gen_switches: dict[int, set[str]] = {}
        self.groups_installed: set[tuple[str, int]] = set()
        # vias with an in_port rule per (switch, host); kept up to date every generation
        self.vias: dict[tuple[str, str], set] = {}
        self.installed_primary: dict[tuple[str, str], str] = {}
        self.gen_drain: dict[int, float] = {}
        self.primary_done: set[tuple] = set()
        self.gids: dict[tuple, int] = {}
        self.tags: dict[tuple, int] = {}
        self.barriers: dict[int, tuple[set, object]] = {}
        self._barrier_seq = 0
        self.plans = {}
        self.started = False

    # ------------------------------------------------------------ helpers
    def spawn_after(self, delay, fn, *args):
        return hub.spawn_after(delay, fn, *args)

    def now(self) -> float:
        return time.time()

    def tag_for(self, key) -> int:
        k = (key, self.generation)
        if k not in self.tags:
            self.tags[k] = (len(self.tags) % 4000) + 2  # VLAN ids 2..4001
        return self.tags[k]

    def gid_for(self, sw: str, host: str, via: str | None = None) -> int:
        return self.gids.setdefault((sw, host, via), len(self.gids) + 1)

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

    def release_held_if_needed(self):
        """Release held-down links if a destination is unreachable without them."""
        if not self.held:
            return
        for s in sorted(set(self.topo.hosts.values())):
            if len(next_hops_to(self.graph, s, excluded_edges=set(self.down))) > \
                    len(next_hops_to(self.graph, s, excluded_edges=self.unusable())):
                for e, timer in self.held.items():
                    timer.cancel()
                    self.logger.info("link %s: hold-down overridden", "-".join(sorted(e)))
                self.held.clear()
                return

    def plan_all(self):
        return {h: plan_destination(self.graph, s, "node", excluded_edges=self.unusable(),
                                    weight=self.weight(), detour_exclusions=self.srlg_exclusions)
                for h, s in sorted(self.topo.hosts.items())}

    # ------------------------------------------------------------ installing
    def reoptimize(self):
        self.release_held_if_needed()
        self.generation += 1
        gen = self.generation
        cookie = DETOUR_BASE + gen
        self.plans = self.plan_all()
        touched = set()
        drain = 0.0
        for host, plans in self.plans.items():
            ip = self.hosts[host]["ip"]
            rules = {}
            for u, hp in plans.items():
                if hp.protected:
                    drain = max(drain, sum(self.graph.weight(a, b)
                                           for a, b in zip(hp.detour, hp.detour[1:])))
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
        self.gen_drain[gen] = drain
        self.logger.info("FA-FRR gen %d: unusable=%s", gen, sorted(map(sorted, self.unusable())))
        # barrier on every switch: also flushes anything a superseded update sent
        self.barrier(list(self.datapaths), lambda: self.switch_groups(gen))

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
        self.run_rounds(gen, self.levels())

    def levels(self):
        """(switch, host) group updates in loop-free rounds (see ffr.apps.fa_frr)."""
        rounds = {}
        for host, plans in self.plans.items():
            hsw = self.topo.hosts[host]
            # first installation: no old next hop, nothing to order
            changed = {u: (u, host) in self.installed_primary
                       and self.installed_primary[(u, host)] != hp.primary
                       for u, hp in plans.items()}
            count = {hsw: 0}

            def c(u):
                # changed switches on u's new path to the destination, u included
                if u not in count:
                    count[u] = changed[u] + c(plans[u].primary)
                return count[u]

            for u in sorted(plans):
                rounds.setdefault(c(u) if changed[u] else 1, []).append((u, host))
        return [rounds[k] for k in sorted(rounds)]

    def run_rounds(self, gen, rounds):
        if gen != self.generation:
            return
        if not rounds:
            self.logger.info("FA-FRR gen %d groups installed: protected", gen)
            drain = max((self.gen_drain.get(g, 0.0) for g in self.gen_switches if g < gen),
                        default=0.0)
            self.spawn_after(drain, self.cleanup, gen)
            return
        touched = set()
        for u, host in rounds[0]:
            hp = self.plans[host][u]
            ip = self.hosts[host]["ip"]
            # OpenFlow drops output to the ingress port, so a packet whose backup
            # turns back to the neighbour it came from needs OFPP_IN_PORT: one
            # extra FF group (and in_port rule) for that neighbour only. Vias
            # used by earlier generations keep being updated, so their rules
            # never point at a stale group.
            vias = self.vias.setdefault((u, host), set())
            if hp.protected:
                vias.add(hp.detour[1])
            for via in [None] + sorted(vias):
                self.install_group(u, host, hp, ip, via)
            self.installed_primary[(u, host)] = hp.primary
            touched.add(u)
        self.barrier(touched, lambda: self.run_rounds(gen, rounds[1:]))

    def install_group(self, u, host, hp, ip, via, pinned=False):
        dp = self.datapaths[u]
        p, ofp = dp.ofproto_parser, dp.ofproto
        in_port = self.ports[(u, via)] if via else None

        def output(port):
            return p.OFPActionOutput(ofp.OFPP_IN_PORT if port == in_port else port)

        prim = self.ports[(u, hp.primary)]
        buckets = [] if pinned else [p.OFPBucket(watch_port=prim, watch_group=ofp.OFPG_ANY,
                                                 actions=[output(prim)])]
        if hp.protected:
            q = self.ports[(u, hp.detour[1])]
            t = self.tag_for(hp.tag_key)
            buckets.append(p.OFPBucket(watch_port=q, watch_group=ofp.OFPG_ANY, actions=[
                p.OFPActionPushVlan(0x8100),
                p.OFPActionSetField(vlan_vid=(t | ofp.OFPVID_PRESENT)),
                output(q)]))
        gid = self.gid_for(u, host, via)
        cmd = ofp.OFPGC_MODIFY if (u, gid) in self.groups_installed else ofp.OFPGC_ADD
        self.send(u, p.OFPGroupMod(dp, cmd, ofp.OFPGT_FF, gid, buckets))
        self.groups_installed.add((u, gid))
        if (u, host, via) not in self.primary_done:
            match = (p.OFPMatch(in_port=in_port, eth_type=ETH_IPV4, ipv4_dst=ip) if via
                     else p.OFPMatch(eth_type=ETH_IPV4, ipv4_dst=ip))
            self.flow(u, match, [p.OFPActionGroup(gid)],
                      PRIO_PRIMARY_IN_PORT if via else PRIO_PRIMARY, COOKIE_PRIMARY)
            self.primary_done.add((u, host, via))

    def cleanup(self, gen):
        if gen != self.generation:
            return
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
        down = (bool(msg.desc.state & ofp.OFPPS_LINK_DOWN)
                or bool(msg.desc.config & ofp.OFPPC_PORT_DOWN)
                or msg.reason == ofp.OFPPR_DELETE)
        # each end reports its own port; the link is live only when both ends are
        if down:
            self.ports_down.add((sw, peer))
        else:
            self.ports_down.discard((sw, peer))
        live = (sw, peer) not in self.ports_down and (peer, sw) not in self.ports_down
        self.link_change(edge(sw, peer), live)

    def link_change(self, e, live: bool):
        now = self.now()
        if not live:
            if e in self.down:
                return
            self.down.add(e)
            self.risk.record_failure(e, now, down=self.down)
            timer = self.held.pop(e, None)
            if timer is not None:
                timer.cancel()
                # the link carries no traffic, but its SRLG peers just got riskier
                if self.risk.shared_risk(e) - self.unusable() and self.lam > 0:
                    self.reoptimize()
                return
            self.logger.info("link %s DOWN: data plane already rerouted, re-optimising",
                             "-".join(sorted(e)))
            self.pin_backups(e)
            self.reoptimize()
        else:
            if e not in self.down:
                return
            self.down.discard(e)
            hd = self.risk.holddown(e, now, self.base_holddown)
            self.logger.info("link %s UP: hold-down %.1fs", "-".join(sorted(e)), hd)
            self.held[e] = hub.spawn_after(hd, self.release, e)

    def pin_backups(self, e):
        """Rewrite the groups next to a failed link with their backup bucket only.

        FF groups are revertive; pinning stops a link that comes back during
        re-optimisation from pulling traffic back (see ffr.apps.fa_frr).
        """
        a, b = sorted(e)
        for host, plans in self.plans.items():
            for u in (a, b):
                hp = plans.get(u)
                if hp is None or not hp.protected or hp.primary != (b if u == a else a):
                    continue
                if self.installed_primary.get((u, host)) != hp.primary:
                    continue  # not installed yet: nothing to pin
                ip = self.hosts[host]["ip"]
                for via in [None] + sorted(self.vias.get((u, host), ())):
                    self.install_group(u, host, hp, ip, via, pinned=True)

    def release(self, e):
        if self.held.pop(e, None) is not None and e not in self.down:
            self.logger.info("link %s stable: back in service", "-".join(sorted(e)))
            self.reoptimize()
