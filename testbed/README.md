# Real-testbed port (OS-Ken/Ryu + Mininet + Open vSwitch)

The emulator in `ffr/` is where the algorithms are developed and evaluated.
This folder runs the **same FA-FRR planning code** against real OpenFlow 1.3
switches.

| File | Purpose | Needs |
|------|---------|-------|
| `ffr_osken_app.py` | the FA-FRR controller app (FF groups, VLAN-tagged detours, barriers, re-optimisation, hold-down) | os-ken (or ryu) |
| `run_controller.py` | launcher (os-ken 4.x has no `osken-manager` binary) | os-ken |
| `topo_export.py` | writes the topology JSON shared by Mininet and the controller | — |
| `mininet_ffr.py` | builds the topology in Mininet, injects a failure, measures loss/outage with 10 ms pings | root, Mininet, OVS |
| `test_osken_app.py` | unit tests with fake datapaths; every message is serialised to OpenFlow wire format | os-ken, pytest |
| `fake_switches.py` | integration test: fake switches over real TCP (handshake, barriers, PORT_STATUS) | os-ken |

## Verified in this repository (no root needed)

```bash
python3.10 -m venv /tmp/osken && /tmp/osken/bin/pip install -r testbed/requirements.txt -e .
/tmp/osken/bin/python -m pytest testbed/test_osken_app.py          # 3 passed

/tmp/osken/bin/python -c "import sys; sys.path.insert(0,'testbed'); \
  from ffr import topology as T; from ffr.network import Network; from topo_export import export; \
  t=T.abilene().add_host_per_switch(); n=Network(t); \
  export(t, lambda a,b:n.switches[a].port_to(b), lambda h:n.switches[t.hosts[h]].port_to(h), '/tmp/t.json')"
/tmp/osken/bin/python testbed/run_controller.py --port 16653 --topo /tmp/t.json &
/tmp/osken/bin/python testbed/fake_switches.py --port 16653 --topo /tmp/t.json
# initial install: 415 flow adds, 110 group adds
# after DEN-KSC failure: 110 group modifies, 11 old-detour deletes
# OK
```

## Full Mininet run (requires root; not executed by the author's CI)

```bash
# terminal 1
sudo python3 testbed/mininet_ffr.py --topo abilene --fail DEN-KSC            # cut
sudo python3 testbed/mininet_ffr.py --topo abilene --fail DEN-KSC --silent --bfd   # gray failure
# terminal 2 (once the topology file is written)
FFR_TOPO=/tmp/ffr_topo.json python3 testbed/run_controller.py
```

Expected behaviour: pairs crossing DEN–KSC lose a handful of 10 ms probes on a
cut (OVS carrier detection), recover without controller involvement, and the
controller log shows `FA-FRR gen 2` after the failure.

Caveats (honest list):
* OVS uses BFD for fast-failover liveness when `bfd:enable=true`; whether it
  also emits `PORT_STATUS` with `OFPPS_LINK_DOWN` on a BFD-only (gray) failure
  depends on the OVS version. If not, the data plane still reroutes, but the
  controller does not re-optimise until the carrier changes.
* Emulated link delays use `tc netem` (TCLink); sub-millisecond accuracy is not
  guaranteed.
* Tags are VLAN ids 2–4001; very large topologies with many generations
  would need MPLS labels instead.
