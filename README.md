# Failure-Aware Fast Rerouting in SDN

An implementation and evaluation of **fast failure recovery in
Software-Defined Networks**:

* a deterministic **OpenFlow emulator** in pure Python (flow tables, group
  tables with fast-failover, port liveness, control-channel latency, rule
  installation time, BFD, LLDP, barriers),
* six **controller strategies**, built up version by version, from "no
  recovery" to **Failure-Aware Fast Reroute (FA-FRR)**,
* an **evaluation suite** (≈1,000 simulations on Abilene and NSFNET) with a
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

| App | Version | How it recovers |
|-----|---------|-----------------|
| `static` | v0.1 | it doesn't (baseline) |
| `reactive` | v0.2 | controller recomputes after PORT_STATUS / LLDP |
| `frr-link` / `frr-node` | v0.3 | fast-failover groups + tagged detours around the link / next switch |
| `e2e` | v0.5 | disjoint primary/backup paths, multi-hop BFD, ingress switch-over |
| `fa-frr` | v0.6 | node/link FRR + risk model, risk-aware paths, SRLG-disjoint backups, hitless re-optimisation, flap damping |

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
docs/                    interim progress report, experiment results, project report and presentation
```

## Documentation

| Doc | Content |
|-----|---------|
| [progress/](docs/progress/README.md) | interim progress report and presentation (v0.4) |
| [results/](docs/results/REPORT.md) | evaluation results, figures and raw data |
| [testbed/](testbed/README.md) | real testbed setup and Mininet results |
| [report/](docs/report/README.md) | project report (Word/PDF) and presentation (PowerPoint/PDF) |

## Versions

Every version is a git tag; `git checkout v0.3` gives you the project as it
was at that step.

| Tag | Adds |
|-----|------|
| v0.1 | emulator + static shortest-path controller (no recovery) |
| v0.2 | PORT_STATUS + reactive restoration by the controller |
| v0.3 | fast-failover groups + tagged detours (frr-link, frr-node) |
| v0.4 | pluggable failure detection (LOS, BFD, LLDP), gray failures, switch crashes |
| v0.5 | end-to-end path protection (Bhandari disjoint paths, multi-hop BFD) |
| v0.6 | FA-FRR: risk model, SRLG-disjoint backups, hitless re-optimisation, flap damping |
| v0.7 | experiment suite, figures, generated report |
| v0.8 | OS-Ken/Ryu app + Mininet scripts, wire-level tests |
| v1.0 | project overview, CI |
| v1.1 | validation on Mininet/Open vSwitch: `IN_PORT` U-turn groups, per-end port state, scenario runner, results |
