"""Exercise the OS-Ken app against fake datapaths (no Mininet needed).

Every OpenFlow message the app emits is serialised to wire format, so the
test catches malformed matches/actions/groups. Run with an environment that
has os-ken installed::

    pip install os-ken && python -m pytest testbed/test_osken_app.py
"""

import itertools
import os
import sys

import pytest

os_ken = pytest.importorskip("os_ken")
from os_ken.ofproto import ofproto_v1_3 as ofp, ofproto_v1_3_parser as parser  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from ffr import topology as T  # noqa: E402
from ffr.network import Network  # noqa: E402
from topo_export import export  # noqa: E402

_xid = itertools.count(1)


class FakeDP:
    def __init__(self, dpid):
        self.id = dpid
        self.ofproto = ofp
        self.ofproto_parser = parser
        self.sent = []

    def set_xid(self, msg):
        if msg.xid is None:
            msg.xid = next(_xid)

    def send_msg(self, msg):
        self.set_xid(msg)
        msg.serialize()  # must encode as valid OpenFlow 1.3
        self.sent.append(msg)


class Ev:
    def __init__(self, msg):
        self.msg = msg


@pytest.fixture
def app(tmp_path):
    topo = T.abilene().add_host_per_switch()
    topo.add_srlg("duct", ("DEN", "KSC"), ("SNV", "DEN"))
    net = Network(topo)
    path = str(tmp_path / "topo.json")
    export(topo, lambda a, b: net.switches[a].port_to(b),
           lambda h: net.switches[topo.hosts[h]].port_to(h), path)
    from ffr_osken_app import FailureAwareFRRApp
    a = FailureAwareFRRApp(topo_path=path)
    a.fake = {}
    for name, dpid in a.dpids.items():
        dp = FakeDP(dpid)
        a.fake[name] = dp
        feat = parser.OFPSwitchFeatures(dp)
        a.on_features(Ev(feat))
    return a


def answer_barriers(app):
    """Reply to every outstanding barrier until the app is quiet."""
    answered = set()
    while True:
        todo = [(dp, m) for dp in app.fake.values() for m in dp.sent
                if isinstance(m, parser.OFPBarrierRequest) and (dp.id, m.xid) not in answered]
        if not todo:
            return
        for dp, m in todo:
            answered.add((dp.id, m.xid))
            reply = parser.OFPBarrierReply(dp)
            reply.xid = m.xid
            app.on_barrier(Ev(reply))


def of_type(app, sw, cls):
    return [m for m in app.fake[sw].sent if isinstance(m, cls)]


def test_initial_install_is_complete_and_valid(app):
    answer_barriers(app)
    assert app.generation == 1
    for sw in app.dpids:
        groups = of_type(app, sw, parser.OFPGroupMod)
        # per remote destination host: a default FF group plus one per ingress neighbour
        assert len(groups) == 10 * (1 + len(app.graph.adj[sw]))
        assert all(g.type == ofp.OFPGT_FF for g in groups)
        assert all(len(g.buckets) == 2 for g in groups)  # Abilene is 2-connected
    # detour rules match on a VLAN tag
    den = of_type(app, "DEN", parser.OFPFlowMod)
    assert any("vlan_vid" in dict(m.match.items()) for m in den)


def port_status(app, sw, peer, state=ofp.OFPPS_LINK_DOWN, config=0):
    dp = app.fake[sw]
    port = app.ports[(sw, peer)]
    desc = parser.OFPPort(port, "00:00:00:00:00:01", f"{sw}-eth{port}", config,
                          state, 0, 0, 0, 0, 0, 0)
    app.on_port_status(Ev(parser.OFPPortStatus(dp, ofp.OFPPR_MODIFY, desc)))


def port_down(app, sw, peer):
    port_status(app, sw, peer)


def test_failure_triggers_hitless_reoptimisation(app):
    answer_barriers(app)
    before = {sw: len(dp.sent) for sw, dp in app.fake.items()}
    port_down(app, "DEN", "KSC")
    port_down(app, "KSC", "DEN")  # duplicate report from the other end
    answer_barriers(app)
    assert app.generation == 2
    for plans in app.plans.values():
        for hp in plans.values():
            assert {hp.switch, hp.primary} != {"DEN", "KSC"}
    # groups were modified (not re-added) and old detours deleted by cookie
    new = [m for m in app.fake["DEN"].sent[before["DEN"]:]]
    assert any(isinstance(m, parser.OFPGroupMod) and m.command == ofp.OFPGC_MODIFY for m in new)
    deletes = [m for dp in app.fake.values() for m in dp.sent
               if isinstance(m, parser.OFPFlowMod) and m.command == ofp.OFPFC_DELETE]
    assert deletes and all(m.cookie == 1001 for m in deletes)


def test_srlg_sibling_is_avoided_by_backups(app):
    answer_barriers(app)
    from ffr.routing import edge
    sib = edge("SNV", "DEN")
    for plans in app.plans.values():
        hp = plans.get("DEN")
        if hp and hp.protected and edge("DEN", hp.primary) == edge("DEN", "KSC"):
            used = {edge(a, b) for a, b in zip(hp.detour, hp.detour[1:])}
            assert sib not in used


def test_link_stays_down_until_both_ends_are_up(app):
    answer_barriers(app)
    from ffr.routing import edge
    e = edge("DEN", "KSC")
    # OVS: the end taken down administratively reports PORT_DOWN with a live state,
    # the far end loses carrier
    port_status(app, "DEN", "KSC", state=ofp.OFPPS_LIVE, config=ofp.OFPPC_PORT_DOWN)
    port_down(app, "KSC", "DEN")
    port_status(app, "KSC", "DEN", state=ofp.OFPPS_LIVE)  # one end recovers
    assert e in app.down and e not in app.held
    port_status(app, "DEN", "KSC", state=ofp.OFPPS_LIVE)  # both ends up
    assert e not in app.down and e in app.held


def test_backup_back_through_the_ingress_port_uses_in_port(app):
    """OpenFlow drops output to the ingress port; a U-turn must use OFPP_IN_PORT."""
    answer_barriers(app)
    uturns = 0
    for host, plans in app.plans.items():
        for u, hp in plans.items():
            if not hp.protected:
                continue
            back = hp.detour[1]
            gid = app.gids[(u, host, back)]
            mod = [m for m in of_type(app, u, parser.OFPGroupMod) if m.group_id == gid][-1]
            out = [a.port for a in mod.buckets[1].actions if isinstance(a, parser.OFPActionOutput)]
            assert out == [ofp.OFPP_IN_PORT]
            assert mod.buckets[1].watch_port == app.ports[(u, back)]
            uturns += 1
    assert uturns > 0
