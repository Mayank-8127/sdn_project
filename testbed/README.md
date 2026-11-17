# Real testbed (OS-Ken/Ryu + Mininet + Open vSwitch)

The emulator in `ffr/` is where the algorithms are developed and evaluated.
This folder runs the **same FA-FRR planning code** against real OpenFlow 1.3
switches.

| File | Purpose | Needs |
|------|---------|-------|
| `ffr_osken_app.py` | the FA-FRR controller app (FF groups, VLAN-tagged detours, barriers, re-optimisation, hold-down) | os-ken (or ryu) |
| `run_controller.py` | launcher (os-ken 4.x has no `osken-manager` binary) | os-ken |
| `topo_export.py` | writes the topology JSON shared by Mininet and the controller | – |
| `mininet_ffr.py` | builds the topology in Mininet, injects a failure, measures loss/outage with 10 ms pings | root, Mininet, OVS |
| `run_experiments.sh` | runs every scenario several times and keeps the logs | root, Mininet, OVS, os-ken |
| `summarise.py` | turns the logs into `results/summary.md` | – |
| `test_osken_app.py` | unit tests with fake datapaths; every message is serialised to OpenFlow wire format | os-ken, pytest |
| `fake_switches.py` | integration test: fake switches over real TCP (handshake, barriers, PORT_STATUS) | os-ken |

## Setup

```bash
# Debian/Ubuntu
sudo apt install mininet openvswitch-switch
# Arch: openvswitch from the repositories, Mininet from source
#   (make mnexec; install it to /usr/local/bin; pip install .)
sudo systemctl start openvswitch-switch     # Arch: ovsdb-server ovs-vswitchd

python3.12 -m venv .venv-testbed
.venv-testbed/bin/pip install -r testbed/requirements.txt -e .
.venv-testbed/bin/pip install mininet       # or the Mininet source tree
```

## Checks without root

```bash
.venv-testbed/bin/python -m pytest testbed/test_osken_app.py      # 5 passed

.venv-testbed/bin/python -c "import sys; sys.path.insert(0,'testbed'); \
  from ffr import topology as T; from ffr.network import Network; from topo_export import export; \
  t=T.abilene().add_host_per_switch(); n=Network(t); \
  export(t, lambda a,b:n.switches[a].port_to(b), lambda h:n.switches[t.hosts[h]].port_to(h), '/tmp/t.json')"
.venv-testbed/bin/python testbed/run_controller.py --port 16653 --topo /tmp/t.json &
.venv-testbed/bin/python testbed/fake_switches.py --port 16653 --topo /tmp/t.json
# initial install: 525 flow adds, 220 group adds
# after DEN-KSC failure: 220 group modifies, 11 old-detour deletes
# OK
```

## Mininet experiments

One scenario by hand, in two terminals:

```bash
sudo .venv-testbed/bin/python testbed/mininet_ffr.py --topo abilene --fail DEN-KSC
FFR_TOPO=/tmp/ffr_topo.json .venv-testbed/bin/python testbed/run_controller.py
```

Variants: `--silent` (gray failure: the interfaces stay up, every frame is
dropped), `--bfd` (OVS BFD on the switch links), `--fail A-B,C-D` (several
links at the same instant), `--srlg NAME:A-B,C-D` (declare a shared risk
group), `--cli` (Mininet CLI at the end, e.g. `sh ovs-ofctl -O OpenFlow13
dump-groups s6`).

All scenarios, five runs each:

```bash
testbed/run_experiments.sh .venv-testbed/bin/python 5
```

## Results

Abilene, 11 OVS switches, link delays from fibre distance, 5 runs per
scenario, probed pairs whose shortest path crosses a failed link
(`testbed/results/`, regenerated with `run_experiments.sh`):

| scenario | runs | pairs | lost / pair | mean outage | worst outage | controller notified | re-optimisation |
|---|---:|---:|---:|---:|---:|---:|---:|
| link cut (DEN-KSC) | 5 | 30 | 1.6 | 12 ms | 20 ms | 6 ms | 36 ms |
| gray failure, no BFD | 5 | 30 | 181.0 | 1810 ms | 1830 ms | never | never |
| gray failure, OVS BFD 10 ms | 5 | 30 | 4.2 | 42 ms | 60 ms | never | never |
| duct cut (DEN-KSC + SNV-DEN), SRLG not declared | 5 | 60 | 4.7 | 46 ms | 90 ms | 9 ms | 51 ms |
| duct cut (DEN-KSC + SNV-DEN), SRLG declared | 5 | 60 | 2.2 | 20 ms | 40 ms | 8 ms | 52 ms |

* **Link cut:** OVS sees the carrier drop and the fast-failover group
  switches to the backup locally. Outages are 12 ms on average, about one
  10 ms probe plus the packets in flight on the dead link. The controller
  hears of the cut 6 ms later and has every group of the next generation in
  place 36 ms after that, while traffic is already on the backup.
* **Gray failure:** without BFD nothing notices the blackhole, and traffic is
  lost for the whole 1.8 s the failure lasts. With OVS BFD at 10 ms × 3 the
  fast-failover group reroutes and the outage drops to 42 ms. OVS does not
  report BFD failures to the controller, so no re-optimisation follows.
* **Duct cut:** when both links of the duct fail at once, a backup that uses
  the other link of the duct is dead too. If the shared risk group is
  declared, FA-FRR's backups avoid it, and the mean outage falls from 46 ms
  to 20 ms (worst case from 90 to 40 ms). Without the declaration those flows
  wait for the controller's re-optimisation (about 50 ms) instead.

The re-optimisation column is measured from the controller's notification to
the log line `groups installed: protected`, when every group points at the
new generation; old detour rules are deleted after a further drain time.

## Notes on OpenFlow and Open vSwitch

* **U-turn backups.** OpenFlow drops a packet that is output to the port it
  arrived on. When a backup path starts by going back towards the previous
  switch, the bucket must use `OFPP_IN_PORT`. That only happens for packets
  that arrive from the backup's first hop, so for every (switch, destination)
  the app installs the default FF group plus one more for that neighbour,
  selected by an `in_port` rule. Tagged detour rules never need it, because a
  detour is a simple path.
* **Loop-free updates.** After a failure the app first pins the groups next to
  the failed link to their backup bucket (FF groups are revertive), then
  installs the new generation's detour rules, then rewrites the groups in
  rounds separated by barriers so that a switch only moves to its new next
  hop once the switches downstream of it on the new path have moved, and
  finally deletes the old detour rules after a drain time.
* **Two ends, two reports.** Each end of a link sends its own `PORT_STATUS`,
  and the end taken down administratively reports `OFPPC_PORT_DOWN` with a
  live state. The app keeps the state of each end and treats the link as up
  only when both ends are up.
* **BFD and the controller.** With `bfd:enable=true`, OVS uses the BFD session
  state for fast-failover liveness, so the data plane reroutes a gray failure.
  It does not send `PORT_STATUS` for a BFD-detected failure, so the
  controller does not re-optimise until the carrier changes.
* Emulated link delays use `tc netem` (TCLink); sub-millisecond accuracy is
  not guaranteed, and pings at 10 ms intervals give outages to the nearest
  10 ms.
* Tags are VLAN ids 2–4001; very large topologies with many generations
  would need MPLS labels instead.
