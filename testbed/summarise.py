#!/usr/bin/env python3
"""Summarise the logs written by run_experiments.sh into a markdown table.

    python3 testbed/summarise.py testbed/results

Per scenario (all runs pooled): probed host pairs, mean packets lost per pair,
mean and worst longest outage, how long the controller took to hear of the
failure and how long its re-optimisation took.
"""

from __future__ import annotations

import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

ORDER = ["cut", "gray-nobfd", "gray-bfd", "srlg-unaware", "srlg-aware"]
LABEL = {
    "cut": "link cut (DEN-KSC)",
    "gray-nobfd": "gray failure, no BFD",
    "gray-bfd": "gray failure, OVS BFD 10 ms",
    "srlg-unaware": "duct cut (DEN-KSC + SNV-DEN), SRLG not declared",
    "srlg-aware": "duct cut (DEN-KSC + SNV-DEN), SRLG declared",
}
PROBE = re.compile(r"lost=\s*(\d+)/(\d+)\s+longest outage=(\d+) ms(?:\s+bursts:([^\n]*))?")
STAMP = re.compile(r"^(\d\d:\d\d:\d\d\.\d{3}) ")


def probes(path: Path):
    # (lost, sent, longest outage ms, number of loss bursts or None for old logs)
    return [(int(l), int(n), int(o), len(re.findall(r"x\d+", b)) if b else None)
            for l, n, o, b in PROBE.findall(path.read_text())]


def events(mn: Path, ctl: Path):
    """(detection ms, re-optimisation ms) for one run.

    Detection: failure injected until the controller hears of it; on a
    fast-failover network the data plane has usually rerouted before that.
    Re-optimisation: that report until the new generation's groups are all
    installed (the network is protected again). Only
    controller events between failure and restoration count.
    """
    marks = dict((w, ts(t)) for t, w in re.findall(r"\*\*\* (\S+) (failing|restoring)", mn.read_text()))
    if "failing" not in marks:
        return None, None
    t_fail, t_restore = marks["failing"], marks.get("restoring")
    t_down = None
    for line in ctl.read_text().splitlines():
        m = STAMP.match(line)
        if not m:
            continue
        t = ts(m.group(1))
        if t < t_fail or (t_restore and t > t_restore):
            continue
        if t_down is None and " DOWN" in line:
            t_down = t
        elif t_down is not None and re.search(r"gen \d+ (groups installed|active)", line):
            # "groups installed": every group rewritten, the network is protected
            # again (old detour rules are deleted later, after a drain time)
            return ms(t_down - t_fail), ms(t - t_down)
    return (ms(t_down - t_fail) if t_down else None), None


def ts(text: str):
    return datetime.strptime(text, "%H:%M:%S.%f")


def ms(delta) -> float:
    return delta.total_seconds() * 1000


def fmt(values):
    return f"{statistics.mean(values):.0f} ms" if values else "never"


def main(folder: str):
    root = Path(folder)
    print("| scenario | runs | pairs | lost / pair | bursts / pair | mean outage | worst outage "
          "| controller notified | re-optimisation |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in ORDER:
        mn = sorted(root.glob(f"{name}-*.mn.log"))
        if not mn:
            continue
        rows = [p for f in mn for p in probes(f)]
        ev = [events(f, Path(str(f).replace(".mn.", ".ctl."))) for f in mn]
        det = [d for d, _ in ev if d is not None]
        reo = [r for _, r in ev if r is not None]
        out = [r[2] for r in rows]
        bursts = [r[3] for r in rows if r[3] is not None]
        b = f"{statistics.mean(bursts):.1f}" if bursts else "-"
        print(f"| {LABEL[name]} | {len(mn)} | {len(rows)} | "
              f"{statistics.mean(r[0] for r in rows):.1f} | {b} | {statistics.mean(out):.0f} ms | "
              f"{max(out)} ms | {fmt(det)} | {fmt(reo)} |")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "testbed/results")
