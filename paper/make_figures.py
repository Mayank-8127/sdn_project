"""Draw the figures of the IEEE paper from the evaluation CSVs.

    python paper/make_figures.py        # reads docs/results/*.csv, writes paper/figures/*.pdf

Every number in the figures comes from the CSV files written by
``python -m ffr experiment --out docs/results``; nothing is typed in by hand.
The aggregation is the one used by the experiment suite (ffr.experiments.suite.aggregate).
"""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from ffr.experiments.plots import APP_COLOR  # noqa: E402  same colours as the report
from ffr.experiments.suite import aggregate  # noqa: E402

RES = ROOT / "docs" / "results"
OUT = HERE / "figures"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
APPS = ["reactive", "frr-node", "e2e", "fa-frr"]
LABEL = {"reactive": "Reactive", "frr-node": "Local FRR (node)", "e2e": "End-to-end",
         "fa-frr": "FA-FRR (proposed)"}

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.02, "pdf.fonttype": 42,
})


def num(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except ValueError:
        return v


def load(name):
    with open(RES / f"{name}.csv") as fh:
        rows = [{k: num(v) for k, v in r.items()} for r in csv.DictReader(fh)]
    for r in rows:
        if "never_recovered" in r:
            r["never_recovered"] = int(r["never_recovered"])
    return rows


SCEN = [("single_link", "Single\nlink"), ("node_crash", "Switch\ncrash"),
        ("srlg", "SRLG\ndouble"), ("sequential", "Sequential\ndouble")]


def summaries():
    out = {}
    for key, _ in SCEN:
        for r in aggregate(load(key)):
            out[(key, r["topo"], r["app"])] = r
    return out


def grouped(metric, ylabel, fname, ylim=None):
    S = summaries()
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.1), sharey=True)
    w = 0.8 / len(APPS)
    for ax, topo, title in zip(axes, ("abilene", "nsfnet"), ("Abilene", "NSFNET")):
        for i, app in enumerate(APPS):
            xs, ys = [], []
            for j, (key, _) in enumerate(SCEN):
                r = S.get((key, topo, app))
                if r is not None and isinstance(r[metric], float):
                    xs.append(j - 0.4 + w * (i + 0.5))
                    ys.append(r[metric])
            ax.bar(xs, ys, w * 0.9, color=APP_COLOR[app], label=LABEL[app])
        ax.set_xticks(range(len(SCEN)), [s for _, s in SCEN])
        ax.set_title(title, fontsize=8.5, color=INK)
        if ylim:
            ax.set_ylim(*ylim)
    axes[0].set_ylabel(ylabel)
    axes[0].legend(ncol=4, loc="lower left", bbox_to_anchor=(0.0, 1.12), fontsize=7.5)
    fig.savefig(OUT / fname)
    plt.close(fig)


def bfd():
    rows = load("bfd_tradeoff")
    iv = sorted({r["bfd_interval_ms"] for r in rows})
    outage = [sum(r["mean_outage_ms"] for r in rows if r["bfd_interval_ms"] == x) /
              sum(1 for r in rows if r["bfd_interval_ms"] == x) for x in iv]
    fig, axes = plt.subplots(1, 2, figsize=(3.5, 1.7))
    c = APP_COLOR["fa-frr"]
    axes[0].plot(iv, outage, "-o", color=c, lw=1.5, ms=3.5)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("BFD interval (ms)")
    axes[0].set_ylabel("Mean outage (ms)")
    axes[1].plot(iv, [2000 / x for x in iv], "-o", color=MUTED, lw=1.5, ms=3.5)
    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("BFD interval (ms)")
    axes[1].set_ylabel("Probes/s per link")
    for ax in axes:
        ax.set_xticks([1, 3.3, 10, 50], ["1", "3.3", "10", "50"])
        ax.grid(True, axis="both")
    fig.tight_layout(w_pad=1.0)
    fig.savefig(OUT / "fig_bfd.pdf")
    plt.close(fig)


def risk():
    rows = load("risk_tradeoff")
    fig, axes = plt.subplots(1, 2, figsize=(3.5, 1.75))
    for ax, topo, title in zip(axes, ("abilene", "nsfnet"), ("Abilene", "NSFNET")):
        rs = sorted((r for r in rows if r["topo"] == topo), key=lambda r: r["lam"])
        ax.plot([r["mean_path_delay_ms"] for r in rs], [r["mean_path_fail_prob_pct"] for r in rs],
                "-o", color=APP_COLOR["fa-frr"], lw=1.5, ms=3.5)
        for r in rs:
            if r["lam"] in (0, 10, 50):
                ax.annotate(f"λ={r['lam']:g}", (r["mean_path_delay_ms"], r["mean_path_fail_prob_pct"]),
                            textcoords="offset points", xytext=(3, 3), fontsize=6.5, color=MUTED)
        ax.set_title(title, fontsize=8, color=INK)
        ax.set_xlabel("Mean path delay (ms)")
        ax.grid(True, axis="both")
    axes[0].set_ylabel("Path failure prob. (%)")
    fig.tight_layout(w_pad=1.0)
    fig.savefig(OUT / "fig_risk.pdf")
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    grouped("survival_pct", "Runs with no lost flow (%)", "fig_survival.pdf", (0, 105))
    grouped("mean_outage_ms", "Mean outage (ms)", "fig_outage.pdf")
    bfd()
    risk()
    shutil.copy(RES / "timeline.png", OUT / "fig_timeline.png")
    shutil.copy(ROOT / "docs" / "report" / "figures" / "fa_frr_architecture.png",
                OUT / "fig_architecture.png")
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
