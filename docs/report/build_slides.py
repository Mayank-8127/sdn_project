"""Build the presentation (PowerPoint + PDF).

    python docs/report/build_figures.py
    python docs/report/build_slides.py      # needs python-pptx and LibreOffice (soffice)

Writes docs/report/FA-FRR_Presentation.pptx and .pdf.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
FIG = HERE / "figures"
RES = ROOT / "docs" / "results"
OUT = HERE / "FA-FRR_Presentation.pptx"
STUDENTS = [("Mayank Bansal", "23BEC026"), ("Anas Khan", "23BCS083"),
            ("Shardendu Mishra", "23BCS122"), ("Himanshu Kumar", "23BCS055"),
            ("Divyanshu", "23BEC017")]

NAVY = RGBColor(0x1F, 0x3A, 0x68)
GREEN = RGBColor(0x00, 0x83, 0x00)
RED = RGBColor(0xE3, 0x49, 0x48)
INK = RGBColor(0x1B, 0x1B, 0x1B)
MUTED = RGBColor(0x5A, 0x5A, 0x5A)
LIGHT = RGBColor(0xF3, 0xF4, 0xF7)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Calibri"
W, H = Inches(13.333), Inches(7.5)


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = W, H
        self.blank = self.prs.slide_layouts[6]
        self.n = 0

    # ---------------------------------------------------------------- primitives
    def text(self, slide, x, y, w, h, text, size=18, color=INK, bold=False, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, italic=False):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Inches(0.05)
        lines = text if isinstance(text, list) else [text]
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            self._rich(p, line, size, color, bold, italic)
        return tb

    def _rich(self, p, line, size, color, bold=False, italic=False):
        # **bold** segments
        parts = line.split("**")
        for j, part in enumerate(parts):
            if not part:
                continue
            r = p.add_run()
            r.text = part
            r.font.name = FONT
            r.font.size = Pt(size)
            r.font.color.rgb = color
            r.font.bold = bold or j % 2 == 1
            r.font.italic = italic

    def bullets(self, slide, x, y, w, h, items, size=20, gap=10):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        for i, it in enumerate(items):
            sub = it.startswith("  ")
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(gap if not sub else gap / 2)
            p.level = 1 if sub else 0
            r = p.add_run()
            r.text = ("–  " if sub else "•  ")
            r.font.size = Pt(size - (3 if sub else 0))
            r.font.color.rgb = NAVY if not sub else MUTED
            r.font.bold = True
            r.font.name = FONT
            self._rich(p, it.strip(), size - (3 if sub else 0), INK if not sub else MUTED)
        return tb

    def rect(self, slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE):
        s = slide.shapes.add_shape(shape, x, y, w, h)
        s.fill.solid()
        s.fill.fore_color.rgb = fill
        if line is None:
            s.line.fill.background()
        else:
            s.line.color.rgb = line
        s.shadow.inherit = False
        return s

    def image(self, slide, path, x, y, max_w, max_h, center=True):
        iw, ih = Image.open(path).size
        scale = min(max_w / iw, max_h / ih)
        w, h = int(iw * scale), int(ih * scale)
        if center:
            x += (max_w - w) // 2
            y += (max_h - h) // 2
        return slide.shapes.add_picture(str(path), x, y, w, h)

    def table(self, slide, x, y, w, header, rows, col_w=None, size=14, row_h=0.42,
              highlight_last=False, highlight_col=None):
        shape = slide.shapes.add_table(len(rows) + 1, len(header), x, y, w,
                                       Inches(row_h * (len(rows) + 1)))
        t = shape.table
        if col_w:
            tot = sum(col_w)
            for i, cw in enumerate(col_w):
                t.columns[i].width = Emu(int(w * cw / tot))
        for r in range(len(rows) + 1):
            for c in range(len(header)):
                cell = t.cell(r, c)
                val = header[c] if r == 0 else rows[r - 1][c]
                cell.text = ""
                p = cell.text_frame.paragraphs[0]
                self._rich(p, str(val), size, WHITE if r == 0 else INK, bold=r == 0)
                cell.margin_left = cell.margin_right = Inches(0.08)
                cell.margin_top = cell.margin_bottom = Inches(0.04)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.fill.solid()
                if r == 0:
                    cell.fill.fore_color.rgb = NAVY
                elif (highlight_last and r == len(rows)) or (highlight_col is not None and c == highlight_col):
                    cell.fill.fore_color.rgb = RGBColor(0xE2, 0xF1, 0xE2)
                else:
                    cell.fill.fore_color.rgb = WHITE if r % 2 else LIGHT
        return shape

    # ---------------------------------------------------------------- slide kinds
    def slide(self, title, kicker=None):
        s = self.prs.slides.add_slide(self.blank)
        self.n += 1
        self.rect(s, 0, 0, W, Inches(0.12), NAVY)
        if kicker:
            self.text(s, Inches(0.6), Inches(0.32), Inches(10), Inches(0.35), kicker.upper(), 12,
                      GREEN, True)
        self.text(s, Inches(0.6), Inches(0.58), Inches(12.1), Inches(0.8), title, 30, NAVY, True)
        self.rect(s, Inches(0.6), Inches(1.38), Inches(1.0), Inches(0.05), GREEN)
        self.text(s, Inches(0.6), Inches(7.05), Inches(9), Inches(0.3),
                  "Failure-Aware Fast Rerouting in SDN", 10, MUTED)
        self.text(s, Inches(11.9), Inches(7.05), Inches(0.9), Inches(0.3), str(self.n), 10, MUTED,
                  align=PP_ALIGN.RIGHT)
        return s

    def callout(self, s, x, y, w, h, text, size=16, fill=RGBColor(0xE8, 0xF3, 0xE8), color=INK):
        self.rect(s, x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE)
        self.rect(s, x, y, Inches(0.08), h, GREEN)
        self.text(s, x + Inches(0.2), y, w - Inches(0.3), h, text, size, color,
                  anchor=MSO_ANCHOR.MIDDLE)

    def save(self):
        self.prs.save(str(OUT))


# ---------------------------------------------------------------------- slides

def title_slide(D: Deck):
    s = D.prs.slides.add_slide(D.blank)
    D.n += 1
    D.rect(s, 0, 0, Inches(5.2), H, NAVY)
    D.text(s, Inches(0.55), Inches(0.7), Inches(4.3), Inches(0.4), "PROJECT PRESENTATION", 13,
           RGBColor(0x9E, 0xD8, 0x9E), True)
    D.text(s, Inches(0.55), Inches(1.2), Inches(4.4), Inches(2.6),
           "Failure-Aware Fast Rerouting in Software-Defined Networks", 34, WHITE, True)
    D.text(s, Inches(0.55), Inches(4.0), Inches(4.3), Inches(1.4),
           "Millisecond recovery that learns how the network fails", 17,
           RGBColor(0xD6, 0xDE, 0xEA), italic=True)
    D.text(s, Inches(0.55), Inches(6.2), Inches(4.3), Inches(0.9),
           ["Department of ______________________", "Institute ____________________________"],
           12, RGBColor(0xD6, 0xDE, 0xEA))

    D.text(s, Inches(5.8), Inches(0.75), Inches(7), Inches(0.4), "Submitted by", 18, NAVY, True)
    D.table(s, Inches(5.8), Inches(1.3), Inches(7.0), ["S. No.", "Name of the Student", "Roll Number"],
            [[f"{i}.", name, roll] for i, (name, roll) in enumerate(STUDENTS, 1)],
            col_w=[1.1, 3.9, 2.0], size=15, row_h=0.52)
    D.text(s, Inches(5.8), Inches(4.75), Inches(7), Inches(0.4), "Under the guidance of", 16,
           MUTED, italic=True)
    D.text(s, Inches(5.8), Inches(5.15), Inches(7), Inches(0.4),
           "_______________________________________", 16, INK)
    D.text(s, Inches(5.8), Inches(5.55), Inches(7), Inches(0.35), "(Name and designation of the guide)",
           11, MUTED, italic=True)
    D.text(s, Inches(5.8), Inches(6.3), Inches(7), Inches(0.4),
           "Academic Year: ______________        Date: ______________", 14, INK)


def agenda(D):
    s = D.slide("Agenda")
    items = ["Motivation and problem statement", "Objectives", "Related work and research gap",
             "System design", "Incremental development", "FA-FRR: the proposed scheme",
             "Experimental setup", "Results", "Real testbed and Mininet results", "Conclusion and future work"]
    for i, it in enumerate(items):
        col, row = divmod(i, 5)
        x, y = Inches(0.8 + col * 6.2), Inches(1.9 + row * 0.95)
        D.rect(s, x, y, Inches(0.62), Inches(0.62), NAVY, shape=MSO_SHAPE.OVAL)
        D.text(s, x, y, Inches(0.62), Inches(0.62), str(i + 1), 18, WHITE, True, PP_ALIGN.CENTER,
               MSO_ANCHOR.MIDDLE)
        D.text(s, x + Inches(0.85), y, Inches(5.2), Inches(0.62), it, 20, INK,
               anchor=MSO_ANCHOR.MIDDLE)


def gap(D):
    s = D.slide("Where classic fast reroute breaks", "Motivation")
    D.table(s, Inches(0.7), Inches(1.75), Inches(11.9), ["Situation", "What plain FRR does"], [
        ["**Correlated failure** – two fibres in one duct cut together",
         "detour uses the other failed link → traffic lost **forever**"],
        ["**Second failure** after the first", "detours have no backup; nobody re-protects → lost forever"],
        ["**Flapping link** (down / up / down …)", "traffic pulled back on every “up” → an outage on every flap"],
        ["**Unequal reliability**", "a flaky 2,000 km fibre treated like a reliable short link"],
    ], col_w=[5, 7], size=17, row_h=0.75)
    D.callout(s, Inches(0.7), Inches(5.6), Inches(11.9), Inches(1.0),
              "**Problem statement:** keep millisecond data-plane recovery, but use knowledge of how the "
              "network fails so traffic survives correlated and repeated failures and stays stable under flapping.",
              17)


def objectives(D):
    s = D.slide("Objectives", "Problem")
    D.bullets(s, Inches(0.8), Inches(1.8), Inches(11.8), Inches(5), [
        "Build a deterministic **OpenFlow emulator**: flow and group tables, port liveness, control delay, "
        "rule-install time, LOS / BFD / LLDP detection",
        "Implement the baselines: **static, reactive, frr-link, frr-node, end-to-end protection**",
        "Design and implement **FA-FRR**: risk model, risk-aware paths, SRLG-disjoint backups, hitless "
        "re-optimisation, flap damping",
        "Evaluate on **Abilene** and **NSFNET** under 7 failure models (~1,000 simulations)",
        "Port the controller to a real OpenFlow 1.3 framework (**OS-Ken / Ryu + Mininet + OVS**)",
    ], 20, 12)


def literature(D):
    s = D.slide("Related work", "Related work")
    D.table(s, Inches(0.6), Inches(1.7), Inches(12.1), ["Work", "Idea", "Gap addressed by FA-FRR"], [
        ["Sharma et al. 2013", "path protection + FF groups + BFD, < 50 ms", "failure-agnostic, single failure"],
        ["van Adrichem et al. 2014", "per-link BFD + FF, few-ms recovery", "no correlated / repeated failures"],
        ["SPIDER (Cascone et al.)", "stateful data-plane detection", "needs a stateful pipeline"],
        ["Not-via, MPLS FRR (RFC 6981, 4090)", "tunnel around the failed element", "no risk model; not SDN"],
        ["Borokhovich et al. 2014", "provable multi-failure FF", "very long paths"],
        ["Reitblatt et al. 2012", "consistent (make-before-break) updates", "not a recovery scheme alone"],
        ["Chiesa et al. 2021 (survey)", "taxonomy of fast-recovery schemes", "frames our design space"],
    ], col_w=[3.6, 4.6, 3.9], size=15, row_h=0.52)
    D.callout(s, Inches(0.6), Inches(6.3), Inches(12.1), Inches(0.6),
              "Gap: fast local recovery **and** failure-aware backup selection have not been combined.", 17)


def design(D):
    s = D.slide("System design: an OpenFlow emulator built from scratch", "Design")
    D.table(s, Inches(0.6), Inches(1.7), Inches(6.6), ["Module", "Role"], [
        ["sim.py", "discrete-event engine"],
        ["openflow.py", "flow / group tables, messages"],
        ["network.py", "links, ports, switches, failures"],
        ["detection.py", "LOS, BFD, path BFD"],
        ["controller.py", "channel delay, LLDP, barriers"],
        ["routing.py", "Dijkstra, Bhandari disjoint paths"],
        ["protection.py / risk.py", "detour planning, risk model"],
        ["apps/", "static, reactive, frr, e2e, fa_frr"],
    ], col_w=[2.6, 4], size=14, row_h=0.5)
    D.bullets(s, Inches(7.6), Inches(1.8), Inches(5.3), Inches(5), [
        "Pure Python, **~4,400 lines**, **109 tests**",
        "Deterministic: same input → same result",
        "Runs without root; ~1,000 simulations in ~3 min",
        "Models OpenFlow 1.3 semantics, not just graphs",
        "Same planning code reused by the real controller",
    ], 18)


def roadmap(D):
    s = D.slide("Built incrementally: basic → advanced", "Implementation")
    D.image(s, FIG / "roadmap.png", Inches(0.5), Inches(1.6), Inches(12.3), Inches(2.4))
    D.table(s, Inches(0.8), Inches(4.2), Inches(11.7), ["Version", "v0.1", "v0.2", "v0.3", "v0.4", "v0.5",
                                                        "v0.6", "v0.7", "v0.8 – v1.1"],
            [["Tests passing", "27", "33", "63", "78", "89", "104", "109", "109 + testbed"]],
            size=15, row_h=0.5, highlight_col=6)
    D.text(s, Inches(0.8), Inches(5.5), Inches(11.7), Inches(1.2),
           "One git tag per version, each with its own tests and documentation; v1.1 validates the "
           "controller on Mininet with Open vSwitch.", 17, MUTED)


def fafrr(D):
    s = D.slide("FA-FRR: fast data plane + learning controller", "Proposed scheme")
    D.image(s, FIG / "fa_frr_architecture.png", Inches(0.5), Inches(1.6), Inches(12.3), Inches(5.3))


def fafrr_ideas(D):
    s = D.slide("The five failure-aware ideas", "Proposed scheme")
    cards = [
        ("1  Risk model", "p(e) = prior(e) + penalty(e)\nEach failure adds a penalty that halves every "
                          "half-life; SRLG siblings become suspect too."),
        ("2  Risk-aware paths", "w(e) = delay/mean + λ·(−ln(1 − p(e)))\nλ = 0 → fastest path; large λ → "
                                "most reliable path."),
        ("3  SRLG-disjoint backups", "Detours avoid the protected element and everything in its risk "
                                     "group: node+SRLG → link+SRLG → node → link."),
        ("4  Hitless re-optimisation", "After each failure: rebuild full protection with "
                                       "make-before-break (3 phases, barriers, new tags)."),
        ("5  Flap damping", "A recovered link waits base·(1 + penalty/flap_penalty) before it carries "
                            "traffic again."),
    ]
    for i, (t, body) in enumerate(cards):
        col, row = i % 3, i // 3
        x, y = Inches(0.6 + col * 4.1), Inches(1.75 + row * 2.6)
        D.rect(s, x, y, Inches(3.85), Inches(2.35), LIGHT)
        D.rect(s, x, y, Inches(3.85), Inches(0.07), GREEN if i != 0 else RED)
        D.text(s, x + Inches(0.2), y + Inches(0.18), Inches(3.5), Inches(0.5), t, 19, NAVY, True)
        D.text(s, x + Inches(0.2), y + Inches(0.75), Inches(3.5), Inches(1.6), body.split("\n"), 14.5, INK)
    D.callout(s, Inches(8.8), Inches(4.35), Inches(3.85), Inches(2.35),
              "Same switch state as plain node protection. The extra work runs in the controller, "
              "in the background, while traffic is already safe on the detour.", 15)


def reopt(D):
    s = D.slide("Hitless re-optimisation and flap damping", "Proposed scheme")
    D.image(s, FIG / "reoptimisation.png", Inches(0.5), Inches(1.6), Inches(12.3), Inches(3.0))
    D.bullets(s, Inches(0.8), Inches(4.8), Inches(11.8), Inches(2.2), [
        "Each configuration is a **generation** with its own tags and cookie, so packets already on a detour are never stranded",
        "Verified by test: FA-FRR loses **exactly** as many packets as plain FRR, so the update adds zero loss",
        "Hold-down keeps a flapping link out of service, so there is no outage on every flap",
    ], 18, 8)


def setup(D):
    s = D.slide("Experimental setup", "Evaluation")
    D.image(s, FIG / "abilene.png", Inches(0.4), Inches(1.6), Inches(6.6), Inches(4.2))
    D.text(s, Inches(0.6), Inches(5.85), Inches(6.3), Inches(0.9),
           "Abilene: 11 switches, 14 links (real distances). The red links share a duct (SRLG).", 14,
           MUTED)
    D.table(s, Inches(7.3), Inches(1.7), Inches(5.6), ["Experiment", "Runs"], [
        ["Single link cut", "35 / app"], ["Switch crash", "25 / app"], ["Gray (silent) failure", "14 / config"],
        ["BFD interval sweep", "7"], ["SRLG double failure", "15 / topo"],
        ["Sequential double failure", "20 / topo"], ["Flapping link", "14 / app"],
        ["State & overhead", "6 topologies"],
    ], col_w=[3.6, 2.0], size=14, row_h=0.47)
    D.text(s, Inches(7.3), Inches(6.1), Inches(5.6), Inches(0.8),
           "Traffic: all host pairs, constant bit rate, every packet numbered. Also NSFNET (14 switches).",
           13, MUTED)


def res_timeline(D):
    s = D.slide("Anatomy of one failure (SEA → ATL, DEN–KSC cut)", "Results")
    D.image(s, RES / "timeline.png", Inches(0.4), Inches(1.6), Inches(7.2), Inches(5.35))
    D.table(s, Inches(7.9), Inches(1.8), Inches(4.9), ["Strategy", "Lost pkts", "Hops after"], [
        ["static", "262 (never recovers)", "–"], ["reactive", "21", "5"], ["frr-link / node", "5", "6"],
        ["e2e", "29", "5"], ["**fa-frr**", "**5**", "**5**"],
    ], col_w=[2, 2.3, 1.4], size=15, row_h=0.55, highlight_last=True)
    D.callout(s, Inches(7.9), Inches(5.3), Inches(4.9), Inches(1.4),
              "FA-FRR loses only the packets in flight, as fast as FRR, and then moves back to the "
              "shortest path.", 15)


def res_single(D):
    s = D.slide("Single link failures and switch crashes", "Results")
    D.image(s, RES / "single_link_lost.png", Inches(0.4), Inches(1.6), Inches(6.2), Inches(4.0))
    D.image(s, RES / "node_crash_survival.png", Inches(6.8), Inches(1.6), Inches(6.2), Inches(4.0))
    D.bullets(s, Inches(0.7), Inches(5.75), Inches(12), Inches(1.3), [
        "Mean outage, Abilene: **reactive 23.2 ms**, e2e 18.7 ms, **FRR and FA-FRR 5.9 ms**; FA-FRR stretch 1.03 vs 1.17 for FRR",
        "Switch crash: link protection survives only 55–64 %; node protection and **FA-FRR 100 %**",
    ], 16, 4)


def res_double(D):
    s = D.slide("Correlated and sequential double failures", "Results: the key finding")
    D.image(s, RES / "srlg_survival.png", Inches(0.4), Inches(1.6), Inches(6.2), Inches(4.0))
    D.image(s, RES / "sequential_survival.png", Inches(6.8), Inches(1.6), Inches(6.2), Inches(4.0))
    D.callout(s, Inches(0.7), Inches(5.8), Inches(11.9), Inches(1.0),
              "FA-FRR survives **100 %** of both. Plain FRR survives 7–33 % (SRLG) and 10–25 % "
              "(sequential), e2e 0–33 %. Reactive also survives, but with 4–5× longer outages.", 17)


def res_gray_flap(D):
    s = D.slide("Silent failures, BFD and flapping links", "Results")
    D.image(s, RES / "bfd_outage.png", Inches(0.4), Inches(1.6), Inches(5.6), Inches(3.6))
    D.image(s, RES / "flapping_lost.png", Inches(6.9), Inches(1.6), Inches(5.6), Inches(3.6))
    D.bullets(s, Inches(0.7), Inches(5.4), Inches(6.0), Inches(1.6), [
        "Loss of signal misses silent failures: FRR never recovers",
        "With BFD: **13.5 ms** vs 167 ms for LLDP",
        "Faster BFD costs more probe packets",
    ], 15, 4)
    D.bullets(s, Inches(6.9), Inches(5.4), Inches(6.0), Inches(1.6), [
        "5 flaps on Abilene: reactive **1,142**, FRR **273**, FA-FRR **82** lost packets",
        "Hold-down: pay once, not on every flap",
    ], 15, 4)


def res_summary(D):
    s = D.slide("Results summary (Abilene / NSFNET)", "Results")
    D.table(s, Inches(0.6), Inches(1.7), Inches(12.1), ["Failure model", "reactive", "frr-node", "e2e",
                                                        "FA-FRR"], [
        ["single link: mean outage (ms)", "23.2 / 21.2", "5.9 / 4.0", "18.7 / 10.4", "**5.9 / 4.0**"],
        ["single link: path stretch", "1.03 / 1.00", "1.17 / 1.19", "1.07 / 1.02", "**1.03 / 1.00**"],
        ["switch crash: survival", "100 / 100 %", "100 / 100 %", "100 / 100 %", "**100 / 100 %**"],
        ["gray failure: mean outage (ms)", "167 (LLDP)", "13.5", "22.0", "**13.5**"],
        ["SRLG double failure: survival", "100 / 100 %", "33 / 7 %", "33 / 0 %", "**100 / 100 %**"],
        ["sequential double: survival", "100 / 100 %", "25 / 10 %", "15 / 15 %", "**100 / 100 %**"],
        ["flapping link: lost packets", "1,142", "273", "n/a", "**82**"],
    ], col_w=[4.2, 2, 2, 2, 2], size=16, row_h=0.52, highlight_col=4)
    D.callout(s, Inches(0.6), Inches(6.3), Inches(12.1), Inches(0.62),
              "FA-FRR is the only scheme that is both **millisecond-fast** and **never loses a flow**, using the "
              "same switch state as plain node protection.", 17)


def testbed(D):
    s = D.slide("Real testbed port: OS-Ken / Ryu + Mininet + Open vSwitch", "Implementation")
    D.table(s, Inches(0.6), Inches(1.7), Inches(7.0), ["Emulator", "OpenFlow 1.3"], [
        ["tag", "VLAN push / set_field / pop"], ["fast-failover group", "OFPGT_FF + watch_port"],
        ["U-turn backup", "OFPP_IN_PORT, per-ingress group"],
        ["re-optimisation", "OFPGC_MODIFY + barriers"], ["old generation", "delete by cookie"],
        ["LOS / BFD", "OVS carrier / OVS BFD"], ["hold-down", "hub.spawn_after"],
    ], col_w=[2.8, 4.2], size=15, row_h=0.52)
    D.bullets(s, Inches(8.0), Inches(1.8), Inches(4.9), Inches(3.5), [
        "Same planning modules, unchanged",
        "Every message checked in **OpenFlow 1.3 wire format**",
        "11 fake switches over real **TCP**",
        "Abilene in **Mininet** with Open vSwitch",
    ], 17)
    D.callout(s, Inches(8.0), Inches(4.6), Inches(4.9), Inches(1.6),
              "Found only on real switches: output to the ingress port is dropped (fixed with "
              "**IN_PORT**), and each link end reports its own port status.", 14)


def testbed_results(D):
    s = D.slide("Mininet results: Abilene, Open vSwitch, 5 runs per scenario", "Results")
    lines = [l for l in (ROOT / "testbed" / "results" / "summary.md").read_text().splitlines()
             if l.startswith("|")][2:]
    rows = []
    for l in lines:
        c = [x.strip() for x in l.strip("|").split("|")]
        rows.append([c[0], c[4], c[5], c[6], c[7]])
    D.table(s, Inches(0.5), Inches(1.6), Inches(12.3),
            ["Scenario", "Mean outage", "Worst outage", "Controller told", "Re-optimised in"],
            rows, col_w=[5.5, 1.7, 1.7, 1.7, 1.7], size=14, row_h=0.55)
    D.callout(s, Inches(0.5), Inches(5.4), Inches(12.3), Inches(1.2),
              "Cut: the FF group reroutes before the controller even hears of it. Gray failure: "
              "**BFD** turns 1.8 s of loss into 40 ms. Duct cut: declaring the SRLG **halves** the "
              "outage (38 → 20 ms).", 15)


def conclusion(D):
    s = D.slide("Conclusion and future work", "Wrap-up")
    D.text(s, Inches(0.7), Inches(1.7), Inches(6), Inches(0.5), "Findings", 20, NAVY, True)
    D.bullets(s, Inches(0.7), Inches(2.25), Inches(6.0), Inches(4.6), [
        "**Detection dominates** recovery time: LOS 1 ms, BFD ~13 ms, LLDP ~170 ms",
        "**Local beats end-to-end** for speed and monitoring cost",
        "**Fate-sharing backups fail when needed**: SRLG awareness raises survival to 100 %",
        "**Re-optimisation makes protection durable**",
        "**Hold-down buys stability** under flapping",
    ], 16, 8)
    D.text(s, Inches(7.1), Inches(1.7), Inches(6), Inches(0.5), "Future work", 20, NAVY, True)
    D.bullets(s, Inches(7.1), Inches(2.25), Inches(5.8), Inches(4.6), [
        "Load-aware backups (congestion on detours)",
        "Multi-failure data-plane resilience",
        "Learn risk parameters from real failure logs",
        "Hardware switches and real BFD timers",
        "Replicated controllers, P4 data planes",
    ], 16, 8)


def thanks(D):
    s = D.prs.slides.add_slide(D.blank)
    D.n += 1
    D.rect(s, 0, 0, W, H, NAVY)
    D.text(s, Inches(0.8), Inches(2.4), Inches(11.7), Inches(1.2), "Thank you", 54, WHITE, True,
           PP_ALIGN.CENTER)
    D.text(s, Inches(0.8), Inches(3.7), Inches(11.7), Inches(0.6), "Questions?", 26,
           RGBColor(0x9E, 0xD8, 0x9E), align=PP_ALIGN.CENTER)
    D.text(s, Inches(0.8), Inches(5.3), Inches(11.7), Inches(0.9),
           "Code, documentation and results: project git repository (tags v0.1 – v1.1)", 15,
           RGBColor(0xD6, 0xDE, 0xEA), align=PP_ALIGN.CENTER)


def main():
    D = Deck()
    for f in (title_slide, agenda, gap, objectives, literature, design, roadmap,
              fafrr, fafrr_ideas, reopt, setup, res_timeline, res_single, res_double, res_gray_flap,
              res_summary, testbed, testbed_results, conclusion, thanks):
        f(D)
    D.prs.core_properties.title = "Failure-Aware Fast Rerouting in SDN"
    D.save()
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(HERE), str(OUT)],
                   check=True, capture_output=True)
    print("wrote", OUT, "and", OUT.with_suffix(".pdf"), f"({D.n} slides)")


if __name__ == "__main__":
    main()
