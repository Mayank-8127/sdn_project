"""Draw the explanatory diagrams used by the report and the slides.

    python docs/report/build_figures.py     # writes docs/report/figures/*.png

The result plots themselves come from ``python -m ffr experiment`` and live in
docs/results/; this script only draws the concept diagrams.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).parent / "figures"
INK, MUTED, LINE, BG = "#0b0b0b", "#52514e", "#b9b7b0", "#ffffff"
BLUE, ORANGE, GREEN, AMBER, PINK, DKGREEN, PURPLE, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
TINT = {BLUE: "#e3eefb", ORANGE: "#fde9e0", GREEN: "#ddf4ea", AMBER: "#fcf1d6",
        PURPLE: "#e8e5f6", RED: "#fbe2e2", MUTED: "#efeeeb", DKGREEN: "#dcefdc"}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                     "savefig.facecolor": BG, "figure.facecolor": BG})


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, text, color=BLUE, size=11, weight="normal", fill=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                linewidth=1.6, edgecolor=color,
                                facecolor=TINT.get(color, "#f4f4f2") if fill else BG))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size,
            color=INK, weight=weight, linespacing=1.35)


def arrow(ax, p, q, color=MUTED, style="-|>", lw=1.6, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=14, color=color,
                                 linewidth=lw, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}"))


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


ABILENE_XY = {"SEA": (0.8, 5.2), "SNV": (0.5, 3.0), "LAX": (1.1, 1.6), "DEN": (3.2, 3.6),
              "KSC": (5.3, 3.3), "HOU": (5.0, 0.9), "IND": (7.1, 3.6), "CHI": (7.0, 4.9),
              "ATL": (7.6, 1.6), "NYC": (9.6, 4.6), "WDC": (9.3, 3.0)}
ABILENE_E = [("SEA", "SNV"), ("SEA", "DEN"), ("SNV", "LAX"), ("SNV", "DEN"), ("LAX", "HOU"),
             ("DEN", "KSC"), ("KSC", "HOU"), ("KSC", "IND"), ("HOU", "ATL"), ("IND", "CHI"),
             ("IND", "ATL"), ("ATL", "WDC"), ("CHI", "NYC"), ("NYC", "WDC")]


def abilene():
    fig, ax = canvas(10.4, 6.0)
    duct = {("DEN", "KSC"), ("SNV", "DEN")}
    for a, b in ABILENE_E:
        (x1, y1), (x2, y2) = ABILENE_XY[a], ABILENE_XY[b]
        hot = (a, b) in duct
        ax.plot([x1, x2], [y1, y2], color=RED if hot else LINE, lw=4 if hot else 2.6, zorder=1,
                solid_capstyle="round")
    for n, (x, y) in ABILENE_XY.items():
        ax.add_patch(plt.Circle((x, y), 0.36, facecolor=TINT[BLUE], edgecolor=BLUE, lw=2, zorder=3))
        ax.text(x, y, n, ha="center", va="center", fontsize=9.5, weight="bold", zorder=4)
    ax.text(2.6, 2.75, "SRLG \"duct\"\nDEN–KSC + SNV–DEN", color=RED, fontsize=9.5, ha="center")
    ax.text(0.1, 5.85, "Abilene (Internet2) backbone: 11 switches, 14 links, one host per switch",
            fontsize=10.5, color=INK)
    save(fig, "abilene.png")


def fa_frr_architecture():
    fig, ax = canvas(11, 5.6)
    box(ax, 0.2, 3.9, 2.3, 1.1, "Failure events\nPORT_STATUS\n(LOS / BFD)", AMBER, 10)
    box(ax, 3.1, 3.9, 2.3, 1.1, "Risk model\nprior + decaying\nflap penalty, SRLG", RED, 10)
    box(ax, 6.0, 3.9, 2.3, 1.1, "Risk-aware\nprimary paths\nw = d/d̄ + λ·(−ln(1−p))", BLUE, 9.5)
    box(ax, 8.7, 3.9, 2.1, 1.1, "SRLG-disjoint\nnode / link\ndetours", PURPLE, 10)
    box(ax, 8.7, 1.9, 2.1, 1.2, "3-phase hitless\ninstall\n(barriers, new tags)", DKGREEN, 10)
    box(ax, 4.6, 1.9, 3.3, 1.2, "Switches: FF groups + tagged\ndetours switch locally\nin ≈ 1 ms", ORANGE, 10)
    box(ax, 0.2, 1.9, 3.6, 1.2, "Hold-down timer\nrecovered link waits\nbase·(1 + penalty/flap)", MUTED, 10)
    arrow(ax, (2.5, 4.45), (3.1, 4.45))
    arrow(ax, (5.4, 4.45), (6.0, 4.45))
    arrow(ax, (8.3, 4.45), (8.7, 4.45))
    arrow(ax, (9.75, 3.9), (9.75, 3.1))
    arrow(ax, (8.7, 2.5), (7.9, 2.5))
    arrow(ax, (4.6, 2.2), (2.5, 3.88), AMBER, rad=-0.2)
    arrow(ax, (3.8, 2.5), (4.6, 2.5), MUTED, ls="--")
    ax.text(3.2, 3.2, "failure", fontsize=8.5, color=AMBER)
    ax.text(0.2, 0.95, "Fast path (data plane, milliseconds): the FF group already holds the backup.\n"
            "Slow path (controller, tens of ms, in the background): learn risk → recompute → re-protect.",
            fontsize=10, color=INK, linespacing=1.5)
    save(fig, "fa_frr_architecture.png")


def reoptimisation():
    fig, ax = canvas(11, 3.0)
    phases = [("Phase 1", "install new-generation\ndetour rules (new tags)", BLUE),
              ("Phase 2", "modify FF groups to the\nnew primaries / backups", PURPLE),
              ("Phase 3", "delete old-generation\ndetour rules (by cookie)", ORANGE)]
    for i, (t, d, c) in enumerate(phases):
        x = 0.2 + i * 3.7
        box(ax, x, 0.7, 2.9, 1.6, f"{t}\n{d}", c, 10)
        if i < 2:
            ax.plot([x + 3.3, x + 3.3], [0.5, 2.5], color=INK, lw=2.4)
            ax.text(x + 3.3, 2.65, "barrier", ha="center", fontsize=9, color=INK)
            arrow(ax, (x + 2.95, 1.5), (x + 3.65, 1.5))
    ax.text(0.2, 0.15, "Packets already on an old detour keep matching the old rules until phase 3, "
            "so the update adds zero loss.", fontsize=9.5, color=MUTED)
    save(fig, "reoptimisation.png")


if __name__ == "__main__":
    abilene()
    fa_frr_architecture()
    reoptimisation()
    print("figures written to", OUT)
