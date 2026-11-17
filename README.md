# Failure-Aware Fast Rerouting in Software-Defined Networks

Course project for **Software Defined Networks (EC-466)**, guided by
**Dr. Jagadeesha R B**.

| Name | Roll number |
|------|-------------|
| Mayank Bansal | 23BEC026 |
| Himanshu Kumar | 23BCS055 |
| Anas Khan | 23BCS083 |
| Shardendu Mishra | 23BCS122 |

This project designs and evaluates **Failure-Aware Fast Reroute (FA-FRR)**, a
failure-recovery scheme for OpenFlow networks. Switches recover from a failure
in milliseconds with pre-installed fast-failover backups, while the controller
learns how the network fails and keeps the backups up to date. It has:

* a deterministic **OpenFlow emulator** in pure Python (flow tables, group
  tables with fast-failover, port liveness, control-channel delay, rule
  installation time, loss-of-signal, BFD, LLDP, barriers);
* **controller strategies**: `static`, `reactive`, `frr-link`, `frr-node`,
  `frr-srlg`, `e2e`, `e2e-srlg` and the proposed `fa-frr` (plus FA-FRR
  ablations that switch off one mechanism each, used by the experiments);
* an **evaluation suite** of 4634 simulations on the Abilene and NSFNET
  backbones that regenerates every result in the paper;
* a port of FA-FRR to a real **OpenFlow 1.3 controller** (OS-Ken) for
  Mininet and Open vSwitch, with the results of the Mininet runs.

The paper is `paper/Failure_Aware_Fast_Rerouting_in_Software_Defined_Networks.pdf`.

## Headline result

| | reactive | local FRR | end-to-end | **FA-FRR** |
|---|---:|---:|---:|---:|
| mean outage, single link cut (Abilene) | 23 ms | 6 ms | 19 ms | **6 ms** |
| survives correlated (SRLG) double failures (Abilene) | 100 % | 33 % | 33 % | **100 %** |
| survives a second failure 200 ms later (Abilene) | 100 % | 25 % | 15 % | **100 %** |
| packets lost on a flapping link | 1,142 | 273 | – | **82** |

## 1. Requirements

* Linux, macOS or Windows (WSL) with **Python 3.10 or newer**.
* About 200 MB of disk for the virtual environment.
* Optional, only for the real testbed: Linux, root access, Mininet and Open
  vSwitch (Section 6).

## 2. Setup

Run these from the project folder (the one containing this README):

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

`pip install -e .` makes the `ffr` package importable from anywhere. The
emulator has no dependencies outside the standard library; `matplotlib`
draws the figures and `pytest` runs the tests.

## 3. Check the installation

```bash
python -m pytest -q
```

Expected: `129 passed` in about a minute.

## 4. Run one scenario

Abilene, traffic between all host pairs, link DEN–KSC cut at 0.4 s:

```bash
python -m ffr run --topo abilene --app reactive --fail DEN-KSC@0.4
python -m ffr run --topo abilene --app fa-frr   --fail DEN-KSC@0.4 -v
```

Each run prints one summary line: packets sent and lost, flows affected,
flows that never recovered and the longest outage. `-v` also prints the
controller's log and every affected flow.

More examples:

```bash
# two links in the same duct (a shared risk link group) fail together
python -m ffr run --topo abilene --app frr-node --srlg duct:DEN-KSC,SNV-DEN --fail DEN-KSC@0.4 --fail SNV-DEN@0.4
python -m ffr run --topo abilene --app fa-frr   --srlg duct:DEN-KSC,SNV-DEN --fail DEN-KSC@0.4 --fail SNV-DEN@0.4

# a silent (gray) failure, detected by BFD
python -m ffr run --topo abilene --app fa-frr --detection los+bfd --fail-silent DEN-KSC@0.4

# a switch crash (the flows to and from KSC itself cannot recover)
python -m ffr run --topo abilene --app fa-frr --fail-node KSC@0.4

# print the flow and group tables of one switch
python -m ffr run --topo ring6 --app frr-link --flows 1 --tables s1

# all options, and the built-in topologies
python -m ffr run --help
python -m ffr topos
```

## 5. Reproduce the results and figures of the paper

### 5.1 All simulation results

```bash
python -m ffr experiment --out results
```

This runs the 4634 simulations on all CPU cores (about 41 minutes on 16 cores)
and writes into `results/`: one CSV file per experiment, the figures, and
`REPORT.md` with every summary table. The copy shipped with the project is in
`docs/results/`. The emulator is deterministic: every table in the new
`REPORT.md` is identical to `docs/results/REPORT.md`, and every value in the
CSV files matches except the `wall_s` column (wall-clock time per run). With
a different Python version the last digit of a floating-point value may
differ (relative difference below 1e-14), because Python 3.12 changed how
`sum()` rounds.

`python -m ffr experiment --quick --out results-quick` runs a reduced suite
in about 2 minutes. One experiment alone: `python -m ffr experiment srlg --out results`
(names: `timeline single_link node_crash gray bfd_tradeoff srlg sequential
flapping flapping_long gap loops srlg_followup risk_dynamic install_time duct_repair
sensitivity state risk_tradeoff`).

### 5.2 Paper figures

```bash
python paper/make_figures.py
```

reads `docs/results/*.csv` and writes the paper's figures to `paper/figures/`.

### 5.3 Where each number in the paper comes from

| Paper | Source file | Command |
|---|---|---|
| Fig. 2 (timeline) | `docs/results/timeline.csv`, `timeline.png` | `python -m ffr experiment timeline` |
| Figs. 3–4, Table III | `single_link.csv`, `node_crash.csv`, `srlg.csv`, `sequential.csv` | `python -m ffr experiment single_link node_crash srlg sequential` |
| Fig. 5 (gap sweep) | `gap.csv` | `python -m ffr experiment gap` |
| Fig. 6 (re-protection time) | `install_time.csv` (planning times in `REPORT.md`) | `python -m ffr experiment install_time` |
| Table IV (loops) | `loops.csv` | `python -m ffr experiment loops` |
| Table V, Fig. 7 | `gray.csv`, `bfd_tradeoff.csv` | `python -m ffr experiment gray bfd_tradeoff` |
| Table VI (flapping), sensitivity | `flapping.csv`, `flapping_long.csv`, `sensitivity.csv` | `python -m ffr experiment flapping flapping_long sensitivity` |
| Fig. 8, Table VII, duct repair | `risk_tradeoff.csv`, `risk_dynamic.csv`, `srlg_followup.csv`, `duct_repair.csv` | `python -m ffr experiment risk_tradeoff risk_dynamic srlg_followup duct_repair` |
| Table VIII (state) | `state.csv`, peak, tag and link-load columns of the other CSVs | `python -m ffr experiment state single_link` |
| Table VIII, OpenFlow 1.3 column | controller against protocol stubs | `python testbed/of13_state.py` (needs `testbed/requirements.txt`) |
| Re-protection time of one cut | controller log | `python -m ffr run --topo abilene --app fa-frr --fail DEN-KSC@0.45 --rate 500 --stop 1.2 -v` |
| Table IX (Mininet) | `testbed/results-2ms/summary.md`, `testbed/results-wan/summary.md` | `testbed/run_experiments.sh` (Section 6) |

### 5.4 Data, parameters and seeds

* **All data is synthetic.** Traffic is constant-bit-rate between every pair
  of hosts, and failures are injected at fixed times. There is no external
  dataset to download. The topologies are built into `ffr/topology.py`:
  Abilene (11 switches, 14 links, delays of 5 µs per km of fibre distance) and
  NSFNET (14 switches, 21 links, 2 ms each).
* **Simulation parameters** (defaults in `ffr/controller.py`,
  `ffr/network.py`, `ffr/experiments/runner.py`): controller one-way delay
  5 ms, controller computation 5 ms, rule installation 1 ms per rule,
  loss-of-signal detection 1 ms, BFD 3.3 ms × 3, 500 packets/s per flow
  (1000 in the timeline), traffic from 250 to 800 ms, first failure at 450 ms.
* **FA-FRR parameters** (`ffr/apps/fa_frr.py`, `ffr/risk.py`): λ = 5, risk
  half-life 5 s, flap penalty 0.3, SRLG correlation 0.5, base hold-down
  200 ms, probability cap 0.99, coincidence window 50 ms.
* **Seeds** (`ffr/experiments/suite.py`, Python `random.Random`): link
  samples seed 7, SRLG pairs seed 3, sequential pairs seed 11 (the first 10
  for the gap sweep), link failure priors seed 5, prior-weighted failures
  seed 13, BFD start phases seed 0, control-channel jitter seeded per run.

## 6. Real testbed (optional: Mininet + Open vSwitch)

The controller in `testbed/` drives real OpenFlow 1.3 switches and reuses the
emulator's planning code. Full details are in `testbed/README.md`.

### 6.1 Checks without root

```bash
pip install -r testbed/requirements.txt
python -m pytest -q testbed/test_osken_app.py
```

Expected: `7 passed`. These tests serialise every controller message to the
OpenFlow wire format.

The controller can also be run against simulated switches over real TCP. In
one terminal, write the Abilene topology file and start the controller:

```bash
python -c "import sys; sys.path.insert(0, 'testbed'); from ffr import topology as T; from ffr.network import Network; from topo_export import export; t = T.abilene().add_host_per_switch(); n = Network(t); export(t, lambda a, b: n.switches[a].port_to(b), lambda h: n.switches[t.hosts[h]].port_to(h), 'topo.json')"
python testbed/run_controller.py --port 16653 --topo topo.json
```

In a second terminal (same folder, virtual environment activated):

```bash
python testbed/fake_switches.py --port 16653 --topo topo.json
```

Expected output, then stop the controller with Ctrl+C:

```
initial install: 525 flow adds, 220 group adds
after DEN-KSC failure: 220 group modifies, 11 old-detour deletes
OK
```

### 6.2 Mininet experiments (root required)

The Python that runs the experiments needs both `os-ken` and the Mininet
package, and Open vSwitch must be running.

```bash
# Ubuntu/Debian: Mininet's mnexec and Open vSwitch from the OS
sudo apt install mininet openvswitch-switch
sudo systemctl start openvswitch-switch
# Arch: openvswitch from the repositories, Mininet from source (AUR)
#   sudo systemctl start ovsdb-server ovs-vswitchd

# the Mininet Python package in the project's virtual environment
pip install -r testbed/requirements.txt
pip install mininet          # or: pip install /path/to/mininet-source-tree
python -c "import mininet, os_ken"    # must print nothing
```

Then run all five scenarios, five runs each, in the two settings the paper
reports (Table IX): probes every 2 ms, without and with a 5 ms one-way delay
on the OpenFlow channel (a `tc netem` delay on loopback that only affects the
controller's port). Do not run them while the emulator suite is running,
since that would distort the timings:

```bash
PING_MS=2 RESULTS=testbed/results-2ms testbed/run_experiments.sh "$(pwd)/.venv/bin/python" 5
```

```bash
PING_MS=2 CTRL_DELAY_MS=5 RESULTS=testbed/results-wan testbed/run_experiments.sh "$(pwd)/.venv/bin/python" 5
```

`run_experiments.sh` calls `sudo` for Mininet, so it may ask for your
password. It writes one log per run and regenerates
`summary.md` in the results folder with `testbed/summarise.py`. If a run log says
"Mininet is not installed", the Python passed to the script cannot import
`mininet`. To run one scenario by hand, or for the scenario options, see
`testbed/README.md`. The logs of the runs reported in the paper are in
`testbed/results-2ms/` and `testbed/results-wan/`.

## 7. Rebuild the project report and slides (optional)

```bash
pip install -r docs/report/requirements.txt    # also needs LibreOffice and poppler-utils
python docs/report/build_figures.py
python docs/report/build_report.py
python docs/report/build_slides.py
```

## Project layout

```
ffr/                     emulator and controller strategies
  sim.py                 discrete-event engine
  topology.py            topologies (Abilene, NSFNET, rings, grids), SRLGs, priors
  openflow.py            matches, actions, flow table, groups, messages
  network.py             links, ports, hosts, OpenFlow switches, failures
  detection.py           loss of signal, BFD, multi-hop BFD
  controller.py          controller base: channel delay, LLDP, barriers
  routing.py             Dijkstra, next-hop trees, Bhandari disjoint paths
  protection.py          backup (detour) planning
  risk.py                failure-aware risk model
  apps/                  static, reactive, frr, e2e, fa_frr
  experiments/           evaluation suite, parallel runner, plots, report
tests/                   pytest suite for the emulator
testbed/                 OS-Ken controller, Mininet scripts, wire-level tests, Mininet logs
docs/results/            simulation results (CSV, figures, REPORT.md)
docs/report/             project report and presentation, with their build scripts
paper/                   IEEE paper (PDF) and the script that draws its figures
requirements.txt         Python packages for the emulator, experiments and tests
```
