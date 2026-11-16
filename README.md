# Failure-Aware Fast Rerouting in SDN

An implementation and evaluation of **fast failure recovery in
Software-Defined Networks**:

* a deterministic **OpenFlow emulator** in pure Python (flow tables, group
  tables with fast-failover, port liveness, control-channel latency, rule
  installation time, BFD, LLDP, barriers),
* six **controller strategies**, from "no recovery" to **Failure-Aware Fast
  Reroute (FA-FRR)**,
* an **evaluation suite** (850 simulations on Abilene and NSFNET) with a
  generated report,
* a **real-testbed port** for OS-Ken/Ryu + Mininet + Open vSwitch, validated
  on Abilene in Mininet.

## Headline result

| | reactive | local FRR | end-to-end | **FA-FRR** |
|---|---:|---:|---:|---:|
| mean outage, single link cut (Abilene) | 23 ms | 6 ms | 19 ms | **6 ms** |
| survives correlated (SRLG) double failures | 100 % | 33 % | 33 % | **100 %** |
| survives a second failure 200 ms later | 100 % | 25 % | 15 % | **100 %** |
| packets lost on a flapping link | 1,142 | 273 | – | **82** |

FA-FRR is the only scheme that is both millisecond-fast and never loses a
flow in these scenarios. On Mininet with Open vSwitch (Abilene, 5 runs) a link
cut costs 14 ms of traffic on average, and declaring the Abilene duct as an
SRLG halves the outage when the duct is cut (38 → 20 ms).
Full data: [docs/results/REPORT.md](docs/results/REPORT.md).

## Quick start

```bash
uv venv && uv pip install -e '.[dev,plots]'     # or: python -m venv .venv && .venv/bin/pip install -e '.[dev,plots]'
.venv/bin/pytest -q

# one scenario: Abilene, all host pairs, link DEN-KSC cut at 0.4 s
.venv/bin/python -m ffr run --topo abilene --app reactive --fail DEN-KSC@0.4 -v
.venv/bin/python -m ffr run --topo abilene --app fa-frr   --fail DEN-KSC@0.4 -v

# correlated failure of two links in the same duct
.venv/bin/python -m ffr run --topo abilene --app frr-node --srlg duct:DEN-KSC,SNV-DEN \
    --fail DEN-KSC@0.4 --fail SNV-DEN@0.4
.venv/bin/python -m ffr run --topo abilene --app fa-frr   --srlg duct:DEN-KSC,SNV-DEN \
    --fail DEN-KSC@0.4 --fail SNV-DEN@0.4

# gray failure, BFD detection, switch crash
.venv/bin/python -m ffr run --topo abilene --app fa-frr --detection los+bfd --fail-silent DEN-KSC@0.4
.venv/bin/python -m ffr run --topo abilene --app fa-frr --fail-node KSC@0.4   # the 20 flows to/from KSC itself cannot recover

# inspect the flow and group tables of a switch
.venv/bin/python -m ffr run --topo ring6 --app frr-link --flows 1 --tables s1

# the whole evaluation (≈3 min on 16 cores; --quick ≈30 s)
.venv/bin/python -m ffr experiment --out results
```

## Strategies (`--app`)

| App | How it recovers |
|-----|-----------------|
| `static` | it doesn't (baseline) |
| `reactive` | controller recomputes after PORT_STATUS / LLDP |
| `frr-link` / `frr-node` | fast-failover groups + tagged detours around the link / next switch |
| `e2e` | disjoint primary/backup paths, multi-hop BFD, ingress switch-over |
| `fa-frr` | node/link FRR + risk model, risk-aware paths, SRLG-disjoint backups, hitless re-optimisation, flap damping |

## Layout

```
ffr/                     the emulator and controller apps
  sim.py                 discrete-event engine
  topology.py            topologies (Abilene, NSFNET, rings, grids), SRLGs, priors
  openflow.py            matches, actions, flow table, groups, messages
  network.py             links, ports, hosts, OpenFlow switches, failures
  detection.py           LOS, BFD, multi-hop path BFD
  controller.py          controller base: channel delay, LLDP, barriers
  routing.py             Dijkstra, next-hop trees, Bhandari disjoint paths
  protection.py          backup (detour) planning
  risk.py                failure-aware risk model
  apps/                  static, reactive, frr, e2e, fa_frr
  experiments/           evaluation suite, plots, report
testbed/                 OS-Ken/Ryu app, Mininet scripts, wire-level tests, Mininet results
tests/                   pytest suite
docs/                    experiment results, project report and presentation
paper/                   IEEE paper (PDF) and the script that draws its figures
```

## Documentation

| Doc | Content |
|-----|---------|
| [results/](docs/results/REPORT.md) | evaluation results, figures and raw data |
| [testbed/](testbed/README.md) | real testbed setup and Mininet results |
| [report/](docs/report/README.md) | project report (Word/PDF) and presentation (PowerPoint/PDF) |
| [paper/](paper/README.md) | IEEE conference paper and how each number in it is regenerated |
