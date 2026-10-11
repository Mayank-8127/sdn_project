# Interim progress review

| File | What it is |
|------|------------|
| `Progress_Report.docx` / `.pdf` | progress report: literature summary, objectives, plan, emulator, strategies, failure detection, first results, remaining work |
| `Progress_Presentation.pptx` / `.pdf` | 13-slide progress presentation |

Both describe the project as of v0.4: the emulator, reactive restoration,
fast reroute with link and node protection, and failure detection (loss of
signal, BFD, LLDP) with gray failures and switch crashes. The guide,
department and institute fields on the first page are left blank; fill them
in the `.docx` / `.pptx` files and export to PDF again.

Numbers: every Abilene and NSFNET link cut in turn for each strategy, the
DEN–KSC cut with the controller 1–40 ms away, the DEN–KSC + SNV–DEN double
failure, a gray failure of DEN–KSC under each detection mechanism and a crash
of switch KSC, all with `python -m ffr run` (500 pkt/s per flow, all host
pairs).
