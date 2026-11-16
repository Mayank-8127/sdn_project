# IEEE conference paper

`main.tex` (IEEEtran, conference mode, as in the Overleaf "IEEE Conference
Template"), `refs.bib` and `figures/`. Upload the folder (or
`Overleaf_Source.zip`) to Overleaf and compile with pdfLaTeX; BibTeX runs
automatically.

Every number in the paper comes from files in this repository:

| In the paper | Source | Regenerate with |
|---|---|---|
| Fig. 2 timeline, Tables III–V, Figs. 3–6 | `docs/results/*.csv`, `docs/results/REPORT.md` | `python -m ffr experiment --out docs/results` |
| Fig. 3–6 drawings | `paper/figures/*.pdf` | `python paper/make_figures.py` |
| Fig. 1 architecture | `docs/report/figures/fa_frr_architecture.png` | `python docs/report/build_figures.py` |
| Table VI (Mininet) | `testbed/results/summary.md` | `testbed/run_experiments.sh <python> 5` (root, Mininet, OVS) |
| Re-optimisation timing (Sec. VI-B) | controller log | `python -m ffr run --topo abilene --app fa-frr --fail DEN-KSC@0.4 --rate 500 -v` |

To build the source archive for Overleaf:

```bash
cd paper && zip -r ../dist/Overleaf_Source.zip main.tex refs.bib figures
```
