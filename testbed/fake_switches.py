#!/usr/bin/env python3
"""Integration check without Mininet: fake OpenFlow 1.3 switches over TCP.

Each fake switch opens a real TCP connection to the controller, performs the
OpenFlow handshake (HELLO, FEATURES, port description), answers barriers and
echo requests, and records every FLOW_MOD / GROUP_MOD it receives. After the
initial installation it reports a link failure (PORT_STATUS) and checks that
the controller re-optimises (new groups + deletion of the old detour rules).

    python3 testbed/run_controller.py --port 16653 --topo /tmp/t.json &
    python3 testbed/fake_switches.py --port 16653 --topo /tmp/t.json

Exit status 0 means the controller behaved as expected.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import threading
import time

from os_ken.ofproto import ofproto_parser, ofproto_v1_3 as ofp, ofproto_v1_3_parser as parser


class _DP:
    """Just enough of a datapath for os-ken's serialisers."""
    ofproto = ofp
    ofproto_parser = parser


# os-ken only knows how to *encode* controller->switch messages, so the few
# switch->controller messages are packed by hand (OpenFlow 1.3 wire format).
def _header(mtype, body, xid=0):
    return struct.pack("!BBHI", ofp.OFP_VERSION, mtype, 8 + len(body), xid) + body


def _port(no, name, state=0):
    return struct.pack(ofp.OFP_PORT_PACK_STR, no, bytes([0, 0, 0, 0, 0, no % 256]),
                       name.encode()[:15], 0, state, 0, 0, 0, 0, 0, 0)


class FakeSwitch(threading.Thread):
    def __init__(self, name, dpid, ports, host, port):
        super().__init__(daemon=True)
        self.name, self.dpid, self.ports = name, dpid, ports
        self.sock = socket.create_connection((host, port))
        self.dp = _DP()
        self.flow_adds = self.flow_deletes = self.group_adds = self.group_mods = 0
        self.lock = threading.Lock()
        self.last_activity = time.time()

    def send(self, msg, xid=0):
        msg.xid = xid
        msg.serialize()
        self.sock.sendall(msg.buf)

    def send_raw(self, data: bytes):
        self.sock.sendall(data)

    def recv_msgs(self):
        buf = b""
        while True:
            data = self.sock.recv(65536)
            if not data:
                return
            buf += data
            while len(buf) >= 8:
                version, mtype, length, xid = ofproto_parser.header(buf)
                if len(buf) < length:
                    break
                raw, buf = buf[:length], buf[length:]
                yield mtype, xid, raw

    def run(self):
        self.send(parser.OFPHello(self.dp))
        for mtype, xid, raw in self.recv_msgs():
            self.last_activity = time.time()
            if mtype == ofp.OFPT_FEATURES_REQUEST:
                body = struct.pack(ofp.OFP_SWITCH_FEATURES_PACK_STR, self.dpid, 0, 1, 0, 0, 0)
                self.send_raw(_header(ofp.OFPT_FEATURES_REPLY, body, xid))
            elif mtype == ofp.OFPT_MULTIPART_REQUEST:
                body = struct.pack("!HH4x", ofp.OFPMP_PORT_DESC, 0) + b"".join(
                    _port(p, f"{self.name}-eth{p}") for p in self.ports)
                self.send_raw(_header(ofp.OFPT_MULTIPART_REPLY, body, xid))
            elif mtype == ofp.OFPT_ECHO_REQUEST:
                self.send_raw(_header(ofp.OFPT_ECHO_REPLY, b"", xid))
            elif mtype == ofp.OFPT_BARRIER_REQUEST:
                self.send_raw(_header(ofp.OFPT_BARRIER_REPLY, b"", xid))
            elif mtype == ofp.OFPT_FLOW_MOD:
                (command,) = struct.unpack_from("!B", raw, 8 + 8 + 8 + 1)
                with self.lock:
                    if command == ofp.OFPFC_ADD:
                        self.flow_adds += 1
                    elif command == ofp.OFPFC_DELETE:
                        self.flow_deletes += 1
            elif mtype == ofp.OFPT_GROUP_MOD:
                (command,) = struct.unpack_from("!H", raw, 8)
                with self.lock:
                    if command == ofp.OFPGC_ADD:
                        self.group_adds += 1
                    else:
                        self.group_mods += 1

    def link_down(self, port_no):
        body = struct.pack("!B7x", ofp.OFPPR_MODIFY) + _port(
            port_no, f"{self.name}-eth{port_no}", ofp.OFPPS_LINK_DOWN)
        self.send_raw(_header(ofp.OFPT_PORT_STATUS, body))


def wait_quiet(switches, quiet=1.0, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if all(time.time() - s.last_activity > quiet for s in switches):
            return True
        time.sleep(0.2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=6653)
    ap.add_argument("--topo", required=True)
    ap.add_argument("--fail", default="DEN-KSC")
    args = ap.parse_args()
    spec = json.load(open(args.topo))
    ports = {s["name"]: [] for s in spec["switches"]}
    for l in spec["links"]:
        ports[l["a"]].append(l["a_port"])
        ports[l["b"]].append(l["b_port"])
    for h in spec["hosts"]:
        ports[h["switch"]].append(h["port"])
    sws = {s["name"]: FakeSwitch(s["name"], s["dpid"], ports[s["name"]], "127.0.0.1", args.port)
           for s in spec["switches"]}
    for s in sws.values():
        s.start()
    time.sleep(1.0)
    wait_quiet(sws.values())
    flows = sum(s.flow_adds for s in sws.values())
    groups = sum(s.group_adds for s in sws.values())
    print(f"initial install: {flows} flow adds, {groups} group adds")
    # per switch and remote host: a default FF group plus one per ingress neighbour
    expected = (len(spec["hosts"]) - 1) * (len(spec["switches"]) + 2 * len(spec["links"]))
    ok = flows > 0 and groups == expected

    a, b = args.fail.split("-")
    link = next(l for l in spec["links"] if {l["a"], l["b"]} == {a, b})
    sws[link["a"]].link_down(link["a_port"])
    sws[link["b"]].link_down(link["b_port"])
    time.sleep(1.0)
    wait_quiet(sws.values())
    mods = sum(s.group_mods for s in sws.values())
    deletes = sum(s.flow_deletes for s in sws.values())
    print(f"after {args.fail} failure: {mods} group modifies, {deletes} old-detour deletes")
    ok = ok and mods > 0 and deletes > 0
    print("OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
