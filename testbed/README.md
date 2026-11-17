# Real testbed (OS-Ken/Ryu + Mininet + Open vSwitch)

The emulator in `ffr/` is where the algorithms are developed and evaluated.
This folder runs the **same FA-FRR planning code** against real OpenFlow 1.3
switches.

| File | Purpose | Needs |
|------|---------|-------|
| `ffr_osken_app.py` | the FA-FRR controller app (FF groups, VLAN-tagged detours, barriers, re-optimisation, hold-down) | os-ken (or ryu) |
| `run_controller.py` | launcher (os-ken 4.x has no `osken-manager` binary) | os-ken |
| `topo_export.py` | writes the topology JSON shared by Mininet and the controller | – |
| `mininet_ffr.py` | builds the topology in Mininet, injects a failure, measures loss/outage with timestamped pings | root, Mininet, OVS |
| `run_experiments.sh` | runs every scenario several times and keeps the logs | root, Mininet, OVS, os-ken |
| `summarise.py` | turns a results folder's logs into its `summary.md` | – |
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
scenario, probed pairs whose shortest path crosses a failed link, probes
requested every 2 ms. The paper's Table IX comes from two folders:

```bash
PING_MS=2 RESULTS=testbed/results-2ms testbed/run_experiments.sh .venv-testbed/bin/python 5
PING_MS=2 CTRL_DELAY_MS=5 RESULTS=testbed/results-wan testbed/run_experiments.sh .venv-testbed/bin/python 5
python3 testbed/summarise.py testbed/results-2ms     # also written to its summary.md
```

Local controller (`results-2ms/`):

| scenario | pairs | probe gap | lost / pair | bursts / pair | mean outage | worst outage | controller notified | re-optimisation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| link cut (DEN-KSC) | 30 | 9.1 ms | 2.3 | 1.5 | 15 ms | 20 ms | 8 ms | 34 ms |
| gray failure, no BFD | 30 | 9.4 ms | 198.0 | 1.0 | 1856 ms | 1960 ms | never | never |
| gray failure, OVS BFD 10 ms | 30 | 8.2 ms | 5.0 | 1.0 | 41 ms | 59 ms | never | never |
| duct cut, SRLG not declared | 60 | 9.3 ms | 5.9 | 1.1 | 52 ms | 98 ms | 8 ms | 56 ms |
| duct cut, SRLG declared | 60 | 8.8 ms | 3.3 | 1.2 | 26 ms | 49 ms | 10 ms | 63 ms |

5 ms one-way delay on the OpenFlow channel (`results-wan/`):

| scenario | pairs | probe gap | lost / pair | bursts / pair | mean outage | worst outage | controller notified | re-optimisation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| link cut (DEN-KSC) | 30 | 9.2 ms | 2.1 | 1.7 | 13 ms | 20 ms | 12 ms | 77 ms |
| gray failure, no BFD | 30 | 9.4 ms | 198.0 | 1.0 | 1852 ms | 1970 ms | never | never |
| gray failure, OVS BFD 10 ms | 30 | 8.1 ms | 5.1 | 1.0 | 41 ms | 59 ms | never | never |
| duct cut, SRLG not declared | 60 | 9.3 ms | 7.7 | 1.1 | 70 ms | 152 ms | 13 ms | 107 ms |
| duct cut, SRLG declared | 60 | 8.9 ms | 3.2 | 1.2 | 27 ms | 56 ms | 14 ms | 104 ms |

The duct cut is DEN-KSC + SNV-DEN.

* **Link cut:** OVS sees the carrier drop and the fast-failover group
  switches to the backup locally, so the outage (13–15 ms, one or two
  probes) does not depend on the control channel. The controller hears of
  the cut 8 ms later (12 ms with the delayed channel) and has every group of
  the next generation in place 34 ms after that (77 ms with the delayed
  channel, about four barrier round trips of 10 ms more). In about half of
  the pairs one more probe is lost about 40 ms after the failure, while the
  update is under way; that is why lost/pair is above mean outage / probe
  gap.
* **Gray failure:** without BFD nothing notices the blackhole, and every
  probe in the 2 s failure is lost. With OVS BFD at 10 ms × 3 the
  fast-failover group reroutes and the outage drops to 41 ms. OVS does not
  report BFD failures to the controller, so no re-optimisation follows.
* **Duct cut:** when both links of the duct fail at once, a backup that uses
  the other link of the duct is dead too. If the shared risk group is
  declared, FA-FRR's backups avoid it, and the mean outage halves (52 to
  26 ms). Without the declaration those flows wait for the controller's
  re-optimisation, so their outage grows with the control-channel delay
  (70 ms, worst 152 ms, with 5 ms); with the declaration it does not.

The re-optimisation column is measured from the controller's notification to
the log line `groups installed: protected`, when every group points at the
new generation; old detour rules are deleted after a further drain time.

**How outages are measured.** `ping -i` only sets a minimum interval; with a
dozen pings on one machine the real pace is 8–9.5 ms, which the summary
reports as the probe gap. Each ping writes timestamped replies (`ping -D`)
to its own file. `mininet_ffr.py` now computes each reply's send time
(timestamp minus round-trip time) and reports the longest gap between the
send times of answered probes, minus the median gap (`send-time outage`).
The gap between reply timestamps is not used: it also contains the extra
round-trip time of a longer detour (23 → 72 ms for ATL–DEN after the duct
cut). The logs in `results-2ms/` and `results-wan/` were written by the
previous version, which printed the reply gap; for these `summarise.py`
uses the probes lost in the longest burst times the probe gap, which agrees
with the send-time gap to within one probe gap. Bursts made only of
reordered replies (when the path gets shorter again after the hold-down)
are not losses and are not counted.

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
  not guaranteed, and outages are resolved to about one probe (8–9.5 ms).
* Tags are VLAN ids 2–4001; very large topologies with many generations
  would need MPLS labels instead.
