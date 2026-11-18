# IEEE conference paper

`Failure_Aware_Fast_Rerouting_in_Software_Defined_Networks.pdf` is the
current paper (Revision 2, after two Google Deep Review rounds).

The LaTeX source (`main.tex`, IEEEtran conference mode, `refs.bib` and
`figures/`) is provided separately as `Overleaf_Source.zip`. Upload the zip to
Overleaf as a new project and compile with pdfLaTeX; BibTeX runs
automatically.

`make_figures.py` draws the paper's figures from `docs/results/` into
`paper/figures/`:

```bash
python paper/make_figures.py
```

Where each table and figure comes from, and the command that regenerates it,
is listed in the project `README.md` (Section 5.3).
