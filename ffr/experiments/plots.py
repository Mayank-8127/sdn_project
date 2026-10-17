"""Figures for the report (matplotlib, optional dependency).

Every strategy keeps the same colour in every figure (fixed categorical
order, validated palette), one y-axis per chart, thin marks, recessive grid.
"""

from __future__ import annotations

import os

# Validated categorical palette (light mode), assigned in fixed order.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7",
           "#e34948"]
APP_ORDER = ["static", "reactive", "frr-link", "frr-node", "e2e", "fa-frr"]
APP_COLOR = dict(zip(APP_ORDER, PALETTE))
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _plt():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # plots are optional
        return None
    plt.rcParams.update({
        "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
        "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.8, "axes.axisbelow": True, "legend.frameon": False,
        "figure.dpi": 110, "savefig.bbox": "tight", "savefig.facecolor": "#fcfcfb",
        "axes.facecolor": "#fcfcfb",
    })
    return plt


def _save(fig, out_dir, name):
    path = os.path.join(out_dir, name)
    fig.savefig(path)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return name


def grouped_bars(summary, metric, ylabel, title, out_dir, name, group="topo", log=False,
                 apps=None):
    plt = _plt()
    if plt is None:
        return None
    groups = list(dict.fromkeys(r[group] for r in summary))
    apps = [a for a in (apps or APP_ORDER) if any(r["app"] == a for r in summary)]
    fig, ax = plt.subplots(figsize=(1.6 + 1.3 * len(groups) * len(apps) / 3, 3.4))
    width = 0.8 / len(apps)
    for i, app in enumerate(apps):
        xs, ys = [], []
        for j, g in enumerate(groups):
            r = next((r for r in summary if r[group] == g and r["app"] == app), None)
            if r is not None and isinstance(r[metric], (int, float)):
                xs.append(j - 0.4 + width * (i + 0.5))
                ys.append(r[metric])
        ax.bar(xs, ys, width * 0.92, color=APP_COLOR[app], label=app)
    ax.set_xticks(range(len(groups)), groups)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", color=INK)
    if log:
        ax.set_yscale("symlog", linthresh=1)
    ax.legend(ncol=min(6, len(apps)), loc="upper left", bbox_to_anchor=(0, -0.12))
    return _save(fig, out_dir, name)


def config_bars(rows, label_key, metric, ylabel, title, out_dir, name):
    """One bar per configuration, coloured by the strategy it uses."""
    plt = _plt()
    if plt is None:
        return None
    rows = [r for r in rows if isinstance(r[metric], (int, float))] + \
           [r for r in rows if not isinstance(r[metric], (int, float))]
    fig, ax = plt.subplots(figsize=(1.2 + 1.3 * len(rows), 3.4))
    for i, r in enumerate(rows):
        v = r[metric]
        if isinstance(v, (int, float)):
            ax.bar(i, v, 0.6, color=APP_COLOR.get(r["app"], PALETTE[0]))
            ax.annotate(f"{v:g}", (i, v), textcoords="offset points", xytext=(0, 3),
                        ha="center", fontsize=8, color=INK)
        else:
            ax.annotate("never\nrecovers", (i, 0), textcoords="offset points", xytext=(0, 3),
                        ha="center", fontsize=8, color=MUTED)
    ax.set_xticks(range(len(rows)), [r[label_key].replace(" + ", "\n+ ") for r in rows])
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", color=INK)
    return _save(fig, out_dir, name)


def timeline(exp, out_dir):
    plt = _plt()
    if plt is None:
        return None
    series, t0 = exp.extra["series"], exp.extra["t0_ms"]
    apps = [a for a in APP_ORDER if a in series]
    fig, axes = plt.subplots(len(apps), 1, figsize=(7, 1.0 * len(apps) + 0.6), sharex=True)
    for ax, app in zip(axes, apps):
        ys = series[app]
        xs = [t0 + i for i in range(len(ys))]
        ax.step(xs, ys, where="post", color=APP_COLOR[app], linewidth=2)
        ax.axvline(t0 + 20, color=MUTED, linewidth=1, linestyle="--")
        ax.set_ylim(-0.2, max(ys) + 0.6)
        ax.set_yticks(range(max(ys) + 1))
        ax.text(1.01, 0.5, app, transform=ax.transAxes, va="center", color=INK)
    axes[0].set_title("Packets delivered per ms (SEA→ATL); dashed line: DEN–KSC cut",
                      loc="left", color=INK)
    axes[-1].set_xlabel("time (ms)")
    return _save(fig, out_dir, "timeline.png")


def line(rows, x, y, xlabel, ylabel, title, out_dir, name, series_key=None, logx=False):
    plt = _plt()
    if plt is None:
        return None
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    keys = list(dict.fromkeys(r[series_key] for r in rows)) if series_key else [None]
    for i, k in enumerate(keys):
        rs = [r for r in rows if series_key is None or r[series_key] == k]
        ax.plot([r[x] for r in rs], [r[y] for r in rs], marker="o", markersize=5,
                linewidth=2, color=PALETTE[i], label=k)
    if logx:
        ax.set_xscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", color=INK)
    if series_key:
        ax.legend()
    return _save(fig, out_dir, name)


def tradeoff(rows, out_dir):
    """Latency vs failure probability, one point per λ; one panel per topology."""
    plt = _plt()
    if plt is None:
        return None
    topos = list(dict.fromkeys(r["topo"] for r in rows))
    fig, axes = plt.subplots(1, len(topos), figsize=(4.6 * len(topos), 3.6))
    axes = axes if len(topos) > 1 else [axes]
    for ax, t in zip(axes, topos):
        rs = [r for r in rows if r["topo"] == t]
        ax.plot([r["mean_path_delay_ms"] for r in rs], [r["mean_path_fail_prob_pct"] for r in rs],
                marker="o", markersize=5, linewidth=2, color=PALETTE[0])
        for r in rs:
            if r["lam"] in (0, 2, 10, 50):
                ax.annotate(f"λ={r['lam']}", (r["mean_path_delay_ms"],
                                              r["mean_path_fail_prob_pct"]),
                            textcoords="offset points", xytext=(5, 3), fontsize=8, color=MUTED)
        ax.set_xlabel("mean primary path delay (ms)")
        ax.set_title(t, loc="left", color=INK)
    axes[0].set_ylabel("mean path failure probability (%)")
    fig.suptitle("Risk-aware routing: latency vs reliability", x=0.01, ha="left", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return _save(fig, out_dir, "risk_tradeoff.png")
