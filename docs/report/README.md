# Report and presentation

| File | What it is |
|------|------------|
| `FA-FRR_Project_Report.docx` / `.pdf` | project report (35 pages): certificate, declaration, abstract, 8 chapters, references, appendix |
| `FA-FRR_Presentation.pptx` / `.pdf` | 20-slide presentation |

The first page of each lists the team. The guide, department and institute
fields are left blank; fill them in the `.docx` / `.pptx` files and export to
PDF again.

To regenerate everything (needs `python-docx`, `python-pptx`, `matplotlib`
and LibreOffice for the PDF export):

```bash
pip install python-docx python-pptx matplotlib
python docs/report/build_figures.py   # concept diagrams -> docs/report/figures/
python docs/report/build_report.py    # report (.docx + .pdf, table of contents with page numbers)
python docs/report/build_slides.py    # slides (.pptx + .pdf)
```

The result charts come from `docs/results/` (`python -m ffr experiment`) and the
Mininet table from `testbed/results/summary.md` (`testbed/run_experiments.sh`).
