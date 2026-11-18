"""Build the project report (Word + PDF).

    python docs/report/build_figures.py
    python docs/report/build_report.py      # needs python-docx and LibreOffice (soffice)

Writes docs/report/FA-FRR_Project_Report.docx and .pdf. The table of contents is
filled in with real page numbers by building twice: the first PDF tells us where
each heading landed.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
FIG = HERE / "figures"
RES = ROOT / "docs" / "results"
OUT = HERE / "FA-FRR_Project_Report.docx"
TITLE = "Failure-Aware Fast Rerouting in Software-Defined Networks"
STUDENTS = [("Mayank Bansal", "23BEC026"), ("Himanshu Kumar", "23BCS055"),
            ("Anas Khan", "23BCS083"), ("Shardendu Mishra", "23BCS122"),
            ("Divyanshu", "23BEC017")]
COURSE = "Software Defined Networks (EC-466)"
GUIDE = "Dr. Jagadeesha R B"
YEAR = "2026–27"
ACCENT = RGBColor(0x1F, 0x3A, 0x68)
GRAY = RGBColor(0x55, 0x55, 0x55)


# --------------------------------------------------------------------------- helpers

class Report:
    def __init__(self, toc_pages: dict[str, str] | None = None):
        self.doc = Document()
        self.toc_pages = toc_pages or {}
        self.headings: list[tuple[int, str]] = []
        self.fig_no = 0
        self.tab_no = 0
        self.chapter = 0
        self._setup()

    # ---- document setup
    def _setup(self):
        d = self.doc
        sec = d.sections[0]
        sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
        sec.left_margin, sec.right_margin = Cm(3.0), Cm(2.2)
        sec.top_margin, sec.bottom_margin = Cm(2.5), Cm(2.3)
        st = d.styles["Normal"]
        st.font.name = "Times New Roman"
        st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        st.font.size = Pt(12)
        pf = st.paragraph_format
        pf.line_spacing = 1.4
        pf.space_after = Pt(6)
        for name, size in (("Heading 1", 18), ("Heading 2", 14), ("Heading 3", 12.5)):
            h = d.styles[name]
            h.font.name = "Times New Roman"
            h.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
            h.font.size = Pt(size)
            h.font.bold = True
            h.font.color.rgb = ACCENT
            h.paragraph_format.space_before = Pt(14 if name != "Heading 1" else 0)
            h.paragraph_format.space_after = Pt(8)
            h.paragraph_format.keep_with_next = True
        self.doc.core_properties.title = TITLE
        self.doc.core_properties.subject = "Project report"

    # ---- inline markup: **bold**, *italic*, `code`
    def _runs(self, p, text, size=None, color=None):
        for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)", text):
            if not part:
                continue
            if part.startswith("**"):
                r = p.add_run(part[2:-2])
                r.bold = True
            elif part.startswith("`"):
                r = p.add_run(part[1:-1])
                r.font.name = "Courier New"
                r.font.size = Pt((size or 12) - 1.5)
            elif part.startswith("*"):
                r = p.add_run(part[1:-1])
                r.italic = True
            else:
                r = p.add_run(part)
            if size and not part.startswith("`"):
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = color
        return p

    def p(self, text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, size=None, color=None, after=None,
          before=None, indent=None):
        para = self.doc.add_paragraph()
        para.alignment = align
        if after is not None:
            para.paragraph_format.space_after = Pt(after)
        if before is not None:
            para.paragraph_format.space_before = Pt(before)
        if indent is not None:
            para.paragraph_format.first_line_indent = Cm(indent)
        return self._runs(para, text, size, color)

    def bullets(self, items, style="List Bullet"):
        for it in items:
            para = self.doc.add_paragraph(style=style)
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            para.paragraph_format.space_after = Pt(3)
            self._runs(para, it)

    def numbered(self, items):
        for i, it in enumerate(items, 1):
            para = self.doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            para.paragraph_format.left_indent = Cm(0.9)
            para.paragraph_format.first_line_indent = Cm(-0.6)
            para.paragraph_format.space_after = Pt(3)
            self._runs(para, f"{i}.  {it}")

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def chapter_heading(self, title):
        self.chapter += 1
        self.fig_no = self.tab_no = 0
        lab = self.doc.add_paragraph()
        lab.paragraph_format.space_after = Pt(2)
        lab.paragraph_format.keep_with_next = True
        lab.paragraph_format.page_break_before = self.chapter > 1
        r = lab.add_run(f"CHAPTER {self.chapter}")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(12), GRAY
        self.h1(f"{self.chapter}. {title}", toc=f"{self.chapter}. {title}")

    def h1(self, text, toc=None, numbered_page_break=False):
        h = self.doc.add_heading(text, level=1)
        h.paragraph_format.page_break_before = numbered_page_break
        if toc is not None:
            self.headings.append((1, toc))
        return h

    def h2(self, text):
        self.headings.append((2, text))
        return self.doc.add_heading(text, level=2)

    def h3(self, text):
        return self.doc.add_heading(text, level=3)

    def equation(self, text):
        self.doc.paragraphs[-1].paragraph_format.keep_with_next = True
        para = self.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = para.add_run(text)
        r.italic = True
        r.font.size = Pt(12.5)
        r.font.name = "Cambria Math"

    def code(self, text, size=9):
        t = self.doc.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = t.rows[0].cells[0]
        _shade(cell, "F3F3F1")
        cell.paragraphs[0].text = ""
        for i, line in enumerate(text.strip("\n").split("\n")):
            para = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.0
            r = para.add_run(line)
            r.font.name = "Courier New"
            r.font.size = Pt(size)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def figure(self, path, caption, width=15.0):
        self.fig_no += 1
        para = self.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.keep_with_next = True
        para.paragraph_format.space_before = Pt(6)
        para.add_run().add_picture(str(path), width=Cm(width))
        cap = self.doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_after = Pt(12)
        self._runs(cap, f"**Figure {self.chapter}.{self.fig_no}:** {caption}", size=10.5)

    def table(self, header, rows, caption=None, widths=None, size=10, bold_last_col=False,
              highlight_row=None):
        if caption:
            self.tab_no += 1
            cap = self.doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap.paragraph_format.keep_with_next = True
            cap.paragraph_format.space_before = Pt(6)
            cap.paragraph_format.space_after = Pt(4)
            self._runs(cap, f"**Table {self.chapter}.{self.tab_no}:** {caption}", size=10.5)
        t = self.doc.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(header):
            c = t.rows[0].cells[i]
            _shade(c, "1F3A68")
            c.paragraphs[0].text = ""
            c.paragraphs[0].paragraph_format.space_after = Pt(0)
            c.paragraphs[0].paragraph_format.line_spacing = 1.1
            r = c.paragraphs[0].add_run(str(h))
            r.bold, r.font.size, r.font.color.rgb = True, Pt(size), RGBColor(255, 255, 255)
        _repeat_header(t.rows[0])
        for ri, row in enumerate(rows):
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].paragraphs[0].text = ""
                self._runs(cells[i].paragraphs[0], str(v), size=size)
                cells[i].paragraphs[0].paragraph_format.space_after = Pt(0)
                cells[i].paragraphs[0].paragraph_format.line_spacing = 1.1
                if highlight_row is not None and ri == highlight_row:
                    _shade(cells[i], "E3F1E3")
                elif ri % 2 == 1:
                    _shade(cells[i], "F5F5F3")
        _set_widths(t, widths or [15.5 / len(header)] * len(header))
        self.doc.add_paragraph().paragraph_format.space_after = Pt(4)
        return t

    def save(self, path):
        self.doc.save(str(path))


def _shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _set_widths(t, widths):
    """Column widths that both Word (cell widths) and LibreOffice (tblGrid) honour."""
    t.autofit = False
    grid = t._tbl.tblGrid
    for col, w in zip(grid.findall(qn("w:gridCol")), widths):
        col.set(qn("w:w"), str(int(Cm(w).twips)))
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)


def _repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def _field(run, instr):
    for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        elif text == instr:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = instr
        else:
            el = OxmlElement("w:t")
            el.text = text
        run._r.append(el)


def _page_numbers(section, fmt, start=None):
    pg = OxmlElement("w:pgNumType")
    pg.set(qn("w:fmt"), fmt)
    if start is not None:
        pg.set(qn("w:start"), str(start))
    cols = section._sectPr.find(qn("w:cols"))
    if cols is not None:
        cols.addprevious(pg)
    else:
        section._sectPr.append(pg)
    footer = section.footer
    footer.is_linked_to_previous = False
    para = footer.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = para.add_run()
    r.font.size = Pt(10)
    _field(r, "PAGE")


def _blank_line(n=34):
    return "_" * n


# --------------------------------------------------------------------------- content

def front_matter(R: Report):
    d = R.doc
    sec = d.sections[0]
    sec.different_first_page_header_footer = True

    def centered(text, size, bold=False, color=None, after=6, italic=False):
        para = d.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(after)
        r = para.add_run(text)
        r.bold, r.italic, r.font.size = bold, italic, Pt(size)
        if color:
            r.font.color.rgb = color
        return para

    # ---------------- title page
    centered("A PROJECT REPORT", 13, True, GRAY, 4)
    centered("on", 12, after=4, italic=True)
    centered(TITLE, 22, True, ACCENT, 14)
    centered("Submitted as part of the course", 11.5, after=2, italic=True)
    centered(COURSE, 13, True, after=16)
    centered("Submitted by", 13, True, after=6)
    t = d.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(("S. No.", "Name of the Student", "Roll Number")):
        c = t.rows[0].cells[i]
        _shade(c, "1F3A68")
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size, r.font.color.rgb = True, Pt(11.5), RGBColor(255, 255, 255)
    for n, (name, roll) in enumerate(STUDENTS, 1):
        cells = t.add_row().cells
        for c, text in zip(cells, (f"{n}.", name, roll)):
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            c.paragraphs[0].add_run(text).font.size = Pt(12)
        t.rows[-1].height = Cm(0.9)
    _set_widths(t, (2.0, 8.5, 5.0))
    centered("", 6, after=10)
    centered("Under the guidance of", 12, italic=True, after=2)
    centered(GUIDE, 13, True, after=2)
    centered("Course Instructor", 10.5, color=GRAY, after=30, italic=True)
    centered("Academic Year " + YEAR, 12, after=0)

    # ---------------- certificate
    R.page_break()
    R.h1("CERTIFICATE")
    R.p(f"This is to certify that the project report entitled **“{TITLE}”** is a bona fide "
        "record of the work carried out by the students listed on the title page as part of "
        f"the course **{COURSE}** during the academic year {YEAR}. "
        "The work embodied in this report has not been submitted elsewhere for the award of any "
        "other degree.", indent=1.0)
    R.p("", after=60)
    t = d.add_table(rows=3, cols=1)
    t.cell(0, 0).paragraphs[0].add_run("_" * 26)
    t.cell(1, 0).paragraphs[0].add_run(GUIDE).bold = True
    t.cell(2, 0).paragraphs[0].add_run("Course Instructor and Project Guide")
    for r in range(3):
        t.cell(r, 0).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # ---------------- declaration
    R.page_break()
    R.h1("DECLARATION")
    R.p(f"We hereby declare that the project report entitled **“{TITLE}”** submitted by us is "
        "an authentic record of our own work carried out under the guidance of "
        f"**{GUIDE}** as part of the course **{COURSE}**. The results embodied in this report "
        "have not been submitted to any "
        "other university or institute for the award of any degree or diploma. All sources of "
        "information and software used have been duly acknowledged.", indent=1.0)
    R.p("", after=30)
    t = d.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(("Name of the Student", "Roll Number", "Signature")):
        c = t.rows[0].cells[i]
        _shade(c, "1F3A68")
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.color.rgb, r.font.size = True, RGBColor(255, 255, 255), Pt(11)
    for name, roll in STUDENTS:
        cells = t.add_row().cells
        cells[0].paragraphs[0].add_run(name).font.size = Pt(11.5)
        cells[1].paragraphs[0].add_run(roll).font.size = Pt(11.5)
        t.rows[-1].height = Cm(1.0)
    _set_widths(t, (7.0, 4.5, 4.0))

    # ---------------- acknowledgement
    R.page_break()
    R.h1("ACKNOWLEDGEMENT")
    R.p(f"We express our sincere gratitude to our course instructor and project guide, "
        f"**{GUIDE}**, for the constant guidance, encouragement and valuable suggestions "
        f"throughout this project, carried out as part of the course {COURSE}. We are "
        "thankful to all faculty members of the department for providing the facilities and "
        "support needed to carry out this work.", align=WD_ALIGN_PARAGRAPH.LEFT, indent=1.0)
    R.p("We also acknowledge the open-source communities behind Python, OS-Ken/Ryu, Mininet and "
        "Open vSwitch, whose tools made this work possible, and the authors of the research "
        "papers cited in this report. Finally, we thank our families and friends for their "
        "support and patience.", indent=1.0)
    R.p("", after=30)
    for name, roll in STUDENTS:
        R.p(f"{name} ({roll})", align=WD_ALIGN_PARAGRAPH.RIGHT, after=2)

    # ---------------- abstract
    R.page_break()
    R.h1("ABSTRACT")
    R.p("Failure recovery in Software-Defined Networks is slow when it depends on the "
        "controller, which must be notified, recompute routes and install new rules in many "
        "switches, taking tens to hundreds of milliseconds. Data-plane *fast "
        "rerouting* with OpenFlow fast-failover groups removes the controller from this "
        "critical path, but classic schemes treat every link as equally reliable, ignore "
        "correlated failures, leave the network unprotected after the first failure and "
        "behave poorly when a link flaps.", indent=1.0)
    R.p("This project designs, implements and evaluates **Failure-Aware Fast Reroute "
        "(FA-FRR)**. FA-FRR keeps millisecond data-plane recovery (fast-failover groups, "
        "tagged node and link detours, BFD detection) and adds a controller that learns from "
        "failures: a per-link risk model with exponentially decaying flap penalties, "
        "risk-aware primary paths, backups that avoid Shared Risk Link Groups (SRLGs), hitless "
        "make-before-break re-optimisation after every failure, and flap damping.", indent=1.0)
    R.p("Everything is built from scratch in Python as a deterministic discrete-event OpenFlow "
        "emulator (about 4,500 lines of code, 109 automated tests), and FA-FRR is compared with five baselines (no recovery, reactive "
        "restoration, local link and node protection, and end-to-end path protection) in "
        "850 simulations on the Abilene and NSFNET research backbones under seven "
        "failure models. FA-FRR is the only scheme that is both millisecond-fast (4–7 ms mean "
        "outage) and never loses a flow: it survives 100 % of correlated double failures and "
        "of sequential double failures, where plain fast reroute survives only 7–33 % and "
        "10–25 % respectively, and it loses 3.3× fewer packets than plain fast reroute on a "
        "flapping link. The same algorithm is also ported to a real OpenFlow 1.3 controller "
        "(OS-Ken/Ryu) and validated on Mininet with Open vSwitch, where a link cut costs 14 ms "
        "of traffic on average and declaring a shared risk group halves the outage of a duct "
        "cut (38 → 20 ms).",
        indent=1.0)
    R.p("**Keywords:** Software-Defined Networking, OpenFlow, fast reroute, fast-failover group, "
        "failure recovery, BFD, shared risk link group, network resilience.",
        align=WD_ALIGN_PARAGRAPH.LEFT)


def table_of_contents(R: Report, entries):
    R.page_break()
    R.h1("TABLE OF CONTENTS")
    for level, text in entries:
        para = R.doc.add_paragraph()
        para.paragraph_format.space_after = Pt(2 if level == 2 else 4)
        para.paragraph_format.space_before = Pt(0 if level == 2 else 6)
        para.paragraph_format.line_spacing = 1.15
        para.paragraph_format.left_indent = Cm(0 if level == 1 else 0.8)
        para.paragraph_format.tab_stops.add_tab_stop(Cm(15.7), WD_TAB_ALIGNMENT.RIGHT,
                                                    WD_TAB_LEADER.DOTS)
        r = para.add_run(f"{text}\t{R.toc_pages.get(text, '')}")
        r.bold = level == 1
        r.font.size = Pt(11.5 if level == 1 else 11)


def ch_introduction(R: Report):
    R.chapter_heading("Introduction")
    R.h2("1.1 Project Overview")
    R.p("This project designs, implements and evaluates **Failure-Aware Fast Reroute "
        "(FA-FRR)**, a failure-recovery scheme for OpenFlow-based Software-Defined Networks "
        "[1]–[3]. FA-FRR combines data-plane fast reroute, which recovers in milliseconds "
        "without involving the controller, with a controller that learns how the network "
        "fails and uses that knowledge to choose and continually refresh the backup paths.",
        indent=1.0)
    R.p("The project delivers four artefacts: (1) a deterministic OpenFlow network emulator "
        "written from scratch in Python; (2) six recovery strategies implemented as "
        "controller applications, five baselines and FA-FRR; (3) an evaluation suite of "
        "850 simulations on the Abilene and NSFNET backbones under seven failure "
        "models; and (4) a port of FA-FRR to a real OpenFlow 1.3 controller (OS-Ken/Ryu) for "
        "Mininet and Open vSwitch, validated on the Abilene topology.", indent=1.0)
    R.h2("1.2 Motivation")
    R.p("Controller-driven restoration in SDN needs a control-channel round trip, route "
        "computation and per-rule installation, so recovery takes tens to hundreds of "
        "milliseconds [4]. Fast reroute with OpenFlow fast-failover groups avoids this by "
        "pre-installing backups, and recovers in roughly the failure-detection time [4], [6]. "
        "Existing fast-reroute schemes are, however, *failure-agnostic*:", indent=1.0)
    R.bullets([
        "they treat all links as equally reliable, although failures in operational networks "
        "are concentrated on a few links [13], [14];",
        "they may protect a link with a backup in the same Shared Risk Link Group (SRLG), for "
        "example a fibre in the same duct, which fails at the same time;",
        "after the first failure the backups are used up and nobody re-protects the network, "
        "so a second failure is fatal;",
        "they move traffic back to a flapping link every time it comes up, causing an outage "
        "on every flap.",
    ])
    R.p("These are exactly the situations in which protection matters most, and they are the "
        "situations FA-FRR is designed for.", indent=1.0)
    R.h2("1.3 Problem Statement")
    R.p("*Design an SDN failure-recovery scheme that keeps the millisecond recovery time of "
        "data-plane fast rerouting while using knowledge about how the network fails "
        "(unequal link reliability, correlated failures, repeated failures and flapping) so "
        "that traffic survives correlated and successive failures and the network stays "
        "stable under flapping links; implement it and evaluate it quantitatively against "
        "the established recovery schemes.*", indent=1.0)
    R.h2("1.4 Objectives")
    R.numbered([
        "Build a deterministic OpenFlow network emulator that models flow tables, group "
        "tables (including fast-failover), port liveness, control-channel latency, rule "
        "installation time and failure detection (loss of signal, BFD, LLDP).",
        "Implement the established recovery strategies as baselines: static routing, reactive "
        "restoration, local link and node fast reroute and end-to-end path protection.",
        "Design and implement **FA-FRR**: risk model, risk-aware primary paths, SRLG-disjoint "
        "backups, hitless re-optimisation and flap damping.",
        "Evaluate all strategies on real research topologies under single, correlated, "
        "sequential, silent and flapping failures, measuring packet loss, outage time, "
        "flow survival, path stretch, switch state and control overhead.",
        "Port the scheme to a real OpenFlow 1.3 controller framework (OS-Ken/Ryu) for "
        "Mininet and Open vSwitch.",
    ])
    R.h2("1.5 Scope of the Project")
    R.p("The project considers wired SDN networks controlled by a single logical OpenFlow "
        "controller with destination-based forwarding of IPv4 traffic between hosts. It "
        "covers link failures, switch crashes, silent (gray) link failures, correlated SRLG "
        "failures and flapping. Controller failure and congestion on backup paths are out of "
        "scope (see Chapter 8).", indent=1.0)
    R.h2("1.6 Organisation of the Report")
    R.p("Chapter 2 reviews related work and identifies the gap addressed. Chapter 3 states "
        "the requirements and specification and Chapter 4 presents the system design, "
        "including the FA-FRR algorithm. Chapter 5 describes the implementation, "
        "testing and the real-controller port, Chapter 6 the experimental setup and Chapter 7 "
        "the results. Chapter 8 concludes and outlines future work. Appendix A explains how "
        "to run the software.", indent=1.0)


def ch_literature(R: Report):
    R.chapter_heading("Related Work")
    R.p("This chapter reviews the work that FA-FRR builds on and positions the project "
        "against it, following the classification of fast-recovery mechanisms by Chiesa et "
        "al. [5].", indent=1.0)
    R.h2("2.1 Recovery in OpenFlow Networks")
    R.p("Sharma et al. [4] showed experimentally that controller-driven restoration in large "
        "OpenFlow networks struggles to meet the 50 ms carrier-grade target, whereas "
        "protection with pre-installed backups, fast-failover groups and switch-local BFD "
        "achieves it, with most of the remaining time spent on detection. Van Adrichem et "
        "al. [6] reduced recovery to a few milliseconds by tuning per-link BFD intervals and "
        "confirmed that detection is the bottleneck. SPIDER [7] uses a stateful programmable "
        "data plane to implement heartbeat detection and remote failure notification inside "
        "the switch pipeline, with recovery delays independent of the controller.",
        indent=1.0)
    R.h2("2.2 IP and MPLS Fast Reroute")
    R.p("Not-via addresses and MPLS-TE fast reroute [19] tunnel packets "
        "around a failed element with full single-failure coverage. The tagged detours of this "
        "project follow the not-via idea: a VLAN tag means “deliver to the destination while "
        "avoiding element X”.", indent=1.0)
    R.h2("2.3 Resilience Theory and Disjoint Paths")
    R.p("Feigenbaum et al. [18] proved that perfect resilience is impossible in general with "
        "static destination-based tables, while Borokhovich, Schiff and Schmid [11] showed "
        "that tagging and richer matching let fast-failover groups guarantee connectivity "
        "under arbitrary failures at the cost of long paths. Suurballe [9] and Bhandari [10] "
        "give algorithms for minimum-cost pairs of disjoint paths, the basis of end-to-end "
        "path protection.", indent=1.0)
    R.h2("2.4 Failure-Aware and Risk-Aware Routing")
    R.p("Studies of operational networks [13], [14] show that failures are non-uniform, "
        "bursty and correlated, which motivates modelling *risk*. Shared Risk Link Groups "
        "capture correlated failures: a backup that shares an SRLG with its primary is not a "
        "real backup. Path reliability can be computed as the product of link availabilities "
        "and optimised with shortest-path algorithms after a logarithmic transformation. BGP "
        "route-flap damping (RFC 2439) penalises flapping routes with an exponentially "
        "decaying penalty, and consistent-update work [12] shows how to change forwarding "
        "state without transient loss by installing the new configuration before removing "
        "the old one (make-before-break).", indent=1.0)
    R.h2("2.5 Summary of Related Work")
    R.table(["Work", "Approach", "Strength", "Limitation addressed here"], [
        ["Sharma et al. [4]", "path protection, FF groups, BFD", "< 50 ms recovery",
         "failure-agnostic; single failure"],
        ["Van Adrichem et al. [6]", "per-link BFD + FF", "few-ms recovery",
         "no correlated / repeated failures"],
        ["SPIDER [7]", "stateful data-plane detection", "controller-independent",
         "needs a stateful pipeline"],
        ["Not-via / MPLS FRR", "tunnelled detours", "full single-failure coverage",
         "no risk model; not SDN"],
        ["Borokhovich et al. [11]", "multi-failure FF via tagging", "provable connectivity",
         "very long paths"],
        ["Reitblatt et al. [12]", "consistent updates", "no transient loss",
         "not a recovery scheme by itself"],
        ["RFC 2439", "flap damping", "stability", "designed for BGP routes"],
    ], "Related work and the gap targeted by FA-FRR", widths=[3.4, 4.0, 3.6, 4.6], size=9.5)
    R.h2("2.6 Research Gap")
    R.p("Existing SDN fast-failover work either gives fast local recovery while treating all "
        "links equally, ignoring correlated failures and leaving the network unprotected after "
        "the first failure, or uses risk-aware path selection only in the slow controller "
        "loop. **FA-FRR combines the two**: millisecond data-plane fast reroute with backups "
        "that are chosen, and continually re-chosen, using a learned model of how the network "
        "fails.", indent=1.0)


def ch_requirements(R: Report):
    R.chapter_heading("System Requirements and Specification")
    R.h2("3.1 Functional Requirements")
    R.table(["ID", "Requirement"], [
        ["FR1", "Model OpenFlow 1.3 switches: prioritised wildcard flow tables, group tables "
                "(ALL, INDIRECT, FAST_FAILOVER) with watch ports, VLAN-style tags, barriers."],
        ["FR2", "Model links with propagation delay, physical state and port liveness; model "
                "control-channel delay and per-rule installation time."],
        ["FR3", "Inject failures: link cut, silent (gray) failure, switch crash, correlated "
                "SRLG failure, sequential failures and flapping."],
        ["FR4", "Detect failures by loss of signal, per-link BFD [8], multi-hop path BFD and "
                "controller LLDP probing."],
        ["FR5", "Provide recovery strategies: static, reactive, frr-link, frr-node, e2e, fa-frr."],
        ["FR6", "Generate constant-bit-rate traffic between all host pairs and record every "
                "packet sent, delivered and lost."],
        ["FR7", "Reproduce all experiments, tables and figures with one command."],
        ["FR8", "Run the FA-FRR controller against real OpenFlow 1.3 switches (Open vSwitch)."],
    ], "Functional requirements", widths=[1.5, 14.0])
    R.h2("3.2 Non-Functional Requirements")
    R.bullets([
        "**Determinism:** identical inputs give identical results (discrete-event simulation, "
        "seeded randomness).",
        "**Portability:** the core runs anywhere Python 3.10+ runs, without root privileges.",
        "**Testability:** every module is covered by an automated test suite.",
        "**Readability:** code and documentation that are easy to follow.",
        "**Performance:** the full evaluation (850 simulations) completes in minutes "
        "on a desktop machine.",
    ])
    R.h2("3.3 Hardware and Software Used")
    R.table(["Item", "Details"], [
        ["Language", "Python 3.10+ (pure Python core, no compiled dependencies)"],
        ["Libraries", "matplotlib (plots), pytest (testing)"],
        ["SDN controller framework", "OS-Ken 4.2 (maintained fork of Ryu)"],
        ["Testbed tools", "Mininet 2.3.1b4, Open vSwitch 4.0 with OpenFlow 1.3 and BFD, "
                          "Linux 7.2"],
        ["Testing / CI", "pytest, GitHub Actions workflow"],
        ["Hardware", "Intel Core i5-12500H, 16 threads; simulations run in parallel on all "
                     "cores, Mininet on the same machine"],
    ], "Software and hardware", widths=[4.5, 11.0])
    R.h2("3.4 Metrics")
    R.table(["Metric", "Definition"], [
        ["Packets lost", "packets sent minus packets delivered, over all flows"],
        ["Outage", "longest run of consecutive lost packets of a flow × send interval "
                   "(infinite if the flow never recovers)"],
        ["Survival", "percentage of failure scenarios in which no flow is permanently lost"],
        ["Dead flows", "flows that never recover, averaged over scenarios"],
        ["Stretch", "hops of the path used after recovery ÷ hops of the best surviving path"],
        ["State", "flow entries and group entries installed in all switches"],
        ["Control overhead", "controller-to-switch messages; probe packets per second"],
    ], "Evaluation metrics", widths=[3.5, 12.0])
    R.h2("3.5 Default Parameters")
    R.table(["Parameter", "Default", "Meaning"], [
        ["link delay", "1 ms or from topology", "propagation delay"],
        ["ctrl_delay", "5 ms", "one-way controller ↔ switch delay"],
        ["rule_install_time", "1 ms", "per FLOW_MOD / GROUP_MOD"],
        ["compute_time", "5 ms", "controller path computation"],
        ["los_delay", "1 ms", "loss-of-signal detection"],
        ["bfd_interval × bfd_mult", "3.3 ms × 3", "BFD timers"],
        ["lldp_interval × lldp_mult", "100 ms × 3", "controller probing"],
        ["traffic", "500–1000 pkt/s CBR", "per host pair"],
    ], "Default emulator parameters", widths=[5.0, 4.5, 6.0])


def ch_design(R: Report):
    R.chapter_heading("System Design")
    R.h2("4.1 Overall Architecture")
    R.p("The system has three layers. The **emulator** models the network: a discrete-event "
        "engine, links and ports, OpenFlow switches with flow and group tables, hosts, "
        "traffic generators and failure detectors. The **controller framework** models the "
        "control channel (delay, per-rule installation time, barriers, LLDP). The "
        "**controller applications** implement the recovery strategies on top of shared "
        "planning modules (routing, protection and risk). The evaluation suite drives "
        "thousands of scenarios through this stack, and the testbed port reuses the same "
        "planning modules to drive real switches.", indent=1.0)
    R.table(["Module", "Responsibility"], [
        ["sim.py", "discrete-event engine (virtual clock, ordered event queue)"],
        ["topology.py", "topologies (linear, ring, grid, Abilene, NSFNET), SRLGs, failure priors"],
        ["openflow.py", "matches, actions, flow table, group table, controller messages"],
        ["network.py", "links, ports, hosts, OpenFlow switches, failure injection"],
        ["detection.py", "loss of signal, per-link BFD, multi-hop path BFD"],
        ["controller.py", "controller base: channel delay, LLDP, barriers, link events"],
        ["routing.py", "Dijkstra, next-hop trees, Bhandari disjoint paths"],
        ["protection.py", "planning of node/link detours for every (switch, destination)"],
        ["risk.py", "failure-aware risk model"],
        ["apps/", "static, reactive, frr (link/node), e2e, fa_frr"],
        ["experiments/", "evaluation suite, plots, report generation"],
        ["testbed/", "OS-Ken/Ryu application, Mininet script, wire-level tests"],
    ], "Software modules", widths=[3.6, 11.9])
    R.h2("4.2 Emulator Design")
    R.p("The emulator is event-driven: instead of waiting in real time it jumps from one "
        "event (a packet arriving, a timer expiring, a link failing) to the next, so a second "
        "of network time with 110 flows at 1,000 packets per second takes well under a second "
        "to simulate and every run is exactly reproducible. A switch processes a packet by "
        "finding the highest-priority matching rule and executing its actions; a group action "
        "consults the group table, and a fast-failover group picks the first bucket whose "
        "watched port is *live*. Port liveness is set by the detection mechanism, which is "
        "kept separate from the physical link state so that a silently failed link stays "
        "“live” until BFD notices it.", indent=1.0)
    R.h2("4.3 Baseline Strategies")
    R.bullets([
        "**static** installs shortest-path rules once and never reacts (lower bound).",
        "**reactive** recomputes shortest paths when it receives `PORT_STATUS` (or misses "
        "LLDP probes) and pushes only the rules that changed.",
        "**frr-link / frr-node** install, for every switch and destination, a fast-failover "
        "group whose first bucket is the primary next hop and whose second bucket tags the "
        "packet and sends it onto a precomputed detour. The detour comes from the "
        "shortest-path tree of the graph without the protected link (frr-link) or without "
        "the next switch (frr-node). Because the detour is a shortest-path tree, one tag per "
        "protected element suffices (not-via style).",
        "**e2e** computes a pair of disjoint paths per host pair with Bhandari's algorithm, "
        "monitors the primary with multi-hop BFD and switches the ingress over when it fails.",
    ])
    R.h2("4.4 FA-FRR Design")
    R.p("FA-FRR keeps the node- and link-protecting fast-failover structure of Section 4.3, "
        "so it recovers just as fast, and adds five failure-aware mechanisms in the "
        "controller (Figure 4.1).", indent=1.0)
    R.figure(FIG / "fa_frr_architecture.png", "FA-FRR: the data plane recovers in "
             "milliseconds while the controller learns and re-protects in the background.", 15.5)
    R.h3("4.4.1 Risk model")
    R.p("For every link e the controller keeps a failure probability", indent=1.0)
    R.equation("p(e) = min(0.99, prior(e) + penalty(e))")
    R.p("The prior comes from the topology (for example proportional to fibre length). Each "
        "observed failure adds a fixed `flap_penalty`; links in the same SRLG as the failed "
        "link receive `correlation × flap_penalty`, because if one fibre in a duct broke the "
        "others are suspect. The penalty halves every `half_life` seconds, as in BGP route "
        "flap damping.", indent=1.0)
    R.h3("4.4.2 Risk-aware primary paths")
    R.p("A path survives only if all its links survive, so its survival probability is "
        "Π(1 − p(e)). Taking −ln turns this product into a sum that Dijkstra's algorithm can "
        "minimise. The link weight combines latency and risk:", indent=1.0)
    R.equation("w(e) = delay(e) / mean_delay + λ · (−ln(1 − p(e)))")
    R.p("λ = 0 gives pure latency routing; a large λ maximises path survival probability.",
        indent=1.0)
    R.h3("4.4.3 SRLG-disjoint backups")
    R.p("For each (switch, destination) the detour that protects element X must avoid X and, "
        "where possible, every link sharing an SRLG with X. Candidates are tried in a fixed "
        "preference order: (1) node protection avoiding the SRLG, (2) link protection "
        "avoiding the SRLG, (3) plain node protection, (4) plain link protection. The order "
        "matters: a node-protecting detour that dies together with the failed link is worse "
        "than a link-protecting detour that is risk-disjoint.", indent=1.0)
    R.h3("4.4.4 Hitless re-optimisation")
    R.p("Fast reroute saves the first milliseconds; afterwards traffic runs on a detour and "
        "the network is no longer protected. FA-FRR therefore recomputes a complete, optimal "
        "and fully protected configuration for the surviving network and installs it in "
        "three phases separated by OpenFlow barriers (Figure 4.2). Each configuration is a "
        "*generation* with fresh tags and its own cookie, so packets already on an old detour "
        "keep matching the old rules until they are deleted. This make-before-break order "
        "adds no packet loss.", indent=1.0)
    R.figure(FIG / "reoptimisation.png", "Three-phase make-before-break re-optimisation.", 15.5)
    R.h3("4.4.5 Flap damping")
    R.p("A link that comes back up is not used immediately. It stays excluded for", indent=1.0)
    R.equation("holddown(e) = base · (1 + penalty(e) / flap_penalty)")
    R.p("so the more it has flapped recently, the longer it waits. If it fails again during "
        "the hold-down nothing has to be recomputed, because it carries no traffic.",
        indent=1.0)
    R.h2("4.5 FA-FRR Algorithm")
    R.code("""
on start:
    plan_and_install(generation = 0)

plan_and_install(gen):
    G  <- current topology minus failed links and links in hold-down
    w  <- risk-aware weights from the risk model
    for each destination d:
        primary next hops <- shortest-path tree towards d in G with weights w
        for each switch s and its next hop n:
            X <- n (node) ; detour <- SPT(G - n - SRLG(s,n)) if it reaches d
            else link (s,n) avoiding SRLG, else plain node, else plain link
            tag <- DETOUR_BASE + gen, keyed by (protected element, variant)
            FF group(s, d) = [ watch(s->n): out(n) ,
                               watch(s->detour): push tag, out(detour) ]
    phase 1: add new detour rules           ; barrier on all switches
    phase 2: add / modify FF groups         ; barrier on all switches
    phase 3: delete rules of generation gen-1 (by cookie)

on PORT_STATUS down(e):          # traffic is already safe on the FF backup
    risk.observe_failure(e)      # + correlated penalty for SRLG siblings
    if e not in hold-down: plan_and_install(gen + 1)

on PORT_STATUS up(e):
    start hold-down timer(e, base * (1 + penalty(e) / flap_penalty))
    on expiry: plan_and_install(gen + 1)
""", size=8.5)


def ch_implementation(R: Report):
    R.chapter_heading("Implementation")
    R.h2("5.1 Code Organisation")
    R.p("The software is a Python package (`ffr`) with no dependencies outside the standard "
        "library, a testbed folder for the real controller and a pytest suite. Table 5.1 "
        "lists the modules.", indent=1.0)
    R.table(["Module", "Role"], [
        ["`sim.py`", "discrete-event engine (time-ordered event queue)"],
        ["`topology.py`", "topologies (Abilene, NSFNET, rings, grids), SRLGs, failure priors"],
        ["`openflow.py`", "matches, actions, flow tables, group tables, OpenFlow messages"],
        ["`network.py`", "links, ports, hosts and switches; link cuts, gray failures, crashes"],
        ["`detection.py`", "loss of signal, per-link BFD, multi-hop path BFD"],
        ["`controller.py`", "controller base: channel delay, LLDP probing, barriers"],
        ["`routing.py`", "Dijkstra, next-hop trees, Bhandari disjoint path pairs"],
        ["`protection.py`", "detour planning for link and node protection"],
        ["`risk.py`", "failure-aware risk model, hold-down"],
        ["`apps/`", "static, reactive, frr (link/node), e2e and fa_frr controllers"],
        ["`experiments/`", "evaluation suite, parallel runner, plots, report generation"],
        ["`testbed/`", "OS-Ken/Ryu application, Mininet scripts, wire-level tests"],
    ], "Modules of the implementation", widths=[3.5, 12.0])
    R.h2("5.2 Key Implementation Details")
    R.bullets([
        "**Tags.** Detoured packets carry a tag (a VLAN id on real switches). Detour rules "
        "match (destination, tag) at a higher priority than primary rules, and the egress "
        "switch pops the tag before delivering to the host.",
        "**Generations and cookies.** Every FA-FRR generation uses a fresh tag range "
        "(`DETOUR_BASE + gen`) and cookie, so the old generation's rules can be deleted in one "
        "message after the new generation is in place.",
        "**Barriers.** The controller counts barrier replies from all switches before moving "
        "to the next phase of an update.",
        "**Outage measurement.** Every packet has a sequence number; the outage of a flow is "
        "the longest run of missing sequence numbers times the sending interval, and is "
        "infinite if the flow never recovers.",
        "**Parallel experiments.** The suite runs independent simulations in parallel with "
        "Python multiprocessing; the 850 simulations take about three minutes on 16 cores.",
    ])
    R.p("Below is the real flow and group table of switch s1 on a six-switch ring under "
        "frr-link, printed by the command-line tool. Destination rules point at fast-failover "
        "groups; tagged rules (priority 200) carry detoured packets.", indent=1.0)
    R.code("""
s1: prio=200   match[dst=hs3,tag=2] -> Output(port=2)
s1: prio=200   match[dst=hs3,tag=3] -> Output(port=1)
s1: prio=100   match[dst=hs1] -> PopTag(), Output(port=3)
s1: prio=100   match[dst=hs6] -> Group(group_id=5)
s1: group 1 [fast_failover] watch=1: Output(port=1) | watch=2: SetTag(tag=1), Output(port=2)
s1: group 5 [fast_failover] watch=2: Output(port=2) | watch=1: SetTag(tag=5), Output(port=1)
""", size=8)
    R.h2("5.3 Testing")
    R.p("Testing used pytest. The 109 automated tests cover the OpenFlow semantics (priority, "
        "wildcards, group types), every detection mechanism, every recovery strategy and the "
        "acceptance criteria of the design, for example that FRR recovery time is about the "
        "detection time, that FA-FRR survives an SRLG double failure that plain FRR does not, "
        "and that re-optimisation is hitless (FA-FRR loses exactly as many packets as plain "
        "FRR). A GitHub Actions workflow runs the tests, the quick experiments and the "
        "testbed tests on every push.",
        indent=1.0)
    R.h2("5.4 Real Testbed Port (OS-Ken/Ryu, Mininet, Open vSwitch)")
    R.p("To show that FA-FRR is not just a simulation artefact, the same planning modules "
        "drive a real OpenFlow 1.3 controller application written for OS-Ken, the maintained "
        "fork of Ryu, for Mininet [15] and Open vSwitch. Table 5.2 shows how the emulator's abstractions map onto OpenFlow 1.3.",
        indent=1.0)
    R.table(["Emulator", "OpenFlow 1.3 / Open vSwitch"], [
        ["Match(dst = h)", "eth_type = 0x0800, ipv4_dst = IP of h"],
        ["SetTag(T) / Match(tag = T)", "push_vlan + set_field vlan_vid = T | OFPVID_PRESENT"],
        ["PopTag()", "pop_vlan in a higher-priority egress rule"],
        ["fast-failover group", "OFPGroupMod type OFPGT_FF, buckets with watch_port; "
                                "OFPGC_MODIFY on re-optimisation"],
        ["Barrier", "OFPBarrierRequest / EventOFPBarrierReply matched by xid"],
        ["generation cookie", "OFPFlowMod DELETE with cookie and cookie_mask"],
        ["LOS / BFD", "OVS carrier state / ovs-vsctl set interface … bfd:enable=true"],
        ["hold-down timer", "hub.spawn_after"],
    ], "Mapping of emulator abstractions to OpenFlow 1.3", widths=[5.0, 10.5], size=9.5)
    R.p("The controller was verified at three levels. First, unit tests drive it with fake "
        "datapaths and serialise every message it emits to OpenFlow 1.3 wire format, so "
        "malformed matches, actions or groups would fail. Second, eleven fake switches open "
        "real TCP connections to the running controller, complete the OpenFlow handshake, "
        "answer barriers and report a link failure: the controller performs the initial "
        "installation (695 flow additions, 390 group additions) and, after the DEN–KSC "
        "failure, the re-optimisation (390 group modifications, 11 deletions of the old "
        "detour generation). Third, the Abilene topology runs in Mininet with Open vSwitch "
        "(Section 7.10).", indent=1.0)
    R.p("Two behaviours of real switches are not modelled by the emulator and were handled in "
        "the port. OpenFlow drops a packet output to the port it arrived on, so a backup that "
        "turns back towards the previous switch must use the reserved port OFPP_IN_PORT; the "
        "controller therefore installs, per switch and destination, one fast-failover group "
        "per ingress neighbour, selected by an in_port rule, besides the default group. "
        "Second, each end of a link sends its own PORT_STATUS, and the end disabled "
        "administratively reports OFPPC_PORT_DOWN with a live state; the controller keeps "
        "the state of each end and treats a link as up only when both ends are up.",
        indent=1.0)


def ch_setup(R: Report):
    R.chapter_heading("Experimental Setup")
    R.h2("6.1 Topologies")
    R.p("Two widely used research backbones are the main topologies: **Abilene** (Internet2, "
        "11 switches and 14 links, link delays from approximate fibre distances, Figure 6.1) "
        "and **NSFNET** (14 switches, 21 links, 2 ms per link), both available in the Internet "
        "Topology Zoo [17]. Rings and grids from 6 to 25 "
        "switches are used for the state and overhead study. One host is attached to each "
        "switch.", indent=1.0)
    R.figure(FIG / "abilene.png", "Abilene topology. The red links form the SRLG “duct” used "
             "in the correlated-failure examples.", 14.0)
    R.h2("6.2 Traffic")
    R.p("Every ordered pair of hosts exchanges constant-bit-rate traffic (110 flows on "
        "Abilene, 182 on NSFNET) at 500 packets per second (1,000 in the single-flow timeline "
        "experiment). Each packet carries a sequence number so that every loss is accounted "
        "for.", indent=1.0)
    R.h2("6.3 Failure Models and Experiments")
    R.table(["Experiment", "What happens", "Runs"], [
        ["Single link failure", "every link is cut once (LOS detection)", "35 per app"],
        ["Switch crash", "every switch crashes once; flows to/from it are excluded", "25 per app"],
        ["Gray failure", "links fail silently; LOS vs BFD vs LLDP vs path BFD", "14 per config"],
        ["BFD trade-off", "BFD interval 1–50 ms, multiplier 3", "7 intervals"],
        ["SRLG double failure", "two links of the same risk group fail together", "15 per topology"],
        ["Sequential double failure", "an independent second link fails 200 ms later", "20 per topology"],
        ["Flapping link", "40 ms down / 40 ms up, five times", "14 per app"],
        ["State and overhead", "rules, groups, messages, probes on 6–25 switches", "6 topologies"],
        ["Risk-aware routing", "latency vs path failure probability for λ = 0 … 50", "analytic"],
        ["Failure timeline", "one flow, packets delivered per millisecond", "6 apps"],
    ], "The ten experiments (850 simulations in total)", widths=[4.2, 8.3, 3.0], size=9.5)


def _md_section_table(section):
    """Rows of the first table under '## <section>' in the generated evaluation report."""
    text = (RES / "REPORT.md").read_text().split(f"## {section}\n", 1)[1]
    lines = [l for l in text.split("\n## ", 1)[0].splitlines() if l.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    return [dict(zip(header, (c.strip() for c in l.strip("|").split("|")))) for l in lines[2:]]


def _testbed_rows():
    """Rows of testbed/results-2ms/summary.md (local controller), written by
    testbed/summarise.py, without the probe-gap and bursts columns."""
    lines = [l for l in (ROOT / "testbed" / "results-2ms" / "summary.md").read_text().splitlines()
             if l.startswith("|")]
    rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]
    return [[r[i] for i in (0, 1, 2, 4, 6, 7, 8, 9)] for r in rows]


def _res_table(R, section, apps, caption, topos=("abilene", "nsfnet")):
    out = []
    for r in _md_section_table(section):
        if r.get("topo") in topos and r["app"] in apps:
            app = "**fa-frr**" if r["app"] == "fa-frr" else r["app"]
            out.append(["Abilene" if r["topo"] == "abilene" else "NSFNET", app,
                        f"{float(r['survival_pct']):.0f} %", r["dead_flows"],
                        f"{float(r['lost_pkts']):,.0f}",
                        r["mean_outage_ms"] if r["mean_outage_ms"] != "n/a" else "∞",
                        r["stretch"]])
    R.table(["Topology", "Strategy", "Survival", "Dead flows", "Lost pkts", "Mean outage (ms)",
             "Stretch"], out, caption, widths=[2.2, 2.3, 1.9, 1.9, 2.1, 2.7, 1.8], size=9)


def ch_results(R: Report):
    R.chapter_heading("Results and Discussion")
    R.p("All numbers in this chapter come from one run of `python -m ffr experiment` (186 s). "
        "Raw CSV files and the generated evaluation report are in `docs/results/`.",
        indent=1.0)
    R.h2("7.1 Anatomy of a Failure")
    R.p("Figure 7.1 follows a single flow (SEA → ATL, 1,000 packets per second) whose path "
        "crosses DEN–KSC, which is cut at 450 ms. The static controller never recovers. The "
        "reactive controller recovers after 21 lost packets, end-to-end protection after 29 "
        "(it must wait for the path BFD timeout) and every fast-reroute scheme after only 5, "
        "the packets that were already in flight on the cut fibre. The gap in arrivals is "
        "longer than the loss because the detour is longer. FA-FRR then re-optimises and "
        "returns the flow to a 5-hop path, whereas plain FRR stays on the 6-hop detour.",
        indent=1.0)
    R.figure(RES / "timeline.png", "Packets delivered per millisecond for one flow when "
             "DEN–KSC is cut (dashed line).", 13.0)
    R.h2("7.2 Single Link Failures")
    _res_table(R, "Single link failures", ("static", "reactive", "frr-node", "e2e", "fa-frr"),
               "Every link cut once (mean over all links)")
    R.p("Every recovery scheme survives a single link failure. Fast reroute loses 4× fewer "
        "packets than reactive restoration and has a 4–5× shorter mean outage (5.9 ms vs "
        "23.2 ms on Abilene). FA-FRR matches plain FRR exactly in loss and outage, and thanks "
        "to re-optimisation also matches reactive restoration in path quality (stretch 1.03 "
        "and 1.00 instead of 1.17–1.19). End-to-end protection is in between because the "
        "ingress has to notice the failure first.", indent=1.0)
    R.figure(RES / "single_link_lost.png", "Packets lost per single link failure.", 12.0)
    R.h2("7.3 Switch Crashes")
    R.p("When a whole switch crashes, link-protecting detours may run through the crashed "
        "switch: frr-link survives only 55 % (Abilene) and 64 % (NSFNET) of crashes. "
        "Node-protecting schemes (frr-node, FA-FRR) and e2e survive all of them, and FA-FRR "
        "again has the best stretch (1.01 / 1.00).", indent=1.0)
    R.figure(RES / "node_crash_survival.png", "Survival under switch crashes.", 12.0)
    R.h2("7.4 Gray Failures and Detection")
    R.table(["Configuration", "Survival", "Mean outage (ms)", "Lost packets"], [
        ["reactive + LLDP (50 ms)", "100 %", "167.2", "1,648"],
        ["frr-node + LOS", "0 %", "∞", "5,505"],
        ["frr-node + BFD", "100 %", "13.5", "131"],
        ["e2e (path BFD)", "100 %", "22.0", "227"],
        ["**fa-frr + BFD**", "100 %", "13.5", "131"],
    ], "Silent link failures on Abilene", widths=[5.5, 2.5, 3.5, 3.0])
    R.p("A silent (gray) failure [16] is invisible to loss of signal, so fast reroute with LOS alone never "
        "recovers. BFD detects it in about 10 ms and fast reroute recovers in 13.5 ms on "
        "average, 12× faster than controller LLDP probing. Figure 7.4 shows the BFD trade-off: "
        "a 1 ms interval gives a 7.7 ms outage but costs 2,000 probe packets per second per "
        "link, while 50 ms costs only 40 but gives a 132 ms outage. Detection dominates "
        "fast-reroute recovery time, in agreement with [4] and [6].", indent=1.0)
    R.figure(RES / "bfd_outage.png", "Mean outage versus BFD interval.", 11.5)
    R.h2("7.5 Correlated (SRLG) Double Failures")
    _res_table(R, "Correlated (SRLG) double failures", ("reactive", "frr-node", "e2e", "fa-frr"),
               "Two links of the same SRLG fail at the same instant")
    R.p("This is where failure awareness matters. When two links that share a duct fail "
        "together, plain FRR's detour often uses the second failed link, so both buckets of "
        "the fast-failover group are dead and the traffic is lost for good: frr-node survives "
        "only 33 % of the cases on Abilene and 7 % on NSFNET, and end-to-end protection 33 % "
        "and 0 %. FA-FRR's SRLG-disjoint backups survive **100 %** of them while keeping a "
        "fast-reroute outage (6.7 / 4.3 ms). Reactive restoration also survives, but with "
        "3.5–5× longer outages and 4–5× more lost packets.", indent=1.0)
    R.figure(RES / "srlg_survival.png", "Survival under correlated SRLG double failures.", 12.0)
    R.h2("7.6 Sequential Double Failures")
    _res_table(R, "Sequential double failures", ("reactive", "frr-node", "e2e", "fa-frr"),
               "A second independent link fails 200 ms after the first")
    R.p("Plain fast reroute is single-shot: after the first failure traffic runs on detours "
        "that have no protection of their own, and a second failure on a detour is fatal. "
        "frr-node survives only 25 % / 10 % and e2e 15 % / 15 % of these cases. FA-FRR "
        "re-optimises within about 70 ms of the first failure, so the network is fully "
        "protected again when the second failure arrives: it survives **100 %** with a "
        "millisecond outage (6.0 / 4.0 ms), against 23.4 / 21.4 ms for reactive restoration.",
        indent=1.0)
    R.figure(RES / "sequential_survival.png", "Survival under sequential double failures.", 12.0)
    R.h2("7.7 Flapping Links")
    R.table(["Strategy", "Lost packets", "Mean outage (ms)", "Stretch"], [
        ["reactive", "1,142", "23.2", "1.03"],
        ["frr-node", "273", "5.9", "1.03"],
        ["**fa-frr**", "**82**", "5.9", "1.41"],
    ], "A link flaps five times (40 ms down / 40 ms up), Abilene", widths=[4, 3.5, 3.5, 3])
    R.p("Fast-failover is revertive: each time the link comes back the traffic returns to it, "
        "and each new failure causes another outage. Reactive restoration pays the full "
        "controller loop on every flap. FA-FRR pays only for the first failure; the hold-down "
        "keeps traffic off the flapping link, losing 3.3× fewer packets than plain FRR and "
        "14× fewer than reactive restoration. The price is a longer path while the link is "
        "held down (stretch 1.41), a deliberate trade of path length for stability.",
        indent=1.0)
    R.figure(RES / "flapping_lost.png", "Packets lost with a flapping link.", 11.0)
    R.h2("7.8 State and Control Overhead")
    R.table(["Topology", "static", "frr-node", "e2e", "fa-frr", "e2e probes/s"], [
        ["Ring (6)", "36 / 0", "132 / 30", "156 / 30", "132 / 30", "18,176"],
        ["Abilene (11)", "121 / 0", "404 / 110", "621 / 110", "404 / 110", "66,654"],
        ["NSFNET (14)", "196 / 0", "593 / 182", "880 / 182", "593 / 182", "110,300"],
        ["Grid 5×5 (25)", "625 / 0", "2,325 / 600", "3,825 / 600", "2,325 / 600", "363,632"],
    ], "Flow entries / group entries in all switches, and e2e monitoring traffic",
        widths=[3, 2.2, 2.5, 2.5, 2.5, 2.8], size=9.5)
    R.p("FA-FRR needs exactly the same steady-state state as plain node protection, about "
        "3.3–3.7× plain shortest-path routing, and no monitoring traffic beyond per-link BFD. "
        "End-to-end protection needs about 50 % more rules and its path-monitoring traffic "
        "grows with the square of the number of hosts. A re-optimisation costs a few hundred "
        "control messages, sent in the background while traffic is already safe on the "
        "detour.", indent=1.0)
    R.h2("7.9 Risk-Aware Routing Trade-off")
    R.p("With heterogeneous link failure priors (0.5–15 %), increasing λ moves primary paths "
        "away from risky links. On NSFNET, λ = 10 lowers the mean path failure probability "
        "from 11.8 % to 9.0 % for 7 % more latency; on Abilene, λ = 20 lowers it from 16.4 % "
        "to 12.3 % for 12 % more latency (Figure 7.8). The operator chooses the point on this "
        "curve.", indent=1.0)
    R.figure(RES / "risk_tradeoff.png", "Mean path latency versus path failure probability "
             "as λ grows.", 15.0)
    R.h2("7.10 Validation on Mininet and Open vSwitch")
    R.p("The OS-Ken controller ran against eleven Open vSwitch switches in Mininet on the "
        "Abilene topology, with link delays from the fibre distances. Hosts whose shortest "
        "path crosses a failed link ping each other as fast as ping allows (2 ms requested, "
        "8–9.5 ms achieved and measured per pair); the outage is the number of probes lost "
        "in the longest burst times the probe interval. A failure lasts 2 s and each scenario "
        "was run five times (Table 7.7). A gray failure is made with a tc filter that drops "
        "every received frame while the interfaces stay up.", indent=1.0)
    R.table(["Scenario", "Runs", "Pairs", "Lost / pair", "Mean outage", "Worst outage",
             "Controller notified", "Re-optimisation"], _testbed_rows(),
            "FA-FRR on Mininet with Open vSwitch (Abilene, 2 s failures, local controller)",
            widths=[4.6, 1.1, 1.2, 1.5, 1.7, 1.7, 2.0, 2.0], size=8.5)
    R.p("On a link cut, Open vSwitch sees the carrier drop and the fast-failover group moves "
        "traffic to the backup without the controller: the mean outage is 15 ms, one or two "
        "probes. The controller hears of the cut about 8 ms after it happens and has every "
        "group of the next generation in place 34 ms later, after traffic has already moved; "
        "with a 5 ms delay on the control channel this grows to 77 ms while the outage stays "
        "the same. A gray failure without BFD is never "
        "detected and traffic is lost for the whole failure; with OVS BFD (10 ms × 3) the "
        "outage drops to 41 ms, matching the detection-dominated behaviour of Section 7.4. "
        "Open vSwitch does not report BFD-detected failures as PORT_STATUS, so the data plane "
        "reroutes but the controller does not re-optimise. When both links of the Abilene "
        "duct fail at once, declaring the shared risk group halves the mean outage (52 to "
        "26 ms) and the worst outage (98 to 49 ms), because the backups no longer use the "
        "other link of the duct. On this testbed the controller is local, so flows on a dead "
        "backup are rescued by re-optimisation within tens of milliseconds; with a 5 ms control "
        "channel their mean outage grows to 70 ms while the declared case stays at 27 ms.", indent=1.0)
    R.h2("7.11 Summary of Results")
    R.table(["Failure model (Abilene / NSFNET)", "reactive", "frr-node", "e2e", "fa-frr"], [
        ["single link: mean outage (ms)", "23.2 / 21.2", "5.9 / 4.0", "18.7 / 10.4", "**5.9 / 4.0**"],
        ["single link: stretch", "1.03 / 1.00", "1.17 / 1.19", "1.07 / 1.02", "**1.03 / 1.00**"],
        ["switch crash: survival", "100 / 100 %", "100 / 100 %", "100 / 100 %", "**100 / 100 %**"],
        ["gray failure: mean outage (ms)", "167 (LLDP)", "13.5", "22.0", "**13.5**"],
        ["SRLG double: survival", "100 / 100 %", "33 / 7 %", "33 / 0 %", "**100 / 100 %**"],
        ["sequential double: survival", "100 / 100 %", "25 / 10 %", "15 / 15 %", "**100 / 100 %**"],
        ["flapping link: lost packets", "1,142", "273", "n/a", "**82**"],
    ], "Summary: FA-FRR is the only scheme that is both fast and never loses a flow",
        widths=[5.2, 2.6, 2.5, 2.5, 2.7], size=9.5)


def ch_conclusion(R: Report):
    R.chapter_heading("Conclusion and Future Work")
    R.h2("8.1 Conclusion")
    R.p("This project built, from first principles, a complete environment for studying "
        "failure recovery in Software-Defined Networks: an OpenFlow emulator, five "
        "established recovery strategies and a new failure-aware fast-reroute scheme, an "
        "evaluation suite and a real-controller port. The main findings are:", indent=1.0)
    R.numbered([
        "**Detection dominates** fast-reroute recovery time: about 1 ms with loss of signal, "
        "about 13 ms with BFD at 3.3 ms × 3, and about 170 ms with controller LLDP probing.",
        "**Local protection beats end-to-end protection** for speed, and its monitoring cost "
        "does not grow with the square of the network size.",
        "**Failure-agnostic backups fail exactly when they are needed:** a backup that shares "
        "a risk group with its primary is no backup. SRLG-disjoint backups raise survival of "
        "correlated double failures from 0–33 % to 100 %.",
        "**Re-optimisation makes protection durable:** without it every data-plane scheme is "
        "single-shot. Hitless make-before-break updates add no loss.",
        "**Hold-down trades path quality for stability:** under flapping, FA-FRR loses 3.3× "
        "fewer packets than plain FRR.",
    ])
    R.p("FA-FRR is the only evaluated scheme that is both millisecond-fast and never loses a "
        "flow in any of the tested failure models, at the same steady-state switch state as "
        "plain node protection.", indent=1.0)
    R.h2("8.2 Limitations")
    R.bullets([
        "The emulator models delays and OpenFlow semantics but not queueing, so congestion "
        "on detours shared by many flows is not measured.",
        "Two failures within the re-optimisation window (about 70 ms on Abilene) rely on the "
        "SRLG model being correct.",
        "The risk-model parameters (λ, half-life, penalty) were chosen by hand.",
        "The Mininet runs use a single machine: link delays come from tc netem and the "
        "controller is local, so control-channel latency is far below that of a WAN.",
        "Open vSwitch does not report BFD-detected failures to the controller, so after a "
        "gray failure the network is not re-protected until the carrier changes.",
        "A single, always-reachable controller is assumed.",
    ])
    R.h2("8.3 Future Work")
    R.bullets([
        "Load-aware backup selection so that detours do not overload shared links.",
        "Multi-failure data-plane resilience in the spirit of Borokhovich et al. [11] for "
        "failures arriving faster than re-optimisation.",
        "Fitting the risk model to real failure logs, or learning it online.",
        "Hardware OpenFlow switches, to measure real rule-installation times and hardware "
        "BFD, and a controller that polls BFD state so gray failures also trigger "
        "re-optimisation.",
        "Distributed or replicated controllers and P4 programmable data planes.",
    ])


def references(R: Report):
    R.h1("REFERENCES", toc="References", numbered_page_break=True)
    refs = [
        "N. McKeown, T. Anderson, H. Balakrishnan, G. Parulkar, L. Peterson, J. Rexford, "
        "S. Shenker and J. Turner, “OpenFlow: Enabling innovation in campus networks,” *ACM "
        "SIGCOMM Computer Communication Review*, vol. 38, no. 2, pp. 69–74, 2008.",
        "Open Networking Foundation, “OpenFlow Switch Specification, Version 1.3,” 2012.",
        "D. Kreutz, F. M. V. Ramos, P. Veríssimo, C. E. Rothenberg, S. Azodolmolky and S. Uhlig, "
        "“Software-defined networking: A comprehensive survey,” *Proceedings of the IEEE*, "
        "vol. 103, no. 1, pp. 14–76, 2015.",
        "S. Sharma, D. Staessens, D. Colle, M. Pickavet and P. Demeester, “OpenFlow: Meeting "
        "carrier-grade recovery requirements,” *Computer Communications*, vol. 36, no. 6, "
        "pp. 656–665, 2013.",
        "M. Chiesa, A. Kamisiński, J. Rak, G. Rétvári and S. Schmid, “A survey of "
        "fast-recovery mechanisms in packet-switched networks,” *IEEE Communications Surveys "
        "& Tutorials*, vol. 23, no. 2, 2021.",
        "N. L. M. van Adrichem, B. J. van Asten and F. A. Kuipers, “Fast recovery in "
        "software-defined networks,” in *Proc. European Workshop on Software Defined "
        "Networks (EWSDN)*, 2014.",
        "C. Cascone, D. Sanvito, L. Pollini, A. Capone and B. Sansò, “Fast failure detection "
        "and recovery in SDN with stateful data plane,” *International Journal of Network "
        "Management*, 2017 (SPIDER; arXiv:1511.05490).",
        "D. Katz and D. Ward, “Bidirectional Forwarding Detection (BFD),” IETF RFC 5880, 2010.",
        "J. W. Suurballe, “Disjoint paths in a network,” *Networks*, vol. 4, no. 2, "
        "pp. 125–145, 1974.",
        "R. Bhandari, *Survivable Networks: Algorithms for Diverse Routing*. Kluwer, 1999.",
        "M. Borokhovich, L. Schiff and S. Schmid, “Provable data plane connectivity with local "
        "fast failover: Introducing OpenFlow graph algorithms,” in *Proc. ACM HotSDN*, 2014.",
        "M. Reitblatt, N. Foster, J. Rexford, C. Schlesinger and D. Walker, “Abstractions for "
        "network update,” in *Proc. ACM SIGCOMM*, 2012.",
        "A. Markopoulou, G. Iannaccone, S. Bhattacharyya, C.-N. Chuah, Y. Ganjali and C. Diot, "
        "“Characterization of failures in an operational IP backbone network,” *IEEE/ACM "
        "Transactions on Networking*, vol. 16, no. 4, 2008.",
        "P. Gill, N. Jain and N. Nagappan, “Understanding network failures in data centers: "
        "Measurement, analysis, and implications,” in *Proc. ACM SIGCOMM*, 2011.",
        "B. Lantz, B. Heller and N. McKeown, “A network in a laptop: Rapid prototyping for "
        "software-defined networks,” in *Proc. ACM HotNets*, 2010.",
        "P. Huang, C. Guo, L. Zhou, J. R. Lorch, Y. Dang, M. Chintalapati and R. Yao, “Gray "
        "failure: The Achilles' heel of cloud-scale systems,” in *Proc. HotOS*, 2017.",
        "S. Knight, H. X. Nguyen, N. Falkner, R. Bowden and M. Roughan, “The Internet Topology "
        "Zoo,” *IEEE Journal on Selected Areas in Communications*, vol. 29, no. 9, 2011.",
        "J. Feigenbaum, B. Godfrey, A. Panda, M. Schapira, S. Shenker and A. Singla, “On the "
        "resilience of routing tables,” in *Proc. ACM PODC* (brief announcement), 2012.",
        "IETF RFCs: 5286 (Loop-Free Alternates), 5714 (IP Fast Reroute Framework), 6981 "
        "(Not-via addresses), 4090 (MPLS-TE Fast Reroute), 2439 (BGP Route Flap Damping).",
    ]
    for i, ref in enumerate(refs, 1):
        para = R.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.left_indent = Cm(1.0)
        para.paragraph_format.first_line_indent = Cm(-1.0)
        para.paragraph_format.space_after = Pt(4)
        para.paragraph_format.line_spacing = 1.15
        R._runs(para, f"[{i}] {ref}", size=11)


def appendices(R: Report):
    R.h1("APPENDIX A: Running the Project", toc="Appendix A: Running the Project",
         numbered_page_break=True)
    R.p("The source code, documentation and results are provided with this report.", indent=1.0)
    R.code("""
# install and test
python -m venv .venv && .venv/bin/pip install -e '.[dev,plots]'
.venv/bin/pytest -q

# one scenario: Abilene, all host pairs, link DEN-KSC cut at 0.4 s
.venv/bin/python -m ffr run --topo abilene --app reactive --fail DEN-KSC@0.4 -v
.venv/bin/python -m ffr run --topo abilene --app fa-frr   --fail DEN-KSC@0.4 -v

# correlated failure of two links in the same duct
.venv/bin/python -m ffr run --topo abilene --app fa-frr --srlg duct:DEN-KSC,SNV-DEN \\
    --fail DEN-KSC@0.4 --fail SNV-DEN@0.4

# gray failure with BFD, switch crash, inspect switch tables
.venv/bin/python -m ffr run --topo abilene --app fa-frr --detection los+bfd \\
    --fail-silent DEN-KSC@0.4
.venv/bin/python -m ffr run --topo abilene --app fa-frr --fail-node KSC@0.4
.venv/bin/python -m ffr run --topo ring6 --app frr-link --flows 1 --tables s1

# the whole evaluation (about 3 min on 16 cores; --quick about 30 s)
.venv/bin/python -m ffr experiment --out results

# real testbed (needs root, Mininet and Open vSwitch): one scenario in two terminals
sudo .venv-testbed/bin/python testbed/mininet_ffr.py --topo abilene --fail DEN-KSC
FFR_TOPO=/tmp/ffr_topo.json .venv-testbed/bin/python testbed/run_controller.py

# all Mininet scenarios, five runs each (logs and summary in testbed/results-2ms/)
PING_MS=2 RESULTS=testbed/results-2ms testbed/run_experiments.sh .venv-testbed/bin/python 5
""", size=8.5)
    R.p("Example output for the SRLG double failure under FA-FRR:", indent=1.0)
    R.code("[fa-frr] flows=110 sent=66000 lost=413 (0.63%) affected_flows=50 never_recovered=0\n"
           "         max_outage=13.0ms mean_outage(recovered)=8.3ms ctrl_msgs=908", size=8.5)



# --------------------------------------------------------------------------- build

def build(toc_pages=None, toc_entries=None, out=OUT):
    R = Report(toc_pages)
    front_matter(R)
    table_of_contents(R, toc_entries or [(1, "placeholder")] * 60)
    # main matter: new section, arabic page numbers from 1
    main = R.doc.add_section(WD_SECTION.NEW_PAGE)
    _page_numbers(R.doc.sections[0], "lowerRoman", 1)
    _page_numbers(main, "decimal", 1)
    main.different_first_page_header_footer = False
    # the chapter helper starts with a page break; the new section already did that
    ch_introduction_no_break(R)
    ch_literature(R)
    ch_requirements(R)
    ch_design(R)
    ch_implementation(R)
    ch_setup(R)
    ch_results(R)
    ch_conclusion(R)
    references(R)
    appendices(R)
    R.save(out)
    return R.headings


def ch_introduction_no_break(R):
    # chapter_heading starts with a page break, but the new section already starts a page
    original = R.page_break
    R.page_break = lambda: None
    try:
        ch_introduction(R)
    finally:
        R.page_break = original


def to_pdf(docx: Path, outdir: Path) -> Path:
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(outdir),
                    str(docx)], check=True, capture_output=True)
    return outdir / (docx.stem + ".pdf")


def heading_pages(pdf: Path, headings):
    """Map each heading to its printed page number (arabic numbering starts at chapter 1)."""
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True).stdout).group(1))
    texts = []
    for i in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(pdf), "-"],
                           capture_output=True, text=True).stdout
        texts.append(re.sub(r"\s+", " ", t))
    start = next(i for i, t in enumerate(texts) if "CHAPTER 1 " in t)
    pages, cursor = {}, start
    for level, text in headings:
        key = re.sub(r"\s+", " ", text)
        if text.startswith("Appendix") or text == "References":
            key = text.upper() if text == "References" else "APPENDIX " + text.split(" ", 1)[1]
        for i in range(cursor, n):
            if key in texts[i]:
                pages[text] = str(i - start + 1)
                cursor = i
                break
    return pages


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        headings = build(out=tmp / "pass1.docx")
        pages = heading_pages(to_pdf(tmp / "pass1.docx", tmp), headings)
        build(pages, headings, OUT)
        # second check: the TOC has the same length in both passes, so pages are stable
        pdf = to_pdf(OUT, HERE)
        missing = [h for _, h in headings if h not in pages]
        if missing:
            print("warning: headings not located:", missing, file=sys.stderr)
    print("wrote", OUT, "and", pdf)


if __name__ == "__main__":
    main()
